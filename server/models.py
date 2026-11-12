"""PostgreSQL models for idempotent server ingestion and audit records."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class IngestedEvent(Base):
    """The durable event ledger; event_id is the server idempotency key."""

    __tablename__ = "ingested_events"
    __table_args__ = (
        CheckConstraint(
            "processing_status IN ('PENDING_INFLUX', 'STORED')",
            name="ck_ingested_events_processing_status",
        ),
        Index("ix_ingested_events_sensor_time", "sensor_id", "measurement_time"),
        Index("ix_ingested_events_status_time", "processing_status", "received_at"),
    )

    event_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    gateway_id: Mapped[str] = mapped_column(String(80), nullable=False)
    sensor_id: Mapped[str] = mapped_column(String(16), nullable=False)
    measurement_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(8), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processing_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="PENDING_INFLUX"
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    influx_written_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IngestionRejection(Base):
    """Rejected records retained for diagnosis; never acknowledged as stored."""

    __tablename__ = "ingestion_rejections"
    __table_args__ = (Index("ix_ingestion_rejections_received", "received_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(80), nullable=False)
    record_index: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    error_code: Mapped[str] = mapped_column(String(80), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    retryable: Mapped[bool] = mapped_column(nullable=False, default=False)
    payload: Mapped[dict | list | str | int | float | None] = mapped_column(JSON, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

