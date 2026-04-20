from __future__ import annotations

import asyncio
import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://db:5432/grimnir")

from geri.main import ACK_PAYLOAD, CSIUDPProtocol
from geri.parser import CSIPacket


class FakeTransport:
    def __init__(self) -> None:
        self.sent: list[tuple[bytes, tuple[str, int]]] = []

    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        self.sent.append((data, addr))


@pytest.mark.asyncio
async def test_protocol_throttles_ack_per_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    queue: asyncio.Queue = asyncio.Queue()
    transport = FakeTransport()
    packet = CSIPacket(
        receiver_name="grimnir-rx-kitc",
        transmitter_mac="aa:bb:cc:dd:ee:ff",
        rssi=-48,
        noise_floor=-92,
        channel=6,
        bandwidth_mhz=40,
        antenna_count=2,
        subcarrier_count=3,
        timestamp_us=123456,
        amplitude=[1.0] * 6,
        phase=[0.5] * 6,
    )
    monkeypatch.setattr("geri.main.parse_packet", lambda _data: packet)
    monkeypatch.setattr("geri.main.ACK_INTERVAL_S", 60.0)

    protocol = CSIUDPProtocol(queue)
    protocol.connection_made(transport)  # type: ignore[arg-type]

    protocol.datagram_received(b"packet-1", ("192.168.0.210", 5005))
    protocol.datagram_received(b"packet-2", ("192.168.0.210", 5005))

    queued = [await queue.get(), await queue.get()]
    assert [item[2] for item in queued] == [packet, packet]
    assert transport.sent == [(ACK_PAYLOAD, ("192.168.0.210", 5005))]


@pytest.mark.asyncio
async def test_protocol_acks_different_peers_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue: asyncio.Queue = asyncio.Queue()
    transport = FakeTransport()
    packet = CSIPacket(
        receiver_name="grimnir-rx-libr",
        transmitter_mac="aa:bb:cc:dd:ee:ff",
        rssi=-47,
        noise_floor=-91,
        channel=6,
        bandwidth_mhz=40,
        antenna_count=2,
        subcarrier_count=3,
        timestamp_us=654321,
        amplitude=[2.0] * 6,
        phase=[1.0] * 6,
    )
    monkeypatch.setattr("geri.main.parse_packet", lambda _data: packet)
    monkeypatch.setattr("geri.main.ACK_INTERVAL_S", 60.0)

    protocol = CSIUDPProtocol(queue)
    protocol.connection_made(transport)  # type: ignore[arg-type]

    protocol.datagram_received(b"packet-1", ("192.168.0.210", 5005))
    protocol.datagram_received(b"packet-2", ("192.168.0.211", 5005))

    assert transport.sent == [
        (ACK_PAYLOAD, ("192.168.0.210", 5005)),
        (ACK_PAYLOAD, ("192.168.0.211", 5005)),
    ]
