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
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB
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


class Room(Base):
    """Named room for location labeling. Name is the PK so FK references cascade on rename."""

    __tablename__ = "rooms"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    floor: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Label(Base):
    """Annotated time windows for training labels."""

    __tablename__ = "labels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    time_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    time_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    room: Mapped[str] = mapped_column(
        Text,
        ForeignKey("rooms.name", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    occupants: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (CheckConstraint("time_end > time_start", name="valid_range"),)


class TrainingSample(Base):
    """Labeled CSI samples copied from csi_samples for long-term ML training storage."""

    __tablename__ = "training_samples"

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
    label: Mapped[str] = mapped_column(Text, nullable=False)

    __mapper_args__ = {
        "primary_key": [time, receiver_id],
    }


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


class TrainingDaemon(Base):
    """Nornir training daemon instance, upserted on each heartbeat."""

    __tablename__ = "training_daemons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    host: Mapped[str] = mapped_column(Text, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(INET)
    capabilities: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class TrainingJob(Base):
    """Queued/running/finished training job handed to a Nornir daemon."""

    __tablename__ = "training_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    spec: Mapped[dict] = mapped_column(JSONB, nullable=False)
    daemon_id: Mapped[int | None] = mapped_column(
        ForeignKey("training_daemons.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'failed', 'complete', 'cancelled')",
            name="training_jobs_status_check",
        ),
    )


class TrainedModel(Base):
    """Registry of trained models. `model_data` is the joblib-serialized payload."""

    __tablename__ = "trained_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    training_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("training_jobs.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    feature_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    model_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
