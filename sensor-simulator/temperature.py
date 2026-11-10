"""
temperature.py - Temperature Sensor Simulator (SEN-001)
Simulates ambient temperature in degrees Celsius (C) using mean-reverting drift.
"""

import argparse
import random
from typing import Any, Dict, Optional, Union

try:
    from sensor_base import BaseSensor, SensorMode, load_simulator_config
except ImportError:
    from .sensor_base import BaseSensor, SensorMode, load_simulator_config


class TemperatureSensor(BaseSensor):
    """
    Simulated Temperature Sensor (SEN-001).
    Produces continuous temperature measurements with realistic temporal inertia.
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
        temp_cfg = full_cfg.get("sensors", {}).get("temperature", {}) if full_cfg else {}

        merged_cfg = {**temp_cfg, **(config or {})}
        norm_cfg = merged_cfg.get("normal", {})
        anom_cfg = merged_cfg.get("anomaly", {})

        effective_sensor_id = sensor_id or merged_cfg.get("sensor_id", "SEN-001")
        effective_name = name or merged_cfg.get("name", "Temperature Sensor")
        effective_unit = unit or merged_cfg.get("unit", "C")
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
            else float(merged_cfg.get("initial_value", 29.5))
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
        self.min_val = float(norm_cfg.get("min_value", 20.0))
        self.max_val = float(norm_cfg.get("max_value", 40.0))
        self.target_mean = float(norm_cfg.get("target_mean", 29.0))
        self.drift_std = float(norm_cfg.get("drift_std", 0.3))
        self.reversion_speed = float(norm_cfg.get("reversion_speed", 0.05))

        # Anomaly parameters
        self.spike_min = float(anom_cfg.get("spike_min", 55.0))
        self.spike_max = float(anom_cfg.get("spike_max", 85.0))
        self.drop_min = float(anom_cfg.get("drop_min", -10.0))
        self.drop_max = float(anom_cfg.get("drop_max", 5.0))

    def generate_normal_value(self) -> float:
        """
        Simulate continuous temperature variation using mean-reverting random walk.
        Smooth drift ensures consecutive readings follow realistic physical transitions.
        """
        # Mean-reverting pull towards target ambient temperature
        drift_pull = self.reversion_speed * (self.target_mean - self.current_value)
        # Small Gaussian noise for thermal micro-fluctuation
        thermal_noise = random.gauss(0.0, self.drift_std)

        new_val = self.current_value + drift_pull + thermal_noise
        # Keep within physical normal boundaries
        new_val = max(self.min_val, min(self.max_val, new_val))
        return new_val

    def generate_anomaly_value(self) -> float:
        """
        Simulate sensor failure, extreme ambient overheating, or circuit fault.
        Randomly chooses between extreme thermal spike, frost fault, or drastic jump.
        """
        anomaly_type = random.choice(["spike", "drop", "jump"])
        if anomaly_type == "spike":
            return random.uniform(self.spike_min, self.spike_max)
        elif anomaly_type == "drop":
            return random.uniform(self.drop_min, self.drop_max)
        else:
            # Sudden swing beyond normal standard deviations
            jump_delta = random.choice([-1.0, 1.0]) * random.uniform(18.0, 30.0)
            return self.current_value + jump_delta


def main() -> None:
    parser = argparse.ArgumentParser(description="Temperature Sensor Simulator (SEN-001)")
    parser.add_argument("--interval", type=float, default=None, help="Generation interval in seconds (default: from config)")
    parser.add_argument("--mode", type=str, default=None, choices=["NORMAL", "ANOMALY", "OFFLINE"], help="Sensor mode (default: from config)")
    parser.add_argument("--count", type=int, default=None, help="Number of events to generate (default: infinite)")
    args = parser.parse_args()

    sensor = TemperatureSensor(mode=args.mode, interval_seconds=args.interval)
    print(f"Starting {sensor.name} [{sensor.sensor_id}] | Mode: {sensor.mode.value} | Interval: {sensor.interval_seconds}s")
    sensor.run(interval_seconds=args.interval, max_iterations=args.count)


if __name__ == "__main__":
    main()
