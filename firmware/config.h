// =============================================================================
// config.h — Shared configuration for CSI transmitter and receiver firmware
//
// Edit these values before flashing each board.
// =============================================================================

#pragma once

// ── Local overrides ───────────────────────────────────────────────────────────
// Copy config.local.h.example → config.local.h and fill in your values.
// config.local.h is gitignored and will never be committed.
// Included first so its defines take precedence over the defaults below.
#if __has_include("config.local.h")
#  include "config.local.h"
#endif

// ── Wi-Fi ────────────────────────────────────────────────────────────────────
#ifndef WIFI_SSID
#  define WIFI_SSID           "YourNetworkSSID"
#endif
#ifndef WIFI_PASSWORD
#  define WIFI_PASSWORD       "YourNetworkPassword"
#endif
#define WIFI_MAX_RETRY      10

// ── CSI Channel ──────────────────────────────────────────────────────────────
// Use a dedicated, low-interference channel. Non-overlapping 2.4GHz: 1, 6, 11
#define CSI_WIFI_CHANNEL    6
#define CSI_BANDWIDTH       WIFI_BW_HT40   // HT40 = more subcarriers

// ── Transmitter ──────────────────────────────────────────────────────────────
#define TX_BEACON_INTERVAL_MS   100     // 10 Hz
#define TX_PACKET_SIZE          128

// ── Receiver ─────────────────────────────────────────────────────────────────
// DNS name of the aggregator container — set this in your local DNS server
// (router / Pi-hole / AdGuard). ESP32 resolves it via DHCP-provided DNS.
#ifndef AGGREGATOR_HOST
#  define AGGREGATOR_HOST     "csi-aggregator.home.arpa"
#endif
#define AGGREGATOR_PORT     5005

// Unique name for this receiver — change before flashing each board.
// This name appears in the dashboard and is used as the DB receiver name.
#ifndef RECEIVER_NAME
#  define RECEIVER_NAME       "rx_ground"   // e.g. "grimnir-rx-library", "grimnir-rx-kitchen"
#endif

// Optional remote syslog discovery domain. Muninn looks up the standard SRV
// name `_syslog._udp.<domain>` through the DHCP-provided DNS resolvers and
// streams logs there over plain UDP syslog. Leave this empty to derive the
// domain from the DNS suffix of AGGREGATOR_HOST.
#ifndef SYSLOG_DISCOVERY_DOMAIN
#  define SYSLOG_DISCOVERY_DOMAIN ""
#endif

// Ack-based recovery watchdog. Muninn expects periodic lightweight UDP ACKs
// from Geri while CSI is actively flowing; if CSI is still being captured but
// ACKs stop for too long, the receiver reboots itself.
#ifndef RECEIVER_WATCHDOG_ACK_TIMEOUT_S
#  define RECEIVER_WATCHDOG_ACK_TIMEOUT_S 60
#endif
#ifndef RECEIVER_WATCHDOG_CSI_GRACE_S
#  define RECEIVER_WATCHDOG_CSI_GRACE_S 15
#endif
#ifndef RECEIVER_WATCHDOG_POLL_MS
#  define RECEIVER_WATCHDOG_POLL_MS 5000
#endif

// MAC address of the Huginn transmitter board.
// Muninn will only process CSI from frames sent by this MAC, ignoring all
// other ambient 802.11 traffic. Set this in config.local.h.
// Format: {0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF}
#ifndef HUGINN_MAC
#  define HUGINN_MAC          {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF}  // placeholder — set in config.local.h
#endif

// ── Logging tags ─────────────────────────────────────────────────────────────
#define LOG_TAG_WIFI        "CSI_WIFI"
#define LOG_TAG_CSI         "CSI_DATA"
#define LOG_TAG_UDP         "CSI_UDP"
