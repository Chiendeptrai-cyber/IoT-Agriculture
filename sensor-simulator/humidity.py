"""
humidity.py - Air Humidity Sensor Simulator (SEN-002)
Simulates relative air humidity percentage (%) with smooth environmental dynamics.
"""

import argparse
import random
from typing import Any, Dict, Optional, Union

try:
    from sensor_base import BaseSensor, SensorMode, load_simulator_config
except ImportError:
    from .sensor_base import BaseSensor, SensorMode, load_simulator_config


class HumiditySensor(BaseSensor):
    """
    Simulated Air Humidity Sensor (SEN-002).
    Generates realistic relative humidity (%) values drifting smoothly over time.
    """

    def __init__(
        self,
        sensor_id: Optional[str] = None,
        name: Optional[str] = None,
        unit: Optional[str] = None,
        interval_seconds: Optional[float] = None,
        mode: Optional[Union[SensorMode, str]] = None,
        initial_value: Optional[float] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        full_cfg = load_simulator_config()
        hum_cfg = full_cfg.get("sensors", {}).get("humidity", {}) if full_cfg else {}

        merged_cfg = {**hum_cfg, **(config or {})}
        norm_cfg = merged_cfg.get("normal", {})
        anom_cfg = merged_cfg.get("anomaly", {})

        effective_sensor_id = sensor_id or merged_cfg.get("sensor_id", "SEN-002")
        effective_name = name or merged_cfg.get("name", "Air Humidity Sensor")
        effective_unit = unit or merged_cfg.get("unit", "%")
        effective_interval = (
            float(interval_seconds)
            if interval_seconds is not None
            else float(merged_cfg.get("interval_seconds", 10.0))
        )
        effective_mode = (
            mode
            if mode is not None
            else merged_cfg.get("mode", SensorMode.NORMAL)
        )
        init_val = (
            initial_value
            if initial_value is not None
            else float(merged_cfg.get("initial_value", 72.0))
        )

        super().__init__(
            sensor_id=effective_sensor_id,
            name=effective_name,
            unit=effective_unit,
            interval_seconds=effective_interval,
            mode=effective_mode,
            initial_value=init_val,
            config=merged_cfg,
        )

        # Normal operation parameters
        self.min_val = float(norm_cfg.get("min_value", 40.0))
        self.max_val = float(norm_cfg.get("max_value", 95.0))
        self.target_mean = float(norm_cfg.get("target_mean", 70.0))
        self.drift_std = float(norm_cfg.get("drift_std", 0.8))
        self.reversion_speed = float(norm_cfg.get("reversion_speed", 0.05))

        # Anomaly parameters
        self.spike_min = float(anom_cfg.get("spike_min", 99.0))
        self.spike_max = float(anom_cfg.get("spike_max", 110.0))
        self.drop_min = float(anom_cfg.get("drop_min", 2.0))
        self.drop_max = float(anom_cfg.get("drop_max", 12.0))

    def generate_normal_value(self) -> float:
        """
        Simulate continuous humidity variation using mean-reverting random walk.
        Smooth drift models atmospheric moisture changes without artificial jumping.
        """
        drift_pull = self.reversion_speed * (self.target_mean - self.current_value)
        humidity_noise = random.gauss(0.0, self.drift_std)

        new_val = self.current_value + drift_pull + humidity_noise
        new_val = max(self.min_val, min(self.max_val, new_val))
        return new_val

    def generate_anomaly_value(self) -> float:
        """
        Simulate abnormal readings:
        - Sensor oversaturation (> 100%)
        - Sudden drop to dry/disconnected state (< 12%)
        - Extreme sudden delta swing
        """
        anomaly_type = random.choice(["spike", "drop", "jump"])
        if anomaly_type == "spike":
            return random.uniform(self.spike_min, self.spike_max)
        elif anomaly_type == "drop":
            return random.uniform(self.drop_min, self.drop_max)
        else:
            jump_delta = random.choice([-1.0, 1.0]) * random.uniform(30.0, 45.0)
            return self.current_value + jump_delta


def main() -> None:
    parser = argparse.ArgumentParser(description="Air Humidity Sensor Simulator (SEN-002)")
    parser.add_argument("--interval", type=float, default=None, help="Generation interval in seconds (default: from config)")
    parser.add_argument("--mode", type=str, default=None, choices=["NORMAL", "ANOMALY", "OFFLINE"], help="Sensor mode (default: from config)")
    parser.add_argument("--count", type=int, default=None, help="Number of events to generate (default: infinite)")
    args = parser.parse_args()

    sensor = HumiditySensor(mode=args.mode, interval_seconds=args.interval)
    print(f"Starting {sensor.name} [{sensor.sensor_id}] | Mode: {sensor.mode.value} | Interval: {sensor.interval_seconds}s")
    sensor.run(interval_seconds=args.interval, max_iterations=args.count)


if __name__ == "__main__":
    main()
