"""
parser.py — Binary CSI UDP packet parser

Mirrors the packet format defined in firmware/receiver/main/main.c

Packet layout (little-endian):
  [0..3]   magic uint32     = 0x43534921 ("CSI!")
  [4..5]   version uint16   = 1
  [6..21]  receiver_name char[16]
  [22..27] transmitter_mac uint8[6]
  [28..29] rssi int16
  [30..31] noise_floor int16
  [32..33] channel uint16
  [34..35] bandwidth_mhz uint16
  [36..37] antenna_count uint16
  [38..39] subcarrier_count uint16
  [40..43] timestamp_us uint32
  [44..N]  amplitude float32[]  len = antenna_count * subcarrier_count
  [N..M]   phase float32[]      len = antenna_count * subcarrier_count
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

PACKET_MAGIC = 0x43534921
HEADER_FMT = "<IH16s6shhhHHHI"  # up to timestamp_us
HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 44 bytes


@dataclass(slots=True)
class CSIPacket:
    receiver_name: str
    transmitter_mac: str       # "aa:bb:cc:dd:ee:ff"
    rssi: int                  # dBm
    noise_floor: int           # dBm
    channel: int
    bandwidth_mhz: int
    antenna_count: int
    subcarrier_count: int
    timestamp_us: int          # device uptime micros (wraps)
    amplitude: list[float]     # length = antenna_count * subcarrier_count
    phase: list[float]         # length = antenna_count * subcarrier_count


class ParseError(Exception):
    pass


def parse_packet(data: bytes) -> CSIPacket:
    """Parse a raw UDP datagram into a CSIPacket.

    Raises ParseError on malformed input.
    """
    if len(data) < HEADER_SIZE:
        raise ParseError(f"Packet too short: {len(data)} < {HEADER_SIZE}")

    (
        magic,
        version,
        name_raw,
        mac_raw,
        rssi,
        noise_floor,
        channel,
        bandwidth_mhz,
        antenna_count,
        subcarrier_count,
        timestamp_us,
    ) = struct.unpack_from(HEADER_FMT, data, 0)

    if magic != PACKET_MAGIC:
        raise ParseError(f"Bad magic: 0x{magic:08X} (expected 0x{PACKET_MAGIC:08X})")

    if version != 1:
        raise ParseError(f"Unknown packet version: {version}")

    receiver_name = name_raw.rstrip(b"\x00").decode("ascii", errors="replace")
    transmitter_mac = ":".join(f"{b:02x}" for b in mac_raw)

    n_floats = antenna_count * subcarrier_count
    expected_size = HEADER_SIZE + n_floats * 4 * 2  # amplitude + phase
    if len(data) < expected_size:
        raise ParseError(
            f"Packet body too short: got {len(data)}, need {expected_size} "
            f"({n_floats} floats × 2 arrays)"
        )

    offset = HEADER_SIZE
    amplitude = list(struct.unpack_from(f"<{n_floats}f", data, offset))
    offset += n_floats * 4
    phase = list(struct.unpack_from(f"<{n_floats}f", data, offset))

    return CSIPacket(
        receiver_name=receiver_name,
        transmitter_mac=transmitter_mac,
        rssi=int(rssi),
        noise_floor=int(noise_floor),
        channel=int(channel),
        bandwidth_mhz=int(bandwidth_mhz),
        antenna_count=int(antenna_count),
        subcarrier_count=int(subcarrier_count),
        timestamp_us=int(timestamp_us),
        amplitude=amplitude,
        phase=phase,
    )
