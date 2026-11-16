# Kịch bản trình diễn cuối

## Chuẩn bị

1. Tại thư mục gốc, chạy **docker compose --env-file .env.example --profile normal up -d --build --wait**.
2. Mở Grafana tại http://127.0.0.1:3000, chọn khoảng thời gian Last 15 minutes.
3. Mở thêm terminal theo dõi log Edge/Server và trang Swagger UI ở http://127.0.0.1:8000/docs.
4. Chạy scripts/verify_all_panels.py --require-data để kiểm tra query của cả chín panel.

## Demo 10 bước

| Bước | Hành động | Bằng chứng mong đợi |
| --- | --- | --- |
| 1. Khởi động | Compose lên đủ 7 service | Compose ps: healthy; /api/v1/health trả ok |
| 2. Telemetry | Để simulator thường chạy 20–30 giây | Edge log nhận đủ ba sensor, SQLite tăng số record |
| 3. Dashboard | Mở Grafana | Ba stat có số liệu; hai trend có timestamp; sensor status hiển thị ba ID |
| 4. Dữ liệu bất thường | Chạy sensor-simulator edge_demo.py trong Compose | Edge log phân loại ANOMALY/quarantine theo kịch bản |
| 5. Cảnh báo | Gửi nhiệt độ >35°C hoặc humidity <40% | Edge ALERT log và Alert History/API alerts có event tương ứng |
| 6. Pump ON/OFF | edge_demo gửi soil moisture dưới 30%, sau đó trên 35% | Log chuyển pump OFF→ON→OFF; không đổi trạng thái trong vùng hysteresis |
| 7. Ngắt Server | docker compose stop server; giữ simulator/broker/Edge chạy khoảng 20 giây | Edge tiếp tục nhận và ghi SQLite; số PENDING tăng; không ACK Server |
| 8. Khôi phục | docker compose start server; chờ healthcheck | Edge tự retry; log SYNC SUCCESS; PENDING giảm dần |
| 9. Chứng minh sync | main.py --status và API/DB counts | Các ID chuyển SYNCED; PostgreSQL có event ID duy nhất; Influx có điểm theo timestamp sensor |
| 10. Kết thúc | Lưu screenshot Grafana và log, rồi docker compose stop nếu muốn | Bằng chứng có thời gian, event ID và kết quả đối chiếu |

Để demo riêng đổi mode NORMAL → ANOMALY → OFFLINE → recovery, chạy sensor-simulator main.py --demo --interval 1. Lệnh này là simulator độc lập; khi kết thúc demo sensor quay về process state bình thường.

## Bằng chứng cần lưu cho báo cáo

- Screenshot dashboard có khoảng thời gian và đủ panel.
- Log Edge cho event_id, cảnh báo, pump, SQLite PENDING/SYNCED.
- Trước/sau offline: tổng/PENDING/SYNCED từ main.py --status.
- Cùng một event_id trong SQLite Edge, PostgreSQL ingested_events và Influx sensor_readings.
- Thời gian bắt đầu/dừng Server, thời gian batch đồng bộ và tổng event xác nhận.
