"""Acceptance KT1: data from all three sensors reaches durable Server stores."""

import json
from pathlib import Path
import sys
import uuid

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from acceptance_support import make_http_session, make_server
from buffer_manager import BufferManager, database_status
from server.database import build_session_factory
from humidity import HumiditySensor
from mqtt_common import sensor_routes
from mqtt_client import EdgeGateway
from server.models import IngestedEvent
from settings import load_config
from soil_moisture import SoilMoistureSensor
from sync_manager import SyncManager
from temperature import TemperatureSensor


def test_kt1_three_sensor_events_reach_edge_and_server_stores(tmp_path):
    """KT1 verifies sensor identity, Edge validation/buffering and Server ACKs."""
    client, engine, influx = make_server()
    buffer = BufferManager(tmp_path / "kt1-edge.db")
    gateway = EdgeGateway(buffer, load_config(), client_id=f"kt1-{uuid.uuid4().hex}")
    session = make_http_session(client)
    sync = SyncManager(
        buffer,
        config=load_config(),
        server_url="http://acceptance.test/api/v1/telemetry/batch",
        session=session,
    )
    sensors = (TemperatureSensor(), HumiditySensor(), SoilMoistureSensor())
    try:
        expected = {sensor.sensor_id for sensor in sensors}
        accepted_events = []
        routes = sensor_routes()

        for sensor in sensors:
            event = sensor.generate_event()
            topic = next(topic for topic, route in routes.items() if route[0] == sensor.sensor_id)
            result = gateway.process(topic, json.dumps(event).encode("utf-8"))
            assert result["status"] == "STORED"
            assert result["sync_status"] == "PENDING"
            accepted_events.append(event)

        assert database_status(buffer.path)["pending"] == 3
        assert {record["sensor_id"] for record in buffer.pending_batch()} == expected

        sync_result = sync.sync_batch()
        assert sync_result.success is True
        assert sync_result.synced == 3
        assert sync_result.remaining_pending == 0
        assert buffer.get_synced_count() == 3
        assert len(influx.rows) == 3

        for sensor_id in expected:
            latest = client.get(f"/api/v1/sensors/{sensor_id}/latest")
            assert latest.status_code == 200
            assert latest.json()["sensor_id"] == sensor_id

        with build_session_factory(engine)() as db_session:
            rows = db_session.execute(select(IngestedEvent)).scalars().all()
        assert len(rows) == 3
        assert {row.sensor_id for row in rows} == expected
        assert {row.event_id for row in rows} == {event["event_id"] for event in accepted_events}
        assert all(row.processing_status == "STORED" for row in rows)

        # A replay with the same identity is acknowledged as duplicate and does
        # not create a second PostgreSQL ledger row or Influx point.
        replay = client.post("/api/v1/telemetry/batch", json={"records": accepted_events})
        assert replay.status_code == 200
        assert replay.json()["accepted"] == 0
        assert replay.json()["duplicates"] == 3
        assert len(influx.rows) == 3
    finally:
        session.close()
        gateway.close()
        buffer.close()
        client.__exit__(None, None, None)
        engine.dispose()
