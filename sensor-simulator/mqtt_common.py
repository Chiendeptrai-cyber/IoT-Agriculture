"""MQTT settings and routing shared by the simulator and diagnostic subscriber."""

import os
import uuid

import paho.mqtt.client as mqtt

from sensor_base import load_simulator_config


def sensor_routes():
    """Derive identity and units from Task 1's configuration."""
    sensors = load_simulator_config()["sensors"]
    return {
        f"farm/sensors/{name}": (sensors[name]["sensor_id"], sensors[name]["unit"])
        for name in ("temperature", "humidity", "soil_moisture")
    }


def add_mqtt_arguments(parser):
    parser.add_argument("--host", default=os.getenv("MQTT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MQTT_PORT", "1883")))
    parser.add_argument("--qos", type=int, choices=(0, 1), default=int(os.getenv("MQTT_QOS", "1")))


def make_client(role):
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"farm-{role}-{uuid.uuid4().hex[:12]}",
        clean_session=True,
        protocol=mqtt.MQTTv311,
    )
    client.reconnect_delay_set(min_delay=1, max_delay=10)
    client.max_queued_messages_set(100)
    return client
