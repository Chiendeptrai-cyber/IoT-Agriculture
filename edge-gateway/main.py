"""Run the local Edge Gateway or inspect its durable SQLite buffer."""

import argparse
import json
import logging
import os
from pathlib import Path
import sqlite3
import time

from settings import DEFAULT_DB_PATH, load_config
from buffer_manager import BufferManager, database_status
from mqtt_client import EdgeGateway


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.getenv("MQTT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MQTT_PORT", "1883")))
    parser.add_argument("--client-id", default=os.getenv("EDGE_MQTT_CLIENT_ID", "farm-edge-001"))
    parser.add_argument("--db", type=Path, default=Path(os.getenv("EDGE_DB_PATH", str(DEFAULT_DB_PATH))))
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--status", action="store_true", help="Read SQLite status without connecting to MQTT")
    parser.add_argument("--duration", type=float, default=None, help="Run N seconds after subscription; default continuous")
    args = parser.parse_args()
    if args.duration is not None and args.duration <= 0:
        parser.error("--duration must be positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    buffer = gateway = None
    try:
        if args.status:
            print(json.dumps(database_status(args.db), ensure_ascii=False, indent=2))
            return
        config = load_config(args.config)
        buffer = BufferManager(args.db)
        logging.info("EDGE SQLite=%s; all telemetry remains PENDING until Server sync is implemented", buffer.path)
        gateway = EdgeGateway(buffer, config, args.host, args.port, args.client_id)
        gateway.start()
        deadline = time.monotonic() + args.duration if args.duration is not None else None
        next_health_check = time.monotonic()
        while deadline is None or time.monotonic() < deadline:
            if time.monotonic() >= next_health_check:
                gateway.check_health()
                next_health_check = time.monotonic() + config["sensor_health"]["check_interval_seconds"]
            if gateway.failed.wait(0.2):
                parser.exit(1, "EDGE ERROR: storage failed; fix disk/permissions and restart Edge\n")
    except KeyboardInterrupt:
        pass
    except (OSError, sqlite3.Error, TimeoutError, ValueError, KeyError) as exc:
        parser.exit(1, f"EDGE ERROR: {exc}\n")
    finally:
        if gateway:
            gateway.close()
        if buffer:
            buffer.close()


if __name__ == "__main__":
    main()
