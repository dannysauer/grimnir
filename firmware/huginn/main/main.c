// =============================================================================
// transmitter/main/main.c — ESP32-S3 CSI Transmitter
//
// Connects to Wi-Fi on the configured channel and sends periodic UDP broadcast
// frames. Receiver ESP32-S3s capture CSI from these frames via the 802.11
// PHY layer — the packet payload content is irrelevant.
//
// Build: idf.py set-target esp32s3 && idf.py build flash monitor
// =============================================================================

#include <errno.h>
#include <string.h>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "lwip/netdb.h"
#include "lwip/sockets.h"
#include "nvs_flash.h"

#include "../../config.h"

#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT      BIT1

static EventGroupHandle_t s_wifi_event_group;
static int s_retry_count = 0;

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

// ── Transmit task ─────────────────────────────────────────────────────────────

static void transmit_task(void *pv)
{
    struct sockaddr_in dest = {
        .sin_family      = AF_INET,
        .sin_port        = htons(AGGREGATOR_PORT),
        .sin_addr.s_addr = htonl(INADDR_BROADCAST),
    };

    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (sock < 0) {
        ESP_LOGE(LOG_TAG_UDP, "socket() failed: %d", errno);
        vTaskDelete(NULL);
        return;
    }

    int bc = 1;
    setsockopt(sock, SOL_SOCKET, SO_BROADCAST, &bc, sizeof(bc));

    uint8_t payload[TX_PACKET_SIZE];
    uint32_t seq = 0;

    while (1) {
        memcpy(payload, &seq, sizeof(seq));
        memset(payload + sizeof(seq), 0xAB, TX_PACKET_SIZE - sizeof(seq));

        int sent = sendto(sock, payload, sizeof(payload), 0,
                          (struct sockaddr *)&dest, sizeof(dest));
        if (sent < 0) {
            ESP_LOGW(LOG_TAG_UDP, "sendto failed: %d", errno);
        } else {
            ESP_LOGD(LOG_TAG_UDP, "TX seq=%lu", (unsigned long)seq);
        }
        seq++;
        vTaskDelay(pdMS_TO_TICKS(TX_BEACON_INTERVAL_MS));
    }

    close(sock);
    vTaskDelete(NULL);
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

    ESP_LOGI(LOG_TAG_WIFI, "=== CSI Transmitter ===");
    wifi_init_sta();
    xTaskCreate(transmit_task, "tx_task", 4096, NULL, 5, NULL);
    ESP_LOGI(LOG_TAG_WIFI, "Transmitting beacons every %dms on ch%d",
             TX_BEACON_INTERVAL_MS, CSI_WIFI_CHANNEL);
}
