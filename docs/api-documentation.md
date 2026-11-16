# Tài liệu REST API

Base path là /api/v1. OpenAPI/Swagger UI nằm tại /docs; JSON schema ở /openapi.json.

| Method | Endpoint | Kết quả |
| --- | --- | --- |
| POST | /api/v1/telemetry/batch | Nhận batch từ Gateway; xác thực từng event; trả accepted, duplicates, rejected và acknowledged_event_ids |
| GET | /api/v1/sensors | Danh sách ba sensor, reading mới nhất và trạng thái ONLINE/STALE/OFFLINE |
| GET | /api/v1/sensors/{sensor_id}/latest | Reading đã lưu mới nhất của sensor; 404 nếu sensor lạ hoặc chưa có dữ liệu |
| GET | /api/v1/alerts?limit=100 | Cảnh báo tính từ event đã STORED; limit 1–1.000 |
| GET | /api/v1/health | Trạng thái API, PostgreSQL và InfluxDB; 503 khi dependency lỗi |

## POST batch

JSON envelope gồm gateway_id (mặc định GW-001) và records, tối thiểu 1, tối đa 1.000 event. Mỗi event gồm event_id, sensor_id, timestamp, sequence, value và unit. Timestamp bắt buộc có timezone. Sensor ID/unit phải khớp; giá trị phải hữu hạn và trong dải vật lý.

Server kiểm tra record độc lập; một record sai không chặn các record hợp lệ. Envelope sai hoặc batch vượt giới hạn trả HTTP 422. Nếu PostgreSQL không khả dụng, trả HTTP 503. HTTP 200 có thể là partial; Edge phải xét acknowledged_event_ids chứ không chỉ dựa vào status hoặc accepted count.

Response có received, accepted, duplicates, rejected, danh sách event IDs và rejected_records. Duplicate chỉ được ACK khi cùng event_id và payload logic khớp event đã lưu. Cùng ID nhưng dữ liệu khác bị từ chối event_id_conflict. Bản ghi bị từ chối không được đánh dấu SYNCED ở Edge.

ACK thành công chỉ gồm event đã STORED trong PostgreSQL và InfluxDB, hoặc duplicate đã STORED. Nếu Influx lỗi, Server giữ ledger PENDING_INFLUX và trả lỗi retryable; Edge giữ bản ghi PENDING.

## Các ngưỡng mặc định

- Nhiệt độ cao: trên 35°C.
- Độ ẩm không khí thấp: dưới 40%.
- Độ ẩm đất thấp: dưới 30%.
- Sensor status: ONLINE dưới 30 giây, STALE từ 30 đến dưới 60 giây, OFFLINE từ 60 giây hoặc chưa có reading.

Ngưỡng API cần giữ đồng nhất với edge-gateway/edge_config.yaml và environment của Compose. Chi tiết request/response, ví dụ và smoke check có tại [server-api.md](server-api.md).
