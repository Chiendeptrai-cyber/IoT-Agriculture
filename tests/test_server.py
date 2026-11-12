"""Task 4 API and ingestion contract tests using SQLite and a fake Influx writer."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from server.database import build_engine, build_session_factory
from server.ingestion import InfluxStore
from server.main import Settings, create_app
from server.models import IngestedEvent, IngestionRejection
from server.schemas import TelemetryRecord


class FakeInflux:
    def __init__(self):
        self.rows = []
        self.attempts = []
        self.fail = False
        self.is_healthy = True

    def write(self, record, gateway_id, received_at):
        self.attempts.append((record, gateway_id, received_at))
        if self.fail:
            raise ConnectionError("fake Influx outage")
        self.rows.append((record, gateway_id, received_at))

    def healthy(self):
        return self.is_healthy

    def close(self):
        pass


def make_client():
    engine = build_engine("sqlite://")
    influx = FakeInflux()
    settings = Settings(
        _env_file=None,
        database_url="sqlite://",
        influx_url="http://unused",
        influx_token="unused",
        influx_org="test",
        influx_bucket="smart_agriculture",
    )
    app = create_app(settings=settings, engine=engine, influx_store=influx)
    client = TestClient(app)
    client.__enter__()
    return client, engine, influx


def telemetry(event_id="EVT-TEST001", *, sensor_id="SEN-001", value=29.5, unit="C", timestamp=None):
    return {
        "event_id": event_id,
        "sensor_id": sensor_id,
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sequence": 1,
        "value": value,
        "unit": unit,
    }


def test_batch_accepts_duplicates_and_rejects_bad_records_independently():
    client, engine, influx = make_client()
    try:
        event = telemetry(value=40.0)
        invalid = telemetry("EVT-BAD0001", sensor_id="SEN-002", value=101, unit="%")
        response = client.post(
            "/api/v1/telemetry/batch",
            json={"gateway_id": "GW-001", "records": [event, event, invalid]},
        )

        assert response.status_code == 200
        body = response.json()
        assert (body["received"], body["accepted"], body["duplicates"], body["rejected"]) == (3, 1, 1, 1)
        assert body["accepted_event_ids"] == [event["event_id"]]
        assert body["duplicate_event_ids"] == [event["event_id"]]
        assert body["acknowledged_event_ids"] == [event["event_id"]]
        assert body["rejected_records"][0]["code"] == "invalid_record"
        assert len(influx.rows) == 1

        factory = build_session_factory(engine)
        with factory() as session:
            stored = session.get(IngestedEvent, event["event_id"])
            rejected = session.execute(select(IngestionRejection)).scalars().all()
            assert stored.processing_status == "STORED"
            assert len(rejected) == 1
    finally:
        client.__exit__(None, None, None)
        engine.dispose()


def test_reusing_event_id_with_different_data_is_rejected_without_ack():
    client, engine, influx = make_client()
    try:
        original = telemetry(value=29.5)
        changed = {**original, "value": 31.0}
        first = client.post("/api/v1/telemetry/batch", json={"records": [original]}).json()
        second = client.post("/api/v1/telemetry/batch", json={"records": [changed]}).json()

        assert first["acknowledged_event_ids"] == [original["event_id"]]
        assert second["accepted"] == 0
        assert second["duplicates"] == 0
        assert second["rejected_records"][0]["code"] == "event_id_conflict"
        assert second["acknowledged_event_ids"] == []
        assert len(influx.rows) == 1
    finally:
        client.__exit__(None, None, None)
        engine.dispose()


def test_influx_failure_never_acks_and_retry_completes_pending_event():
    client, engine, influx = make_client()
    try:
        influx.fail = True
        event = telemetry("EVT-RETRY001")
        failed = client.post("/api/v1/telemetry/batch", json={"records": [event]}).json()
        assert failed["accepted"] == 0
        assert failed["acknowledged_event_ids"] == []
        assert failed["rejected_records"][0]["retryable"] is True
        first_received_at = influx.attempts[0][2]

        factory = build_session_factory(engine)
        with factory() as session:
            row = session.get(IngestedEvent, event["event_id"])
            assert row.processing_status == "PENDING_INFLUX"

        influx.fail = False
        retried = client.post("/api/v1/telemetry/batch", json={"records": [event]}).json()
        assert retried["accepted"] == 1
        assert retried["acknowledged_event_ids"] == [event["event_id"]]
        assert influx.attempts[1][2] == first_received_at
        with factory() as session:
            assert session.get(IngestedEvent, event["event_id"]).processing_status == "STORED"
    finally:
        client.__exit__(None, None, None)
        engine.dispose()


def test_query_endpoints_and_sensor_timestamp_status():
    client, engine, _influx = make_client()
    try:
        measured_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        event = telemetry(
            "EVT-QUERY001",
            value=40.0,
            timestamp=measured_at.isoformat().replace("+00:00", "Z"),
        )
        result = client.post("/api/v1/telemetry/batch", json={"records": [event]})
        assert result.json()["acknowledged_event_ids"] == [event["event_id"]]

        sensors_response = client.get("/api/v1/sensors")
        assert sensors_response.status_code == 200, sensors_response.text
        sensors = sensors_response.json()["sensors"]
        temperature = next(sensor for sensor in sensors if sensor["sensor_id"] == "SEN-001")
        assert temperature["status"] == "ONLINE"
        assert temperature["latest"]["timestamp"].endswith("Z")
        assert temperature["latest"]["received_at"] != temperature["latest"]["timestamp"]

        latest = client.get("/api/v1/sensors/SEN-001/latest")
        assert latest.status_code == 200
        assert latest.json()["value"] == 40.0
        assert client.get("/api/v1/sensors/SEN-999/latest").status_code == 404

        alerts = client.get("/api/v1/alerts?limit=10").json()
        assert alerts["count"] == 1
        assert alerts["alerts"][0]["type"] == "HIGH_TEMPERATURE"
    finally:
        client.__exit__(None, None, None)
        engine.dispose()


def test_health_reports_degraded_when_influx_is_unavailable():
    client, engine, influx = make_client()
    try:
        assert client.get("/api/v1/health").status_code == 200
        influx.is_healthy = False
        response = client.get("/api/v1/health")
        assert response.status_code == 503
        assert response.json()["status"] == "degraded"
        assert response.json()["dependencies"]["influxdb"]["status"] == "unavailable"
    finally:
        client.__exit__(None, None, None)
        engine.dispose()


def test_influx_point_uses_sensor_time_and_keeps_server_receive_time_separate(monkeypatch):
    class FakeWriteApi:
        def __init__(self):
            self.record = None

        def write(self, *, bucket, org, record):
            assert bucket == "smart_agriculture"
            assert org == "test"
            self.record = record

        def close(self):
            pass

    class FakeInfluxClient:
        def __init__(self, **_kwargs):
            self.writer = FakeWriteApi()

        def write_api(self, *, write_options):
            return self.writer

        def close(self):
            pass

    monkeypatch.setattr("server.ingestion.InfluxDBClient", FakeInfluxClient)
    store = InfluxStore("http://unused", "unused", "test", "smart_agriculture")
    measurement_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    received_at = datetime.now(timezone.utc)
    record = TelemetryRecord.model_validate(
        telemetry("EVT-TIME001", timestamp=measurement_time.isoformat().replace("+00:00", "Z"))
    )

    store.write(record, "GW-001", received_at)
    point = store.write_api.record
    assert point._time == measurement_time.replace(microsecond=measurement_time.microsecond)
    assert point._fields["received_at"] == received_at.isoformat()
    assert point._tags["event_id"] == record.event_id
    store.close()


def test_swagger_and_openapi_are_available():
    client, engine, _influx = make_client()
    try:
        assert client.get("/docs").status_code == 200
        spec = client.get("/openapi.json").json()
        assert "/api/v1/telemetry/batch" in spec["paths"]
        assert "/api/v1/health" in spec["paths"]
    finally:
        client.__exit__(None, None, None)
        engine.dispose()

