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
//   [4..5]    version   uint16  2
//   [6..37]   name      char[32] null-padded receiver name
//   [38..43]  tx_mac    uint8[6] transmitter MAC
//   [44..45]  rssi      int16   dBm
//   [46..47]  noise     int16   dBm
//   [48..49]  channel   uint16
//   [50..51]  bw        uint16  MHz
//   [52..53]  antennas  uint16
//   [54..55]  subcarriers uint16
//   [56..59]  ts_us     uint32  device uptime micros
//   [60..N]   amplitude float32[] antenna_count * subcarrier_count
//   [N..M]    phase     float32[] antenna_count * subcarrier_count
// =============================================================================

#include <errno.h>
#include <stdbool.h>
#include <math.h>
#include <stdio.h>
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
#include "syslog_client.h"

// ── Constants ─────────────────────────────────────────────────────────────────
#define PACKET_MAGIC       0x43534921U
#define PACKET_VERSION     2
#define MAX_SUBCARRIERS    128
#define MAX_ANTENNAS       4
#define CSI_QUEUE_LEN      32
#define HEADER_SIZE        60
#define ACK_PAYLOAD        "grimnir-ack"
#define ACK_PAYLOAD_LEN    11
#define WIFI_SCAN_MAX_APS  16

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
static QueueHandle_t      s_csi_free_queue;
static csi_entry_t        s_csi_pool[CSI_QUEUE_LEN];
static int                s_sock = -1;
static struct sockaddr_in s_agg_addr;
static int                s_retry_count = 0;
static volatile int64_t   s_last_raw_csi_us = 0;
static volatile int64_t   s_last_csi_us = 0;
static volatile int64_t   s_first_unacked_csi_us = 0;
static volatile int64_t   s_last_ack_us = 0;
static volatile bool      s_ack_watchdog_armed = false;
static volatile int       s_last_send_errno = 0;
static volatile uint32_t  s_send_success_count = 0;
static volatile uint32_t  s_send_error_count = 0;
static volatile uint32_t  s_raw_csi_count = 0;
static volatile uint32_t  s_huginn_csi_count = 0;
static volatile uint32_t  s_unmatched_csi_count = 0;
static uint8_t            s_last_unmatched_mac[6] = {0};
static volatile uint16_t  s_last_unmatched_channel = 0;
static volatile int8_t    s_last_unmatched_rssi = 0;
static volatile bool      s_transport_reset_in_progress = false;

static void clear_ack_watchdog_state(void)
{
    s_ack_watchdog_armed = false;
    s_last_ack_us = 0;
    s_first_unacked_csi_us = 0;
}

static void format_mac(char *out, size_t out_len, const uint8_t mac[6])
{
    snprintf(
        out,
        out_len,
        "%02x:%02x:%02x:%02x:%02x:%02x",
        mac[0],
        mac[1],
        mac[2],
        mac[3],
        mac[4],
        mac[5]
    );
}

// ── Wi-Fi ─────────────────────────────────────────────────────────────────────

static void wifi_event_handler(void *arg, esp_event_base_t base,
                                int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        ESP_LOGI(LOG_TAG_WIFI, "Wi-Fi station started");
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
        clear_ack_watchdog_state();
        s_last_raw_csi_us = 0;
        s_last_csi_us = 0;
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
        xEventGroupClearBits(s_wifi_event_group, WIFI_FAIL_BIT);
        xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
    }
}

static void pin_wifi_bssid_on_csi_channel(wifi_config_t *wifi_cfg)
{
    if (CSI_WIFI_CHANNEL == 0) {
        return;
    }

    wifi_scan_config_t scan_cfg = {
        .ssid = (uint8_t *)WIFI_SSID,
        .channel = CSI_WIFI_CHANNEL,
        .show_hidden = false,
    };

    ESP_LOGI(
        LOG_TAG_WIFI,
        "Scanning for SSID=%s on CSI channel %d",
        WIFI_SSID,
        CSI_WIFI_CHANNEL
    );
    esp_err_t scan_result = esp_wifi_scan_start(&scan_cfg, true);
    if (scan_result != ESP_OK) {
        ESP_LOGE(LOG_TAG_WIFI, "Wi-Fi scan failed: %s", esp_err_to_name(scan_result));
        esp_restart();
    }

    wifi_ap_record_t records[WIFI_SCAN_MAX_APS] = {0};
    uint16_t record_count = WIFI_SCAN_MAX_APS;
    ESP_ERROR_CHECK(esp_wifi_scan_get_ap_records(&record_count, records));

    if (record_count == 0) {
        ESP_LOGE(
            LOG_TAG_WIFI,
            "No AP named %s found on CSI channel %d",
            WIFI_SSID,
            CSI_WIFI_CHANNEL
        );
        esp_restart();
    }

    wifi_ap_record_t *best = &records[0];
    for (uint16_t i = 1; i < record_count; ++i) {
        if (records[i].rssi > best->rssi) {
            best = &records[i];
        }
    }

    char bssid_str[18];
    format_mac(bssid_str, sizeof(bssid_str), best->bssid);
    ESP_LOGI(
        LOG_TAG_WIFI,
        "Selected AP bssid=%s primary_ch=%u rssi=%d",
        bssid_str,
        best->primary,
        best->rssi
    );

    wifi_cfg->sta.channel = best->primary;
    wifi_cfg->sta.bssid_set = true;
    memcpy(wifi_cfg->sta.bssid, best->bssid, sizeof(wifi_cfg->sta.bssid));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, wifi_cfg));
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
    pin_wifi_bssid_on_csi_channel(&wifi_cfg);
    ESP_ERROR_CHECK(esp_wifi_connect());

    EventBits_t bits = xEventGroupWaitBits(
        s_wifi_event_group, WIFI_CONNECTED_BIT | WIFI_FAIL_BIT,
        pdFALSE, pdFALSE, portMAX_DELAY);

    if (bits & WIFI_CONNECTED_BIT) {
        wifi_ap_record_t ap_info = {0};
        if (esp_wifi_sta_get_ap_info(&ap_info) == ESP_OK) {
            char bssid_str[18];
            format_mac(bssid_str, sizeof(bssid_str), ap_info.bssid);
            ESP_LOGI(
                LOG_TAG_WIFI,
                "Connected: SSID=%s bssid=%s primary_ch=%u rssi=%d",
                WIFI_SSID,
                bssid_str,
                ap_info.primary,
                ap_info.rssi
            );
        } else {
            ESP_LOGI(LOG_TAG_WIFI, "Connected: SSID=%s", WIFI_SSID);
        }
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

    struct sockaddr_in local_addr = {
        .sin_family = AF_INET,
        .sin_port = htons(0),
        .sin_addr.s_addr = htonl(INADDR_ANY),
    };
    if (bind(s_sock, (struct sockaddr *)&local_addr, sizeof(local_addr)) < 0) {
        ESP_LOGE(LOG_TAG_UDP, "bind() failed: %d (%s)", errno, strerror(errno));
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
    struct sockaddr_in bound_addr = {0};
    socklen_t bound_len = sizeof(bound_addr);
    if (getsockname(s_sock, (struct sockaddr *)&bound_addr, &bound_len) == 0) {
        ESP_LOGI(
            LOG_TAG_UDP,
            "Aggregator: %s → %s:%d (local UDP %u)",
            AGGREGATOR_HOST,
            ip_str,
            AGGREGATOR_PORT,
            ntohs(bound_addr.sin_port)
        );
    } else {
        ESP_LOGI(LOG_TAG_UDP, "Aggregator: %s → %s:%d", AGGREGATOR_HOST, ip_str, AGGREGATOR_PORT);
    }
}

static void reset_udp_transport(const char *reason)
{
    if (s_transport_reset_in_progress) {
        return;
    }

    s_transport_reset_in_progress = true;
    ESP_LOGW(LOG_TAG_UDP, "Resetting UDP transport: %s", reason);

    clear_ack_watchdog_state();
    s_last_send_errno = 0;

    int old_sock = s_sock;
    s_sock = -1;
    if (old_sock >= 0) {
        close(old_sock);
    }

    init_udp_socket();
    s_transport_reset_in_progress = false;
}

// ── CSI callback (runs in Wi-Fi task context — must be fast) ──────────────────

static void csi_callback(void *ctx, wifi_csi_info_t *info)
{
    if (!info || !info->buf || info->len == 0) return;

    s_last_raw_csi_us = esp_timer_get_time();
    ++s_raw_csi_count;

    // Only process CSI from the Huginn transmitter — drop all ambient traffic.
    static const uint8_t huginn_mac[6] = HUGINN_MAC;
    if (memcmp(info->mac, huginn_mac, 6) != 0) {
        ++s_unmatched_csi_count;
        memcpy(s_last_unmatched_mac, info->mac, sizeof(s_last_unmatched_mac));
        s_last_unmatched_channel = info->rx_ctrl.channel;
        s_last_unmatched_rssi = info->rx_ctrl.rssi;
        return;
    }
    ++s_huginn_csi_count;

    int64_t now_us = esp_timer_get_time();
    if (s_last_csi_us == 0) {
        char mac_str[18];
        format_mac(mac_str, sizeof(mac_str), info->mac);
        ESP_LOGI(LOG_TAG_CSI, "Huginn CSI detected from %s", mac_str);
    }
    s_last_csi_us = now_us;
    if (s_first_unacked_csi_us == 0) {
        s_first_unacked_csi_us = now_us;
    }

    csi_entry_t *entry = NULL;
    if (xQueueReceive(s_csi_free_queue, &entry, 0) != pdTRUE || entry == NULL) {
        return;
    }
    memset(entry, 0, sizeof(*entry));

    memcpy(entry->tx_mac, info->mac, 6);
    entry->rssi           = info->rx_ctrl.rssi;
    entry->noise_floor    = info->rx_ctrl.noise_floor;
    entry->channel        = info->rx_ctrl.channel;
    entry->bandwidth_mhz  = (info->rx_ctrl.cwb == 1) ? 40 : 20;
    entry->timestamp_us   = (uint32_t)(esp_timer_get_time() & 0xFFFFFFFF);

    // CSI buf layout: alternating imaginary, real pairs (int8)
    // Total length = 2 * antenna_count * subcarrier_count
    int n_complex = info->len / 2;  // number of complex samples per antenna

    // Determine antenna count from secondary channel info
    uint16_t antennas = 1;
    if (info->rx_ctrl.secondary_channel != WIFI_SECOND_CHAN_NONE) antennas = 2;

    uint16_t subcarriers = (uint16_t)(n_complex / antennas);
    if (subcarriers > MAX_SUBCARRIERS) subcarriers = MAX_SUBCARRIERS;
    if (antennas > MAX_ANTENNAS) antennas = MAX_ANTENNAS;

    entry->antenna_count    = antennas;
    entry->subcarrier_count = subcarriers;

    int total = antennas * subcarriers;
    for (int i = 0; i < total && i * 2 + 1 < info->len; i++) {
        int8_t imag = info->buf[i * 2];
        int8_t real = info->buf[i * 2 + 1];
        entry->amplitude[i] = sqrtf((float)(real * real) + (float)(imag * imag));
        entry->phase[i]     = atan2f((float)imag, (float)real);
    }

    if (xQueueSend(s_csi_queue, &entry, 0) != pdTRUE) {
        xQueueSend(s_csi_free_queue, &entry, 0);
    }
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
    char     receiver_name[RECEIVER_NAME_MAX_LEN];
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
_Static_assert(
    sizeof(RECEIVER_NAME) <= RECEIVER_NAME_MAX_LEN + 1,
    "RECEIVER_NAME is longer than the on-wire header field"
);

static void udp_send_task(void *pv)
{
    csi_entry_t *entry = NULL;
    // Max packet: header + 2 float arrays
    static uint8_t pkt_buf[HEADER_SIZE + MAX_ANTENNAS * MAX_SUBCARRIERS * 4 * 2];

    while (1) {
        if (xQueueReceive(s_csi_queue, &entry, portMAX_DELAY) != pdTRUE) continue;
        if (entry == NULL) continue;
        if (s_sock < 0) {
            xQueueSend(s_csi_free_queue, &entry, portMAX_DELAY);
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }

        int n_values = entry->antenna_count * entry->subcarrier_count;
        int pkt_len  = HEADER_SIZE + n_values * 4 * 2;

        csi_packet_header_t *hdr = (csi_packet_header_t *)pkt_buf;
        hdr->magic           = PACKET_MAGIC;
        hdr->version         = PACKET_VERSION;
        memset(hdr->receiver_name, 0, sizeof(hdr->receiver_name));
        strncpy(hdr->receiver_name, RECEIVER_NAME, sizeof(hdr->receiver_name) - 1);
        memcpy(hdr->tx_mac, entry->tx_mac, 6);
        hdr->rssi            = (int16_t)entry->rssi;
        hdr->noise_floor     = (int16_t)entry->noise_floor;
        hdr->channel         = entry->channel;
        hdr->bandwidth_mhz   = entry->bandwidth_mhz;
        hdr->antenna_count   = entry->antenna_count;
        hdr->subcarrier_count = entry->subcarrier_count;
        hdr->timestamp_us    = entry->timestamp_us;

        float *amp_out   = (float *)(pkt_buf + HEADER_SIZE);
        float *phase_out = (float *)(pkt_buf + HEADER_SIZE + n_values * 4);
        memcpy(amp_out,   entry->amplitude, n_values * 4);
        memcpy(phase_out, entry->phase,     n_values * 4);

        int sock = s_sock;
        int sent = sendto(sock, pkt_buf, pkt_len, 0,
                          (struct sockaddr *)&s_agg_addr, sizeof(s_agg_addr));
        if (sent < 0) {
            int send_errno = errno;
            s_last_send_errno = send_errno;
            ++s_send_error_count;
            ESP_LOGW(LOG_TAG_UDP, "sendto failed: %d (%s)", send_errno, strerror(send_errno));

            if (sock == s_sock && send_errno != EINTR) {
                reset_udp_transport("send error");
            }

            vTaskDelay(pdMS_TO_TICKS(100));
        } else {
            ++s_send_success_count;
            ESP_LOGD(LOG_TAG_UDP, "Sent %d bytes (%d subcarriers × %d ant)",
                     sent, entry->subcarrier_count, entry->antenna_count);
        }
        xQueueSend(s_csi_free_queue, &entry, portMAX_DELAY);
    }
}

static void udp_ack_task(void *pv)
{
    uint8_t buf[64];

    while (1) {
        int sock = s_sock;
        if (sock < 0) {
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }

        int received = recvfrom(sock, buf, sizeof(buf), 0, NULL, NULL);
        if (received < 0) {
            int recv_errno = errno;
            if (recv_errno == EINTR) continue;
            if (sock != s_sock || recv_errno == EBADF) continue;
            ESP_LOGW(LOG_TAG_UDP, "recvfrom failed: %d (%s)", recv_errno, strerror(recv_errno));
            vTaskDelay(pdMS_TO_TICKS(250));
            continue;
        }

        if (received == ACK_PAYLOAD_LEN && memcmp(buf, ACK_PAYLOAD, ACK_PAYLOAD_LEN) == 0) {
            bool first_ack = !s_ack_watchdog_armed;
            s_last_ack_us = esp_timer_get_time();
            s_ack_watchdog_armed = true;
            s_first_unacked_csi_us = 0;
            if (first_ack) {
                ESP_LOGI(LOG_TAG_UDP, "Aggregator ACKs flowing");
            }
        }
    }
}

static void receiver_watchdog_task(void *pv)
{
    const int64_t ack_timeout_us =
        (int64_t)RECEIVER_WATCHDOG_ACK_TIMEOUT_S * 1000000LL;
    const int64_t csi_grace_us =
        (int64_t)RECEIVER_WATCHDOG_CSI_GRACE_S * 1000000LL;
    const int64_t idle_log_interval_us = 30000000LL;
    int64_t last_idle_log_us = 0;

    while (1) {
        vTaskDelay(pdMS_TO_TICKS(RECEIVER_WATCHDOG_POLL_MS));

        if ((xEventGroupGetBits(s_wifi_event_group) & WIFI_CONNECTED_BIT) == 0) continue;

        int64_t now_us = esp_timer_get_time();
        if (s_last_csi_us == 0) {
            if (now_us - last_idle_log_us >= idle_log_interval_us) {
                char mac_str[18];
                format_mac(mac_str, sizeof(mac_str), s_last_unmatched_mac);
                ESP_LOGW(
                    LOG_TAG_CSI,
                    "No Huginn CSI seen since boot "
                    "(raw=%lu unmatched=%lu last_unmatched=%s ch=%u rssi=%d)",
                    (unsigned long)s_raw_csi_count,
                    (unsigned long)s_unmatched_csi_count,
                    mac_str,
                    s_last_unmatched_channel,
                    s_last_unmatched_rssi
                );
                last_idle_log_us = now_us;
            }
            continue;
        }

        if (now_us - s_last_csi_us > csi_grace_us) {
            if (now_us - last_idle_log_us >= idle_log_interval_us) {
                char mac_str[18];
                format_mac(mac_str, sizeof(mac_str), s_last_unmatched_mac);
                ESP_LOGW(
                    LOG_TAG_CSI,
                    "No Huginn CSI seen for %lld ms "
                    "(raw=%lu matched=%lu unmatched=%lu last_unmatched=%s ch=%u rssi=%d)",
                    (long long)((now_us - s_last_csi_us) / 1000LL),
                    (unsigned long)s_raw_csi_count,
                    (unsigned long)s_huginn_csi_count,
                    (unsigned long)s_unmatched_csi_count,
                    mac_str,
                    s_last_unmatched_channel,
                    s_last_unmatched_rssi
                );
                last_idle_log_us = now_us;
            }
            clear_ack_watchdog_state();
            continue;
        }

        if (!s_ack_watchdog_armed) {
            if (
                s_first_unacked_csi_us != 0 &&
                now_us - s_first_unacked_csi_us > ack_timeout_us
            ) {
                ESP_LOGW(
                    LOG_TAG_UDP,
                    "CSI is active but aggregator ACKs never started after %lld ms "
                    "(send_ok=%lu send_err=%lu last_errno=%d) — resetting transport",
                    (long long)((now_us - s_first_unacked_csi_us) / 1000LL),
                    (unsigned long)s_send_success_count,
                    (unsigned long)s_send_error_count,
                    s_last_send_errno
                );
                reset_udp_transport("ACKs never started");
            }
            continue;
        }

        if (s_last_ack_us != 0 && now_us - s_last_ack_us <= ack_timeout_us) {
            continue;
        }

        ESP_LOGW(
            LOG_TAG_UDP,
            "No aggregator ACK for %lld ms while CSI is still active "
            "(send_ok=%lu send_err=%lu last_errno=%d) — resetting transport",
            (long long)((now_us - s_last_ack_us) / 1000LL),
            (unsigned long)s_send_success_count,
            (unsigned long)s_send_error_count,
            s_last_send_errno
        );
        reset_udp_transport("ACK timeout");
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

    s_csi_queue = xQueueCreate(CSI_QUEUE_LEN, sizeof(csi_entry_t *));
    s_csi_free_queue = xQueueCreate(CSI_QUEUE_LEN, sizeof(csi_entry_t *));
    if (s_csi_queue == NULL || s_csi_free_queue == NULL) {
        ESP_LOGE(LOG_TAG_CSI, "Failed to create CSI queues");
        esp_restart();
    }
    for (size_t i = 0; i < CSI_QUEUE_LEN; ++i) {
        csi_entry_t *entry = &s_csi_pool[i];
        xQueueSend(s_csi_free_queue, &entry, 0);
    }

    wifi_init_sta();
    syslog_client_start(RECEIVER_NAME);
    init_udp_socket();
    enable_csi();

    xTaskCreate(udp_send_task, "udp_send", 8192, NULL, 10, NULL);
    xTaskCreate(udp_ack_task, "udp_ack", 4096, NULL, 9, NULL);
    xTaskCreate(receiver_watchdog_task, "rx_watchdog", 4096, NULL, 8, NULL);

    ESP_LOGI(LOG_TAG_CSI, "Streaming CSI → %s:%d", AGGREGATOR_HOST, AGGREGATOR_PORT);
}
