"""
soil_moisture.py - Soil Moisture Sensor Simulator (SEN-003)
Simulates soil volumetric water content percentage (%) with high physical inertia.
"""

import argparse
import random
from typing import Any, Dict, Optional, Union

try:
    from sensor_base import BaseSensor, SensorMode, load_simulator_config
except ImportError:
    from .sensor_base import BaseSensor, SensorMode, load_simulator_config


class SoilMoistureSensor(BaseSensor):
    """
    Simulated Soil Moisture Sensor (SEN-003).
    Models slow, damped moisture transitions reflecting real soil physical inertia.
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
        soil_cfg = full_cfg.get("sensors", {}).get("soil_moisture", {}) if full_cfg else {}

        merged_cfg = {**soil_cfg, **(config or {})}
        norm_cfg = merged_cfg.get("normal", {})
        anom_cfg = merged_cfg.get("anomaly", {})

        effective_sensor_id = sensor_id or merged_cfg.get("sensor_id", "SEN-003")
        effective_name = name or merged_cfg.get("name", "Soil Moisture Sensor")
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
            else float(merged_cfg.get("initial_value", 58.0))
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
        self.min_val = float(norm_cfg.get("min_value", 30.0))
        self.max_val = float(norm_cfg.get("max_value", 80.0))
        self.target_mean = float(norm_cfg.get("target_mean", 55.0))
        self.drift_std = float(norm_cfg.get("drift_std", 0.2))
        self.reversion_speed = float(norm_cfg.get("reversion_speed", 0.02))

        # Anomaly parameters
        self.spike_min = float(anom_cfg.get("spike_min", 96.0))
        self.spike_max = float(anom_cfg.get("spike_max", 100.0))
        self.drop_min = float(anom_cfg.get("drop_min", 0.0))
        self.drop_max = float(anom_cfg.get("drop_max", 5.0))

    def generate_normal_value(self) -> float:
        """
        Simulate soil moisture dynamics with low variance, representing ground water retention.
        """
        drift_pull = self.reversion_speed * (self.target_mean - self.current_value)
        soil_noise = random.gauss(0.0, self.drift_std)

        new_val = self.current_value + drift_pull + soil_noise
        new_val = max(self.min_val, min(self.max_val, new_val))
        return new_val

    def generate_anomaly_value(self) -> float:
        """
        Simulate severe soil anomalies:
        - Sensor extracted from soil / detached probe (0% - 5%)
        - Total waterlogging / submerged probe (96% - 100%)
        - Abrupt unnatural jump
        """
        anomaly_type = random.choice(["drop", "spike", "jump"])
        if anomaly_type == "drop":
            return random.uniform(self.drop_min, self.drop_max)
        elif anomaly_type == "spike":
            return random.uniform(self.spike_min, self.spike_max)
        else:
            jump_delta = random.choice([-1.0, 1.0]) * random.uniform(25.0, 40.0)
            return self.current_value + jump_delta


def main() -> None:
    parser = argparse.ArgumentParser(description="Soil Moisture Sensor Simulator (SEN-003)")
    parser.add_argument("--interval", type=float, default=None, help="Generation interval in seconds (default: from config)")
    parser.add_argument("--mode", type=str, default=None, choices=["NORMAL", "ANOMALY", "OFFLINE"], help="Sensor mode (default: from config)")
    parser.add_argument("--count", type=int, default=None, help="Number of events to generate (default: infinite)")
    args = parser.parse_args()

    sensor = SoilMoistureSensor(mode=args.mode, interval_seconds=args.interval)
    print(f"Starting {sensor.name} [{sensor.sensor_id}] | Mode: {sensor.mode.value} | Interval: {sensor.interval_seconds}s")
    sensor.run(interval_seconds=args.interval, max_iterations=args.count)


if __name__ == "__main__":
    main()
