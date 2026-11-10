"""
test_simulator.py - Automated Test Suite for Sensor Simulator.
Validates all acceptance criteria:
1. Distinct Sensor IDs (SEN-001, SEN-002, SEN-003).
2. JSON schema compliance.
3. Timestamp ISO 8601 validity & timezone.
4. Monotonic sequence increments per sensor.
5. Mode transitions: NORMAL, ANOMALY, OFFLINE.
6. Absolute event_id uniqueness across all events.
7. Smooth continuous time-series drift.
"""

from datetime import datetime
import json
import sys
from pathlib import Path
import pytest
import jsonschema

# Add sensor-simulator to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sensor-simulator"))

from sensor_base import (
    BaseSensor,
    SensorMode,
    SENSOR_EVENT_SCHEMA,
    generate_event_id,
    get_iso_timestamp,
)
from temperature import TemperatureSensor
from humidity import HumiditySensor
from soil_moisture import SoilMoistureSensor


class TestSensorSimulator:

    def test_three_sensors_distinct_ids(self):
        """Tiêu chuẩn 1: Có đủ ba cảm biến với ID riêng biệt."""
        s1 = TemperatureSensor()
        s2 = HumiditySensor()
        s3 = SoilMoistureSensor()

        assert s1.sensor_id == "SEN-001"
        assert s2.sensor_id == "SEN-002"
        assert s3.sensor_id == "SEN-003"

        ids = {s1.sensor_id, s2.sensor_id, s3.sensor_id}
        assert len(ids) == 3, "Sensor IDs must be distinct"

        assert s1.unit == "C"
        assert s2.unit == "%"
        assert s3.unit == "%"

    def test_json_schema_compliance(self):
        """Tiêu chuẩn 3: Dữ liệu tuân thủ JSON schema thống nhất."""
        sensors = [TemperatureSensor(), HumiditySensor(), SoilMoistureSensor()]

        for sensor in sensors:
            for _ in range(25):
                event = sensor.generate_event()
                assert event is not None
                # Validate against standard JSON Schema
                jsonschema.validate(instance=event, schema=SENSOR_EVENT_SCHEMA)

                # Validate serialization to JSON string and back
                json_str = json.dumps(event)
                deserialized = json.loads(json_str)
                assert deserialized == event

    def test_timestamp_validity_and_timezone(self):
        """Tiêu chuẩn 4: Timestamp có định dạng thời gian hợp lệ và có múi giờ rõ ràng."""
        sensors = [TemperatureSensor(), HumiditySensor(), SoilMoistureSensor()]

        for sensor in sensors:
            event = sensor.generate_event()
            ts_str = event["timestamp"]

            # Must contain timezone indicator ('Z' or offset like '+00:00' / '+07:00')
            assert ts_str.endswith("Z") or "+" in ts_str or "-" in ts_str[10:]

            # Parse with datetime.fromisoformat
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            assert dt.tzinfo is not None, "Timestamp must have explicit timezone"

    def test_sequence_monotonic_increment(self):
        """Tiêu chuẩn 5: Sequence tăng theo từng cảm biến."""
        s1 = TemperatureSensor()
        s2 = HumiditySensor()

        # Sensor 1 sequence progression
        seqs_s1 = [s1.generate_event()["sequence"] for _ in range(5)]
        assert seqs_s1 == [1, 2, 3, 4, 5]

        # Sensor 2 sequence progression independently
        seqs_s2 = [s2.generate_event()["sequence"] for _ in range(3)]
        assert seqs_s2 == [1, 2, 3]

        # Ensure s1 continues from where it was
        assert s1.generate_event()["sequence"] == 6

    def test_mode_transitions_normal_anomaly_offline(self):
        """Tiêu chuẩn 6: Chuyển đổi được giữa NORMAL, ANOMALY và OFFLINE."""
        sensor = TemperatureSensor(initial_value=28.0)

        # 1. NORMAL mode
        sensor.set_mode(SensorMode.NORMAL)
        assert sensor.mode == SensorMode.NORMAL
        evt_norm = sensor.generate_event()
        assert evt_norm is not None
        assert 20.0 <= evt_norm["value"] <= 40.0

        # 2. ANOMALY mode
        sensor.set_mode(SensorMode.ANOMALY)
        assert sensor.mode == SensorMode.ANOMALY
        evt_anom = sensor.generate_event()
        assert evt_anom is not None
        # In anomaly mode, value deviates or spikes/drops
        jsonschema.validate(instance=evt_anom, schema=SENSOR_EVENT_SCHEMA)

        # 3. OFFLINE mode
        sensor.set_mode(SensorMode.OFFLINE)
        assert sensor.mode == SensorMode.OFFLINE
        seq_before_offline = sensor.sequence
        evt_offline = sensor.generate_event()
        assert evt_offline is None, "OFFLINE sensor must not emit event"
        assert sensor.sequence == seq_before_offline, "Sequence must not advance when offline"

        # 4. Return to NORMAL
        sensor.set_mode(SensorMode.NORMAL)
        evt_resume = sensor.generate_event()
        assert evt_resume is not None
        assert evt_resume["sequence"] == seq_before_offline + 1

    def test_no_duplicate_event_ids(self):
        """Tiêu chuẩn 8: Không phát sinh hai event có cùng event_id."""
        sensors = [TemperatureSensor(), HumiditySensor(), SoilMoistureSensor()]
        event_ids = []

        total_events = 1500
        for i in range(total_events):
            sensor = sensors[i % 3]
            evt = sensor.generate_event()
            event_ids.append(evt["event_id"])

        unique_ids = set(event_ids)
        assert len(unique_ids) == total_events, f"Collision detected! Expected {total_events} unique IDs, got {len(unique_ids)}"

    def test_smooth_continuous_drift(self):
        """Yêu cầu 1: Dữ liệu cần thay đổi theo thời gian, không chỉ là số ngẫu nhiên độc lập."""
        # Consecutive steps should have smooth changes, not huge uniform jumps
        sensor = TemperatureSensor(initial_value=29.0)
        deltas = []
        for _ in range(50):
            val1 = sensor.generate_normal_value()
            sensor.current_value = val1
            val2 = sensor.generate_normal_value()
            deltas.append(abs(val2 - val1))
            sensor.current_value = val2

        avg_step = sum(deltas) / len(deltas)
        # Normal step should be smooth (< 1.5 C on average)
        assert avg_step < 1.5, f"Steps should be smooth, got average delta {avg_step}"
