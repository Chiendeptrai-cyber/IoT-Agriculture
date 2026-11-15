"""Generate realistic time-series telemetry and push to the Server API for Grafana verification."""

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
import random
import sys
import urllib.request
import urllib.error

SERVER_URL = "http://127.0.0.1:8000/api/v1/telemetry/batch"

def generate_records(duration_minutes: int = 15, step_seconds: int = 15):
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(minutes=duration_minutes)
    
    total_steps = int((duration_minutes * 60) / step_seconds)
    records = []
    
    temp = 28.0
    humid = 60.0
    soil = 38.0
    pump_on = False

    run_id = int(now.timestamp())

    for i in range(total_steps):
        t = start_time + timedelta(seconds=i * step_seconds)
        timestamp_str = t.isoformat()
        
        # 1. Temperature (°C): base sinusoidal wave with peak > 35.5°C
        temp = 28.0 + 8.0 * math.sin(2 * math.pi * i / total_steps) + random.uniform(-0.3, 0.3)
        records.append({
            "event_id": f"EVT-DEMO-{run_id}-TEMP-{i:04d}",
            "sensor_id": "SEN-001",
            "timestamp": timestamp_str,
            "sequence": i + 1,
            "value": round(temp, 1),
            "unit": "C"
        })
        
        # 2. Humidity (%): inversely correlated with temperature, drops below 40%
        humid = 65.0 - (temp - 25.0) * 2.5 + random.uniform(-0.5, 0.5)
        humid = max(35.0, min(80.0, humid))
        records.append({
            "event_id": f"EVT-DEMO-{run_id}-HUM-{i:04d}",
            "sensor_id": "SEN-002",
            "timestamp": timestamp_str,
            "sequence": i + 1,
            "value": round(humid, 1),
            "unit": "%"
        })
        
        # 3. Soil Moisture (%): dry down cycle then pump watering
        if not pump_on:
            soil -= random.uniform(0.15, 0.35)
            if soil < 28.0:
                pump_on = True
        else:
            soil += random.uniform(0.4, 0.8)
            if soil > 37.0:
                pump_on = False
        
        records.append({
            "event_id": f"EVT-DEMO-{run_id}-SOIL-{i:04d}",
            "sensor_id": "SEN-003",
            "timestamp": timestamp_str,
            "sequence": i + 1,
            "value": round(soil, 1),
            "unit": "%"
        })

    return records


def send_batch(records, gateway_id="GW-001"):
    payload = {
        "gateway_id": gateway_id,
        "records": records
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        SERVER_URL,
        data=data,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        print(f"HTTP Error {exc.code}: {body}")
        raise
    except Exception as exc:
        print(f"Connection error: {exc}")
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=int, default=15, help="Span of historical data in minutes")
    parser.add_argument("--step", type=int, default=15, help="Interval between readings in seconds")
    parser.add_argument("--batch-size", type=int, default=50, help="Batch size per HTTP POST")
    args = parser.parse_args()

    print(f"Generating {args.minutes} minutes of telemetry (step: {args.step}s)...")
    records = generate_records(args.minutes, args.step)
    print(f"Generated {len(records)} records across 3 sensors.")

    total_accepted = 0
    total_duplicates = 0
    total_rejected = 0

    for i in range(0, len(records), args.batch_size):
        chunk = records[i:i + args.batch_size]
        res = send_batch(chunk)
        total_accepted += res.get("accepted", 0)
        total_duplicates += res.get("duplicates", 0)
        total_rejected += res.get("rejected", 0)
        print(f"Batch {i//args.batch_size + 1}: sent {len(chunk)}, accepted {res.get('accepted')}, dups {res.get('duplicates')}")

    # Add 1 duplicate to demonstrate idempotency & sync status
    if records:
        print("Testing duplicate record submission...")
        dup_res = send_batch([records[0]])
        print(f"Duplicate test result: accepted={dup_res.get('accepted')}, duplicates={dup_res.get('duplicates')}")

    # Add 1 deliberate invalid record to demonstrate rejection audit
    print("Testing deliberate invalid record submission...")
    invalid_res = send_batch([{
        "event_id": "EVT-DELIBERATE-INVALID-001",
        "sensor_id": "SEN-001",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sequence": 9999,
        "value": 999.0,  # exceeds physical max (125°C)
        "unit": "C"
    }])
    print(f"Invalid record test result: accepted={invalid_res.get('accepted')}, rejected={invalid_res.get('rejected')}")

    print("\n--- Summary ---")
    print(f"Total accepted: {total_accepted}")
    print(f"Total duplicates: {total_duplicates}")
    print(f"Total rejected: {total_rejected + invalid_res.get('rejected', 0)}")
    print("Telemetry data successfully seeded into PostgreSQL and InfluxDB!")

if __name__ == "__main__":
    main()
