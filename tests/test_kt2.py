"""Acceptance KT2: thresholds, anomaly classification and pump hysteresis."""

import json
from pathlib import Path
import sys
import uuid

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "sensor-simulator"))

from acceptance_support import make_http_session, make_server
from buffer_manager import BufferManager, database_status
from data_validator import utc_now
from mqtt_common import sensor_routes
from mqtt_client import EdgeGateway
from server.database import build_session_factory
from server.models import IngestedEvent
from settings import load_config
from sync_manager import SyncManager


def event(sensor_id, value, sequence):
    unit = "C" if sensor_id == "SEN-001" else "%"
    return {
        "event_id": f"EVT-KT2-{uuid.uuid4().hex.upper()}",
        "sensor_id": sensor_id,
        "timestamp": utc_now().isoformat(),
        "sequence": sequence,
        "value": value,
        "unit": unit,
    }


def test_kt2_threshold_alerts_anomalies_and_virtual_pump(tmp_path):
    client, engine, influx = make_server()
    config = load_config()
    buffer = BufferManager(tmp_path / "kt2-edge.db")
    gateway = EdgeGateway(buffer, config, client_id=f"kt2-{uuid.uuid4().hex}")
    session = make_http_session(client)
    sync = SyncManager(
        buffer,
        config=config,
        server_url="http://acceptance.test/api/v1/telemetry/batch",
        session=session,
    )
    routes = {sensor_id: topic for topic, (sensor_id, _unit) in sensor_routes().items()}
    high_temperature = event("SEN-001", 40.0, 1)
    low_humidity = event("SEN-002", 35.0, 1)
    dry_soil = event("SEN-003", 25.0, 1)
    recovered_soil = event("SEN-003", 38.0, 2)
    accepted = (high_temperature, low_humidity, dry_soil, recovered_soil)
    try:
        results = []
        for record in accepted:
            results.append(
                gateway.process(
                    routes[record["sensor_id"]],
                    json.dumps(record).encode("utf-8"),
                )
            )

        # Physical-range validation rejects this rather than treating it as a
        # valid anomaly that can influence alerts or control.
        invalid = event("SEN-002", 101.0, 2)
        rejected = gateway.process(
            routes["SEN-002"], json.dumps(invalid).encode("utf-8")
        )
        assert rejected["status"] == "QUARANTINED"

        assert [result["classification"] for result in results] == [
            "ANOMALY", "ANOMALY", "ANOMALY", "NORMAL"
        ]
        assert results[2]["pump"] == "ON"
        assert results[3]["pump"] == "OFF"
        local = database_status(buffer.path)
        assert (local["total"], local["pending"], local["quarantined"]) == (4, 4, 1)
        assert local["device_actions"] == 2
        assert local["pump"]["state"] == "OFF"
        assert {item["kind"] for item in local["recent_alerts"]} == {
            "HIGH_TEMPERATURE", "LOW_HUMIDITY"
        }

        synced = sync.sync_batch()
        assert synced.success is True
        assert synced.synced == 4
        assert buffer.get_pending_count() == 0
        assert len(influx.rows) == 4

        alert_response = client.get("/api/v1/alerts?limit=20")
        assert alert_response.status_code == 200
        alerts = alert_response.json()["alerts"]
        assert {alert["type"] for alert in alerts} == {
            "HIGH_TEMPERATURE", "LOW_HUMIDITY", "LOW_SOIL_MOISTURE"
        }
        assert {alert["event_id"] for alert in alerts} == {
            high_temperature["event_id"], low_humidity["event_id"], dry_soil["event_id"]
        }

        with build_session_factory(engine)() as db_session:
            stored = db_session.execute(select(IngestedEvent)).scalars().all()
        assert len(stored) == 4
        assert all(row.processing_status == "STORED" for row in stored)
        assert invalid["event_id"] not in {row.event_id for row in stored}
    finally:
        session.close()
        gateway.close()
        buffer.close()
        client.__exit__(None, None, None)
        engine.dispose()
