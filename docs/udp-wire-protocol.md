# UDP Wire Protocol

Muninn receiver firmware sends CSI samples to Geri over UDP. Geri parses the
packet format in `geri/src/geri/parser.py` and stores accepted samples in
TimescaleDB.

The current firmware emits packet version 2. Geri still accepts version 1 for
backward compatibility with older receiver firmware.

## Transport

| Property | Value |
|----------|-------|
| Protocol | UDP |
| Default destination port | `5005` |
| Sender | Muninn receiver firmware |
| Receiver | Geri aggregator service |
| ACK payload | `grimnir-ack` |
| ACK cadence | Geri sends lightweight ACKs no more often than `ACK_INTERVAL_S`, default 5 seconds, per sender address. |

Muninn uses ACK flow as a recovery signal. If CSI is still flowing but ACKs stop
long enough, the receiver watchdog reboots the board.

## Version 2 Packet Layout

All integer and float values are little-endian. The version 2 header is exactly
60 bytes.

| Offset | Size | Type | Field | Notes |
|--------|------|------|-------|-------|
| 0 | 4 | `uint32` | `magic` | Must be `0x43534921`, the ASCII string `CSI!`. |
| 4 | 2 | `uint16` | `version` | Current value is `2`. |
| 6 | 32 | `char[32]` | `receiver_name` | Null-padded ASCII receiver name. |
| 38 | 6 | `uint8[6]` | `transmitter_mac` | Huginn transmitter MAC bytes. |
| 44 | 2 | `int16` | `rssi` | RSSI in dBm. |
| 46 | 2 | `int16` | `noise_floor` | Noise floor in dBm. |
| 48 | 2 | `uint16` | `channel` | Wi-Fi channel. |
| 50 | 2 | `uint16` | `bandwidth_mhz` | Channel bandwidth in MHz. |
| 52 | 2 | `uint16` | `antenna_count` | Number of antennas represented in this packet. |
| 54 | 2 | `uint16` | `subcarrier_count` | Number of subcarriers represented per antenna. |
| 56 | 4 | `uint32` | `timestamp_us` | Device uptime in microseconds. Wraps after about 71 minutes. |
| 60 | `N * 4` | `float32[]` | `amplitude` | `N = antenna_count * subcarrier_count`. |
| `60 + N * 4` | `N * 4` | `float32[]` | `phase` | `N = antenna_count * subcarrier_count`. |

## Version 1 Compatibility Layout

Version 1 differs only in the receiver-name field width and therefore the
header size.

| Offset | Size | Type | Field |
|--------|------|------|-------|
| 0 | 4 | `uint32` | `magic` |
| 4 | 2 | `uint16` | `version = 1` |
| 6 | 16 | `char[16]` | `receiver_name` |
| 22 | 6 | `uint8[6]` | `transmitter_mac` |
| 28 | 2 | `int16` | `rssi` |
| 30 | 2 | `int16` | `noise_floor` |
| 32 | 2 | `uint16` | `channel` |
| 34 | 2 | `uint16` | `bandwidth_mhz` |
| 36 | 2 | `uint16` | `antenna_count` |
| 38 | 2 | `uint16` | `subcarrier_count` |
| 40 | 4 | `uint32` | `timestamp_us` |
| 44 | `N * 4` | `float32[]` | `amplitude` |
| `44 + N * 4` | `N * 4` | `float32[]` | `phase` |

## Validation Rules

Geri rejects a datagram when:

- The datagram is shorter than the minimum version 1 header.
- `magic` is not `0x43534921`.
- `version` is not `1` or `2`.
- The datagram is shorter than the expected header for that version.
- The datagram does not contain enough `float32` values for
  `antenna_count * subcarrier_count` amplitude and phase arrays.

Parser behavior is covered by `geri/tests/test_parser.py`.

## Source of Truth

- Current firmware layout: `firmware/muninn/main/main.c`
- Receiver-name length default: `firmware/config.h`
- Parser constants and validation: `geri/src/geri/parser.py`
- Regression tests: `geri/tests/test_parser.py`
