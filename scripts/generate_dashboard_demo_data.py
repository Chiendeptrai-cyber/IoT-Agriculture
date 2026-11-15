"""Generate realistic time-series telemetry and push to the Server API for Grafana verification.

Uses a physically-grounded environmental model (Mean-Reverting Thermal Inertia & Evapotranspiration Dynamics)
rather than an artificial sinusoidal wave to represent real microclimate conditions.
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import random
import sys
import urllib.request
import urllib.error

SERVER_URL = "http://127.0.0.1:8000/api/v1/telemetry/batch"

def generate_records(duration_minutes: int = 15, step_seconds: int = 15):
    """Generate realistic agricultural telemetry with thermal inertia and physical dynamics.
    
    Replaces artificial mathematical sine waves with an Ornstein-Uhlenbeck mean-reverting
    thermal process, diurnal solar heat accumulation, thermodynamic humidity coupling,
    and soil moisture evapotranspiration/infiltration cycles.
    """
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(minutes=duration_minutes)
    
    total_steps = max(1, int((duration_minutes * 60) / step_seconds))
    records = []
    
    # Initial state representing realistic greenhouse baseline
    temp = 28.2
    humid = 62.0
    soil = 37.5
    pump_on = False

    run_id = int(now.timestamp())

    for i in range(total_steps):
        t = start_time + timedelta(seconds=i * step_seconds)
        timestamp_str = t.isoformat()
        
        # Normalized progress through simulation interval [0.0, 1.0]
        progress = i / max(1, total_steps - 1)
        
        # 1. Temperature (°C): Realistic physical diurnal thermal accumulation with inertia.
        # Solar radiation increases ambient temperature towards midday peak (reaching ~36.2°C),
        # followed by radiative cooling, modeled with continuous thermal inertia and Gaussian noise.
        # Peak heat envelope centered around 40%-65% of the timeline
        if progress < 0.2:
            target_ambient = 28.0 + progress * 15.0  # Morning warming: 28.0°C -> 31.0°C
        elif progress < 0.6:
            # Solar peak heat accumulation: rises to ~36.5°C (triggers > 35°C alert)
            target_ambient = 31.0 + (progress - 0.2) * 13.5
        elif progress < 0.8:
            # Sustained warm afternoon with gradual dissipation
            target_ambient = 36.4 - (progress - 0.6) * 18.0
        else:
            # Evening cooling back towards baseline
            target_ambient = 32.8 - (progress - 0.8) * 19.0
            
        # Physical thermal inertia: gradual adjustment towards target + micro-turbulent air noise
        thermal_inertia = 0.15
        thermal_noise = random.gauss(0.0, 0.18)
        temp += thermal_inertia * (target_ambient - temp) + thermal_noise
        temp = max(22.0, min(39.0, temp))

        records.append({
            "event_id": f"EVT-DEMO-{run_id}-TEMP-{i:04d}",
            "sensor_id": "SEN-001",
            "timestamp": timestamp_str,
            "sequence": i + 1,
            "value": round(temp, 1),
            "unit": "C"
        })
        
        # 2. Humidity (%): Thermodynamically coupled to temperature (vapor pressure saturation).
        # Drops naturally as air warms up; when temperature exceeds 35°C, humidity drops below 40% (alert).
        target_humid = 68.0 - (temp - 26.0) * 2.8
        humid_inertia = 0.2
        humid_noise = random.gauss(0.0, 0.35)
        humid += humid_inertia * (target_humid - humid) + humid_noise
        humid = max(34.0, min(82.0, humid))

        records.append({
            "event_id": f"EVT-DEMO-{run_id}-HUM-{i:04d}",
            "sensor_id": "SEN-002",
            "timestamp": timestamp_str,
            "sequence": i + 1,
            "value": round(humid, 1),
            "unit": "%"
        })
        
        # 3. Soil Moisture (%): Realistic physical soil dynamics.
        # Soil dries through evapotranspiration (faster when ambient temperature is elevated).
        # When moisture drops below 29% (< 30% threshold), pump turns ON.
        # Irrigation causes infiltration and moisture increase until reaching > 36% (> 35%),
        # where pump turns OFF and soil drains / dries again.
        if not pump_on:
            # Evapotranspiration drying rate depends on ambient temperature
            evapotranspiration = 0.15 + (max(0.0, temp - 28.0) * 0.02) + random.uniform(0.02, 0.08)
            soil -= evapotranspiration
            if soil < 28.5:
                pump_on = True
        else:
            # Irrigation water absorption rate with capillary damping
            absorption_rate = random.uniform(0.55, 0.95)
            soil += absorption_rate
            if soil > 36.5:
                pump_on = False
        
        soil = max(24.0, min(65.0, soil))

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
