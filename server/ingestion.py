"""Batch validation, idempotency, PostgreSQL ledger and InfluxDB persistence."""

from datetime import datetime, timezone
import logging
from typing import Any
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .models import IngestedEvent, IngestionRejection
from .schemas import TelemetryRecord, as_utc


LOG = logging.getLogger(__name__)
SENSOR_TYPES = {
    "SEN-001": "temperature",
    "SEN-002": "humidity",
    "SEN-003": "soil_moisture",
}


class InfluxStore:
    """Synchronous InfluxDB writer; route handlers run in FastAPI's worker pool."""

    def __init__(self, url: str, token: str, org: str, bucket: str):
        self.url = url.rstrip("/")
        self.org = org
        self.bucket = bucket
        self.client = InfluxDBClient(url=self.url, token=token, org=org, timeout=5000)
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)

    def write(self, record: TelemetryRecord, gateway_id: str, received_at: datetime) -> None:
        # event_id is a tag so a retry after a lost HTTP response targets the same
        # Influx point. At the assignment's single-gateway scale this is bounded
        # by the planned seven-day retention window.
        point = (
            Point("sensor_readings")
            .tag("sensor_id", record.sensor_id)
            .tag("sensor_type", SENSOR_TYPES[record.sensor_id])
            .tag("event_id", record.event_id)
            .tag("gateway_id", gateway_id)
            .field("value", record.value)
            .field("unit", record.unit)
            .field("sequence", record.sequence)
            .field("received_at", received_at.isoformat())
            .time(record.timestamp, WritePrecision.NS)
        )
        self.write_api.write(bucket=self.bucket, org=self.org, record=point)

    def healthy(self) -> bool:
        from urllib.request import urlopen

        try:
            with urlopen(f"{self.url}/health", timeout=2) as response:
                service_ready = 200 <= response.status < 300
            if not service_ready:
                return False
            return self.client.buckets_api().find_bucket_by_name(self.bucket) is not None
        except Exception:
            return False

    def close(self) -> None:
        self.write_api.close()
        self.client.close()


def _raw_payload(value: Any) -> dict | list | str | int | float | None:
    return jsonable_encoder(value)


def _event_id(value: Any) -> str | None:
    if isinstance(value, TelemetryRecord):
        return value.event_id
    if isinstance(value, dict) and isinstance(value.get("event_id"), str):
        return value["event_id"][:160]
    return None


def _record_rejection(
    session_factory,
    *,
    request_id: str,
    index: int,
    raw: Any,
    code: str,
    message: str,
    retryable: bool,
    received_at: datetime,
) -> None:
    with session_factory() as session, session.begin():
        session.add(
            IngestionRejection(
                request_id=request_id,
                record_index=index,
                event_id=_event_id(raw),
                error_code=code,
                error_message=message[:2000],
                retryable=retryable,
                payload=_raw_payload(raw),
                received_at=received_at,
            )
        )


def _same_event(existing: IngestedEvent, record: TelemetryRecord) -> bool:
    return (
        existing.sensor_id == record.sensor_id
        and as_utc(existing.measurement_time) == record.timestamp
        and existing.sequence == record.sequence
        and existing.value == record.value
        and existing.unit == record.unit
    )


def _ensure_event_row(
    session_factory,
    record: TelemetryRecord,
    *,
    gateway_id: str,
    received_at: datetime,
) -> tuple[str, str | None, str | None, datetime | None]:
    """Return state, failure message, original gateway ID and first receive time."""

    with session_factory() as session:
        existing = session.get(IngestedEvent, record.event_id)
        if existing is not None:
            if not _same_event(existing, record):
                return "conflict", "event_id already exists with different measurement data", None, None
            return (
                "stored" if existing.processing_status == "STORED" else "pending",
                None,
                existing.gateway_id,
                as_utc(existing.received_at),
            )

        session.add(
            IngestedEvent(
                event_id=record.event_id,
                gateway_id=gateway_id,
                sensor_id=record.sensor_id,
                measurement_time=record.timestamp,
                sequence=record.sequence,
                value=record.value,
                unit=record.unit,
                received_at=received_at,
                processing_status="PENDING_INFLUX",
                payload=record.model_dump(mode="json"),
            )
        )
        try:
            session.commit()
            return "new", None, gateway_id, received_at
        except IntegrityError:
            session.rollback()
            existing = session.get(IngestedEvent, record.event_id)
            if existing is None:
                raise
            if not _same_event(existing, record):
                return "conflict", "event_id already exists with different measurement data", None, None
            return (
                "stored" if existing.processing_status == "STORED" else "pending",
                None,
                existing.gateway_id,
                as_utc(existing.received_at),
            )


def _set_event_error(session_factory, event_id: str, message: str) -> None:
    with session_factory() as session, session.begin():
        row = session.get(IngestedEvent, event_id)
        if row is not None and row.processing_status != "STORED":
            row.last_error = message[:2000]


def _mark_event_stored(session_factory, event_id: str, stored_at: datetime) -> None:
    with session_factory() as session, session.begin():
        row = session.get(IngestedEvent, event_id)
        if row is None:
            raise RuntimeError("durable event row disappeared before completion")
        row.processing_status = "STORED"
        row.influx_written_at = stored_at
        row.last_error = None


def _validation_message(error: ValidationError) -> str:
    issues = error.errors(include_url=False)
    return "; ".join(
        f"{'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}"
        for issue in issues
    )[:2000]


def ingest_batch(
    session_factory,
    influx_store,
    *,
    gateway_id: str,
    records: list[Any],
) -> dict:
    """Process records independently and acknowledge only completed durable writes."""

    request_id = uuid4().hex
    received_at = datetime.now(timezone.utc)
    accepted_ids: list[str] = []
    duplicate_ids: list[str] = []
    rejected: list[dict] = []

    for index, raw in enumerate(records):
        try:
            record = raw if isinstance(raw, TelemetryRecord) else TelemetryRecord.model_validate(raw)
        except ValidationError as exc:
            message = _validation_message(exc)
            _record_rejection(
                session_factory,
                request_id=request_id,
                index=index,
                raw=raw,
                code="invalid_record",
                message=message,
                retryable=False,
                received_at=received_at,
            )
            rejected.append({
                "index": index,
                "event_id": _event_id(raw),
                "code": "invalid_record",
                "message": message,
                "retryable": False,
            })
            continue

        try:
            existing_state, conflict, event_gateway_id, event_received_at = _ensure_event_row(
                session_factory,
                record,
                gateway_id=gateway_id,
                received_at=received_at,
            )
        except SQLAlchemyError:
            LOG.exception("PostgreSQL failed while recording event %s", record.event_id)
            raise

        if existing_state == "conflict":
            message = conflict or "event_id conflict"
            _record_rejection(
                session_factory,
                request_id=request_id,
                index=index,
                raw=raw,
                code="event_id_conflict",
                message=message,
                retryable=False,
                received_at=received_at,
            )
            rejected.append({
                "index": index,
                "event_id": record.event_id,
                "code": "event_id_conflict",
                "message": message,
                "retryable": False,
            })
            continue

        if existing_state == "stored":
            duplicate_ids.append(record.event_id)
            continue

        try:
            influx_store.write(record, event_gateway_id or gateway_id, event_received_at or received_at)
        except Exception as exc:
            LOG.warning("InfluxDB persistence failed for event %s: %s", record.event_id, exc)
            try:
                _set_event_error(session_factory, record.event_id, str(exc))
            except SQLAlchemyError:
                LOG.exception("PostgreSQL failed while recording retry state for %s", record.event_id)
                raise
            message = "Time-series persistence failed; resend this event."
            try:
                _record_rejection(
                    session_factory,
                    request_id=request_id,
                    index=index,
                    raw=raw,
                    code="influx_unavailable",
                    message=message,
                    retryable=True,
                    received_at=received_at,
                )
            except SQLAlchemyError:
                LOG.exception("PostgreSQL failed while auditing event %s failure", record.event_id)
                raise
            rejected.append({
                "index": index,
                "event_id": record.event_id,
                "code": "influx_unavailable",
                "message": message,
                "retryable": True,
            })
        else:
            # A PostgreSQL failure here propagates as HTTP 503. A retry repeats
            # the deterministic Influx point and then completes the ledger row.
            _mark_event_stored(session_factory, record.event_id, datetime.now(timezone.utc))
            accepted_ids.append(record.event_id)

    acknowledged_ids = list(dict.fromkeys(accepted_ids + duplicate_ids))
    return {
        "status": "success" if not rejected else "partial",
        "request_id": request_id,
        "received": len(records),
        "accepted": len(accepted_ids),
        "duplicates": len(duplicate_ids),
        "rejected": len(rejected),
        "accepted_event_ids": accepted_ids,
        "duplicate_event_ids": duplicate_ids,
        "acknowledged_event_ids": acknowledged_ids,
        "rejected_records": rejected,
    }
