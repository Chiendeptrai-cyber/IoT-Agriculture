"""
main.py - Master Simulator Runner for All 3 Sensors.
Orchestrates SEN-001, SEN-002, and SEN-003 concurrently.
Supports standard continuous execution, demo mode switching, and custom intervals.
"""

import argparse
import logging
import sys
import threading
import time
from typing import List

from humidity import HumiditySensor
from sensor_base import BaseSensor, SensorMode, load_simulator_config
from soil_moisture import SoilMoistureSensor
from temperature import TemperatureSensor


def build_sensor_fleet(
    interval: float = None,
    default_mode: str = "NORMAL",
) -> List[BaseSensor]:
    """Instantiate the 3 required sensors with configuration."""
    cfg = load_simulator_config()
    default_int = interval if interval is not None else cfg.get("simulation", {}).get("default_interval_seconds", 10.0)

    sensors: List[BaseSensor] = [
        TemperatureSensor(interval_seconds=default_int, mode=default_mode),
        HumiditySensor(interval_seconds=default_int, mode=default_mode),
        SoilMoistureSensor(interval_seconds=default_int, mode=default_mode),
    ]
    return sensors


def run_fleet_concurrently(
    sensors: List[BaseSensor],
    interval: float,
    count: int = None,
    callback=None,
    print_terminal: bool = True,
) -> None:
    """Run all sensors in parallel threads."""
    threads = []
    for s in sensors:
        t = threading.Thread(
            target=s.run,
            kwargs={"interval_seconds": interval, "max_iterations": count,
                    "callback": callback, "print_terminal": print_terminal},
            daemon=True,
        )
        threads.append(t)
        t.start()

    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print("\nStopping sensor simulation...")
        for s in sensors:
            s.stop()
        for t in threads:
            t.join()


def run_demo_scenario(interval: float = 2.0, callback=None, print_terminal=True) -> None:
    """
    Automated scenario showcasing the acceptance criteria:
    - Phase 1: All sensors NORMAL
    - Phase 2: SEN-001 transitions to ANOMALY (heat spike)
    - Phase 3: SEN-002 transitions to OFFLINE (sensor disconnect)
    - Phase 4: Recovery back to NORMAL
    """
    sensors = build_sensor_fleet(interval=interval)
    temp, hum, soil = sensors

    def emit(sensor):
        event = sensor.emit_event(print_terminal=print_terminal)
        if callback:
            callback(event)

    print("=" * 70)
    print("DEMO SCENARIO: DYNAMIC MODE TRANSITION (NORMAL -> ANOMALY -> OFFLINE -> RECOVERY)")
    print("=" * 70)

    # Phase 1: NORMAL
    print(f"\n[PHASE 1] NORMAL OPERATION (All sensors emit smooth realistic telemetry)")
    for s in sensors:
        s.set_mode(SensorMode.NORMAL)
    for _ in range(2):
        for s in sensors:
            emit(s)
        time.sleep(interval)

    # Phase 2: ANOMALY on Temperature (SEN-001)
    print(f"\n[PHASE 2] ANOMALY INJECTION (SEN-001 Temperature Sensor in ANOMALY mode)")
    temp.set_mode(SensorMode.ANOMALY)
    for _ in range(2):
        for s in sensors:
            emit(s)
        time.sleep(interval)

    # Phase 3: OFFLINE on Humidity (SEN-002)
    print(f"\n[PHASE 3] OFFLINE SIMULATION (SEN-002 Air Humidity Sensor goes OFFLINE)")
    hum.set_mode(SensorMode.OFFLINE)
    for _ in range(2):
        for s in sensors:
            emit(s)
        time.sleep(interval)

    # Phase 4: Recovery
    print(f"\n[PHASE 4] RECOVERY (All sensors restored to NORMAL)")
    for s in sensors:
        s.set_mode(SensorMode.NORMAL)
    for _ in range(2):
        for s in sensors:
            emit(s)
        time.sleep(interval)

    print("\n" + "=" * 70)
    print("DEMO COMPLETED SUCCESSFULLY.")
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-Sensor IoT Simulator")
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Emission interval in seconds (default: 10s from config)",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="NORMAL",
        choices=["NORMAL", "ANOMALY", "OFFLINE"],
        help="Initial mode for all sensors",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Number of emission cycles per sensor (default: continuous)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run automated dynamic mode switching demo scenario",
    )

    from mqtt_common import add_mqtt_arguments
    add_mqtt_arguments(parser)
    parser.add_argument("--terminal", action="store_true", help="Task 1 terminal output without MQTT")
    parser.add_argument("--sensor", choices=["all", "temperature", "humidity", "soil_moisture"], default="all")
    args = parser.parse_args()
    if args.interval is not None and args.interval <= 0:
        parser.error("--interval must be positive")
    if args.count is not None and args.count <= 0:
        parser.error("--count must be positive")
    if args.demo and args.sensor != "all":
        parser.error("--demo requires --sensor all")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    cfg = load_simulator_config()
    default_int = args.interval if args.interval is not None else cfg.get("simulation", {}).get("default_interval_seconds", 10.0)

    sensors = build_sensor_fleet(interval=default_int, default_mode=args.mode)
    if args.sensor != "all":
        sensors = [sensors[["temperature", "humidity", "soil_moisture"].index(args.sensor)]]

    print("=" * 70)
    print(f"Starting Multi-Sensor Simulator | Interval: {default_int}s | Mode: {args.mode}")
    print("Sensors initialized:")
    for s in sensors:
        print(f"  - {s.sensor_id}: {s.name} (Unit: '{s.unit}', Mode: {s.mode.value})")
    print("Output: terminal JSON" if args.terminal else f"Output: MQTT {args.host}:{args.port}, QoS {args.qos}")
    print("Press Ctrl+C to terminate.")
    print("=" * 70)

    publisher = None
    try:
        if not args.terminal:
            from mqtt_publisher import MqttPublisher
            publisher = MqttPublisher(args.host, args.port, args.qos)
            publisher.start()
        callback = publisher.publish if publisher else None
        if args.demo:
            run_demo_scenario(
                interval=args.interval if args.interval is not None else 1.0,
                callback=callback, print_terminal=args.terminal,
            )
        else:
            run_fleet_concurrently(
                sensors, interval=default_int, count=args.count,
                callback=callback, print_terminal=args.terminal,
            )
    except KeyboardInterrupt:
        pass
    except (TimeoutError, OSError) as exc:
        parser.exit(1, f"MQTT ERROR: {exc}\n")
    finally:
        if publisher:
            publisher.close()


if __name__ == "__main__":
    main()
