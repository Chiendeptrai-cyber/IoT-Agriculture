# Software-Defined Smart Agriculture Monitoring System

Hệ thống giám sát nông nghiệp thông minh mô phỏng bằng phần mềm theo mô hình IoT nhiều tầng (Multi-tier IoT Architecture):
- **Tầng Cảm biến (Sensor Simulation Layer)**: Mô phỏng 3 cảm biến (Nhiệt độ `SEN-001`, Độ ẩm không khí `SEN-002`, Độ ẩm đất `SEN-003`) với các chế độ `NORMAL`, `ANOMALY`, `OFFLINE`.
- **Tầng Truyền thông (Communication Layer)**: Truyền tin chuẩn JSON 6 trường qua Eclipse Mosquitto MQTT Broker (QoS 1, Topic phân cấp).
- **Tầng Biên (Edge Computing Layer)**: Edge Gateway xác thực dữ liệu, lưu trữ bền vững SQLite (WAL mode), xử lý cảnh báo nhiệt độ/độ ẩm, điều khiển máy bơm ảo (Hysteresis), và theo dõi sức khỏe cảm biến (`ONLINE` / `STALE` / `OFFLINE`) độc lập với Server.
- **Tầng Máy chủ & Lưu trữ (Server Layer)**: FastAPI REST API, PostgreSQL (Event ledger, Idempotency, Quản lý lỗi), InfluxDB v2 (Lưu trữ Time-series theo timestamp cảm biến).
- **Tầng Trực quan hóa (Visualization Layer)**: Grafana Dashboard 9 panels hiển thị chỉ số tức thời, biểu đồ xu hướng, trạng thái thiết bị và tình trạng đồng bộ dữ liệu.

---

## 1. Cài Đặt Môi Trường (Setup)

### Yêu cầu tiên quyết:
- **Python 3.10+** (khuyến nghị 3.12)
- **Docker** & **Docker Compose**

### Thiết lập Virtual Environment:
```bash
# Di chuyển vào thư mục dự án
cd "$HOME/project/IoT Project"

# 1. Tạo môi trường ảo Python:
python3 -m venv .venv

# 2. Kích hoạt môi trường ảo:
# Trên Linux / macOS:
source .venv/bin/activate
# Trên Windows PowerShell:
# .\.venv\Scripts\Activate.ps1

# 3. Cài đặt toàn bộ thư viện cần thiết:
pip install -r requirements.txt
```
> **Mẹo**: Sau khi kích hoạt môi trường ảo (`source .venv/bin/activate`), bạn có thể gõ lệnh `python ...` trực tiếp mà không bao giờ gặp lỗi thiếu thư viện `paho-mqtt` hay `yaml`.

---

## 2. Khởi Động Hạ Tầng Docker (Infrastructure)

Hạ tầng hệ thống được container hóa toàn bộ bằng Docker Compose, bao gồm:
- **Hạ tầng lõi**: Mosquitto (MQTT 1883), PostgreSQL (5433), InfluxDB (8086), Server API (8000), Grafana (3000).
- **Edge Gateway**: Tự động chạy ngầm trong container, kết nối MQTT nội bộ, lưu đệm SQLite vào volume bền vững (`edge_data`), tự động đồng bộ HTTP lên Server mỗi 5s.
- **Sensor Simulator**: Sẵn sàng chạy theo kịch bản tương tác (CLI) hoặc chạy ngầm (Profiles).

```bash
# 1. Tạo file cấu hình môi trường nếu chưa có:
cp -n .env.example .env

# 2. Khởi chạy toàn bộ hệ thống (Hạ tầng + Edge Gateway tự động chạy):
docker compose --env-file .env --profile normal up -d --build --wait

# 3. Kiểm tra trạng thái các container (tất cả phải ở trạng thái healthy/running):
docker compose --env-file .env --profile normal ps
```

### Các Cổng Dịch Vụ Mặc Định:
| Dịch vụ | Địa chỉ URL / Cổng | Tài khoản mặc định | Chức năng |
|---|---|---|---|
| **Grafana Dashboard** | <http://localhost:3000> | `admin` / `admin` (hoặc mở trực tiếp không cần đăng nhập) | Trực quan hóa dữ liệu và giám sát hệ thống |
| **Server REST API** | <http://localhost:8000/docs> | *Không yêu cầu* | Swagger UI tài liệu API & tiếp nhận batch dữ liệu |
| **InfluxDB UI** | <http://localhost:8086> | `agri_admin` / `agri_dev_only` | Quản lý database chuỗi thời gian (Org/Bucket: `smart_agriculture`) |
| **Mosquitto MQTT** | `127.0.0.1:1883` | *Anonymous local* | MQTT Broker nhận dữ liệu cảm biến |
| **PostgreSQL** | `127.0.0.1:5433` | `agri` / `agri_dev_only` | Event ledger, Idempotency & Rejections audit |

---

## 3. Hướng Dẫn Vận Hành & Chạy Cảm Biến (Quick Start)

Khi hạ tầng và Edge Gateway đã chạy ngầm trong Docker (`docker compose up -d`), bạn chỉ cần chạy bộ mô phỏng cảm biến.

Có 2 cách vận hành linh hoạt bằng Docker (và 1 cách chạy trực tiếp bằng Python host):

### 🎯 Cách 1: Chạy Tương Tác Qua Docker (Khuyên Dùng khi Test / Demo trực quan)
Chạy trực tiếp trong Terminal hiện tại, xem log phát sinh dữ liệu thời gian thực. Nhấn `Ctrl + C` để dừng:

```bash
# Chế độ A: Phát sinh dữ liệu định kỳ bình thường (10 giây/lần gửi):
docker compose -f infrastructure/docker-compose.yml run --rm sensor-simulator python3 main.py

# Chế độ B: Kịch bản Demo chuyển đổi trạng thái (NORMAL -> ANOMALY -> OFFLINE -> RECOVERY, 1s/lần):
docker compose -f infrastructure/docker-compose.yml run --rm sensor-simulator python3 main.py --demo --interval 1

# Chế độ C: Kịch bản kích hoạt ngưỡng cảnh báo & bật/tắt bơm tức thời:
docker compose -f infrastructure/docker-compose.yml run --rm sensor-simulator python3 edge_demo.py
```

---

### 🚀 Cách 2: Chạy Ngầm Bằng Docker Compose Profiles (Dễ dàng chuyển đổi chế độ)
Chạy container cảm biến ngầm trong Docker mà không cần giữ mở terminal:

```bash
# 1. Bật chế độ chạy định kỳ thông thường (10s/lần):
docker compose --env-file .env -f infrastructure/docker-compose.yml --profile normal up -d

# 2. Hoặc chuyển sang chế độ Demo chuyển đổi trạng thái (1s/lần):
docker compose --env-file .env -f infrastructure/docker-compose.yml --profile normal stop
docker compose --env-file .env -f infrastructure/docker-compose.yml --profile demo up -d

# 3. Xem log dữ liệu đang gửi:
docker compose -f infrastructure/docker-compose.yml logs -f sensor-simulator
# hoặc (khi ở chế độ demo):
docker compose -f infrastructure/docker-compose.yml logs -f sensor-simulator-demo

# 4. Dừng gửi dữ liệu cảm biến:
docker compose -f infrastructure/docker-compose.yml stop sensor-simulator sensor-simulator-demo
```

---

### 💻 Cách 3: Chạy Bằng Python Trên Máy Chủ (Dành cho Lập Trình Viên)
Nếu bạn muốn debug trực tiếp mã nguồn bằng Python trên host:
```bash
source .venv/bin/activate

# Chạy cảm biến:
python3 sensor-simulator/main.py --demo --interval 1
```

---

### Các Lệnh Tiện Ích Khác:

- **Xem log thời gian thực của Edge Gateway**:
  ```bash
  docker compose -f infrastructure/docker-compose.yml logs -f edge-gateway
  ```

- **Kiểm tra trạng thái bộ đệm SQLite & máy bơm của Edge Gateway**:
  ```bash
  docker compose -f infrastructure/docker-compose.yml exec edge-gateway python3 main.py --status
  ```

- **Nạp nhanh 15–60 phút dữ liệu mẫu vào Server & Grafana**:
  ```bash
  source .venv/bin/activate
  python3 scripts/generate_dashboard_demo_data.py --minutes 30 --step 15
  ```


---

## 4. Dashboard Giám Sát Grafana (Task 5)

Truy cập: **<http://localhost:3000>** (Dashboard: `Smart Agriculture Monitoring Dashboard`)

Dashboard được chia thành 4 khu vực với **9 panels**:
1. **Thông số Môi trường Tức thời**:
   - `Temperature`: Nhiệt độ hiện tại (°C), ngưỡng Xanh (<30°C), Vàng (30-35°C), Đỏ (>35°C).
   - `Air Humidity`: Độ ẩm không khí hiện tại (%), ngưỡng Đỏ (<40%), Xanh (≥40%).
   - `Soil Moisture`: Độ ẩm đất hiện tại (%), ngưỡng Đỏ (<30%), Xanh (30-35%), Lam (>35%).
2. **Biến động theo Thời gian (Trends)**:
   - `Temperature Trend`: Biểu đồ nhiệt độ time-series kèm đường ngưỡng đỏ **35°C**.
   - `Soil Moisture Trend`: Biểu đồ độ ẩm đất kèm 2 đường ngưỡng hysteresis **30%** (bật bơm) và **35%** (tắt bơm).
3. **Trạng thái Vận hành**:
   - `Sensor Status`: Bảng chi tiết 3 cảm biến (`ONLINE` <30s, `STALE` 30-60s, `OFFLINE` >60s).
   - `Pump Status`: Trạng thái máy bơm ảo (`ON (ĐANG TƯỚI)` / `OFF (NGỪNG TƯỚI)`).
   - `Sync Status`: Thống kê số bản ghi đã đồng bộ (`STORED`), chờ đồng bộ (`PENDING`) và bị cách ly (`REJECTED`).
4. **Lịch sử Cảnh báo**:
   - `Alert History`: Danh sách chi tiết các sự kiện vượt ngưỡng phát sinh trong hệ thống.

*Chi tiết tài liệu và ảnh chụp màn hình xem tại: [docs/grafana-dashboard.md](docs/grafana-dashboard.md).*

---

## 5. Kiểm Thử Hệ Thống (Testing)

Chạy bộ kiểm thử tự động với Pytest:
```bash
source .venv/bin/activate

# 1. Chạy toàn bộ unit tests:
python -m pytest tests -v

# 2. Kiểm thử tự động 9/9 query của Dashboard Grafana:
python scripts/verify_all_panels.py
```

---

## 6. Dừng Hệ Thống

Khi muốn dừng toàn bộ các tiến trình và hạ tầng:
- Nhấn `Ctrl + C` tại các Terminal đang chạy Edge Gateway và Sensor Simulator.
- Tắt các dịch vụ Docker:
  ```bash
  docker compose --env-file .env --profile normal down
  ```
- Nếu muốn xóa trắng toàn bộ dữ liệu database để demo lại từ đầu:
  ```bash
  docker compose --env-file .env --profile normal down -v
  ```

## Task 8 — Kiểm thử nghiệm thu và tài liệu bàn giao

Task 8 bổ sung acceptance tests KT1–KT3, đo capacity Edge SQLite thật, kiểm tra query Grafana và kịch bản bảo vệ. Tài liệu kỹ thuật:

- Kiến trúc: docs/architecture.md; luồng dữ liệu: docs/data-flow.md.
- Công nghệ và database: docs/technology-stack.md, docs/database-design.md.
- API, dung lượng, kiểm thử và bằng chứng: docs/api-documentation.md, docs/capacity-calculation.md, docs/test-results.md, docs/task8-verification.json.
- Triển khai, báo cáo, demo: docs/deployment-guide.md, docs/project-report.md, docs/final-demo-script.md.

Chạy full suite với Mosquitto thật và kiểm thử restart broker trên Windows PowerShell:

```powershell
$env:RUN_MQTT_INTEGRATION = "1"
$env:RUN_MQTT_RESTART = "1"
python -m pytest -p no:cacheprovider -q -rs tests
Remove-Item Env:RUN_MQTT_INTEGRATION, Env:RUN_MQTT_RESTART
python scripts/verify_all_panels.py --require-data
```
