# Luồng dữ liệu

## Telemetry thường

1. Mỗi sensor sinh event mỗi 10 giây. SEN-001, SEN-002, SEN-003 dùng topic riêng.
2. Publisher phát JSON qua MQTT QoS 1, retain=false. Payload có event_id, sensor_id, timestamp, sequence, value và unit.
3. Edge kiểm tra JSON, schema, sensor/topic/unit, timestamp và dải vật lý. Bản ghi sai vào SQLite quarantine và không điều khiển thiết bị.
4. Edge ghi event hợp lệ, phân loại NORMAL/ANOMALY, cập nhật health, cảnh báo và pump state trong cùng transaction SQLite. Event mới ở trạng thái PENDING.
5. Sau khi transaction commit, Edge ACK MQTT. Nếu lưu cục bộ lỗi, Edge không ACK để broker giao lại.
6. Sync Manager gửi batch PENDING qua POST /api/v1/telemetry/batch. Timeout, lỗi kết nối và lỗi HTTP tạm thời được retry bằng exponential backoff.
7. Server xác thực từng record. PostgreSQL dùng event_id làm khóa duy nhất; Influx point dùng cùng event_id để retry idempotent.
8. Server trả acknowledged_event_ids sau khi PostgreSQL và InfluxDB lưu thành công. Edge chỉ chuyển các ID này sang SYNCED; ID chưa ACK vẫn PENDING.
9. Grafana truy vấn InfluxDB cho chuỗi cảm biến và PostgreSQL cho sensor status, pump, sync counts và alert history.

## Hợp đồng event

| Trường | Kiểu | Ý nghĩa |
| --- | --- | --- |
| event_id | string | ID duy nhất, tiền tố EVT- |
| sensor_id | string | SEN-001, SEN-002 hoặc SEN-003 |
| timestamp | ISO 8601 | Thời điểm đo sensor, có múi giờ |
| sequence | integer >= 1 | Bộ đếm tăng riêng từng sensor |
| value | finite number | Giá trị đo |
| unit | string | C cho nhiệt độ, % cho độ ẩm |

## Mất kết nối Server

```mermaid
sequenceDiagram
  participant Sensor
  participant MQTT as Mosquitto
  participant Edge
  participant SQLite
  participant Server
  Sensor->>MQTT: publish QoS 1
  MQTT->>Edge: deliver event
  Edge->>SQLite: validate + commit PENDING and local effects
  Edge-->>MQTT: ACK after commit
  Edge->>Server: HTTP batch
  Server--xEdge: timeout / connection failure
  Note over Edge,SQLite: keep PENDING; retry with exponential backoff
  Edge->>Server: retry after recovery
  Server->>Server: PostgreSQL ledger + Influx write
  Server-->>Edge: acknowledged_event_ids
  Edge->>SQLite: mark only acknowledged IDs SYNCED
```

Influx point dùng timestamp sensor; received_at là thời gian Server nhận riêng, không thay thế thời điểm đo. Xem [Task 6 buffer and sync](task6-buffer-sync.md) và [API documentation](api-documentation.md).
