FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies for edge-gateway and sensor-simulator (which edge-gateway imports)
COPY edge-gateway/requirements.txt /app/edge-requirements.txt
COPY sensor-simulator/requirements.txt /app/sim-requirements.txt

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r /app/edge-requirements.txt -r /app/sim-requirements.txt

# Copy code
COPY sensor-simulator/ /app/sensor-simulator/
COPY edge-gateway/ /app/edge-gateway/

# Create data directory for durable SQLite buffer
RUN mkdir -p /data && useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /data /app
USER appuser

WORKDIR /app/edge-gateway

ENV EDGE_DB_PATH=/data/edge.db \
    MQTT_HOST=mosquitto \
    MQTT_PORT=1883 \
    SERVER_BATCH_URL=http://server:8000/api/v1/telemetry/batch \
    SERVER_HEALTH_URL=http://server:8000/api/v1/health

CMD ["python3", "main.py"]
