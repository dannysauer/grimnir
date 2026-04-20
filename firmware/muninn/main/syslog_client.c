#include "syslog_client.h"

#include <ctype.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "esp_log.h"
#include "esp_random.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "lwip/dns.h"
#include "lwip/ip_addr.h"
#include "lwip/netdb.h"
#include "lwip/sockets.h"

#include "../../config.h"

#define LOG_TAG_SYSLOG "CSI_SYSLOG"

#define DNS_PORT                53
#define DNS_PACKET_MAX          512
#define DNS_HEADER_SIZE         12
#define DNS_TYPE_SRV            33
#define DNS_CLASS_IN            1
#define DNS_FLAG_RD             0x0100
#define DNS_RCODE_MASK          0x000F
#define DNS_QUERY_TIMEOUT_MS    2000
#define DNS_MAX_LABEL_LEN       63
#define DNS_MAX_NAME_LEN        256
#define SYSLOG_QUEUE_LEN        32
#define SYSLOG_LINE_MAX         256
#define SYSLOG_PACKET_MAX       384
#define SYSLOG_APP_NAME         "muninn"
#define SYSLOG_FACILITY_USER    1

typedef struct {
    char line[SYSLOG_LINE_MAX];
} syslog_line_t;

typedef struct {
    uint16_t priority;
    uint16_t weight;
    uint16_t port;
    char     target[DNS_MAX_NAME_LEN];
} srv_record_t;

static QueueHandle_t    s_syslog_queue = NULL;
static int              s_syslog_sock = -1;
static struct sockaddr_in s_syslog_addr;
static char             s_receiver_name[RECEIVER_NAME_MAX_LEN + 1];
static vprintf_like_t   s_orig_vprintf = NULL;

static uint16_t read_be16(const uint8_t *buf)
{
    return (uint16_t)((buf[0] << 8) | buf[1]);
}

static void write_be16(uint8_t *buf, uint16_t value)
{
    buf[0] = (uint8_t)(value >> 8);
    buf[1] = (uint8_t)(value & 0xFF);
}

static bool is_ipv4_literal(const char *host)
{
    int dots = 0;
    if (host == NULL || *host == '\0') {
        return false;
    }
    for (const char *p = host; *p; ++p) {
        if (*p == '.') {
            ++dots;
            continue;
        }
        if (!isdigit((unsigned char)*p)) {
            return false;
        }
    }
    return dots == 3;
}

static void trim_trailing_dot(char *value)
{
    size_t len = strlen(value);
    while (len > 0 && value[len - 1] == '.') {
        value[len - 1] = '\0';
        --len;
    }
}

static bool get_syslog_domain(char *out, size_t out_len)
{
    if (SYSLOG_DISCOVERY_DOMAIN[0] != '\0') {
        snprintf(out, out_len, "%s", SYSLOG_DISCOVERY_DOMAIN);
        trim_trailing_dot(out);
        return out[0] != '\0';
    }

    if (is_ipv4_literal(AGGREGATOR_HOST)) {
        return false;
    }

    const char *dot = strchr(AGGREGATOR_HOST, '.');
    if (dot == NULL || dot[1] == '\0') {
        return false;
    }

    snprintf(out, out_len, "%s", dot + 1);
    trim_trailing_dot(out);
    return out[0] != '\0';
}

static int encode_dns_name(uint8_t *buf, size_t buf_len, const char *name)
{
    size_t offset = 0;
    const char *label = name;

    while (*label != '\0') {
        const char *dot = strchr(label, '.');
        size_t label_len = (dot == NULL) ? strlen(label) : (size_t)(dot - label);
        if (label_len == 0 || label_len > DNS_MAX_LABEL_LEN || offset + label_len + 1 >= buf_len) {
            return -1;
        }
        buf[offset++] = (uint8_t)label_len;
        memcpy(buf + offset, label, label_len);
        offset += label_len;
        if (dot == NULL) {
            break;
        }
        label = dot + 1;
    }

    if (offset >= buf_len) {
        return -1;
    }
    buf[offset++] = 0;
    return (int)offset;
}

static int dns_skip_name(const uint8_t *packet, size_t packet_len, size_t offset, size_t *next_offset)
{
    size_t current = offset;
    int jumps = 0;

    while (current < packet_len) {
        uint8_t len = packet[current];
        if (len == 0) {
            *next_offset = current + 1;
            return 0;
        }
        if ((len & 0xC0) == 0xC0) {
            if (current + 1 >= packet_len || ++jumps > 16) {
                return -1;
            }
            *next_offset = current + 2;
            return 0;
        }
        if ((len & 0xC0) != 0 || current + 1 + len > packet_len) {
            return -1;
        }
        current += 1 + len;
    }

    return -1;
}

static int dns_read_name(
    const uint8_t *packet,
    size_t packet_len,
    size_t offset,
    char *out,
    size_t out_len,
    size_t *next_offset
)
{
    size_t current = offset;
    size_t written = 0;
    bool jumped = false;

    if (out_len == 0) {
        return -1;
    }

    for (int jumps = 0; current < packet_len && jumps < 32; ++jumps) {
        uint8_t len = packet[current];
        if (len == 0) {
            if (!jumped) {
                *next_offset = current + 1;
            }
            out[written] = '\0';
            return 0;
        }

        if ((len & 0xC0) == 0xC0) {
            if (current + 1 >= packet_len) {
                return -1;
            }
            uint16_t pointer = (uint16_t)(((len & 0x3F) << 8) | packet[current + 1]);
            if (!jumped) {
                *next_offset = current + 2;
                jumped = true;
            }
            if (pointer >= packet_len) {
                return -1;
            }
            current = pointer;
            continue;
        }

        if ((len & 0xC0) != 0 || current + 1 + len > packet_len) {
            return -1;
        }

        if (written != 0) {
            if (written + 1 >= out_len) {
                return -1;
            }
            out[written++] = '.';
        }
        if (written + len >= out_len) {
            return -1;
        }

        memcpy(out + written, packet + current + 1, len);
        written += len;
        current += 1 + len;
    }

    return -1;
}

static bool choose_srv_record(const srv_record_t *candidate, srv_record_t *best, bool *have_best)
{
    if (!*have_best) {
        *best = *candidate;
        *have_best = true;
        return true;
    }

    if (candidate->priority < best->priority) {
        *best = *candidate;
        return true;
    }
    if (candidate->priority == best->priority && candidate->weight > best->weight) {
        *best = *candidate;
        return true;
    }

    return false;
}

static bool query_srv_record(const char *service_name, char *target_out, size_t target_len, uint16_t *port_out)
{
    uint8_t packet[DNS_PACKET_MAX] = {0};
    uint16_t query_id = (uint16_t)esp_random();
    size_t query_len = DNS_HEADER_SIZE;
    int encoded_len = encode_dns_name(packet + query_len, sizeof(packet) - query_len, service_name);
    if (encoded_len < 0) {
        return false;
    }
    query_len += (size_t)encoded_len;
    if (query_len + 4 > sizeof(packet)) {
        return false;
    }

    write_be16(packet + 0, query_id);
    write_be16(packet + 2, DNS_FLAG_RD);
    write_be16(packet + 4, 1);
    write_be16(packet + query_len, DNS_TYPE_SRV);
    write_be16(packet + query_len + 2, DNS_CLASS_IN);
    query_len += 4;

    for (uint8_t i = 0; i < DNS_MAX_SERVERS; ++i) {
        const ip_addr_t *dns_server = dns_getserver(i);
        if (dns_server == NULL || ip_addr_isany(dns_server)) {
            continue;
        }

        char dns_ip[INET6_ADDRSTRLEN] = {0};
        if (ipaddr_ntoa_r(dns_server, dns_ip, sizeof(dns_ip)) == NULL || dns_ip[0] == '\0') {
            continue;
        }

        int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
        if (sock < 0) {
            continue;
        }

        struct timeval timeout = {
            .tv_sec = DNS_QUERY_TIMEOUT_MS / 1000,
            .tv_usec = (DNS_QUERY_TIMEOUT_MS % 1000) * 1000,
        };
        (void)setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));

        struct sockaddr_in dns_addr = {
            .sin_family = AF_INET,
            .sin_port = htons(DNS_PORT),
        };
        dns_addr.sin_addr.s_addr = inet_addr(dns_ip);

        if (sendto(sock, packet, query_len, 0, (struct sockaddr *)&dns_addr, sizeof(dns_addr)) < 0) {
            close(sock);
            continue;
        }

        uint8_t response[DNS_PACKET_MAX] = {0};
        int received = recvfrom(sock, response, sizeof(response), 0, NULL, NULL);
        close(sock);
        if (received < DNS_HEADER_SIZE) {
            continue;
        }

        uint16_t response_id = read_be16(response + 0);
        uint16_t flags = read_be16(response + 2);
        uint16_t qdcount = read_be16(response + 4);
        uint16_t ancount = read_be16(response + 6);
        if (response_id != query_id || (flags & DNS_RCODE_MASK) != 0 || ancount == 0) {
            continue;
        }

        size_t offset = DNS_HEADER_SIZE;
        bool malformed = false;
        for (uint16_t q = 0; q < qdcount; ++q) {
            if (dns_skip_name(response, (size_t)received, offset, &offset) != 0 || offset + 4 > (size_t)received) {
                malformed = true;
                break;
            }
            offset += 4;
        }
        if (malformed) {
            continue;
        }

        srv_record_t best = {0};
        bool have_best = false;
        for (uint16_t a = 0; a < ancount && offset < (size_t)received; ++a) {
            if (dns_skip_name(response, (size_t)received, offset, &offset) != 0 || offset + 10 > (size_t)received) {
                malformed = true;
                break;
            }

            uint16_t type = read_be16(response + offset);
            uint16_t rr_class = read_be16(response + offset + 2);
            uint16_t rdlength = read_be16(response + offset + 8);
            offset += 10;

            if (offset + rdlength > (size_t)received) {
                malformed = true;
                break;
            }

            if (type == DNS_TYPE_SRV && rr_class == DNS_CLASS_IN && rdlength >= 7) {
                srv_record_t candidate = {
                    .priority = read_be16(response + offset),
                    .weight = read_be16(response + offset + 2),
                    .port = read_be16(response + offset + 4),
                };
                size_t ignored = 0;
                if (dns_read_name(
                        response,
                        (size_t)received,
                        offset + 6,
                        candidate.target,
                        sizeof(candidate.target),
                        &ignored
                    ) == 0) {
                    trim_trailing_dot(candidate.target);
                    (void)choose_srv_record(&candidate, &best, &have_best);
                }
            }

            offset += rdlength;
        }

        if (!malformed && have_best) {
            snprintf(target_out, target_len, "%s", best.target);
            *port_out = best.port;
            return true;
        }
    }

    return false;
}

static bool resolve_syslog_endpoint(struct sockaddr_in *addr_out, char *service_name, size_t service_len)
{
    char domain[DNS_MAX_NAME_LEN] = {0};
    if (!get_syslog_domain(domain, sizeof(domain))) {
        ESP_LOGW(
            LOG_TAG_SYSLOG,
            "Remote syslog disabled: no discovery domain (set SYSLOG_DISCOVERY_DOMAIN or use an FQDN AGGREGATOR_HOST)"
        );
        return false;
    }

    snprintf(service_name, service_len, "_syslog._udp.%s", domain);

    char target[DNS_MAX_NAME_LEN] = {0};
    uint16_t port = 0;
    if (!query_srv_record(service_name, target, sizeof(target), &port)) {
        ESP_LOGW(LOG_TAG_SYSLOG, "Remote syslog disabled: no SRV record for %s", service_name);
        return false;
    }

    struct addrinfo hints = {
        .ai_family = AF_INET,
        .ai_socktype = SOCK_DGRAM,
    };
    struct addrinfo *res = NULL;
    if (getaddrinfo(target, NULL, &hints, &res) != 0 || res == NULL) {
        ESP_LOGW(LOG_TAG_SYSLOG, "Remote syslog disabled: failed to resolve %s", target);
        return false;
    }

    memcpy(addr_out, res->ai_addr, sizeof(*addr_out));
    addr_out->sin_port = htons(port);
    freeaddrinfo(res);

    char ip_str[16] = {0};
    inet_ntoa_r(addr_out->sin_addr, ip_str, sizeof(ip_str));
    ESP_LOGI(LOG_TAG_SYSLOG, "Remote syslog via %s -> %s:%u (%s)", service_name, target, port, ip_str);
    return true;
}

static int syslog_severity_from_line(const char *line)
{
    switch (line[0]) {
        case 'E':
            return 3;
        case 'W':
            return 4;
        case 'D':
        case 'V':
            return 7;
        case 'I':
        default:
            return 6;
    }
}

static void sanitize_log_line(const char *input, char *output, size_t output_len)
{
    bool in_escape = false;
    size_t written = 0;

    if (output_len == 0) {
        return;
    }

    for (const unsigned char *src = (const unsigned char *)input; *src != '\0'; ++src) {
        unsigned char ch = *src;

        if (in_escape) {
            if (ch >= '@' && ch <= '~') {
                in_escape = false;
            }
            continue;
        }

        if (ch == '\x1B') {
            in_escape = true;
            continue;
        }
        if (ch == '\r' || ch == '\n') {
            continue;
        }
        if (!isprint(ch) && ch != '\t') {
            continue;
        }
        if (written + 1 >= output_len) {
            break;
        }
        output[written++] = (char)ch;
    }

    while (written > 0 && isspace((unsigned char)output[written - 1])) {
        --written;
    }
    output[written] = '\0';
}

static void syslog_send_task(void *pv)
{
    syslog_line_t line = {0};
    char packet[SYSLOG_PACKET_MAX] = {0};

    while (1) {
        if (xQueueReceive(s_syslog_queue, &line, portMAX_DELAY) != pdTRUE) {
            continue;
        }

        int severity = syslog_severity_from_line(line.line);
        int priority = (SYSLOG_FACILITY_USER * 8) + severity;
        int packet_len = snprintf(
            packet,
            sizeof(packet),
            "<%d>1 - %s %s - - - %s",
            priority,
            s_receiver_name,
            SYSLOG_APP_NAME,
            line.line
        );
        if (packet_len <= 0) {
            continue;
        }
        if ((size_t)packet_len >= sizeof(packet)) {
            packet_len = (int)sizeof(packet) - 1;
        }
        (void)sendto(
            s_syslog_sock,
            packet,
            (size_t)packet_len,
            0,
            (struct sockaddr *)&s_syslog_addr,
            sizeof(s_syslog_addr)
        );
    }
}

static int syslog_vprintf(const char *format, va_list args)
{
    va_list copy;
    va_copy(copy, args);
    int written = s_orig_vprintf ? s_orig_vprintf(format, args) : vprintf(format, args);

    if (
        s_syslog_queue != NULL &&
        xTaskGetSchedulerState() == taskSCHEDULER_RUNNING &&
        !xPortInIsrContext()
    ) {
        char rendered[SYSLOG_LINE_MAX] = {0};
        syslog_line_t line = {0};
        if (vsnprintf(rendered, sizeof(rendered), format, copy) > 0) {
            sanitize_log_line(rendered, line.line, sizeof(line.line));
            if (line.line[0] != '\0') {
                (void)xQueueSend(s_syslog_queue, &line, 0);
            }
        }
    }

    va_end(copy);
    return written;
}

bool syslog_client_init(const char *receiver_name)
{
    char service_name[DNS_MAX_NAME_LEN] = {0};
    if (!resolve_syslog_endpoint(&s_syslog_addr, service_name, sizeof(service_name))) {
        return false;
    }

    s_syslog_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (s_syslog_sock < 0) {
        ESP_LOGW(LOG_TAG_SYSLOG, "Remote syslog disabled: socket() failed");
        return false;
    }

    s_syslog_queue = xQueueCreate(SYSLOG_QUEUE_LEN, sizeof(syslog_line_t));
    if (s_syslog_queue == NULL) {
        close(s_syslog_sock);
        s_syslog_sock = -1;
        ESP_LOGW(LOG_TAG_SYSLOG, "Remote syslog disabled: queue allocation failed");
        return false;
    }

    snprintf(s_receiver_name, sizeof(s_receiver_name), "%s", receiver_name);
    xTaskCreate(syslog_send_task, "syslog_send", 4096, NULL, 7, NULL);
    s_orig_vprintf = esp_log_set_vprintf(syslog_vprintf);
    ESP_LOGI(LOG_TAG_SYSLOG, "Remote syslog capture enabled");
    return true;
}
