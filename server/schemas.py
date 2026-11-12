"""Public request and response schemas for the REST API."""

from datetime import datetime, timezone
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SensorId = Literal["SEN-001", "SEN-002", "SEN-003"]
SensorType = Literal["temperature", "humidity", "soil_moisture"]


class TelemetryRecord(BaseModel):
    """One canonical sensor event shared with the simulator and Edge."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(pattern=r"^EVT-[A-Za-z0-9_-]+$", max_length=80)
    sensor_id: SensorId
    timestamp: datetime
    sequence: int = Field(strict=True, ge=1)
    value: float = Field(allow_inf_nan=False)
    unit: Literal["C", "%"]

    @field_validator("value", mode="before")
    @classmethod
    def reject_boolean_measurements(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("value must be a numeric measurement, not a boolean")
        return value

    @field_validator("timestamp", mode="before")
    @classmethod
    def require_iso_timestamp(cls, value: Any) -> Any:
        if not isinstance(value, str):
            raise ValueError("timestamp must be an ISO 8601 string")
        return value

    @field_validator("timestamp")
    @classmethod
    def require_timezone_and_normalize_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_sensor_unit_and_physical_range(self) -> "TelemetryRecord":
        expected = {
            "SEN-001": ("C", -40.0, 125.0),
            "SEN-002": ("%", 0.0, 100.0),
            "SEN-003": ("%", 0.0, 100.0),
        }[self.sensor_id]
        expected_unit, low, high = expected
        if self.unit != expected_unit:
            raise ValueError(f"{self.sensor_id} requires unit {expected_unit!r}")
        if not low <= self.value <= high:
            raise ValueError(
                f"{self.sensor_id} value must be in the physical range [{low}, {high}]"
            )
        return self


RawRecord = TelemetryRecord | dict[str, Any]


class TelemetryBatchRequest(BaseModel):
    """A batch accepts raw objects as well as valid records so bad rows can be counted."""

    model_config = ConfigDict(extra="forbid")

    gateway_id: str = Field(default="GW-001", min_length=1, max_length=80)
    records: list[RawRecord] = Field(min_length=1, max_length=1000)

    @field_validator("gateway_id")
    @classmethod
    def validate_gateway_id(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("gateway_id may contain only letters, digits, '_' and '-'")
        return value


class RejectedRecord(BaseModel):
    index: int = Field(ge=0)
    event_id: str | None = None
    code: str
    message: str
    retryable: bool


class TelemetryBatchResponse(BaseModel):
    status: Literal["success", "partial"]
    request_id: str
    received: int
    accepted: int
    duplicates: int
    rejected: int
    accepted_event_ids: list[str]
    duplicate_event_ids: list[str]
    acknowledged_event_ids: list[str]
    rejected_records: list[RejectedRecord]


class LatestReading(BaseModel):
    event_id: str
    sensor_id: SensorId
    timestamp: datetime
    received_at: datetime
    sequence: int
    value: float
    unit: Literal["C", "%"]


class SensorSummary(BaseModel):
    sensor_id: SensorId
    sensor_type: SensorType
    name: str
    unit: Literal["C", "%"]
    status: Literal["ONLINE", "STALE", "OFFLINE"]
    latest: LatestReading | None


class SensorListResponse(BaseModel):
    sensors: list[SensorSummary]


class AlertItem(BaseModel):
    alert_id: str
    event_id: str
    sensor_id: SensorId
    type: Literal["HIGH_TEMPERATURE", "LOW_HUMIDITY", "LOW_SOIL_MOISTURE"]
    severity: Literal["WARNING", "HIGH"]
    timestamp: datetime
    value: float
    unit: Literal["C", "%"]
    threshold: float


class AlertListResponse(BaseModel):
    alerts: list[AlertItem]
    count: int


class DependencyHealth(BaseModel):
    status: Literal["ok", "unavailable"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str
    timestamp: datetime
    dependencies: dict[str, DependencyHealth]


def as_utc(value: datetime) -> datetime:
    """Normalize datetimes returned by drivers, including SQLite test doubles."""

    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

