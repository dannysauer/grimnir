from __future__ import annotations

import struct

import pytest
from geri.parser import HEADER_FORMAT, HEADER_SIZE, PACKET_MAGIC, ParseError, parse_packet


def _build_packet(
    *,
    magic: int = PACKET_MAGIC,
    version: int = 1,
    receiver_name: str = "rx_ground",
    transmitter_mac: bytes = b"\xaa\xbb\xcc\xdd\xee\xff",
    rssi: int = -47,
    noise_floor: int = -92,
    channel: int = 6,
    bandwidth_mhz: int = 20,
    antenna_count: int = 2,
    subcarrier_count: int = 3,
    timestamp_us: int = 123456,
    amplitude: list[float] | None = None,
    phase: list[float] | None = None,
) -> bytes:
    n_values = antenna_count * subcarrier_count
    if amplitude is None:
        amplitude = [float(i) for i in range(1, n_values + 1)]
    if phase is None:
        phase = [float(i) * -0.5 for i in range(1, n_values + 1)]

    header = struct.pack(
        HEADER_FORMAT,
        magic,
        version,
        receiver_name.encode("ascii").ljust(16, b"\x00"),
        transmitter_mac,
        rssi,
        noise_floor,
        channel,
        bandwidth_mhz,
        antenna_count,
        subcarrier_count,
        timestamp_us,
    )
    body = struct.pack(f"<{n_values * 2}f", *(amplitude + phase))
    return header + body


def test_parse_packet_round_trips_valid_payload() -> None:
    packet = parse_packet(_build_packet())

    assert packet.receiver_name == "rx_ground"
    assert packet.transmitter_mac == "aa:bb:cc:dd:ee:ff"
    assert packet.rssi == -47
    assert packet.noise_floor == -92
    assert packet.channel == 6
    assert packet.bandwidth_mhz == 20
    assert packet.antenna_count == 2
    assert packet.subcarrier_count == 3
    assert packet.timestamp_us == 123456
    assert packet.amplitude == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    assert packet.phase == [-0.5, -1.0, -1.5, -2.0, -2.5, -3.0]


def test_parse_packet_trims_receiver_name_padding() -> None:
    packet = parse_packet(_build_packet(receiver_name="rx_upstairs"))
    assert packet.receiver_name == "rx_upstairs"


def test_parse_packet_rejects_short_header() -> None:
    with pytest.raises(ParseError, match="Packet too short"):
        parse_packet(b"\x00" * (HEADER_SIZE - 1))


def test_parse_packet_rejects_bad_magic() -> None:
    with pytest.raises(ParseError, match="Bad magic"):
        parse_packet(_build_packet(magic=0xDEADBEEF))


def test_parse_packet_rejects_unknown_version() -> None:
    with pytest.raises(ParseError, match="Unknown version"):
        parse_packet(_build_packet(version=2))


def test_parse_packet_rejects_short_float_payload() -> None:
    raw = _build_packet()[:-4]
    with pytest.raises(ParseError, match="Packet too short for"):
        parse_packet(raw)
