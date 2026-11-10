# Smart Agriculture — Task 1, Task 2 & Task 2.1

Task 1 mô phỏng ba cảm biến. Task 2 truyền JSON qua Eclipse Mosquitto bằng MQTT/TCP, QoS 1. Task 2.1 xây dựng Edge để kiểm tra, phân loại, lưu SQLite, cảnh báo, điều khiển bơm ảo và theo dõi ONLINE/STALE/OFFLINE độc lập với Server.

- [Hướng dẫn Task 2: cấu hình, sơ đồ, chạy và nghiệm thu](docs/mqtt.md)
- [Task 2.1: Edge, SQLite, Sensor Health và demo khi không có Server](docs/edge.md)
- [Kết quả kiểm thử](docs/test-results.md)
- [Chi tiết mô phỏng Task 1](sensor-simulator/README.md)

## Quick Start:
```bash
# Từ thư mục gốc, dùng Python 3.12+ trong virtual environment:
python -m venv .venv
# Linux: source .venv/bin/activate
# PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r sensor-simulator/requirements.txt

# Khởi động broker:
docker compose -f infrastructure/docker-compose.yml up -d --wait mosquitto

# Terminal 1: Edge Gateway (nhận, kiểm tra, lưu và xử lý cục bộ)
python edge-gateway/main.py

# Terminal 2: ba cảm biến publish MQTT mỗi 10 giây
python sensor-simulator/main.py

# Demo NORMAL → ANOMALY → OFFLINE → NORMAL qua MQTT:
python sensor-simulator/main.py --demo --interval 1

# Demo cố định cảnh báo, bơm ảo, dữ liệu sai và chống trùng:
python sensor-simulator/edge_demo.py

# Terminal khác: xem SQLite, PENDING/SYNCED, cảnh báo, bơm và sensor health:
python edge-gateway/main.py --status

# Subscriber chỉ xem dữ liệu, có thể chạy song song với Edge:
python sensor-simulator/mqtt_subscriber.py

# Chạy lại Task 1, chỉ xuất terminal:
python sensor-simulator/main.py --terminal --count 3 --interval 1

# Unit tests (integration tests được bỏ qua nếu chưa bật):
python -m pytest tests -v
```

Broker demo chỉ mở trên `127.0.0.1:1883`, cho phép anonymous. MQTT không phụ thuộc Server.
Database mặc định: `edge-gateway/edge.db`, được tạo khi chạy Edge. Có thể dùng database cũ qua `--db data/edge.db`.
Edge lưu dữ liệu PENDING và xử lý tại chỗ mà không cần Server. Buffer có hàm cập nhật SYNCED từ danh sách event_id đã được Server xác nhận; HTTP sync worker sẽ nối với REST API của Task 3.
