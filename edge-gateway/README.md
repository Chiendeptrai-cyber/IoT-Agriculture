# Task 2.1 — Edge Gateway

Nhận MQTT từ ba cảm biến, kiểm tra/phân loại, lưu SQLite, tạo cảnh báo, điều khiển bơm ảo bằng hysteresis và theo dõi ONLINE/STALE/OFFLINE. Không cần Server để xử lý tại chỗ.

Từ thư mục gốc repository:

```powershell
.\.venv\Scripts\python.exe -m pip install -r edge-gateway/requirements.txt
docker compose -f infrastructure/docker-compose.yml up -d --wait mosquitto

# Terminal 1
.\.venv\Scripts\python.exe edge-gateway/main.py

# Terminal 2
.\.venv\Scripts\python.exe sensor-simulator/edge_demo.py --interval 2

# Terminal 3
.\.venv\Scripts\python.exe edge-gateway/main.py --status
```

Database mặc định `edge-gateway/edge.db` được tạo khi chạy; không commit database và file WAL/SHM lên Git. Dùng `--db data/edge.db` nếu muốn tiếp tục database cũ. Cấu hình ở `edge_config.yaml`, có thể chọn file riêng bằng `--config`.

Sau khi publisher ngừng gửi: STALE sau 30 giây, OFFLINE sau 60 giây; bản đo hợp lệ mới khôi phục ONLINE. Xem `sensor_health` trong `--status`. Bản tin trùng hoặc lỗi không gia hạn ONLINE.

Buffer có `pending_batch()` và `mark_synced(acknowledged_event_ids, sent_event_ids=...)`. Chưa có HTTP sync worker; chỉ dùng mark_synced sau ACK lưu bền vững đã kiểm tra từ Server khi tích hợp Task 3.

[Hướng dẫn đầy đủ và demo sensor health](../docs/edge.md) · [Kết quả kiểm thử](../docs/test-results.md).
