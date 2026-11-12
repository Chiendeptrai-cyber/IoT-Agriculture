# Task 4 — Server và REST API

## Phạm vi

Server nhận batch telemetry từ Edge, xác thực từng record, lưu event ledger trong PostgreSQL và ghi time-series vào InfluxDB. Event chỉ được ACK sau khi PostgreSQL đã commit trạng thái `STORED` và InfluxDB trả lời thành công. Nếu InfluxDB lỗi, event còn `PENDING_INFLUX`; Edge nhận `retryable: true` và có thể gửi lại cùng `event_id`.

PostgreSQL đặt `event_id` làm primary key/UNIQUE idempotency key. Một lần gửi lại có cùng `event_id` và cùng nội dung đã được lưu sẽ được trả là duplicate và vẫn nằm trong `acknowledged_event_ids`. Cùng `event_id` nhưng nội dung khác bị từ chối. Invalid records được giữ trong `ingestion_rejections` để chẩn đoán và không được ACK.

InfluxDB bucket mặc định là `smart_agriculture`, measurement là `sensor_readings`. Tag gồm `sensor_id`, `sensor_type`, `event_id` và `gateway_id`; fields gồm `value`, `unit`, `sequence`, `received_at`. Timestamp của Influx point luôn là `timestamp` gốc của cảm biến; `received_at` là thời gian riêng do Server ghi nhận. `event_id` là tag để một lần retry ghi lại cùng point, phù hợp với quy mô mô phỏng hiện tại.

## Khởi chạy

Từ thư mục `IoT-Agriculture`:

```bash
cp .env.example .env
docker compose --env-file .env -f infrastructure/docker-compose.yml up -d --build --wait
docker compose --env-file .env -f infrastructure/docker-compose.yml ps
```

PowerShell:

```powershell
Copy-Item .env.example .env
docker compose --env-file .env -f infrastructure/docker-compose.yml up -d --build --wait
docker compose --env-file .env -f infrastructure/docker-compose.yml ps
```

Swagger UI: <http://127.0.0.1:8000/docs>  
OpenAPI JSON: <http://127.0.0.1:8000/openapi.json>  
InfluxDB UI: <http://127.0.0.1:8086>  
PostgreSQL, InfluxDB và API chỉ publish port lên loopback của máy host. Credentials trong `.env.example` chỉ dành cho máy demo.

Compose tạo schema PostgreSQL khi Server khởi động lần đầu và InfluxDB khởi tạo bucket theo `.env`. Volumes giữ dữ liệu khi container được khởi động lại. Xóa volumes sẽ xóa dữ liệu database; muốn reset demo có thể dùng `docker compose --env-file .env -f infrastructure/docker-compose.yml down -v`.

## API

Tất cả endpoint nằm dưới `/api/v1`. FastAPI tự tạo Swagger UI tại `/docs`.

### `POST /api/v1/telemetry/batch`

Request:

```json
{
  "gateway_id": "GW-001",
  "records": [
    {
      "event_id": "EVT-EXAMPLE001",
      "sensor_id": "SEN-001",
      "timestamp": "2026-11-10T10:00:00Z",
      "sequence": 1,
      "value": 29.5,
      "unit": "C"
    }
  ]
}
```

`gateway_id` có thể bỏ qua; mặc định là `GW-001` để tương thích với Edge buffer hiện tại. Batch nhận 1–1.000 record. Envelope sai hoặc batch vượt giới hạn trả HTTP 422. Mỗi object trong `records` được xét riêng để một record lỗi không chặn các record hợp lệ khác.

Response mẫu:

```json
{
  "status": "success",
  "request_id": "...",
  "received": 1,
  "accepted": 1,
  "duplicates": 0,
  "rejected": 0,
  "accepted_event_ids": ["EVT-EXAMPLE001"],
  "duplicate_event_ids": [],
  "acknowledged_event_ids": ["EVT-EXAMPLE001"],
  "rejected_records": []
}
```

Edge có thể truyền `acknowledged_event_ids` thẳng cho `BufferManager.mark_synced()`. Chỉ record mới đã ghi xong cả hai nơi và duplicate đã lưu bền vững mới nằm trong danh sách này. Record bị từ chối có `index` (đếm từ 0), `event_id` nếu đọc được, `code`, `message` và `retryable`. Lỗi InfluxDB là retryable; lỗi schema hoặc xung đột nội dung của event ID là không retryable. Lỗi PostgreSQL làm cả request trả HTTP 503, không có ACK thành công trong response.

Record yêu cầu đúng sáu trường từ Edge: `event_id`, `sensor_id`, `timestamp`, `sequence`, `value`, `unit`. Timestamp phải ISO 8601 có múi giờ và được chuẩn hóa UTC; giá trị phải hữu hạn, unit và sensor ID phải khớp, và giá trị phải nằm trong dải vật lý: temperature [-40, 125], humidity/soil moisture [0, 100]. Vượt ngưỡng cảnh báo nhưng còn trong dải vật lý vẫn được chấp nhận.

Record lỗi `retryable: false` không nằm trong ACK. Edge Sync Manager cần dừng retry tự động với event đó và đưa lý do ra log/trạng thái vận hành để xử lý; không được đổi nó thành `SYNCED`.

### `GET /api/v1/sensors`

Trả danh sách ba sensor đã biết, record mới nhất đã lưu và trạng thái dựa trên thời điểm Server nhận: `ONLINE` dưới 30 giây, `STALE` từ 30 đến dưới 60 giây, `OFFLINE` từ 60 giây hoặc chưa có dữ liệu. Đây là trạng thái nhìn từ Server; khi Edge mất kết nối, dashboard Server chỉ biết dữ liệu đồng bộ gần nhất.

### `GET /api/v1/sensors/{sensor_id}/latest`

Trả record mới nhất đã lưu cho sensor. Sensor ID không tồn tại hoặc chưa có record sẽ trả HTTP 404.

### `GET /api/v1/alerts?limit=100`

Sinh danh sách cảnh báo từ telemetry đã lưu: temperature trên `TEMPERATURE_HIGH_THRESHOLD` (mặc định 35°C), humidity dưới `HUMIDITY_LOW_THRESHOLD` (mặc định 40%) và soil moisture dưới `SOIL_MOISTURE_LOW_THRESHOLD` (mặc định 30%). `limit` nằm trong 1–1.000. Cảnh báo được suy ra từ event ledger nên không lưu thành một bản ghi alert riêng. Giữ các biến này đồng nhất với `edge-gateway/edge_config.yaml`.

### `GET /api/v1/health`

Trả trạng thái API và PostgreSQL/InfluxDB. HTTP 200 khi cả hai storage sẵn sàng; HTTP 503 và `status: degraded` nếu một dependency không sẵn sàng.

## Smoke check

```bash
curl -fsS http://127.0.0.1:8000/api/v1/health
curl -fsS http://127.0.0.1:8000/api/v1/sensors
curl -fsS http://127.0.0.1:8000/api/v1/sensors/SEN-001/latest
curl -fsS 'http://127.0.0.1:8000/api/v1/alerts?limit=20'
```

PowerShell có thể dùng `Invoke-RestMethod` cho các lệnh GET. POST batch ví dụ Bash:

```bash
curl -sS -X POST http://127.0.0.1:8000/api/v1/telemetry/batch \
  -H 'Content-Type: application/json' \
  --data '{"gateway_id":"GW-001","records":[{"event_id":"EVT-EXAMPLE001","sensor_id":"SEN-001","timestamp":"2026-11-10T10:00:00Z","sequence":1,"value":29.5,"unit":"C"}]}'
```

Gửi lại cùng JSON: lần đầu phải có `accepted: 1`; lần sau `duplicates: 1` và cùng ID vẫn được ACK. Kiểm tra `influx_written_at` và `processing_status` trong `ingested_events`; với InfluxDB UI, query measurement `sensor_readings` và đối chiếu timestamp UTC với timestamp trong request. Kiểm tra record lỗi trong `ingestion_rejections`.

Chạy kiểm thử logic API cục bộ (SQLite tạm và Influx writer giả lập):

```bash
python -m pip install -r server/requirements-dev.txt
python -m pytest tests/test_server.py -q
```

Các test này kiểm tra hợp đồng HTTP, validation, duplicate, retry và timestamp. Chúng không thay thế integration test với container PostgreSQL và InfluxDB.

## Ghi chú vận hành

- `create_all()` phù hợp cho lần bàn giao đầu và demo. Trước khi schema thay đổi thường xuyên, chuyển sang migrations có phiên bản.
- Dịch vụ được cấu hình retry-safe: nếu Influx ghi thành công nhưng HTTP response bị mất, gửi lại event ID đó không tạo event logic thứ hai và trỏ tới cùng Influx point.
- Không bật anonymous access ra mạng. Mẫu Compose chỉ bind các cổng lên `127.0.0.1`; đổi credentials trước khi chia sẻ máy demo.

