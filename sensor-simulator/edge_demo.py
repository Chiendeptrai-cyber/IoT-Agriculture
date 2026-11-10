"""Deterministic MQTT inputs for demonstrating the offline Edge Gateway."""

import argparse
from datetime import datetime, timezone
import logging
import time

from mqtt_common import add_mqtt_arguments, sensor_routes
from mqtt_publisher import MqttPublisher
from sensor_base import generate_event_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_mqtt_arguments(parser)
    parser.add_argument("--interval", type=float, default=1)
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    publisher = MqttPublisher(args.host, args.port, args.qos)
    sequences = {}
    first_event = None
    try:
        publisher.start()
        for name, value in [("temperature", 40), ("humidity", 35), ("soil_moisture", 20),
                            ("soil_moisture", 32), ("soil_moisture", 40), ("humidity", 150)]:
            topic = f"farm/sensors/{name}"
            sensor_id, unit = sensor_routes()[topic]
            sequences[sensor_id] = sequences.get(sensor_id, 0) + 1
            event = {"event_id": generate_event_id(), "sensor_id": sensor_id,
                     "timestamp": datetime.now(timezone.utc).isoformat(),
                     "sequence": sequences[sensor_id], "value": value, "unit": unit}
            first_event = first_event or event
            logging.info("DEMO INPUT topic=%s value=%s%s", topic, value, unit)
            if not publisher.publish(event):
                parser.exit(1, "DEMO ERROR: publish was not confirmed\n")
            time.sleep(args.interval)
        logging.info("DEMO DUPLICATE: resend the first event_id; Edge must not create another alert")
        if not publisher.publish(first_event):
            parser.exit(1, "DEMO ERROR: duplicate publish was not confirmed\n")
        print("Demo sent: 5 valid readings, 1 invalid humidity reading, 1 duplicate.")
        print("On a fresh Edge database: pending=5, alerts=2, quarantined=1, device_actions=2, pump=OFF.")
    except KeyboardInterrupt:
        pass
    except (TimeoutError, OSError) as exc:
        parser.exit(1, f"DEMO ERROR: {exc}\n")
    finally:
        publisher.close()


if __name__ == "__main__":
    main()
