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

Hạ tầng bao gồm Mosquitto, PostgreSQL, InfluxDB, Server API và Grafana:

```bash
# 1. Tạo file cấu hình môi trường nếu chưa có:
cp -n .env.example .env

# 2. Khởi chạy toàn bộ container:
docker compose --env-file .env -f infrastructure/docker-compose.yml up -d --build

# 3. Kiểm tra trạng thái các container (tất cả phải ở trạng thái healthy/running):
docker compose --env-file .env -f infrastructure/docker-compose.yml ps
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

## 3. Hướng Dẫn Vận Hành Hệ Thống (Quick Start)

Để chạy luồng hoạt động đầy đủ của hệ thống, hãy mở các cửa sổ Terminal:

### Terminal 1: Khởi động Edge Gateway
Tiếp nhận dữ liệu MQTT từ Broker, kiểm tra tính hợp lệ, lưu trữ SQLite bền vững, phát cảnh báo và điều khiển máy bơm cục bộ:
```bash
source .venv/bin/activate
python edge-gateway/main.py
```

### Terminal 2: Chạy Bộ Mô Phỏng Cảm Biến
Phát sinh dữ liệu cho 3 cảm biến và gửi lên Mosquitto MQTT:
```bash
source .venv/bin/activate

# Cách A: Chạy định kỳ thông thường (mỗi 10 giây/lần gửi):
python sensor-simulator/main.py

# Cách B: Chạy kịch bản Demo chuyển đổi trạng thái (NORMAL -> ANOMALY -> OFFLINE -> RECOVERY):
python sensor-simulator/main.py --demo --interval 1

# Cách C: Chạy demo kiểm tra cảnh báo và bật/tắt bơm tức thời:
python sensor-simulator/edge_demo.py
```

### Terminal 3 (Tùy chọn): Kiểm tra trạng thái Edge Gateway
Xem thống kê số bản ghi `PENDING`, trạng thái máy bơm và sức khỏe cảm biến:
```bash
python edge-gateway/main.py --status
```

### Terminal 4 (Tùy chọn): Nạp dữ liệu mẫu nhanh lên Server & Grafana
Nếu bạn muốn nạp ngay 15 phút dữ liệu biến thiên liên tục vào Server, InfluxDB và PostgreSQL để xem biểu đồ trên Grafana:
```bash
python scripts/generate_dashboard_demo_data.py --minutes 15 --step 15
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
  docker compose --env-file .env -f infrastructure/docker-compose.yml down
  ```
- Nếu muốn xóa trắng toàn bộ dữ liệu database để demo lại từ đầu:
  ```bash
  docker compose --env-file .env -f infrastructure/docker-compose.yml down -v
  ```
