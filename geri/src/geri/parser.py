"""
parser.py — Binary CSI UDP packet parser.

Mirrors the packet format defined in firmware/muninn/main/main.c

Wire layout (little-endian):
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
  44       N    float32[]   amplitude  (len = antenna_count × subcarrier_count)
  44+N     N    float32[]   phase      (len = antenna_count × subcarrier_count)

Total header: 44 bytes
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

PACKET_MAGIC = 0x43534921
HEADER_FORMAT = "<IH16s6shhHHHHI"  # h=int16 for rssi+noise_floor, H=uint16 elsewhere
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 44 bytes


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
    if len(data) < HEADER_SIZE:
        raise ParseError(f"Packet too short: {len(data)} < {HEADER_SIZE}")

    (
        magic,
        version,
        receiver_name_raw,
        mac_bytes,
        rssi,
        noise_floor,
        channel,
        bandwidth_mhz,
        antenna_count,
        subcarrier_count,
        timestamp_us,
    ) = struct.unpack_from(HEADER_FORMAT, data, 0)

    if magic != PACKET_MAGIC:
        raise ParseError(f"Bad magic: 0x{magic:08X}")
    if version != 1:
        raise ParseError(f"Unknown version: {version}")

    n_values = antenna_count * subcarrier_count
    expected_size = HEADER_SIZE + n_values * 4 * 2  # two float32[] arrays
    if len(data) < expected_size:
        raise ParseError(
            f"Packet too short for {n_values} subcarriers: {len(data)} < {expected_size}"
        )

    floats_fmt = f"<{n_values * 2}f"
    flat = struct.unpack_from(floats_fmt, data, HEADER_SIZE)
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
