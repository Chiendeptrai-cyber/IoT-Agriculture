"""Inspect the Edge SQLite footprint and project telemetry storage capacity."""

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sqlite3
import statistics
import sys


def percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    index = math.ceil(ratio * len(values)) - 1
    return values[max(0, min(index, len(values) - 1))]


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=os.getenv("EDGE_DB_PATH", str(Path(__file__).resolve().parents[1] / "edge-gateway" / "edge.db")),
        help="Path to the Edge SQLite database (defaults to EDGE_DB_PATH or edge-gateway/edge.db)",
    )
    parser.add_argument("--sensor-count", type=int, default=3)
    parser.add_argument("--interval-seconds", type=float, default=10.0)
    parser.add_argument("--retention-days", type=int, default=30)
    args = parser.parse_args()

    if args.sensor_count <= 0 or args.interval_seconds <= 0 or args.retention_days <= 0:
        parser.error("sensor count, interval and retention days must be positive")
    path = Path(args.db).expanduser().resolve()
    if not path.is_file():
        print(f"SQLite database not found: {path}", file=sys.stderr)
        return 2

    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        page_count = connection.execute("PRAGMA page_count").fetchone()[0]
        statuses = dict(connection.execute(
            "SELECT sync_status, COUNT(*) FROM telemetry GROUP BY sync_status"
        ).fetchall())
        total = sum(statuses.values())
        by_sensor = dict(connection.execute(
            "SELECT sensor_id, COUNT(*) FROM telemetry GROUP BY sensor_id"
        ).fetchall())
        synced_rows = connection.execute(
            "SELECT received_at, synced_at FROM telemetry WHERE synced_at IS NOT NULL"
        ).fetchall()
        payload_average, payload_max = connection.execute(
            "SELECT AVG(length(payload)), MAX(length(payload)) FROM telemetry"
        ).fetchone()
    except sqlite3.Error as exc:
        print(f"Cannot inspect Edge SQLite schema: {exc}", file=sys.stderr)
        return 2
    finally:
        connection.close()

    latency_ms = sorted(
        max(0.0, (parse_time(synced) - parse_time(received)).total_seconds() * 1000)
        for received, synced in synced_rows
    )
    db_bytes = path.stat().st_size
    wal_path = Path(f"{path}-wal")
    shm_path = Path(f"{path}-shm")
    wal_bytes = wal_path.stat().st_size if wal_path.exists() else 0
    shm_bytes = shm_path.stat().st_size if shm_path.exists() else 0
    allocated_bytes = page_size * page_count
    records_per_day = args.sensor_count * 86400 / args.interval_seconds
    records_for_retention = records_per_day * args.retention_days
    allocated_bytes_per_record = allocated_bytes / total if total else None
    report = {
        "database": str(path),
        "telemetry": {
            "total": total,
            "pending": statuses.get("PENDING", 0),
            "synced": statuses.get("SYNCED", 0),
            "by_sensor": by_sensor,
            "average_payload_bytes": round(payload_average, 2) if payload_average is not None else None,
            "max_payload_bytes": payload_max,
        },
        "sqlite_storage": {
            "page_size_bytes": page_size,
            "page_count": page_count,
            "allocated_bytes": allocated_bytes,
            "main_file_bytes": db_bytes,
            "wal_bytes": wal_bytes,
            "shm_bytes": shm_bytes,
            "active_total_bytes": db_bytes + wal_bytes + shm_bytes,
            "allocated_bytes_per_telemetry_record": round(allocated_bytes_per_record, 2)
            if allocated_bytes_per_record is not None else None,
        },
        "capacity_projection": {
            "sensor_count": args.sensor_count,
            "interval_seconds": args.interval_seconds,
            "records_per_hour": round(records_per_day / 24, 2),
            "records_per_day": int(records_per_day),
            "retention_days": args.retention_days,
            "records_for_retention": int(records_for_retention),
            "projected_allocated_bytes": round(allocated_bytes_per_record * records_for_retention)
            if allocated_bytes_per_record is not None else None,
        },
        "sync_delay_ms": {
            "samples": len(latency_ms),
            "mean": round(statistics.fmean(latency_ms), 2) if latency_ms else None,
            "median": round(statistics.median(latency_ms), 2) if latency_ms else None,
            "p95": round(percentile(latency_ms, 0.95), 2) if latency_ms else None,
            "max": round(max(latency_ms), 2) if latency_ms else None,
        },
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
