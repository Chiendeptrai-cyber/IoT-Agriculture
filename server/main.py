"""FastAPI entry point for the Smart Agriculture central server."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging

from fastapi import FastAPI, HTTPException, Query, Response
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import desc, or_, select
from sqlalchemy.exc import SQLAlchemyError

from .database import build_engine, build_session_factory, check_database, initialize_database
from .ingestion import InfluxStore, ingest_batch
from .models import IngestedEvent
from .schemas import (
    AlertItem,
    AlertListResponse,
    DependencyHealth,
    HealthResponse,
    LatestReading,
    SensorListResponse,
    SensorSummary,
    TelemetryBatchRequest,
    TelemetryBatchResponse,
    as_utc,
)


LOG = logging.getLogger("smart_agriculture.server")

SENSOR_REGISTRY = (
    ("SEN-001", "temperature", "Temperature Sensor", "C"),
    ("SEN-002", "humidity", "Air Humidity Sensor", "%"),
    ("SEN-003", "soil_moisture", "Soil Moisture Sensor", "%"),
)
SENSOR_IDS = {item[0] for item in SENSOR_REGISTRY}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://agri:agri_dev_only@127.0.0.1:5432/smart_agriculture"
    influx_url: str = "http://127.0.0.1:8086"
    influx_token: str = "smart-agriculture-dev-token"
    influx_org: str = "smart_agriculture"
    influx_bucket: str = "smart_agriculture"
    stale_after_seconds: int = 30
    offline_after_seconds: int = 60
    temperature_high_threshold: float = 35.0
    humidity_low_threshold: float = 40.0
    soil_moisture_low_threshold: float = 30.0


def _reading(row: IngestedEvent) -> LatestReading:
    return LatestReading(
        event_id=row.event_id,
        sensor_id=row.sensor_id,
        timestamp=as_utc(row.measurement_time),
        received_at=as_utc(row.received_at),
        sequence=row.sequence,
        value=row.value,
        unit=row.unit,
    )


def create_app(
    *,
    settings: Settings | None = None,
    engine=None,
    influx_store=None,
    initialize_schema: bool = True,
) -> FastAPI:
    settings = settings or Settings()
    if settings.stale_after_seconds <= 0 or settings.offline_after_seconds <= settings.stale_after_seconds:
        raise ValueError("sensor status thresholds must satisfy 0 < STALE < OFFLINE")

    owns_engine = engine is None
    engine = engine or build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    owns_influx_store = influx_store is None
    influx_store = influx_store or InfluxStore(
        settings.influx_url,
        settings.influx_token,
        settings.influx_org,
        settings.influx_bucket,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if initialize_schema:
            initialize_database(engine)
        yield
        if owns_influx_store:
            influx_store.close()
        if owns_engine:
            engine.dispose()

    app = FastAPI(
        title="Smart Agriculture Server API",
        description=(
            "Receives Edge batches, validates each telemetry record, stores event identity "
            "in PostgreSQL and time-series data in InfluxDB."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.influx_store = influx_store

    @app.post(
        "/api/v1/telemetry/batch",
        response_model=TelemetryBatchResponse,
        summary="Ingest a batch from an Edge Gateway",
        description=(
            "Each row is validated independently. `acknowledged_event_ids` contains only "
            "new records persisted in both stores and exact duplicates already stored."
        ),
    )
    def post_telemetry_batch(
        payload: TelemetryBatchRequest,
    ) -> TelemetryBatchResponse:
        try:
            result = ingest_batch(
                session_factory,
                influx_store,
                gateway_id=payload.gateway_id,
                records=payload.records,
            )
        except SQLAlchemyError as exc:
            LOG.exception("PostgreSQL unavailable during telemetry ingestion")
            raise HTTPException(
                status_code=503,
                detail="PostgreSQL could not durably record this batch; retry it later.",
                headers={"Retry-After": "2"},
            ) from exc
        return TelemetryBatchResponse.model_validate(result)

    @app.get(
        "/api/v1/sensors",
        response_model=SensorListResponse,
        summary="List known sensors and their latest server-side status",
    )
    def list_sensors() -> SensorListResponse:
        now = datetime.now(timezone.utc)
        summaries: list[SensorSummary] = []
        with session_factory() as session:
            for sensor_id, sensor_type, name, unit in SENSOR_REGISTRY:
                row = session.execute(
                    select(IngestedEvent)
                    .where(
                        IngestedEvent.sensor_id == sensor_id,
                        IngestedEvent.processing_status == "STORED",
                    )
                    .order_by(desc(IngestedEvent.measurement_time), desc(IngestedEvent.sequence))
                    .limit(1)
                ).scalar_one_or_none()
                if row is None:
                    state = "OFFLINE"
                    latest = None
                else:
                    elapsed = max(0.0, (now - as_utc(row.received_at)).total_seconds())
                    if elapsed < settings.stale_after_seconds:
                        state = "ONLINE"
                    elif elapsed < settings.offline_after_seconds:
                        state = "STALE"
                    else:
                        state = "OFFLINE"
                    latest = _reading(row)
                summaries.append(
                    SensorSummary(
                        sensor_id=sensor_id,
                        sensor_type=sensor_type,
                        name=name,
                        unit=unit,
                        status=state,
                        latest=latest,
                    )
                )
        return SensorListResponse(sensors=summaries)

    @app.get(
        "/api/v1/sensors/{sensor_id}/latest",
        response_model=LatestReading,
        summary="Get the latest stored reading for one sensor",
    )
    def get_latest(sensor_id: str) -> LatestReading:
        if sensor_id not in SENSOR_IDS:
            raise HTTPException(status_code=404, detail="Unknown sensor_id")
        with session_factory() as session:
            row = session.execute(
                select(IngestedEvent)
                .where(
                    IngestedEvent.sensor_id == sensor_id,
                    IngestedEvent.processing_status == "STORED",
                )
                .order_by(desc(IngestedEvent.measurement_time), desc(IngestedEvent.sequence))
                .limit(1)
            ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="No stored readings for this sensor")
        return _reading(row)

    @app.get(
        "/api/v1/alerts",
        response_model=AlertListResponse,
        summary="List threshold alerts derived from stored telemetry",
    )
    def list_alerts(limit: int = Query(default=100, ge=1, le=1000)) -> AlertListResponse:
        conditions = or_(
            (IngestedEvent.sensor_id == "SEN-001")
            & (IngestedEvent.value > settings.temperature_high_threshold),
            (IngestedEvent.sensor_id == "SEN-002")
            & (IngestedEvent.value < settings.humidity_low_threshold),
            (IngestedEvent.sensor_id == "SEN-003")
            & (IngestedEvent.value < settings.soil_moisture_low_threshold),
        )
        with session_factory() as session:
            rows = session.execute(
                select(IngestedEvent)
                .where(IngestedEvent.processing_status == "STORED", conditions)
                .order_by(desc(IngestedEvent.measurement_time), desc(IngestedEvent.event_id))
                .limit(limit)
            ).scalars().all()
        alerts: list[AlertItem] = []
        for row in rows:
            alert_type, threshold = {
                "SEN-001": ("HIGH_TEMPERATURE", settings.temperature_high_threshold),
                "SEN-002": ("LOW_HUMIDITY", settings.humidity_low_threshold),
                "SEN-003": ("LOW_SOIL_MOISTURE", settings.soil_moisture_low_threshold),
            }[row.sensor_id]
            alerts.append(
                AlertItem(
                    alert_id=f"{row.event_id}:{alert_type}",
                    event_id=row.event_id,
                    sensor_id=row.sensor_id,
                    type=alert_type,
                    severity="HIGH" if row.sensor_id == "SEN-001" else "WARNING",
                    timestamp=as_utc(row.measurement_time),
                    value=row.value,
                    unit=row.unit,
                    threshold=threshold,
                )
            )
        return AlertListResponse(alerts=alerts, count=len(alerts))

    @app.get(
        "/api/v1/health",
        response_model=HealthResponse,
        summary="Check API and storage dependency health",
    )
    def health(response: Response) -> HealthResponse:
        dependencies = {"postgresql": "ok", "influxdb": "ok"}
        try:
            check_database(engine)
        except Exception:
            dependencies["postgresql"] = "unavailable"
        try:
            if not influx_store.healthy():
                dependencies["influxdb"] = "unavailable"
        except Exception:
            dependencies["influxdb"] = "unavailable"
        healthy = all(value == "ok" for value in dependencies.values())
        response.status_code = 200 if healthy else 503
        return HealthResponse(
            status="ok" if healthy else "degraded",
            service="smart-agriculture-server",
            timestamp=datetime.now(timezone.utc),
            dependencies={
                name: DependencyHealth(status=value)
                for name, value in dependencies.items()
            },
        )

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {"service": "smart-agriculture-server", "docs": "/docs", "openapi": "/openapi.json"}

    return app


app = create_app()

