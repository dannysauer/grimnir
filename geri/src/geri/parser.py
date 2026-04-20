"""
parser.py — Binary CSI UDP packet parser.

Mirrors the packet format defined in firmware/muninn/main/main.c

Wire layout (little-endian):
  Version 1:
    Offset  Size  Type        Field
    ------  ----  ----------  -----
     0       4    uint32      magic = 0x43534921 ("CSI!")
     4       2    uint16      version = 1
     6      16    char[16]    receiver_name (null-padded)
    22       6    uint8[6]    transmitter_mac
    28       2    int16       rssi (dBm)
    30       2    int16       noise_floor (dBm)
    32       2    uint16      channel
    34       2    uint16      bandwidth_mhz
    36       2    uint16      antenna_count
    38       2    uint16      subcarrier_count
    40       4    uint32      timestamp_us (device uptime, wraps)
    44       N    float32[]   amplitude
    44+N     N    float32[]   phase

  Version 2:
    Offset  Size  Type        Field
    ------  ----  ----------  -----
     0       4    uint32      magic = 0x43534921 ("CSI!")
     4       2    uint16      version = 2
     6      32    char[32]    receiver_name (null-padded)
    38       6    uint8[6]    transmitter_mac
    44       2    int16       rssi (dBm)
    46       2    int16       noise_floor (dBm)
    48       2    uint16      channel
    50       2    uint16      bandwidth_mhz
    52       2    uint16      antenna_count
    54       2    uint16      subcarrier_count
    56       4    uint32      timestamp_us (device uptime, wraps)
    60       N    float32[]   amplitude
    60+N     N    float32[]   phase
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

PACKET_MAGIC = 0x43534921
HEADER_FORMAT_V1 = "<IH16s6shhHHHHI"
HEADER_FORMAT_V2 = "<IH32s6shhHHHHI"
HEADER_SIZE_V1 = struct.calcsize(HEADER_FORMAT_V1)
HEADER_SIZE_V2 = struct.calcsize(HEADER_FORMAT_V2)
HEADER_BY_VERSION = {
    1: (HEADER_FORMAT_V1, HEADER_SIZE_V1),
    2: (HEADER_FORMAT_V2, HEADER_SIZE_V2),
}
HEADER_SIZE = HEADER_SIZE_V2


@dataclass(slots=True)
class CSIPacket:
    receiver_name: str  # e.g. "rx_ground"
    transmitter_mac: str  # "aa:bb:cc:dd:ee:ff"
    rssi: int  # dBm
    noise_floor: int  # dBm
    channel: int
    bandwidth_mhz: int
    antenna_count: int
    subcarrier_count: int
    timestamp_us: int  # device uptime micros (wraps ~71 min)
    amplitude: list[float]  # length = antenna_count × subcarrier_count
    phase: list[float]  # length = antenna_count × subcarrier_count


class ParseError(Exception):
    pass


def parse_packet(data: bytes) -> CSIPacket:
    """Parse a raw UDP datagram into a CSIPacket. Raises ParseError on bad input."""
    if len(data) < HEADER_SIZE_V1:
        raise ParseError(f"Packet too short: {len(data)} < {HEADER_SIZE_V1}")

    magic, version = struct.unpack_from("<IH", data, 0)

    if magic != PACKET_MAGIC:
        raise ParseError(f"Bad magic: 0x{magic:08X}")
    if version not in HEADER_BY_VERSION:
        raise ParseError(f"Unknown version: {version}")

    header_format, header_size = HEADER_BY_VERSION[version]
    if len(data) < header_size:
        raise ParseError(f"Packet too short: {len(data)} < {header_size}")

    (
        _magic,
        _version,
        receiver_name_raw,
        mac_bytes,
        rssi,
        noise_floor,
        channel,
        bandwidth_mhz,
        antenna_count,
        subcarrier_count,
        timestamp_us,
    ) = struct.unpack_from(header_format, data, 0)

    n_values = antenna_count * subcarrier_count
    expected_size = header_size + n_values * 4 * 2  # two float32[] arrays
    if len(data) < expected_size:
        raise ParseError(
            f"Packet too short for {n_values} subcarriers: {len(data)} < {expected_size}"
        )

    floats_fmt = f"<{n_values * 2}f"
    flat = struct.unpack_from(floats_fmt, data, header_size)
    amplitude = list(flat[:n_values])
    phase = list(flat[n_values:])

    receiver_name = receiver_name_raw.rstrip(b"\x00").decode("ascii", errors="replace")
    transmitter_mac = ":".join(f"{b:02x}" for b in mac_bytes)

    return CSIPacket(
        receiver_name=receiver_name,
        transmitter_mac=transmitter_mac,
        rssi=rssi,
        noise_floor=noise_floor,
        channel=channel,
        bandwidth_mhz=bandwidth_mhz,
        antenna_count=antenna_count,
        subcarrier_count=subcarrier_count,
        timestamp_us=timestamp_us,
        amplitude=amplitude,
        phase=phase,
    )
