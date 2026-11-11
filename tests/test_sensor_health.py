"""Task 2.1 health transitions, recovery, persistence and actual MQTT silence."""

from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import paho.mqtt.client as mqtt
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "edge-gateway"))

from buffer_manager import BufferManager, database_status
from mqtt_client import EdgeGateway
from sensor_health import SensorHealthMonitor
from settings import DEFAULT_DB_PATH, load_config, sensor_routes


def event(sequence=1, *, timestamp=None):
    return {"event_id": f"EVT-{uuid.uuid4().hex}", "sensor_id": "SEN-001", "unit": "C", "value": 29.5,
            "timestamp": (timestamp or datetime.now(timezone.utc)).isoformat(), "sequence": sequence}


@pytest.mark.parametrize("age,expected", [(0, "ONLINE"), (29.999, "ONLINE"), (30, "STALE"),
                                          (59.999, "STALE"), (60, "OFFLINE"), (120, "OFFLINE")])
def test_exact_health_boundaries(age, expected):
    received = datetime.now(timezone.utc)
    assert SensorHealthMonitor().classify(received, received, now=received + timedelta(seconds=age)) == expected


def test_never_seen_sensor_gets_startup_grace_without_false_online():
    started = datetime.now(timezone.utc)
    monitor = SensorHealthMonitor()
    assert monitor.classify(None, started, now=started) == "STALE"
    assert monitor.classify(None, started, now=started + timedelta(seconds=59)) == "STALE"
    assert monitor.classify(None, started, now=started + timedelta(seconds=60)) == "OFFLINE"


@pytest.mark.parametrize("stale,offline", [(0, 60), (-1, 60), (60, 60), (61, 60),
                                          (True, 60), (float("nan"), 60), (30, float("inf"))])
def test_invalid_health_thresholds(stale, offline):
    with pytest.raises(ValueError):
        SensorHealthMonitor(stale, offline)


def test_receipt_time_transitions_persist_and_duplicate_invalid_do_not_refresh(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    path = tmp_path / "health.db"
    buffer = BufferManager(path)
    gateway = EdgeGateway(buffer, load_config())
    payload = event()
    topic = "farm/sensors/temperature"
    try:
        assert gateway.process(topic, json.dumps(payload).encode())["status"] == "STORED"
        state = database_status(path)["sensor_health"][0]
        received = datetime.fromisoformat(state["last_received_at"])
        assert state["state"] == "ONLINE"
        gateway.check_health(now=received + timedelta(seconds=30))
        assert database_status(path)["sensor_health"][0]["state"] == "STALE"
        gateway.check_health(now=received + timedelta(seconds=60))
        offline = database_status(path)
        assert offline["sensor_health"][0]["state"] == "OFFLINE"
        count = len(offline["recent_health_events"])
        gateway.check_health(now=received + timedelta(seconds=61))
        assert len(database_status(path)["recent_health_events"]) == count
        assert gateway.process(topic, json.dumps(payload).encode())["status"] == "DUPLICATE"
        assert gateway.process(topic, b"bad")["classification"] == "INVALID"
        unchanged = database_status(path)["sensor_health"][0]
        assert unchanged["last_received_at"] == state["last_received_at"]
        assert unchanged["state"] == "OFFLINE"
        assert "state=STALE" in caplog.text and "state=OFFLINE" in caplog.text
    finally:
        buffer.close()
    restored = BufferManager(path)
    try:
        gateway = EdgeGateway(restored, load_config())
        assert database_status(path)["sensor_health"][0]["state"] == "OFFLINE"
        gateway.process(topic, json.dumps(event(sequence=2)).encode())
        assert database_status(path)["sensor_health"][0]["state"] == "ONLINE"
        assert database_status(path)["total"] == 2
    finally:
        restored.close()


def test_health_uses_received_at_not_original_measurement_time(tmp_path):
    buffer = BufferManager(tmp_path / "delayed.db")
    try:
        now = datetime.now(timezone.utc)
        result = buffer.store("farm/sensors/temperature", event(timestamp=now - timedelta(minutes=5)), load_config(), now=now)
        assert result["control_applied"] is False
        health = database_status(buffer.path)["sensor_health"][0]
        assert health["state"] == "ONLINE"
        assert health["last_received_at"] == now.isoformat()
    finally:
        buffer.close()


@pytest.mark.parametrize("interval", [0, -1, True, float("nan"), 31])
def test_invalid_poll_interval_is_rejected(tmp_path, interval):
    config = load_config()
    config["sensor_health"]["check_interval_seconds"] = interval
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path)


def test_legacy_config_gets_health_defaults(tmp_path):
    config = load_config()
    del config["sensor_health"]
    path = tmp_path / "legacy.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    assert load_config(path)["sensor_health"] == {
        "stale_after_seconds": 30, "offline_after_seconds": 60, "check_interval_seconds": 1
    }


def test_health_config_must_be_a_mapping(tmp_path):
    config = load_config()
    config["sensor_health"] = None
    path = tmp_path / "bad-health.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        load_config(path)


@pytest.mark.parametrize("normal", [[-50, 40], [40, 20]])
def test_invalid_normal_ranges_are_rejected(tmp_path, normal):
    config = load_config()
    config["normal_ranges"]["temperature"] = normal
    path = tmp_path / "bad-range.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError, match="normal range"):
        load_config(path)


def test_default_database_matches_task21_delivery_path():
    assert DEFAULT_DB_PATH == ROOT / "edge-gateway" / "edge.db"


def test_live_timer_detects_silence_and_recovery_without_server(tmp_path):
    if os.getenv("RUN_MQTT_INTEGRATION") != "1":
        pytest.skip("Set RUN_MQTT_INTEGRATION=1 and start Mosquitto")
    from mqtt_publisher import MqttPublisher
    host, port = os.getenv("MQTT_HOST", "127.0.0.1"), int(os.getenv("MQTT_PORT", "1883"))
    config = load_config()
    config["sensor_health"] = {"stale_after_seconds": 0.8, "offline_after_seconds": 1.6, "check_interval_seconds": 0.1}
    config_path = tmp_path / "fast.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    path, log_path = tmp_path / "live-health.db", tmp_path / "health-log.txt"
    client_id = f"edge-health-test-{uuid.uuid4().hex}"
    publisher = MqttPublisher(host, port)
    process = None
    def wait_for(predicate, description):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if predicate():
                return
            assert process.poll() is None, log_path.read_text(encoding="utf-8", errors="replace")
            time.sleep(0.025)
        pytest.fail(f"Timed out: {description}")
    def snapshot():
        return database_status(path)
    try:
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "-u", str(ROOT / "edge-gateway" / "main.py"), "--host", host, "--port", str(port),
                 "--client-id", client_id, "--db", str(path), "--config", str(config_path)], stdout=log, stderr=log,
            )
            wait_for(lambda: "EDGE MQTT SUBSCRIBED" in log_path.read_text(encoding="utf-8", errors="replace"), "MQTT subscription")
            publisher.start()
            first = event()
            assert publisher.publish(first)
            wait_for(lambda: snapshot()["sensor_health"][0]["state"] == "ONLINE", "ONLINE")
            online = snapshot()
            wait_for(lambda: snapshot()["sensor_health"][0]["state"] == "STALE", "STALE without any MQTT callback")
            stale = snapshot()
            wait_for(lambda: snapshot()["sensor_health"][0]["state"] == "OFFLINE", "OFFLINE without any MQTT callback")
            offline = snapshot()
            assert offline["total"] == offline["pending"] == 1
            assert all(h["state"] == "OFFLINE" for h in offline["sensor_health"])
            assert publisher.publish(first)
            wait_for(lambda: "EDGE DUPLICATE" in log_path.read_text(encoding="utf-8", errors="replace"), "duplicate receipt")
            after_duplicate = snapshot()
            assert after_duplicate["sensor_health"][0]["state"] == "OFFLINE"
            assert publisher.publish(event(sequence=2))
            wait_for(lambda: snapshot()["sensor_health"][0]["state"] == "ONLINE", "ONLINE recovery")
            recovered = snapshot()
            assert recovered["total"] == recovered["pending"] == 2
            assert recovered["synced"] == 0
            # Verify the public status CLI as well as direct SQLite queries.
            status = subprocess.run([sys.executable, str(ROOT / "edge-gateway" / "main.py"),
                                     "--status", "--db", str(path)], capture_output=True, text=True, timeout=10)
            assert status.returncode == 0, status.stderr
            assert json.loads(status.stdout)["total"] == 2
            evidence = os.getenv("EDGE_HEALTH_EVIDENCE_PATH")
            if evidence:
                Path(evidence).write_text(json.dumps({"config": config["sensor_health"], "online": online,
                    "stale": stale, "offline": offline, "after_duplicate": after_duplicate, "recovered": recovered,
                    "process_log": log_path.read_text(encoding="utf-8", errors="replace")}, indent=2), encoding="utf-8")
    finally:
        publisher.close()
        if process is not None:
            process.kill()
            process.wait(timeout=10)
        cleanup = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=True)
        try:
            cleanup.connect(host, port, keepalive=15)
            cleanup.loop_start()
            deadline = time.monotonic() + 5
            while not cleanup.is_connected() and time.monotonic() < deadline:
                time.sleep(0.05)
        except OSError:
            pass
        finally:
            cleanup.disconnect()
            cleanup.loop_stop()
