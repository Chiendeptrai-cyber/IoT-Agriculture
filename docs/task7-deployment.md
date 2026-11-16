# Task 7 — Triển khai toàn hệ thống bằng Docker Compose

## Khởi động toàn bộ hệ thống

Từ thư mục gốc repo, chạy một lệnh:

```powershell
docker compose --env-file .env.example --profile normal up -d --build --wait
```

Lệnh này dùng `docker-compose.yml` ở thư mục gốc và khởi động cả bảy service. File root đưa vào cấu hình chi tiết trong `infrastructure/docker-compose.yml`; cấu hình cũ vẫn dùng được. Simulator được giữ trong profile `normal` để cách chạy hạ tầng riêng trong README và các chế độ demo không bị thay đổi. Lệnh trên bật profile đó; Simulator phát dữ liệu mỗi 10 giây. Hai simulator demo chỉ chạy khi bật profile tương ứng.

Kiểm tra trạng thái:

```powershell
docker compose ps
docker compose logs --tail 50 sensor-simulator edge-gateway server
```

Các giao diện sau khi khởi động:

- Grafana: <http://localhost:3000>
- Swagger UI: <http://localhost:8000/docs>
- InfluxDB: <http://localhost:8086>
- MQTT broker: `localhost:1883`
- PostgreSQL: `localhost:5433`

## Network, healthcheck và lưu dữ liệu

Các service dùng bridge network `smart-agriculture-network`; Compose cấp DNS theo tên service như `mosquitto`, `server`, `postgres` và `influxdb`. Edge chỉ cần broker để khởi động, nên vẫn chạy và lưu SQLite nếu Server tạm thời không khả dụng.

Compose kiểm tra sức khỏe PostgreSQL, InfluxDB, Mosquitto, Server, Grafana, Edge và Simulator. `--wait` chỉ trả về khi các service có healthcheck đã healthy.

Named volumes giữ dữ liệu khi container được tạo lại hoặc restart:

- `edge_data`: SQLite tại `/data/edge.db`.
- `postgres_data`: PostgreSQL.
- `influxdb_data` và `influxdb_config`: InfluxDB.
- `grafana_data`: cấu hình và dữ liệu Grafana.
- `mosquitto_data`: dữ liệu broker.

`docker compose down` không xóa các named volume. **Không dùng `docker compose down -v` nếu cần giữ dữ liệu.**

## Kiểm tra sau restart

```powershell
docker compose --env-file .env.example --profile normal restart edge-gateway postgres influxdb
docker compose --env-file .env.example --profile normal up -d --wait
docker compose --env-file .env.example --profile normal exec -T edge-gateway python3 main.py --status
docker compose --env-file .env.example --profile normal exec -T postgres psql -U agri -d smart_agriculture -c "SELECT COUNT(*) FROM ingested_events;"
```

Đối chiếu một event đã lưu trước restart trong PostgreSQL và InfluxDB; số lượng event Edge và trạng thái PENDING/SYNCED xem bằng lệnh `--status` ở trên. Restart không xóa named volume.

## Xử lý lỗi triển khai thường gặp

- **Docker daemon không chạy:** mở Docker Desktop, chờ Engine sẵn sàng rồi chạy `docker info`.
- **Port bị chiếm:** dừng ứng dụng đang dùng cổng 1883, 3000, 5433, 8000 hoặc 8086. Có thể đổi `GRAFANA_PORT` và `POSTGRES_PORT` trong file env; các port còn lại đổi ở `infrastructure/docker-compose.yml`.
- **Service đang `starting` hoặc `unhealthy`:** xem log bằng `docker compose logs --tail 100 <service>`. PostgreSQL và InfluxDB cần healthy trước Server; Mosquitto cần healthy trước Simulator và Edge.
- **Edge có PENDING nhưng chưa đồng bộ:** kiểm tra `docker compose logs edge-gateway server` và `docker compose exec -T edge-gateway python3 main.py --status`. Edge giữ dữ liệu cục bộ trong lúc Server offline và tự retry khi kết nối lại.
- **Grafana không có dữ liệu:** kiểm tra `sensor-simulator`, `mosquitto` và `edge-gateway`; chọn khoảng thời gian bao gồm lúc dữ liệu được gửi.
- **Đổi token hoặc thông tin khởi tạo InfluxDB:** bảo đảm env của InfluxDB, Server và Grafana dùng cùng org, bucket và token. InfluxDB chỉ áp dụng thông tin khởi tạo khi volume được tạo lần đầu; thay env không tự đổi thông tin trong volume hiện có.
- **Muốn làm sạch dữ liệu:** `docker compose down -v` xóa các named volume, gồm cả SQLite, PostgreSQL, InfluxDB và Grafana. Chỉ chạy khi chủ đích xóa toàn bộ dữ liệu.
