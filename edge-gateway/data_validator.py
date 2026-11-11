"""Validate wire payloads before they enter the Edge telemetry buffer."""

from datetime import datetime, timezone
import json
import math
import re

import jsonschema

from settings import SENSOR_EVENT_SCHEMA, sensor_routes
from threshold_engine import evaluate

VALIDATOR = jsonschema.Draft7Validator(SENSOR_EVENT_SCHEMA)
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")


def utc_now():
    return datetime.now(timezone.utc)


def event_time(event):
    return datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00")).astimezone(timezone.utc)


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def validate_payload(topic, payload, config, *, retained=False, now=None):
    if retained:
        raise ValueError("Retained telemetry is not a live reading")
    if len(payload) > config["max_payload_bytes"]:
        raise ValueError("Payload exceeds max_payload_bytes")
    routes = sensor_routes()
    if topic not in routes:
        raise ValueError("Unknown sensor topic")
    event = json.loads(payload, object_pairs_hook=unique_keys)
    VALIDATOR.validate(event)
    sensor_id, unit = routes[topic]
    if event["sensor_id"] != sensor_id or event["unit"] != unit:
        raise ValueError("sensor_id/unit does not match topic")
    if not math.isfinite(event["value"]):
        raise ValueError("Measurement must be finite")
    name = topic.rsplit("/", 1)[-1]
    minimum, maximum = config["valid_ranges"][name]
    if not minimum <= event["value"] <= maximum:
        raise ValueError(f"Measurement outside physical range [{minimum}, {maximum}]")
    if not TIMESTAMP.fullmatch(event["timestamp"]):
        raise ValueError("Expected ISO 8601 timestamp with explicit timezone")
    measured_at = event_time(event)
    if (measured_at - (now or utc_now())).total_seconds() > config["future_tolerance_seconds"]:
        raise ValueError("Measurement timestamp is too far in the future")
    return event


def classify_event(topic, event, config):
    """A valid reading may still require an agricultural threshold response."""
    alerts, _ = evaluate(topic, event["value"], "OFF", config["thresholds"])
    dry_soil = topic.endswith("/soil_moisture") and event["value"] < config["thresholds"]["soil_on_below"]
    minimum, maximum = config["normal_ranges"][topic.rsplit("/", 1)[-1]]
    outside_normal = not minimum <= event["value"] <= maximum
    return "ANOMALY" if alerts or dry_soil or outside_normal else "NORMAL"
