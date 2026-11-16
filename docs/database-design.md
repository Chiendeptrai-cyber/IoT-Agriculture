# Thiết kế cơ sở dữ liệu

## Edge SQLite

Database nằm ở /data/edge.db trên named volume edge_data. SQLite bật WAL và synchronous FULL.

| Bảng | Khóa / ràng buộc | Nội dung |
| --- | --- | --- |
| telemetry | event_id primary key; sync_status chỉ PENDING/SYNCED | Payload, sensor/time/sequence/value/unit, receive/process time, classification và sync state |
| alerts | FK event_id; unique(event_id, kind) | Cảnh báo ngưỡng tại Edge |
| device_state | device_id primary key | Pump state và event gây đổi trạng thái |
| device_actions | unique event_id, FK telemetry | Chuyển trạng thái ON/OFF đã commit |
| sensor_watermarks | sensor_id primary key | Timestamp/sequence mới nhất để chống dữ liệu cũ tác động pump |
| quarantine | ID tự tăng | Payload sai và lý do; không sync như telemetry hợp lệ |
| sensor_health, sensor_health_events | sensor_id, FK | ONLINE/STALE/OFFLINE và lịch sử chuyển trạng thái |

## PostgreSQL

### ingested_events

- event_id là primary key và idempotency key.
- processing_status nhận PENDING_INFLUX hoặc STORED.
- Giữ gateway_id, sensor_id, measurement_time, sequence, value, unit, received_at, payload, last_error và influx_written_at.
- Index theo (sensor_id, measurement_time) và (processing_status, received_at) phục vụ API/dashboard.
- Event PENDING_INFLUX chưa được ACK. Retry cùng event ID ghi lại cùng Influx point rồi hoàn tất ledger.

### ingestion_rejections

Audit từng record bị từ chối: request ID, vị trí trong batch, event ID nếu có, error code/message, retryable, payload và receive time. Record bị từ chối không được ACK.

## InfluxDB

- Bucket: smart_agriculture.
- Measurement: sensor_readings.
- Tags: sensor_id, sensor_type, event_id, gateway_id.
- Fields: value, unit, sequence, received_at.
- Point timestamp: timestamp gốc sensor; client ghi với độ chính xác nanosecond.

event_id là tag để retry ghi lên cùng point. Cách này phù hợp quy mô demo một gateway; triển khai lớn/dài hạn cần đánh giá cardinality và retention.

## ACK và nhất quán

Không có distributed transaction giữa PostgreSQL và InfluxDB. Server dùng PostgreSQL làm ledger:

1. Commit event ở PENDING_INFLUX.
2. Ghi đồng bộ point vào InfluxDB.
3. Commit trạng thái STORED.
4. Chỉ khi bước 3 thành công, event ID mới được trả trong ACK.

Nếu tiến trình dừng giữa bước 2 và 3, retry ghi lại point xác định rồi hoàn tất ledger. Nếu Influx lỗi, event vẫn còn trong PostgreSQL và Edge giữ bản ghi PENDING để retry.
