"""Diagnostic subscriber. Validated receipts are JSONL on stdout; logs on stderr."""

import argparse
from datetime import datetime, timezone
import json
import logging
import math
import threading

import jsonschema

from mqtt_common import add_mqtt_arguments, make_client, sensor_routes
from sensor_base import SENSOR_EVENT_SCHEMA

LOG = logging.getLogger(__name__)


def validate_payload(topic, payload):
    event = json.loads(payload)
    jsonschema.Draft7Validator(
        SENSOR_EVENT_SCHEMA, format_checker=jsonschema.FormatChecker()
    ).validate(event)
    sensor_id, unit = sensor_routes()[topic]
    if event["sensor_id"] != sensor_id or event["unit"] != unit:
        raise ValueError("Topic does not match sensor_id/unit")
    if not math.isfinite(event["value"]):
        raise ValueError("Measurement must be finite")
    # jsonschema's date-time checker needs optional packages on some installs.
    measured_at = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
    if "T" not in event["timestamp"] or measured_at.utcoffset() is None:
        raise ValueError("Timestamp must include time and an explicit timezone")
    return event


class MqttSubscriber:
    def __init__(self, host="127.0.0.1", port=1883, qos=1, on_event=None):
        self.host, self.port, self.qos = host, port, qos
        self.on_event = on_event
        self.ready = threading.Event()
        self.client = make_client("subscriber")
        self.client.on_connect = self._on_connect
        self.client.on_connect_fail = self._on_connect_fail
        self.client.on_disconnect = self._on_disconnect
        self.client.on_subscribe = self._on_subscribe
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            LOG.error("MQTT connection refused: %s", reason_code)
            return
        # Re-subscribe on every connection, including after a broker restart.
        client.subscribe([(topic, self.qos) for topic in sensor_routes()])

    def _on_connect_fail(self, client, userdata):
        LOG.warning("MQTT CONNECT_FAILED; retry in 1..10s")

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties):
        if any(code.is_failure for code in reason_codes):
            LOG.error("MQTT subscription refused: %s", reason_codes)
            return
        self.ready.set()
        LOG.info("MQTT SUBSCRIBED all three sensor topics qos=%s", self.qos)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.ready.clear()
        if reason_code.is_failure:
            LOG.warning("MQTT DISCONNECTED: %s; automatic reconnect", reason_code)

    def _on_message(self, client, userdata, message):
        try:
            if message.retain:
                raise ValueError("Retained telemetry rejected: expected live measurements")
            event = validate_payload(message.topic, message.payload)
        except (ValueError, KeyError, UnicodeError, jsonschema.ValidationError) as exc:
            LOG.warning("MQTT INVALID topic=%s: %s", message.topic, exc)
            return
        receipt = {
            "topic": message.topic,
            "qos": message.qos,
            "received_at": datetime.now(timezone.utc).isoformat(),
            "event": event,
        }
        if self.on_event:
            self.on_event(receipt)
        else:
            print(json.dumps(receipt, ensure_ascii=False, allow_nan=False), flush=True)

    def start(self, timeout=10):
        self.client.connect_async(self.host, self.port, keepalive=15)
        self.client.loop_start()
        if not self.ready.wait(timeout):
            self.close()
            raise TimeoutError(f"No subscription acknowledgement from {self.host}:{self.port}")

    def close(self):
        self.client.disconnect()
        self.client.loop_stop()
        self.ready.clear()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_mqtt_arguments(parser)
    parser.add_argument("--duration", type=float, default=None, help="Stop after N seconds; default continuous")
    args = parser.parse_args()
    if args.duration is not None and args.duration <= 0:
        parser.error("--duration must be positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    subscriber = MqttSubscriber(args.host, args.port, args.qos)
    try:
        subscriber.start()
        threading.Event().wait(args.duration)
    except KeyboardInterrupt:
        pass
    except (TimeoutError, OSError) as exc:
        parser.exit(1, f"MQTT ERROR: {exc}\n")
    finally:
        subscriber.close()


if __name__ == "__main__":
    main()
