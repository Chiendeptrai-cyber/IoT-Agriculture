# Smart Agriculture — Task 1 & Task 2

Task 1 mô phỏng ba cảm biến. Task 2 truyền JSON qua Eclipse Mosquitto bằng MQTT/TCP, QoS 1.

- [Hướng dẫn Task 2: cấu hình, sơ đồ, chạy và nghiệm thu](docs/mqtt.md)
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

# Terminal 1: subscriber (chạy trước publisher)
python sensor-simulator/mqtt_subscriber.py

# Terminal 2: ba cảm biến publish MQTT mỗi 10 giây
python sensor-simulator/main.py

# Demo NORMAL → ANOMALY → OFFLINE → NORMAL qua MQTT:
python sensor-simulator/main.py --demo --interval 1

# Chạy lại Task 1, chỉ xuất terminal:
python sensor-simulator/main.py --terminal --count 3 --interval 1

# Unit tests (integration tests được bỏ qua nếu chưa bật):
python -m pytest tests/test_simulator.py tests/test_mqtt.py -v
```

Broker demo chỉ mở trên `127.0.0.1:1883`, cho phép anonymous. MQTT không phụ thuộc Server.
Subscriber hiện tại phục vụ kiểm thử; validation nghiệp vụ, SQLite và xử lý Edge là các task tiếp theo.
