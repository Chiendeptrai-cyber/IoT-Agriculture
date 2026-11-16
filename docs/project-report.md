# Báo cáo dự án — Smart Agriculture Monitoring System

## Tóm tắt

Dự án xây dựng hệ thống giám sát nông nghiệp IoT mô phỏng theo kiến trúc sensor → MQTT → Edge → REST Server → time-series/event storage → Grafana. Mục tiêu chính là thu thập dữ liệu ba sensor, phát hiện ngưỡng, điều khiển pump ảo có hysteresis và tiếp tục làm việc khi Server offline.

## Kết quả theo tiêu chí nghiệm thu

| Hạng mục | Kết quả và bằng chứng |
| --- | --- |
| KT1 — Thu thập ba sensor | Acceptance test tạo event từ ba simulator, qua validator/SQLite và Sync Manager vào API; xác minh đúng sensor ID, PostgreSQL ledger, Influx write và duplicate replay |
| KT2 — Threshold/anomaly/pump | Acceptance test xác minh nhiệt độ cao, humidity thấp, soil-moisture alert trên Server; anomaly classification; giá trị vật lý sai vào quarantine; pump ON dưới 30%, OFF trên 35% |
| KT3 — Offline/recovery | Bộ test network simulator giữ dữ liệu PENDING khi Server offline, retry/backoff, ACK chính xác, tránh duplicate và PENDING về 0 |
| MQTT | Integration test dùng Mosquitto thật; xác minh ba topic, QoS 1, không retained/replay; restart broker và client recovery |
| Server/API | Test batch validation, duplicate conflict, timestamp, ACK bền vững, health, query endpoint và Swagger |
| Grafana | Query thực của 9/9 panel trả frame; Last 15 minutes gồm sensor values, trends, 3 sensor status, pump, sync và alert history |
| Compose/persistence | Bảy service healthy trước/sau restart; event marker giữ nguyên trong Edge SQLite, PostgreSQL và InfluxDB |

Kết quả chi tiết và lệnh tái chạy ở [test results](test-results.md). Kiến trúc, luồng dữ liệu, database/API và triển khai được liên kết trong [architecture](architecture.md), [data flow](data-flow.md), [database design](database-design.md), [API](api-documentation.md), [deployment](deployment-guide.md).

## Năng lực quan sát

Ở chu kỳ mặc định 10 giây với ba sensor, tải danh nghĩa là 25.920 event/ngày và 777.600 event/30 ngày. Snapshot Edge SQLite sau kiểm thử có 1.478 event; page allocation 778.240 B và 526,55 B/event. Phép chiếu 30 ngày khoảng 409 MB trước dự phòng. Độ trễ Edge nhận đến SYNCED ở 1.478 mẫu: median 2,25 giây, P95 4,91 giây; max 121,46 giây do bao gồm retry/đợi mạng. Chi tiết có tại [capacity calculation](capacity-calculation.md).

## Triển khai và trình diễn

Khởi động bằng lệnh duy nhất trong [deployment guide](deployment-guide.md). Kịch bản diễn tập đủ 10 bước trong [final demo script](final-demo-script.md). README giữ nội dung và bố cục cũ; lệnh khởi động được cập nhật để bật profile normal, đồng thời thêm link các tài liệu bàn giao Task 8.

## Giới hạn hiện biết

- Môi trường dùng credentials demo và anonymous viewer Grafana; không dùng nguyên cấu hình này trên mạng công cộng.
- Influx bucket chưa đặt retention limit; cần xác định retention theo yêu cầu lưu trữ trước triển khai dài hạn.
- Dung lượng là ngoại suy tuyến tính từ volume demo và không thay cho load/stress test.
- InfluxDB và PostgreSQL không có distributed transaction; PostgreSQL ledger PENDING_INFLUX cùng idempotent retry bảo toàn ACK semantics.
