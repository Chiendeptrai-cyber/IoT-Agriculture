"""Load Edge settings and reuse Task 1's schema and sensor registry."""

import math
from pathlib import Path
import sys

import yaml

from sensor_health import SensorHealthMonitor

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = Path(__file__).with_name("edge.db")
# The repository uses script directories, not installed Python packages.
# Reuse the simulator's contract instead of maintaining a second JSON schema.
sys.path.append(str(ROOT / "sensor-simulator"))
from mqtt_common import sensor_routes
from sensor_base import SENSOR_EVENT_SCHEMA


def load_config(path=None):
    path = Path(path) if path else Path(__file__).with_name("edge_config.yaml")
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Edge configuration must be a YAML mapping")
    for key in ("temperature_high", "humidity_low", "soil_on_below", "soil_off_above"):
        value = config["thresholds"][key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"Invalid threshold: {key}")
    if config["thresholds"]["soil_on_below"] >= config["thresholds"]["soil_off_above"]:
        raise ValueError("soil_on_below must be less than soil_off_above")
    normal_ranges = config.setdefault("normal_ranges", {
        "temperature": [20, 40], "humidity": [40, 95], "soil_moisture": [30, 80]
    })
    for name in ("temperature", "humidity", "soil_moisture"):
        bounds = config["valid_ranges"][name]
        if len(bounds) != 2 or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in bounds
        ) or bounds[0] >= bounds[1]:
            raise ValueError(f"Invalid range: {name}")
        normal = normal_ranges[name]
        if len(normal) != 2 or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in normal
        ) or not bounds[0] <= normal[0] < normal[1] <= bounds[1]:
            raise ValueError(f"Invalid normal range: {name}")
    for key in ("control_max_age_seconds", "future_tolerance_seconds", "max_payload_bytes"):
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{key} must be positive")
    # Preserve compatibility with configuration files created before Task 2.1.
    health = config.setdefault("sensor_health", {})
    if not isinstance(health, dict):
        raise ValueError("sensor_health must be a YAML mapping")
    health.setdefault("stale_after_seconds", 30)
    health.setdefault("offline_after_seconds", 60)
    health.setdefault("check_interval_seconds", 1)
    SensorHealthMonitor(health["stale_after_seconds"], health["offline_after_seconds"])
    interval = health["check_interval_seconds"]
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not math.isfinite(interval) or interval <= 0:
        raise ValueError("check_interval_seconds must be a finite positive number")
    if interval > health["stale_after_seconds"]:
        raise ValueError("check_interval_seconds must not exceed stale_after_seconds")
    return config
