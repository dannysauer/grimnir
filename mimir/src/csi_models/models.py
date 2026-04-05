"""SQLAlchemy ORM models matching the Grimnir PostgreSQL schema."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import Float


class Base(DeclarativeBase):
    """Base declarative model class."""


class Receiver(Base):
    """ESP32-S3 transmitter or receiver device metadata."""

    __tablename__ = "receivers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mac: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    role: Mapped[str] = mapped_column(Text, nullable=False, default="receiver")
    floor: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    location: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("role IN ('transmitter', 'receiver')", name="receivers_role_check"),
    )


class CsiSample(Base):
    """Raw CSI sample rows stored in the TimescaleDB hypertable."""

    __tablename__ = "csi_samples"

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    receiver_id: Mapped[int] = mapped_column(ForeignKey("receivers.id"), nullable=False)
    transmitter_mac: Mapped[str] = mapped_column(Text, nullable=False)
    rssi: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    noise_floor: Mapped[int | None] = mapped_column(SmallInteger)
    channel: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    bandwidth: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    antenna_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=2)
    subcarrier_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    amplitude: Mapped[list[float]] = mapped_column(ARRAY(Float), nullable=False)
    phase: Mapped[list[float]] = mapped_column(ARRAY(Float), nullable=False)
    raw_bytes: Mapped[bytes | None] = mapped_column(LargeBinary)
    label: Mapped[str | None] = mapped_column(Text)

    __mapper_args__ = {
        "primary_key": [time, receiver_id, transmitter_mac, channel, rssi, subcarrier_count],
    }


class Label(Base):
    """Annotated time windows for training labels."""

    __tablename__ = "labels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    time_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    time_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    room: Mapped[str] = mapped_column(Text, nullable=False)
    occupants: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("time_end > time_start", name="valid_range"),
    )


class ReceiverHeartbeat(Base):
    """Last-seen heartbeat data for a receiver device."""

    __tablename__ = "receiver_heartbeats"

    receiver_id: Mapped[int] = mapped_column(ForeignKey("receivers.id"), primary_key=True)
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    ip_address: Mapped[str | None] = mapped_column(INET)
    firmware_version: Mapped[str | None] = mapped_column(Text)
