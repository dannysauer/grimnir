// =============================================================================
// receiver/main/main.c — ESP32-S3 CSI Receiver
//
// Connects to Wi-Fi, enables CSI capture on all incoming 802.11 frames,
// and streams structured binary UDP packets to the aggregator service.
//
// Change RECEIVER_NAME in config.h before flashing each board.
//
// UDP packet format (little-endian):
//   [0..3]    magic     uint32  0x43534921 ("CSI!")
//   [4..5]    version   uint16  1
//   [6..21]   name      char[16] null-padded receiver name
//   [22..27]  tx_mac    uint8[6] transmitter MAC
//   [28..29]  rssi      int16   dBm
//   [30..31]  noise     int16   dBm
//   [32..33]  channel   uint16
//   [34..35]  bw        uint16  MHz
//   [36..37]  antennas  uint16
//   [38..39]  subcarriers uint16
//   [40..43]  ts_us     uint32  device uptime micros
//   [44..N]   amplitude float32[] antenna_count * subcarrier_count
//   [N..M]    phase     float32[] antenna_count * subcarrier_count
// =============================================================================

#include <errno.h>
#include <math.h>
#include <string.h>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "lwip/netdb.h"
#include "lwip/sockets.h"
#include "nvs_flash.h"

#include "../../config.h"

// ── Constants ─────────────────────────────────────────────────────────────────
#define PACKET_MAGIC       0x43534921U
#define PACKET_VERSION     1
#define MAX_SUBCARRIERS    128
#define MAX_ANTENNAS       4
#define CSI_QUEUE_LEN      32
#define HEADER_SIZE        44

#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT      BIT1

// ── Types ─────────────────────────────────────────────────────────────────────
typedef struct {
    uint8_t  tx_mac[6];
    int8_t   rssi;
    int8_t   noise_floor;
    uint16_t channel;
    uint16_t bandwidth_mhz;
    uint16_t antenna_count;
    uint16_t subcarrier_count;
    uint32_t timestamp_us;
    float    amplitude[MAX_ANTENNAS * MAX_SUBCARRIERS];
    float    phase[MAX_ANTENNAS * MAX_SUBCARRIERS];
} csi_entry_t;

// ── Globals ───────────────────────────────────────────────────────────────────
static EventGroupHandle_t s_wifi_event_group;
static QueueHandle_t      s_csi_queue;
static int                s_sock = -1;
static struct sockaddr_in s_agg_addr;
static int                s_retry_count = 0;

// ── Wi-Fi ─────────────────────────────────────────────────────────────────────

static void wifi_event_handler(void *arg, esp_event_base_t base,
                                int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        if (s_retry_count < WIFI_MAX_RETRY) {
            esp_wifi_connect();
            ESP_LOGW(LOG_TAG_WIFI, "Retry %d/%d", ++s_retry_count, WIFI_MAX_RETRY);
        } else {
            xEventGroupSetBits(s_wifi_event_group, WIFI_FAIL_BIT);
        }
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        s_retry_count = 0;
        ip_event_got_ip_t *ev = (ip_event_got_ip_t *)data;
        ESP_LOGI(LOG_TAG_WIFI, "Got IP: " IPSTR, IP2STR(&ev->ip_info.ip));
        xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
    }
}

static void wifi_init_sta(void)
{
    s_wifi_event_group = xEventGroupCreate();

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    esp_event_handler_instance_t inst_any, inst_got_ip;
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL, &inst_any));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL, &inst_got_ip));

    wifi_config_t wifi_cfg = {
        .sta = {
            .ssid     = WIFI_SSID,
            .password = WIFI_PASSWORD,
            .channel  = CSI_WIFI_CHANNEL,
        },
    };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_cfg));
    ESP_ERROR_CHECK(esp_wifi_set_bandwidth(WIFI_IF_STA, CSI_BANDWIDTH));
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));
    ESP_ERROR_CHECK(esp_wifi_start());

    EventBits_t bits = xEventGroupWaitBits(
        s_wifi_event_group, WIFI_CONNECTED_BIT | WIFI_FAIL_BIT,
        pdFALSE, pdFALSE, portMAX_DELAY);

    if (bits & WIFI_CONNECTED_BIT) {
        ESP_LOGI(LOG_TAG_WIFI, "Connected: SSID=%s ch=%d", WIFI_SSID, CSI_WIFI_CHANNEL);
    } else {
        ESP_LOGE(LOG_TAG_WIFI, "Connection failed — rebooting");
        esp_restart();
    }
}

// ── UDP socket ────────────────────────────────────────────────────────────────

static void init_udp_socket(void)
{
    s_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (s_sock < 0) {
        ESP_LOGE(LOG_TAG_UDP, "socket() failed: %d", errno);
        esp_restart();
    }

    // Resolve aggregator hostname via DNS
    struct addrinfo hints = { .ai_family = AF_INET, .ai_socktype = SOCK_DGRAM };
    struct addrinfo *res  = NULL;
    int err = getaddrinfo(AGGREGATOR_HOST, NULL, &hints, &res);
    if (err != 0 || res == NULL) {
        ESP_LOGE(LOG_TAG_UDP, "DNS lookup failed for %s: %d", AGGREGATOR_HOST, err);
        esp_restart();
    }

    memcpy(&s_agg_addr, res->ai_addr, sizeof(s_agg_addr));
    s_agg_addr.sin_port = htons(AGGREGATOR_PORT);
    freeaddrinfo(res);

    char ip_str[16];
    inet_ntoa_r(s_agg_addr.sin_addr, ip_str, sizeof(ip_str));
    ESP_LOGI(LOG_TAG_UDP, "Aggregator: %s → %s:%d", AGGREGATOR_HOST, ip_str, AGGREGATOR_PORT);
}

// ── CSI callback (runs in Wi-Fi task context — must be fast) ──────────────────

static void csi_callback(void *ctx, wifi_csi_info_t *info)
{
    if (!info || !info->buf || info->len == 0) return;

    csi_entry_t entry = {0};

    memcpy(entry.tx_mac, info->mac, 6);
    entry.rssi           = info->rx_ctrl.rssi;
    entry.noise_floor    = info->rx_ctrl.noise_floor;
    entry.channel        = info->rx_ctrl.channel;
    entry.bandwidth_mhz  = (info->rx_ctrl.cwb == 1) ? 40 : 20;
    entry.timestamp_us   = (uint32_t)(esp_timer_get_time() & 0xFFFFFFFF);

    // CSI buf layout: alternating imaginary, real pairs (int8)
    // Total length = 2 * antenna_count * subcarrier_count
    int n_complex = info->len / 2;  // number of complex samples per antenna

    // Determine antenna count from secondary channel info
    uint16_t antennas = 1;
    if (info->rx_ctrl.secondary_channel != WIFI_SECOND_CHAN_NONE) antennas = 2;

    uint16_t subcarriers = (uint16_t)(n_complex / antennas);
    if (subcarriers > MAX_SUBCARRIERS) subcarriers = MAX_SUBCARRIERS;
    if (antennas > MAX_ANTENNAS) antennas = MAX_ANTENNAS;

    entry.antenna_count    = antennas;
    entry.subcarrier_count = subcarriers;

    int total = antennas * subcarriers;
    for (int i = 0; i < total && i * 2 + 1 < info->len; i++) {
        int8_t imag = info->buf[i * 2];
        int8_t real = info->buf[i * 2 + 1];
        entry.amplitude[i] = sqrtf((float)(real * real) + (float)(imag * imag));
        entry.phase[i]     = atan2f((float)imag, (float)real);
    }

    xQueueSend(s_csi_queue, &entry, 0);  // drop if queue full
}

static void enable_csi(void)
{
    wifi_csi_config_t csi_cfg = {
        .lltf_en           = true,
        .htltf_en          = true,
        .stbc_htltf2_en    = true,
        .ltf_merge_en      = true,
        .channel_filter_en = true,
        .manu_scale        = false,
    };
    ESP_ERROR_CHECK(esp_wifi_set_csi_config(&csi_cfg));
    ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(csi_callback, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_csi(true));
    ESP_LOGI(LOG_TAG_CSI, "CSI capture enabled");
}

// ── UDP send task ─────────────────────────────────────────────────────────────

// Wire packet header (44 bytes, little-endian)
typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint16_t version;
    char     receiver_name[16];
    uint8_t  tx_mac[6];
    int16_t  rssi;
    int16_t  noise_floor;
    uint16_t channel;
    uint16_t bandwidth_mhz;
    uint16_t antenna_count;
    uint16_t subcarrier_count;
    uint32_t timestamp_us;
} csi_packet_header_t;

_Static_assert(sizeof(csi_packet_header_t) == HEADER_SIZE, "Header size mismatch");

static void udp_send_task(void *pv)
{
    csi_entry_t entry;
    // Max packet: header + 2 float arrays
    static uint8_t pkt_buf[HEADER_SIZE + MAX_ANTENNAS * MAX_SUBCARRIERS * 4 * 2];

    while (1) {
        if (xQueueReceive(s_csi_queue, &entry, portMAX_DELAY) != pdTRUE) continue;

        int n_values = entry.antenna_count * entry.subcarrier_count;
        int pkt_len  = HEADER_SIZE + n_values * 4 * 2;

        csi_packet_header_t *hdr = (csi_packet_header_t *)pkt_buf;
        hdr->magic           = PACKET_MAGIC;
        hdr->version         = PACKET_VERSION;
        memset(hdr->receiver_name, 0, sizeof(hdr->receiver_name));
        strncpy(hdr->receiver_name, RECEIVER_NAME, sizeof(hdr->receiver_name) - 1);
        memcpy(hdr->tx_mac, entry.tx_mac, 6);
        hdr->rssi            = (int16_t)entry.rssi;
        hdr->noise_floor     = (int16_t)entry.noise_floor;
        hdr->channel         = entry.channel;
        hdr->bandwidth_mhz   = entry.bandwidth_mhz;
        hdr->antenna_count   = entry.antenna_count;
        hdr->subcarrier_count = entry.subcarrier_count;
        hdr->timestamp_us    = entry.timestamp_us;

        float *amp_out   = (float *)(pkt_buf + HEADER_SIZE);
        float *phase_out = (float *)(pkt_buf + HEADER_SIZE + n_values * 4);
        memcpy(amp_out,   entry.amplitude, n_values * 4);
        memcpy(phase_out, entry.phase,     n_values * 4);

        int sent = sendto(s_sock, pkt_buf, pkt_len, 0,
                          (struct sockaddr *)&s_agg_addr, sizeof(s_agg_addr));
        if (sent < 0) {
            ESP_LOGW(LOG_TAG_UDP, "sendto failed: %d", errno);
        } else {
            ESP_LOGD(LOG_TAG_UDP, "Sent %d bytes (%d subcarriers × %d ant)",
                     sent, entry.subcarrier_count, entry.antenna_count);
        }
    }
}

// ── Entry point ───────────────────────────────────────────────────────────────

void app_main(void)
{
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    ESP_LOGI(LOG_TAG_WIFI, "=== CSI Receiver: %s ===", RECEIVER_NAME);

    s_csi_queue = xQueueCreate(CSI_QUEUE_LEN, sizeof(csi_entry_t));

    wifi_init_sta();
    init_udp_socket();
    enable_csi();

    xTaskCreate(udp_send_task, "udp_send", 8192, NULL, 10, NULL);

    ESP_LOGI(LOG_TAG_CSI, "Streaming CSI → %s:%d", AGGREGATOR_HOST, AGGREGATOR_PORT);
}
