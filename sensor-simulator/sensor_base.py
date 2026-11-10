"""
sensor_base.py - Base class and core schemas for IoT Sensor Simulators.
Provides unified JSON schema validation, lifecycle management, and event generation.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union
import uuid

import jsonschema
import yaml

# Unified JSON Schema for Sensor Events
SENSOR_EVENT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "SensorEvent",
    "type": "object",
    "required": ["event_id", "sensor_id", "timestamp", "sequence", "value", "unit"],
    "properties": {
        "event_id": {
            "type": "string",
            "pattern": "^EVT-[A-Za-z0-9_-]+$",
            "description": "Unique identifier for each event",
        },
        "sensor_id": {
            "type": "string",
            "pattern": "^SEN-[0-9]{3}$",
            "description": "Sensor identifier (e.g., SEN-001)",
        },
        "timestamp": {
            "type": "string",
            "format": "date-time",
            "description": "ISO 8601 timestamp with explicit timezone",
        },
        "sequence": {
            "type": "integer",
            "minimum": 1,
            "description": "Monotonically increasing sequence number per sensor",
        },
        "value": {
            "type": "number",
            "description": "Sensor reading",
        },
        "unit": {
            "type": "string",
            "description": "Unit of measurement (e.g., C, %)",
        },
    },
    "additionalProperties": False,
}


class SensorMode(str, Enum):
    """Operating modes for the simulated sensor."""
    NORMAL = "NORMAL"
    ANOMALY = "ANOMALY"
    OFFLINE = "OFFLINE"

    @classmethod
    def from_str(cls, value: str) -> "SensorMode":
        val = value.strip().upper()
        if val in cls.__members__:
            return cls[val]
        raise ValueError(f"Invalid sensor mode: {value}. Allowed modes: {list(cls.__members__.keys())}")


def generate_event_id() -> str:
    """Generate a globally unique event ID with prefix 'EVT-'."""
    # Combines UUID4 hex to ensure zero collision probability
    unique_suffix = uuid.uuid4().hex[:12].upper()
    return f"EVT-{unique_suffix}"


def get_iso_timestamp(tz: Optional[timezone] = timezone.utc) -> str:
    """Return an ISO 8601 timestamp string with explicit timezone."""
    now = datetime.now(tz or timezone.utc)
    if tz == timezone.utc or now.utcoffset() == timezone.utc.utcoffset(None):
        return now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return now.isoformat(timespec="seconds")


def load_simulator_config(config_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Load configuration from simulator_config.yaml."""
    if config_path is None:
        config_path = Path(__file__).resolve().parent / "simulator_config.yaml"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        return {}

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class BaseSensor(ABC):
    """
    Abstract base class for all IoT sensors.
    Handles sequence increments, state transitions, JSON schema validation,
    and output emission.
    """

    def __init__(
        self,
        sensor_id: str,
        name: str,
        unit: str,
        interval_seconds: float = 10.0,
        mode: Union[SensorMode, str] = SensorMode.NORMAL,
        initial_value: float = 0.0,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.sensor_id: str = sensor_id
        self.name: str = name
        self.unit: str = unit
        self.interval_seconds: float = float(interval_seconds)
        self.mode: SensorMode = SensorMode.from_str(mode) if isinstance(mode, str) else mode
        self.sequence: int = 0
        self.current_value: float = float(initial_value)
        self.config: Dict[str, Any] = config or {}
        self._is_running: bool = False

    def set_mode(self, mode: Union[SensorMode, str]) -> None:
        """Dynamically transition between NORMAL, ANOMALY, and OFFLINE."""
        new_mode = SensorMode.from_str(mode) if isinstance(mode, str) else mode
        self.mode = new_mode

    @abstractmethod
    def generate_normal_value(self) -> float:
        """
        Generate realistic value drifting smoothly over time.
        Must be implemented by concrete sensor subclass.
        """
        pass

    @abstractmethod
    def generate_anomaly_value(self) -> float:
        """
        Generate abnormal value (e.g. spike, drop, or extreme reading).
        Must be implemented by concrete sensor subclass.
        """
        pass

    def generate_value(self) -> float:
        """Generate value according to current mode."""
        if self.mode == SensorMode.NORMAL:
            self.current_value = self.generate_normal_value()
        elif self.mode == SensorMode.ANOMALY:
            self.current_value = self.generate_anomaly_value()
        else:
            raise RuntimeError(f"Cannot generate value when sensor {self.sensor_id} is OFFLINE.")
        return self.current_value

    def generate_event(self) -> Optional[Dict[str, Any]]:
        """
        Generate a single sensor event.
        Returns None when the sensor is OFFLINE.
        Returns validated event dict when NORMAL or ANOMALY.
        """
        if self.mode == SensorMode.OFFLINE:
            return None

        self.sequence += 1
        value = self.generate_value()

        event = {
            "event_id": generate_event_id(),
            "sensor_id": self.sensor_id,
            "timestamp": get_iso_timestamp(),
            "sequence": self.sequence,
            "value": round(float(value), 2),
            "unit": self.unit,
        }

        # Validate against JSON schema
        self.validate_event(event)
        return event

    @staticmethod
    def validate_event(event: Dict[str, Any]) -> None:
        """Validate event data against JSON schema specification."""
        jsonschema.validate(instance=event, schema=SENSOR_EVENT_SCHEMA)

    def emit_event(self, print_terminal: bool = True) -> Optional[Dict[str, Any]]:
        """
        Generate and optionally print the event JSON to the terminal.
        If OFFLINE, outputs a notification message and returns None.
        """
        if self.mode == SensorMode.OFFLINE:
            if print_terminal:
                print(f"[{get_iso_timestamp()}] [STATUS] Sensor {self.sensor_id} ({self.name}) is OFFLINE (no data emitted).")
            return None

        event = self.generate_event()
        if print_terminal and event is not None:
            print(json.dumps(event, ensure_ascii=False))
        return event

    def stop(self) -> None:
        """Stop the running loop."""
        self._is_running = False

    def run(
        self,
        interval_seconds: Optional[float] = None,
        max_iterations: Optional[int] = None,
        callback: Optional[Callable[[Optional[Dict[str, Any]]], None]] = None,
        print_terminal: bool = True,
    ) -> None:
        """
        Execute continuous simulation loop emitting events at regular intervals.
        """
        import time

        interval = interval_seconds if interval_seconds is not None else self.interval_seconds
        self._is_running = True
        iterations = 0

        try:
            while self._is_running:
                event = self.emit_event(print_terminal=print_terminal)
                if callback:
                    callback(event)

                iterations += 1
                if max_iterations is not None and iterations >= max_iterations:
                    break

                # Sleep in short increments for responsive interrupt/stop
                sleep_start = time.time()
                while self._is_running and (time.time() - sleep_start < interval):
                    time.sleep(min(0.2, interval))
        except KeyboardInterrupt:
            self.stop()
