"""Edge acceptance: durable offline processing, idempotency and ACK ordering."""

from datetime import timedelta
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock
import uuid

import paho.mqtt.client as mqtt
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "edge-gateway"))

from settings import load_config, sensor_routes
from buffer_manager import BufferManager, database_status
from data_validator import utc_now
from mqtt_client import EdgeGateway


def reading(kind="soil_moisture", value=20, sequence=1, timestamp=None, event_id=None):
    topic = f"farm/sensors/{kind}"
    sensor_id, unit = sensor_routes()[topic]
    return topic, {
        "event_id": event_id or f"EVT-{uuid.uuid4().hex}", "sensor_id": sensor_id,
        "timestamp": timestamp or utc_now().isoformat(), "sequence": sequence, "value": value, "unit": unit,
    }


def send(gateway, kind="soil_moisture", value=20, sequence=1, **kwargs):
    topic, event = reading(kind, value, sequence, **kwargs)
    return event, gateway.process(topic, json.dumps(event).encode())


@pytest.fixture
def edge(tmp_path):
    buffer = BufferManager(tmp_path / "edge.db")
    gateway = EdgeGateway(buffer, load_config(), client_id=f"edge-test-{uuid.uuid4().hex}")
    yield gateway
    gateway.close()
    buffer.close()


def test_offline_reading_alerts_and_pump_commit_together(edge):
    send(edge, "temperature", 40)
    send(edge, "humidity", 35)
    event, result = send(edge)
    assert result["pump"] == "ON"
    status = database_status(edge.buffer.path)
    assert (status["total"], status["pending"], status["synced"]) == (3, 3, 0)
    assert status["alerts"] == 2
    assert status["device_actions"] == 1
    assert status["pump"]["last_event_id"] == event["event_id"]
    assert {r["kind"] for r in status["recent_alerts"]} == {"HIGH_TEMPERATURE", "LOW_HUMIDITY"}
    assert edge.buffer.connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert edge.buffer.connection.execute("PRAGMA synchronous").fetchone()[0] == 2


def test_restart_keeps_measurements_pending_alerts_and_pump(tmp_path):
    path = tmp_path / "restart.db"
    buffer = BufferManager(path)
    gateway = EdgeGateway(buffer, load_config())
    event, _ = send(gateway)
    send(gateway, "temperature", 40)
    buffer.close()
    restored = BufferManager(path)
    try:
        assert database_status(path)["pending"] == 2
        assert database_status(path)["pump"]["state"] == "ON"
        assert database_status(path)["alerts"] == 1
        assert event in restored.pending_batch()
    finally:
        restored.close()


def test_duplicate_and_conflicting_id_do_not_repeat_effects(edge):
    event, _ = send(edge)
    topic = "farm/sensors/soil_moisture"
    assert edge.process(topic, json.dumps(event).encode())["status"] == "DUPLICATE"
    event["value"] = 50
    assert edge.process(topic, json.dumps(event).encode())["status"] == "QUARANTINED"
    status = database_status(edge.buffer.path)
    assert (status["total"], status["device_actions"], status["quarantined"]) == (1, 1, 1)
    assert status["pump"]["state"] == "ON"


def test_hysteresis_strict_boundaries_and_restart_state(edge):
    for seq, (value, expected) in enumerate([(30, "OFF"), (29, "ON"), (30, "ON"),
                                              (35, "ON"), (36, "OFF"), (35, "OFF")], 1):
        _, result = send(edge, value=value, sequence=seq)
        assert result["pump"] == expected
    assert database_status(edge.buffer.path)["device_actions"] == 2


def test_threshold_boundaries_are_not_alerts(edge):
    send(edge, "temperature", 35)
    send(edge, "humidity", 40)
    assert database_status(edge.buffer.path)["alerts"] == 0


@pytest.mark.parametrize("bad", ["json", "missing", "sensor", "unit", "nan", "infinity", "huge_integer",
                                  "range", "timestamp", "future", "sequence", "duplicate_key", "oversize", "retained"])
def test_invalid_readings_are_quarantined(edge, bad):
    topic, event = reading()
    retained = bad == "retained"
    if bad == "missing":
        del event["event_id"]
    elif bad == "sensor":
        event["sensor_id"] = "SEN-001"
    elif bad == "unit":
        event["unit"] = "C"
    elif bad == "nan":
        event["value"] = float("nan")
    elif bad == "infinity":
        event["value"] = float("inf")
    elif bad == "huge_integer":
        event["value"] = 10 ** 400
    elif bad == "range":
        event["value"] = 101
    elif bad == "timestamp":
        event["timestamp"] = "2026-11-10"
    elif bad == "future":
        event["timestamp"] = (utc_now() + timedelta(minutes=10)).isoformat()
    elif bad == "sequence":
        event["sequence"] = 0
    payload = json.dumps(event).encode()
    if bad == "json":
        payload = b"{broken"
    elif bad == "duplicate_key":
        payload = payload[:-1] + b', "value": 99}'
    elif bad == "oversize":
        payload = b"x" * (edge.config["max_payload_bytes"] + 1)
    assert edge.process(topic, payload, retained=retained)["status"] == "QUARANTINED"
    status = database_status(edge.buffer.path)
    assert status["total"] == 0
    assert status["quarantined"] == 1
    assert status["pump"]["state"] == "OFF"


def test_delayed_and_out_of_order_data_saved_without_reversing_pump(edge):
    now = utc_now()
    send(edge, value=20, sequence=5, timestamp=now.isoformat())
    _, result = send(edge, value=60, sequence=6, timestamp=(now - timedelta(seconds=1)).isoformat())
    assert result["control_applied"] is False
    assert result["pump"] == "ON"
    _, result = send(edge, "temperature", 50, timestamp=(now - timedelta(minutes=5)).isoformat())
    assert result["control_applied"] is False
    assert database_status(edge.buffer.path)["total"] == 3
    assert database_status(edge.buffer.path)["alerts"] == 0


def test_ack_only_after_another_connection_can_read_committed_record(edge):
    topic, event = reading()
    client = Mock()
    def ack(mid, qos):
        status = database_status(edge.buffer.path)
        assert status["pending"] == 1
        assert status["pump"]["state"] == "ON"
        assert status["device_actions"] == 1
        return 0
    client.ack.side_effect = ack
    edge._on_message(client, None, SimpleNamespace(topic=topic, payload=json.dumps(event).encode(), retain=False, qos=1, mid=42))
    client.ack.assert_called_once_with(42, 1)


def test_storage_failure_rolls_back_everything_and_does_not_ack(edge, monkeypatch):
    import buffer_manager
    def fail(*args):
        raise sqlite3.OperationalError("simulated disk full")
    monkeypatch.setattr(buffer_manager, "evaluate", fail)
    topic, event = reading()
    client = Mock()
    edge._on_message(client, None, SimpleNamespace(topic=topic, payload=json.dumps(event).encode(), retain=False, qos=1, mid=43))
    assert edge.failed.is_set()
    client.ack.assert_not_called()
    client.disconnect.assert_called_once()
    status = database_status(edge.buffer.path)
    assert (status["total"], status["alerts"], status["device_actions"]) == (0, 0, 0)
    assert status["pump"]["state"] == "OFF"


def test_quarantine_commits_before_ack(edge):
    client = Mock()
    client.ack.side_effect = lambda mid, qos: 0 if database_status(edge.buffer.path)["quarantined"] == 1 else 99
    edge._on_message(client, None, SimpleNamespace(topic="farm/sensors/humidity", payload=b"{broken", retain=False, qos=1, mid=44))
    assert database_status(edge.buffer.path)["quarantined"] == 1
    client.ack.assert_called_once_with(44, 1)


def test_same_second_older_sequence_does_not_control(edge):
    now = utc_now().replace(microsecond=0).isoformat()
    send(edge, value=20, sequence=2, timestamp=now)
    _, result = send(edge, value=60, sequence=1, timestamp=now)
    assert result["control_applied"] is False
    assert result["pump"] == "ON"


def test_invalid_hysteresis_config_fails_before_running(tmp_path):
    import yaml
    config = load_config()
    config["thresholds"]["soil_on_below"] = 40
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError, match="soil_on_below"):
        load_config(path)


def wait_for_total(path, total):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.exists() and database_status(path)["total"] >= total:
            return
        time.sleep(0.05)
    pytest.fail(f"Edge did not persist {total} records")


def test_live_mqtt_edge_without_server_survives_process_restart(tmp_path):
    if os.getenv("RUN_MQTT_INTEGRATION") != "1":
        pytest.skip("Set RUN_MQTT_INTEGRATION=1 and start Mosquitto")
    from mqtt_publisher import MqttPublisher
    host = os.getenv("MQTT_HOST", "127.0.0.1")
    port = int(os.getenv("MQTT_PORT", "1883"))
    # Use an available port as an unreachable Server URL. There is no Server process.
    server_probe = socket.socket()
    server_probe.bind(("127.0.0.1", 0))
    unavailable_server = f"http://127.0.0.1:{server_probe.getsockname()[1]}"
    # The port is reserved but not listening, so no Server can accept requests.
    path = tmp_path / "live-edge.db"
    client_id = f"edge-integration-{uuid.uuid4().hex}"
    environment = dict(os.environ, SERVER_URL=unavailable_server)
    command = [sys.executable, "-u", str(ROOT / "edge-gateway" / "main.py"),
               "--host", host, "--port", str(port), "--db", str(path), "--client-id", client_id]
    publisher = MqttPublisher(host, port)
    def launch(log, log_path):
        process = subprocess.Popen(command, env=environment, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if "EDGE MQTT SUBSCRIBED" in log_path.read_text(encoding="utf-8", errors="replace"):
                    return process
                assert process.poll() is None, "Edge exited before subscribing"
                time.sleep(0.05)
            pytest.fail("Edge did not subscribe")
        except BaseException:
            process.kill()
            process.wait(timeout=10)
            raise
    # Open log files directly to avoid pipe deadlocks while testing process restarts.
    first_path, second_path = tmp_path / "first.txt", tmp_path / "second.txt"
    process = None
    try:
        publisher.start()
        with first_path.open("w", encoding="utf-8") as log:
            process = launch(log, first_path)
            for kind, value in [("temperature", 40), ("humidity", 35), ("soil_moisture", 20)]:
                _, event = reading(kind, value)
                assert publisher.publish(event)
            wait_for_total(path, 3)
            before = database_status(path)
            assert (before["pending"], before["alerts"], before["pump"]["state"]) == (3, 2, "ON")
            # Abrupt process termination: committed data and state must survive.
            process.kill()
            process.wait(timeout=10)
            process = None
        assert database_status(path)["pending"] == 3
        with second_path.open("w", encoding="utf-8") as log:
            process = launch(log, second_path)
            assert database_status(path)["pump"]["state"] == "ON"
            assert publisher.publish(reading("soil_moisture", 32, sequence=2)[1])
            wait_for_total(path, 4)
            assert database_status(path)["pump"]["state"] == "ON"
            assert publisher.publish(reading("soil_moisture", 40, sequence=3)[1])
            wait_for_total(path, 5)
            after = database_status(path)
            assert (after["pending"], after["synced"], after["pump"]["state"], after["device_actions"]) == (5, 0, "OFF", 2)
            demo = subprocess.run(
                [sys.executable, str(ROOT / "sensor-simulator" / "edge_demo.py"), "--host", host,
                 "--port", str(port), "--interval", "0.05"],
                capture_output=True, text=True, timeout=20,
            )
            assert demo.returncode == 0, demo.stderr
            wait_for_total(path, 10)
            deadline = time.monotonic() + 5
            while database_status(path)["quarantined"] < 1 or "EDGE DUPLICATE" not in second_path.read_text(encoding="utf-8", errors="replace"):
                assert time.monotonic() < deadline, "Demo duplicate/quarantine not processed"
                time.sleep(0.05)
            after_demo = database_status(path)
            assert (after_demo["pending"], after_demo["alerts"], after_demo["device_actions"], after_demo["quarantined"]) == (10, 4, 4, 1)
        evidence = os.getenv("EDGE_EVIDENCE_PATH")
        if evidence:
            Path(evidence).write_text(json.dumps({"server_url_unavailable": unavailable_server,
                "before_restart": before, "after_restart": after, "after_demo": after_demo,
                "first_process_log": first_path.read_text(encoding="utf-8", errors="replace"),
                "second_process_log": second_path.read_text(encoding="utf-8", errors="replace")}, indent=2), encoding="utf-8")
    finally:
        server_probe.close()
        publisher.close()
        if process is not None:
            process.kill()
            process.wait(timeout=10)
        # Remove this test's persistent broker session so later demos do not
        # accumulate messages for abandoned integration-test client IDs.
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
