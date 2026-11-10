"""Receive MQTT telemetry, commit local effects, then acknowledge delivery."""

import logging
import sqlite3
import threading

import jsonschema
import paho.mqtt.client as mqtt

from data_validator import validate_payload
from settings import sensor_routes
from sensor_health import SensorHealthMonitor

LOG = logging.getLogger(__name__)


class EdgeGateway:
    def __init__(self, buffer, config, host="127.0.0.1", port=1883, client_id="farm-edge-001"):
        self.buffer, self.config = buffer, config
        self.host, self.port = host, port
        self.buffer.configure(config)
        health = config["sensor_health"]
        self.health_monitor = SensorHealthMonitor(health["stale_after_seconds"], health["offline_after_seconds"])
        self.ready = threading.Event()
        self.failed = threading.Event()
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            clean_session=False,
            protocol=mqtt.MQTTv311,
            manual_ack=True,
        )
        self.client.reconnect_delay_set(min_delay=1, max_delay=10)
        self.client.on_connect = self._on_connect
        self.client.on_connect_fail = self._on_connect_fail
        self.client.on_disconnect = self._on_disconnect
        self.client.on_subscribe = self._on_subscribe
        self.client.on_message = self._on_message

    def process(self, topic, payload, *, retained=False):
        try:
            event = validate_payload(topic, payload, self.config, retained=retained)
            LOG.info("EDGE Received %s: %s %s; Validation successful", event["sensor_id"], event["value"], event["unit"])
            result = self.buffer.store(topic, event, self.config)
        except (ValueError, UnicodeError, RecursionError, OverflowError, jsonschema.ValidationError) as exc:
            reason = str(exc)
            self.buffer.quarantine(topic, payload, reason, max_bytes=self.config["max_payload_bytes"])
            LOG.warning("EDGE QUARANTINED topic=%s reason=%s", topic, reason.splitlines()[0])
            return {"status": "QUARANTINED", "classification": "INVALID", "reason": reason}
        LOG.info("EDGE %s event_id=%s", result["status"], result["event_id"])
        if result["status"] == "STORED":
            LOG.info("EDGE DURABLE Record persisted to SQLite event_id=%s classification=%s sync_status=PENDING control_applied=%s",
                     result["event_id"], result["classification"], result["control_applied"])
            if result["health_change"]:
                self._log_health(result["health_change"])
            for kind in result["alerts"]:
                LOG.warning("EDGE ALERT kind=%s event_id=%s", kind, result["event_id"])
            if result["pump_changed"]:
                LOG.info("EDGE VIRTUAL_PUMP state=%s event_id=%s", result["pump"], result["event_id"])
        return result

    @staticmethod
    def _log_health(change):
        level = {"ONLINE": logging.INFO, "STALE": logging.WARNING, "OFFLINE": logging.ERROR}[change["state"]]
        LOG.log(level, "EDGE SENSOR_HEALTH sensor_id=%s previous=%s state=%s reason=%s",
                change["sensor_id"], change["previous_state"], change["state"], change["reason"])

    def check_health(self, *, now=None):
        changes = self.buffer.check_sensor_health(self.health_monitor, now=now)
        for change in changes:
            self._log_health(change)
        return changes

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            LOG.error("EDGE MQTT connection refused: %s", reason_code)
            return
        client.subscribe([(topic, 1) for topic in sensor_routes()])

    def _on_connect_fail(self, client, userdata):
        LOG.warning("EDGE MQTT CONNECT_FAILED; retry in 1..10s")

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties):
        if any(code.is_failure for code in reason_codes):
            LOG.error("EDGE subscription refused: %s", reason_codes)
            return
        self.ready.set()
        LOG.info("EDGE MQTT SUBSCRIBED three topics qos=1; SQLite ready; Server not required")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.ready.clear()
        if reason_code.is_failure:
            LOG.warning("EDGE MQTT DISCONNECTED: %s; automatic reconnect", reason_code)

    def _on_message(self, client, userdata, message):
        try:
            self.process(message.topic, message.payload, retained=message.retain)
        except (sqlite3.Error, OSError):
            # Fail closed. Do not acknowledge a record that did not commit.
            LOG.exception("EDGE STORAGE_FAILED; MQTT message not acknowledged; stopping Edge")
            self.failed.set()
            client.disconnect()
            return
        if message.qos > 0:
            result = client.ack(message.mid, message.qos)
            if result != mqtt.MQTT_ERR_SUCCESS:
                LOG.warning("EDGE ACK_NOT_SENT mid=%s rc=%s; duplicate delivery is safe", message.mid, result)

    def start(self, timeout=10):
        self.check_health()
        self.client.connect_async(self.host, self.port, keepalive=15)
        self.client.loop_start()
        if not self.ready.wait(timeout):
            self.close()
            raise TimeoutError(f"No Edge subscription acknowledgement from {self.host}:{self.port}")

    def close(self):
        self.client.disconnect()
        self.client.loop_stop()
        self.ready.clear()
