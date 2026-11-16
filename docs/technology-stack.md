# Công nghệ sử dụng

| Công nghệ | Vị trí | Vai trò |
| --- | --- | --- |
| Python 3.12 | Simulator, Edge, Server | Runtime ứng dụng |
| Paho MQTT 2.x | Simulator và Edge | Publisher/subscriber QoS 1; manual ACK tại Edge |
| Eclipse Mosquitto 2.0.22 | Broker | Chuyển telemetry publish/subscribe |
| JSON Schema, jsonschema | Sensor/Edge | Hợp đồng payload và validation |
| PyYAML | Simulator/Edge | Cấu hình sensor, threshold, range và retry |
| SQLite | Edge | Buffer, sync status, cảnh báo, pump, quarantine và health |
| Requests | Edge Sync Manager | HTTP batch, timeout, retry |
| FastAPI + Uvicorn | Server | REST API, OpenAPI, Swagger UI |
| Pydantic | Server | Kiểm tra schema và chuẩn hóa datetime UTC |
| SQLAlchemy 2 + psycopg 3 | Server | PostgreSQL event ledger và audit |
| PostgreSQL 16 | Server/Grafana | Event ID duy nhất, trạng thái xử lý và vận hành |
| InfluxDB Client + InfluxDB 2.7 | Server/Grafana | Time-series measurement sensor_readings |
| Grafana 11.3 | Dashboard | Flux/SQL panels và provisioning |
| Docker Compose v2 | Toàn hệ thống | Network, healthcheck, dependencies, named volumes |
| Pytest | Kiểm thử | Unit, acceptance và integration tests |
| Markdown + Mermaid | docs | Kiến trúc, luồng dữ liệu, triển khai và báo cáo |

Dependency bounds nằm trong từng requirements.txt. Container Python dùng python:3.12-slim; tag database, broker và Grafana nằm trong [Compose](../infrastructure/docker-compose.yml).

## Vai trò các kho dữ liệu

- SQLite ở Edge để hệ thống tiếp tục thu thập và xử lý khi Server không sẵn sàng.
- PostgreSQL làm event ledger có khóa duy nhất, lưu audit record bị từ chối và hỗ trợ API vận hành.
- InfluxDB lưu giá trị theo thời gian. Point timestamp là timestamp sensor; received_at được giữ ở field riêng.
- Grafana dùng InfluxDB cho telemetry và PostgreSQL cho trạng thái sensor, pump, sync cùng alert history.
