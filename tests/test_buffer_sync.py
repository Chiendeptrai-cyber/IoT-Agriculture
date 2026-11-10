"""Classification, non-destructive schema upgrades and explicit Server ACKs."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "edge-gateway"))

from buffer_manager import BufferManager, database_status
from mqtt_client import EdgeGateway
from settings import load_config, sensor_routes


def make_event(kind="temperature", value=29.5):
    topic = f"farm/sensors/{kind}"
    sensor_id, unit = sensor_routes()[topic]
    return topic, {"event_id": f"EVT-{uuid.uuid4().hex}", "sensor_id": sensor_id, "unit": unit,
                   "value": value, "timestamp": datetime.now(timezone.utc).isoformat(), "sequence": 1}


@pytest.fixture
def buffer(tmp_path):
    result = BufferManager(tmp_path / "buffer.db")
    yield result
    result.close()


@pytest.mark.parametrize("kind,value,classification", [("temperature", 35, "NORMAL"), ("temperature", 40, "ANOMALY"),
    ("humidity", 40, "NORMAL"), ("humidity", 35, "ANOMALY"), ("soil_moisture", 30, "NORMAL"),
    ("soil_moisture", 20, "ANOMALY"), ("soil_moisture", 40, "NORMAL"),
    ("temperature", -4, "ANOMALY"), ("humidity", 98, "ANOMALY"), ("soil_moisture", 90, "ANOMALY")])
def test_explicit_classification_is_persisted(buffer, kind, value, classification):
    gateway = EdgeGateway(buffer, load_config())
    topic, event = make_event(kind, value)
    result = gateway.process(topic, json.dumps(event).encode())
    assert result["classification"] == classification
    assert buffer.connection.execute("SELECT classification FROM telemetry").fetchone()[0] == classification
    assert database_status(buffer.path)["classifications"] == {classification: 1}


def test_invalid_classification_is_quarantined_and_not_a_health_heartbeat(buffer):
    gateway = EdgeGateway(buffer, load_config())
    topic, event = make_event("humidity", 150)
    result = gateway.process(topic, json.dumps(event).encode())
    assert result["classification"] == "INVALID"
    assert buffer.connection.execute("SELECT classification FROM quarantine").fetchone()[0] == "INVALID"
    assert database_status(buffer.path)["sensor_health"][1]["last_received_at"] is None


def store_events(buffer, count=3):
    ids = []
    for _ in range(count):
        topic, event = make_event()
        buffer.store(topic, event, load_config())
        ids.append(event["event_id"])
    return ids


def test_partial_ack_updates_only_acknowledged_ids_and_is_idempotent(buffer):
    ids = store_events(buffer)
    acknowledged_at = datetime.now(timezone.utc)
    assert buffer.mark_synced([ids[0]], sent_event_ids=ids, acknowledged_at=acknowledged_at) == 1
    assert {event["event_id"] for event in buffer.pending_batch()} == set(ids[1:])
    assert database_status(buffer.path)["total"] == 3
    assert (database_status(buffer.path)["pending"], database_status(buffer.path)["synced"]) == (2, 1)
    assert buffer.mark_synced([ids[0]], sent_event_ids=ids, acknowledged_at=acknowledged_at + timedelta(minutes=1)) == 0
    row = buffer.connection.execute("SELECT synced_at FROM telemetry WHERE event_id=?", (ids[0],)).fetchone()
    assert row[0] == acknowledged_at.isoformat()
    assert buffer.mark_synced(ids[1:], sent_event_ids=ids) == 2
    assert buffer.pending_batch() == []
    assert database_status(buffer.path)["synced"] == 3


def test_absent_ack_keeps_every_record_pending(buffer):
    ids = store_events(buffer)
    assert buffer.mark_synced([], sent_event_ids=ids) == 0
    assert len(buffer.pending_batch()) == 3
    assert buffer.connection.execute("SELECT COUNT(*) FROM telemetry WHERE synced_at IS NOT NULL").fetchone()[0] == 0


def test_unknown_ack_rolls_back_entire_update(buffer):
    ids = store_events(buffer)
    unknown = "EVT-NOT-LOCAL"
    with pytest.raises(ValueError, match="missing"):
        buffer.mark_synced([ids[0], unknown], sent_event_ids=[*ids, unknown])
    assert database_status(buffer.path)["pending"] == 3


def test_ack_outside_sent_batch_is_rejected(buffer):
    ids = store_events(buffer)
    with pytest.raises(ValueError, match="outside"):
        buffer.mark_synced([ids[1]], sent_event_ids=[ids[0]])
    assert database_status(buffer.path)["pending"] == 3


@pytest.mark.parametrize("bad", ["EVT-001", 1, [None], [True], [""], ["EVT-X"] * 1001])
def test_bad_ack_format_does_not_change_status(buffer, bad):
    ids = store_events(buffer)
    with pytest.raises(ValueError):
        buffer.mark_synced(bad, sent_event_ids=ids)
    assert database_status(buffer.path)["pending"] == 3


def test_naive_ack_datetime_is_rejected(buffer):
    ids = store_events(buffer)
    with pytest.raises(ValueError, match="timezone"):
        buffer.mark_synced([ids[0]], sent_event_ids=ids, acknowledged_at=datetime.now())
    assert database_status(buffer.path)["pending"] == 3


def test_synced_status_and_original_payload_survive_reopening(tmp_path):
    path = tmp_path / "sync.db"
    buffer = BufferManager(path)
    topic, event = make_event()
    buffer.store(topic, event, load_config())
    buffer.mark_synced([event["event_id"]], sent_event_ids=[event["event_id"]])
    buffer.close()
    restored = BufferManager(path)
    try:
        assert restored.pending_batch() == []
        row = restored.connection.execute("SELECT * FROM telemetry").fetchone()
        assert json.loads(row["payload"]) == event
        assert row["sync_status"] == "SYNCED" and row["synced_at"] is not None
    finally:
        restored.close()


def test_legacy_database_upgrades_without_losing_pending_records(tmp_path):
    path = tmp_path / "legacy.db"
    topic, event = make_event(value=40)
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(path) as connection:
        connection.execute("""CREATE TABLE telemetry (
            event_id TEXT PRIMARY KEY, sensor_id TEXT, timestamp TEXT, sequence INTEGER,
            value REAL, unit TEXT, topic TEXT, payload TEXT, received_at TEXT,
            processed_at TEXT, control_applied INTEGER, sync_status TEXT DEFAULT 'PENDING')""")
        connection.execute("INSERT INTO telemetry VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (event["event_id"], event["sensor_id"], event["timestamp"], 1, 40, "C", topic,
             json.dumps(event), now, now, 1, "PENDING"))
    upgraded = BufferManager(path)
    try:
        gateway = EdgeGateway(upgraded, load_config())
        gateway.check_health()
        status = database_status(path)
        assert status["total"] == status["pending"] == 1
        assert status["classifications"] == {"ANOMALY": 1}
        assert upgraded.pending_batch() == [event]
        assert len(status["sensor_health"]) == 3
        assert status["sensor_health"][0]["last_received_at"] == now
        assert status["sensor_health"][0]["state"] == "ONLINE"
        assert upgraded.mark_synced([event["event_id"]], sent_event_ids=[event["event_id"]]) == 1
    finally:
        upgraded.close()
