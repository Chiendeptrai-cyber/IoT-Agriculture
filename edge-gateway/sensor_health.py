"""Classify sensor delivery health using Edge receipt time, independent of Server."""

from datetime import datetime, timezone
import math


class SensorHealthMonitor:
    def __init__(self, stale_after_seconds=30, offline_after_seconds=60):
        for value in (stale_after_seconds, offline_after_seconds):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError("Health timeouts must be finite positive numbers")
        if stale_after_seconds >= offline_after_seconds:
            raise ValueError("stale_after_seconds must be less than offline_after_seconds")
        self.stale_after_seconds = stale_after_seconds
        self.offline_after_seconds = offline_after_seconds

    def classify(self, last_received_at, monitoring_since, *, now=None):
        now = now or datetime.now(timezone.utc)
        reference = last_received_at or monitoring_since
        elapsed = max(0, (now - reference).total_seconds())
        if elapsed >= self.offline_after_seconds:
            return "OFFLINE"
        # A sensor never observed must not be reported ONLINE during startup.
        if last_received_at is None or elapsed >= self.stale_after_seconds:
            return "STALE"
        return "ONLINE"
