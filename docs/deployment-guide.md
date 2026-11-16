# Hướng dẫn triển khai

## Khởi động toàn bộ hệ thống

Tại thư mục gốc repository, dùng một lệnh:

**docker compose --env-file .env.example --profile normal up -d --build --wait**

Lệnh này khởi động cả bảy service: sensor-simulator, mosquitto, edge-gateway, server, postgres, influxdb và grafana. Profile normal bật simulator; Compose chỉ trả về khi các service có healthcheck đã healthy. Với cấu hình cá nhân, copy .env.example thành .env rồi dùng --env-file .env.

## Kiểm tra nhanh

- Trạng thái container: **docker compose --env-file .env.example --profile normal ps**
- Log luồng dữ liệu: **docker compose --env-file .env.example --profile normal logs --tail 100 sensor-simulator mosquitto edge-gateway server**
- Edge buffer: **docker compose --env-file .env.example --profile normal exec -T edge-gateway python3 main.py --status**
- API health: GET http://127.0.0.1:8000/api/v1/health
- Swagger: http://127.0.0.1:8000/docs
- Grafana: http://127.0.0.1:3000
- InfluxDB: http://127.0.0.1:8086
- MQTT host port: 1883; PostgreSQL host port: 5433.

## Docker network và persistent data

Các service giao tiếp trên bridge network smart-agriculture-network bằng DNS service name. SQLite Edge nằm trong edge_data; PostgreSQL trong postgres_data; InfluxDB trong influxdb_data và influxdb_config; Grafana trong grafana_data; broker trong mosquitto_data. Restart/recreate container không xóa named volume. Lệnh down -v sẽ xóa toàn bộ dữ liệu, chỉ dùng khi thật sự muốn reset demo.

## Cấu hình và profile

- .env.example chứa biến cấu hình mẫu; credentials mặc định chỉ dành cho demo local.
- normal: hệ thống thường, simulator mỗi 10 giây.
- demo: kịch bản đổi NORMAL/ANOMALY/OFFLINE.
- edge-demo: chuỗi kiểm thử threshold/pump/quarantine.
- Server phụ thuộc PostgreSQL và InfluxDB healthy; Edge chỉ cần Mosquitto để bắt đầu; Simulator chờ broker và Edge healthy.

## Lỗi thường gặp

| Triệu chứng | Kiểm tra / cách khắc phục |
| --- | --- |
| Docker daemon chưa sẵn sàng | Mở Docker Desktop, chờ Engine rồi chạy docker info |
| Port 1883/3000/5433/8000/8086 bị chiếm | Kiểm tra tiến trình đang bind; đổi GRAFANA_PORT/POSTGRES_PORT hoặc mapping trong Compose |
| Server unhealthy | Xem logs server postgres influxdb; xác nhận URL trong container dùng service name, không dùng localhost |
| Edge còn PENDING | Xem log edge-gateway server và main.py --status; khi Server trở lại, Sync Manager tự retry |
| Dashboard không có dữ liệu | Chọn đúng thời gian, kiểm tra Simulator → Mosquitto → Edge → Server và datasource |
| Influx token/org/bucket sai | Đồng bộ env giữa InfluxDB và Server; volume đã khởi tạo sẽ giữ token setup ban đầu |
| SQLite báo lỗi/đầy ổ | Kiểm tra quyền và dung lượng volume edge_data; không xóa DB/WAL khi Edge đang chạy |

Chi tiết dependency, healthcheck và kiểm tra sau restart xem tại [Task 7 deployment](task7-deployment.md).
