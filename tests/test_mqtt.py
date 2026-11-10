"""Task 2 unit tests and opt-in tests against the real Docker Mosquitto broker."""

import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sensor-simulator"))

from main import build_sensor_fleet
from mqtt_common import sensor_routes
from mqtt_publisher import MqttPublisher
from mqtt_subscriber import MqttSubscriber, validate_payload


@pytest.mark.parametrize("sensor", build_sensor_fleet())
def test_publish_routes_valid_json_and_waits_for_ack(sensor):
    publisher = MqttPublisher()
    publisher.client = Mock()
    publisher.connected.set()
    info = publisher.client.publish.return_value
    info.rc = 0
    info.is_published.return_value = True
    event = sensor.generate_event()
    assert publisher.publish(event)
    args, kwargs = publisher.client.publish.call_args
    assert sensor_routes()[args[0]] == (event["sensor_id"], event["unit"])
    assert json.loads(args[1]) == event
    assert kwargs == {"qos": 1, "retain": False}
    info.wait_for_publish.assert_called_once()


def test_offline_and_disconnected_never_report_success(caplog):
    publisher = MqttPublisher()
    publisher.client = Mock()
    for sensor in build_sensor_fleet(default_mode="OFFLINE"):
        assert not publisher.publish(sensor.generate_event())
    assert not publisher.publish(build_sensor_fleet()[0].generate_event())
    publisher.client.publish.assert_not_called()
    assert "SKIPPED_DISCONNECTED" in caplog.text


@pytest.mark.parametrize("failure", ["rc", "timeout", "exception"])
def test_missing_ack_is_logged(failure, caplog):
    publisher = MqttPublisher()
    publisher.connected.set()
    publisher.client = Mock()
    info = publisher.client.publish.return_value
    info.rc = 4 if failure == "rc" else 0
    info.is_published.return_value = False
    if failure == "exception":
        info.wait_for_publish.side_effect = RuntimeError("Disconnected")
    assert not publisher.publish(build_sensor_fleet()[0].generate_event())
    assert "NOT_CONFIRMED" in caplog.text or "ACK_TIMEOUT" in caplog.text


@pytest.mark.parametrize("bad", ["json", "missing", "identity", "unit", "timestamp", "nan", "sequence"])
def test_invalid_payload_rejected(bad):
    event = build_sensor_fleet()[0].generate_event()
    if bad == "missing":
        del event["event_id"]
    elif bad == "identity":
        event["sensor_id"] = "SEN-002"
    elif bad == "unit":
        event["unit"] = "%"
    elif bad == "timestamp":
        event["timestamp"] = "2026-11-10"
    elif bad == "nan":
        event["value"] = float("nan")
    elif bad == "sequence":
        event["sequence"] = 0
    payload = b"{broken" if bad == "json" else json.dumps(event).encode()
    with pytest.raises((ValueError, jsonschema.ValidationError)):
        validate_payload("farm/sensors/temperature", payload)


def test_subscriber_rejects_bad_and_retained_messages_then_accepts_live(caplog):
    receipts = []
    subscriber = MqttSubscriber(on_event=receipts.append)
    event = build_sensor_fleet()[0].generate_event()
    msg = SimpleNamespace(topic="farm/sensors/temperature", payload=b"bad", retain=False, qos=1)
    subscriber._on_message(None, None, msg)
    msg.payload = json.dumps(event).encode()
    msg.retain = True
    subscriber._on_message(None, None, msg)
    assert not receipts
    msg.retain = False
    subscriber._on_message(None, None, msg)
    assert receipts[0]["event"] == event
    assert "received_at" in receipts[0]
    assert "INVALID" in caplog.text


def test_subscriber_resubscribes_after_reconnect():
    subscriber = MqttSubscriber()
    client = Mock()
    reason = SimpleNamespace(is_failure=False)
    subscriber._on_connect(client, None, None, reason, None)
    subscriber._on_disconnect(client, None, None, reason, None)
    subscriber._on_connect(client, None, None, reason, None)
    assert client.subscribe.call_count == 2
    assert client.subscribe.call_args.args[0] == [(topic, 1) for topic in sensor_routes()]


def wait_until(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    pytest.fail("Timed out waiting for MQTT state")


@pytest.fixture
def live_pair():
    if os.getenv("RUN_MQTT_INTEGRATION") != "1":
        pytest.skip("Set RUN_MQTT_INTEGRATION=1 and start the Mosquitto broker")
    host = os.getenv("MQTT_HOST", "127.0.0.1")
    port = int(os.getenv("MQTT_PORT", "1883"))
    receipts = queue.Queue()
    subscriber = MqttSubscriber(host, port, on_event=receipts.put)
    publisher = MqttPublisher(host, port)
    try:
        subscriber.start()
        publisher.start()
        yield publisher, subscriber, receipts
    finally:
        publisher.close()
        subscriber.close()


def test_live_three_topics_offline_and_no_retained_replay(live_pair):
    publisher, subscriber, receipts = live_pair
    fleet = build_sensor_fleet()
    events = [sensor.generate_event() for sensor in fleet]
    for event in events:
        assert publisher.publish(event)
    received = [receipts.get(timeout=5) for _ in events]
    assert {r["topic"] for r in received} == set(sensor_routes())
    assert {r["event"]["event_id"] for r in received} == {e["event_id"] for e in events}
    assert all(r["qos"] == 1 for r in received)
    for sensor in fleet:
        sensor.set_mode("OFFLINE")
        assert not publisher.publish(sensor.generate_event())
    with pytest.raises(queue.Empty):
        receipts.get(timeout=1)
    # A newly subscribed client must not receive the last old measurement.
    late_receipts = queue.Queue()
    late = MqttSubscriber(publisher.host, publisher.port, on_event=late_receipts.put)
    try:
        late.start()
        with pytest.raises(queue.Empty):
            late_receipts.get(timeout=1)
    finally:
        late.close()
    evidence_path = os.getenv("MQTT_EVIDENCE_PATH")
    if evidence_path:
        Path(evidence_path).write_text(
            "\n".join(json.dumps(r) for r in received) + "\n", encoding="utf-8"
        )


def test_live_cli_publishes_all_sensors(live_pair):
    publisher, subscriber, receipts = live_pair
    result = subprocess.run(
        [sys.executable, str(ROOT / "sensor-simulator" / "main.py"),
         "--host", publisher.host, "--port", str(publisher.port), "--interval", "0.1", "--count", "2"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    received = [receipts.get(timeout=5) for _ in range(6)]
    for topic in sensor_routes():
        assert {r["event"]["sequence"] for r in received if r["topic"] == topic} == {1, 2}


def test_live_broker_restart_recovers(live_pair, caplog):
    if os.getenv("RUN_MQTT_RESTART") != "1":
        pytest.skip("Set RUN_MQTT_RESTART=1 to allow stopping the local test broker")
    publisher, subscriber, receipts = live_pair
    command = ["docker", "compose", "-f", str(ROOT / "infrastructure" / "docker-compose.yml")]
    subprocess.run(command + ["stop", "mosquitto"], check=True, timeout=40)
    try:
        wait_until(lambda: not publisher.connected.is_set() and not subscriber.ready.is_set())
        assert not publisher.publish(build_sensor_fleet()[0].generate_event())
        with pytest.raises(queue.Empty):
            receipts.get(timeout=1)
    finally:
        subprocess.run(command + ["start", "mosquitto"], check=True, timeout=40)
    wait_until(lambda: publisher.connected.is_set() and subscriber.ready.is_set(), timeout=30)
    for sensor in build_sensor_fleet():
        assert publisher.publish(sensor.generate_event())
    received = [receipts.get(timeout=5) for _ in range(3)]
    assert {r["topic"] for r in received} == set(sensor_routes())
    assert "DISCONNECTED" in caplog.text
    assert "SKIPPED_DISCONNECTED" in caplog.text
