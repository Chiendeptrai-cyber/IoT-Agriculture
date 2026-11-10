"""Evaluate demonstration thresholds; persistence is handled by BufferManager."""

from device_controller import desired_pump_state


def evaluate(topic, value, pump_state, thresholds):
    name = topic.rsplit("/", 1)[-1]
    alerts = []
    if name == "temperature" and value > thresholds["temperature_high"]:
        alerts.append(("HIGH_TEMPERATURE", thresholds["temperature_high"]))
    if name == "humidity" and value < thresholds["humidity_low"]:
        alerts.append(("LOW_HUMIDITY", thresholds["humidity_low"]))
    next_state = (
        desired_pump_state(pump_state, value, thresholds)
        if name == "soil_moisture" else pump_state
    )
    return alerts, next_state
