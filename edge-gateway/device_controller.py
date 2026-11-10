"""Pure state transition for a virtual water pump with hysteresis."""


def desired_pump_state(current, moisture, thresholds):
    if moisture < thresholds["soil_on_below"]:
        return "ON"
    if moisture > thresholds["soil_off_above"]:
        return "OFF"
    return current
