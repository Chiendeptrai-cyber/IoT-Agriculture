"""Publish Task 1 telemetry with QoS 1 and explicit delivery/outage logging."""

import json
import logging
import threading

import paho.mqtt.client as mqtt

from mqtt_common import make_client, sensor_routes
from sensor_base import BaseSensor

LOG = logging.getLogger(__name__)


class MqttPublisher:
    def __init__(self, host="127.0.0.1", port=1883, qos=1, timeout=10):
        if qos not in (0, 1):
            raise ValueError("QoS must be 0 or 1")
        self.host, self.port, self.qos, self.timeout = host, port, qos, timeout
        self.routes = {sensor_id: (topic, unit) for topic, (sensor_id, unit) in sensor_routes().items()}
        self.connected = threading.Event()
        self.client = make_client("publisher")
        self.client.on_connect = self._on_connect
        self.client.on_connect_fail = self._on_connect_fail
        self.client.on_disconnect = self._on_disconnect

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            LOG.error("MQTT connection refused: %s", reason_code)
            return
        self.connected.set()
        LOG.info("MQTT CONNECTED %s:%s", self.host, self.port)

    def _on_connect_fail(self, client, userdata):
        LOG.warning("MQTT CONNECT_FAILED %s:%s; retry in 1..10s", self.host, self.port)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected.clear()
        if reason_code.is_failure:
            LOG.warning("MQTT DISCONNECTED: %s; automatic reconnect in 1..10s", reason_code)

    def start(self):
        self.client.connect_async(self.host, self.port, keepalive=15)
        self.client.loop_start()
        if not self.connected.wait(self.timeout):
            self.close()
            raise TimeoutError(f"Broker {self.host}:{self.port} unavailable after {self.timeout}s")

    def publish(self, event):
        # OFFLINE sensors return None: never invent a placeholder measurement.
        if event is None:
            return False
        BaseSensor.validate_event(event)
        topic, unit = self.routes[event["sensor_id"]]
        if event["unit"] != unit:
            raise ValueError("Sensor unit does not match its topic")
        payload = json.dumps(event, ensure_ascii=False, allow_nan=False)
        if not self.connected.is_set():
            LOG.warning("MQTT SKIPPED_DISCONNECTED event_id=%s topic=%s", event["event_id"], topic)
            return False
        info = self.client.publish(topic, payload, qos=self.qos, retain=False)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            LOG.warning("MQTT NOT_CONFIRMED event_id=%s rc=%s", event["event_id"], info.rc)
            return False
        try:
            info.wait_for_publish(timeout=self.timeout)
            if not info.is_published():
                LOG.warning("MQTT ACK_TIMEOUT event_id=%s; delivery uncertain", event["event_id"])
                return False
        except (RuntimeError, ValueError) as exc:
            LOG.warning("MQTT NOT_CONFIRMED event_id=%s: %s", event["event_id"], exc)
            return False
        LOG.info("MQTT PUBLISHED topic=%s event_id=%s qos=%s", topic, event["event_id"], self.qos)
        return True

    def close(self):
        self.client.disconnect()
        self.client.loop_stop()
        self.connected.clear()


if __name__ == "__main__":
    from main import main

    main()
