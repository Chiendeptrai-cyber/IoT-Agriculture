FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/sensor-simulator

COPY sensor-simulator/requirements.txt /app/sensor-simulator/requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r /app/sensor-simulator/requirements.txt

COPY sensor-simulator/ /app/sensor-simulator/

RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

ENV MQTT_HOST=mosquitto \
    MQTT_PORT=1883

CMD ["python3", "main.py", "--interval", "10"]
