# Hướng Dẫn Sử Dụng Dashboard Giám Sát Grafana

Tài liệu hướng dẫn cấu hình, khởi chạy và sử dụng Dashboard trực quan hóa cho hệ thống **Software-Defined Smart Agriculture Monitoring System**.

---

## 1. Tổng quan & Kiến trúc Trực quan hóa

Dashboard giám sát được xây dựng trên **Grafana 11.3.0**, đóng vai trò là giao diện trung tâm để:
- **Người quản lý trang trại**: Theo dõi các thông số môi trường tức thời (°C, %), biến động qua thời gian, nhận biết tình trạng hạn hán hay nhiệt độ cao để đưa ra quyết định canh tác.
- **Nhân viên vận hành**: Giám sát trạng thái hoạt động của cảm biến (`ONLINE` / `STALE` / `OFFLINE`), kiểm tra tình trạng bật/tắt của máy bơm tưới nước mô phỏng, lịch sử cảnh báo và tình trạng đồng bộ dữ liệu giữa Edge Gateway và Server.

### Kết nối Dữ liệu (Data Sources)
Hệ thống sử dụng cơ chế **Provisioning tự động** kết nối với 2 nguồn dữ liệu:
1. **InfluxDB v2 (Flux)**: Truy vấn dữ liệu chuỗi thời gian (`sensor_readings`) trong bucket `smart_agriculture` theo đúng Measurement Timestamp của cảm biến.
2. **PostgreSQL**: Truy vấn thông tin sự kiện (`ingested_events`), trạng thái đồng bộ (`STORED` / `PENDING_INFLUX`), lịch sử cảnh báo và log lỗi (`ingestion_rejections`).

---

## 2. Khởi chạy Hệ thống

Từ thư mục gốc dự án:

```bash
# 1. Tạo file cấu hình môi trường nếu chưa có:
cp .env.example .env

# 2. Khởi động toàn bộ cụm dịch vụ (Mosquitto, InfluxDB, PostgreSQL, Server API, Grafana):
docker compose --env-file .env -f infrastructure/docker-compose.yml up -d --build --wait

# 3. Kiểm tra trạng thái các container:
docker compose --env-file .env -f infrastructure/docker-compose.yml ps
```

### Thông tin truy cập dịch vụ:
- **Grafana Dashboard**: <http://127.0.0.1:3000>
  - *Tài khoản quản trị*: `admin` / `admin`
  - *Chế độ xem ẩn danh*: Đã được kích hoạt sẵn (`Viewer`), người dùng có thể mở thẳng đường dẫn trên trình duyệt để quan sát mà không bắt buộc đăng nhập.
- **Server REST API & Swagger UI**: <http://127.0.0.1:8000/docs>
- **InfluxDB Management UI**: <http://127.0.0.1:8086> (User: `agri_admin`, Pass: `agri_dev_only`)

---

## 3. Đặc tả 9 Panels Giám Sát

Dashboard `Smart Agriculture Monitoring Dashboard` bao gồm 4 khu vực chức năng với 9 panels:

### Nhóm 1: Thông số Môi trường Hiện tại (Realtime Telemetry)
1. **Temperature (`SEN-001`)**:
   - *Mục đích*: Đo nhiệt độ môi trường xung quanh.
   - *Đơn vị*: Độ C (`celsius`).
   - *Ngưỡng màu*: Xanh (<30°C: lý tưởng), Vàng (30–35°C: cảnh báo nhẹ), Đỏ (>35°C: vượt ngưỡng cảnh báo nhiệt độ cao).
2. **Air Humidity (`SEN-002`)**:
   - *Mục đích*: Đo độ ẩm không khí.
   - *Đơn vị*: Phần trăm (`%`).
   - *Ngưỡng màu*: Đỏ (<40%: không khí quá khô, cảnh báo), Xanh (≥40%: bình thường).
3. **Soil Moisture (`SEN-003`)**:
   - *Mục đích*: Đo độ ẩm của đất canh tác.
   - *Đơn vị*: Phần trăm (`%`).
   - *Ngưỡng màu*: Đỏ (<30%: đất khô, kích hoạt bơm tưới), Xanh (30–35%: khoảng duy trì), Lam (>35%: đất đủ ẩm, tắt bơm).

### Nhóm 2: Biến động Dữ liệu theo Thời gian (Trends & History)
4. **Temperature Trend**:
   - Biểu đồ thời gian (Time-series) hiển thị diễn biến nhiệt độ liên tục theo Measurement Timestamp.
   - Kèm đường ngưỡng cảnh báo màu đỏ cố định tại mức **35°C**.
5. **Soil Moisture Trend**:
   - Biểu đồ thời gian hiển thị chu kỳ khô dần của đất và sự phục hồi khi máy bơm hoạt động.
   - Kèm 2 đường ngưỡng hysteresis: **30%** (ngưỡng bật bơm) và **35%** (ngưỡng tắt bơm).

### Nhóm 3: Trạng thái Hệ thống & Vận hành (System Operations)
6. **Sensor Status**:
   - Hiển thị danh sách cả 3 cảm biến (`SEN-001`, `SEN-002`, `SEN-003`), giá trị mới nhất, thời gian đo và trạng thái hoạt động:
     - 🟢 **ONLINE**: Có bản tin gửi về trong vòng dưới 30 giây.
     - 🟡 **STALE**: Không có bản tin từ 30 đến dưới 60 giây.
     - 🔴 **OFFLINE**: Quá 60 giây không nhận được dữ liệu.
7. **Pump Status (Máy bơm ảo)**:
   - Hiển thị trực quan trạng thái của máy bơm tưới nước:
     - 🟢 **ON (ĐANG TƯỚI)**: Khi độ ẩm đất < 30%.
     - 🔵 **OFF (NGỪNG TƯỚI)**: Khi độ ẩm đất > 35%.
     - 🟠 **HOLD (DUY TRÌ)**: Khi độ ẩm đất đang nằm trong dải 30% – 35%.
8. **Sync Status (Đồng bộ dữ liệu)**:
   - Thống kê các chỉ số:
     - **Đã đồng bộ (`STORED`)**: Số lượng bản ghi đã được lưu bền vững vào cả PostgreSQL và InfluxDB.
     - **Chờ Influx (`PENDING`)**: Bản ghi đã vào ledger nhưng đang chờ ghi sang time-series.
     - **Bị từ chối (`REJECTED`)**: Số lượng gói tin không hợp lệ bị cách ly để phục vụ kiểm tra lỗi.

### Nhóm 4: Lịch sử Cảnh báo Môi trường (Alert History)
9. **Alert History**:
   - Bảng tổng hợp tất cả các sự kiện vượt ngưỡng được trích xuất từ cơ sở dữ liệu:
     - Cột hiển thị: Event ID, Thời gian (UTC), Mã cảm biến, Loại cảnh báo (`Nhiệt độ cao`, `Độ ẩm thấp`, `Độ ẩm đất thấp`), Mức độ nghiêm trọng (`HIGH`, `WARNING`), Giá trị đo thực tế.

---

## 4. Hướng dẫn Vận hành & Nghiệm thu

### 4.1. Nạp dữ liệu thực tế / Demo
Chạy script sinh dữ liệu đo lường thực tế để kiểm chứng khả năng hiển thị của Dashboard:

```bash
# Nạp 15 phút dữ liệu mô phỏng liên tục:
python scripts/generate_dashboard_demo_data.py --minutes 15 --step 15
```

### 4.2. Lọc thời gian và Tự động làm mới (Auto Refresh)
- Ở góc trên bên phải của Grafana Dashboard:
  - Chọn khoảng thời gian quan sát (ví dụ: `Last 5 minutes`, `Last 15 minutes`, `Last 1 hour`).
  - Chọn chu kỳ tự động cập nhật: `5s`, `10s` hoặc `30s`. Khi có luồng dữ liệu mới từ Edge Gateway hoặc Sensor Simulator đẩy lên, các panel sẽ tự động cập nhật biểu đồ và giá trị tức thời.

### 4.3. Xuất & Nhập file cấu hình Dashboard JSON
- File cấu hình Dashboard JSON được lưu trữ phiên bản tại:
  `infrastructure/grafana/dashboards/smart_agriculture_dashboard.json`
- Khi cần xuất thủ công từ giao diện Grafana:
  1. Vào Dashboard Settings (biểu tượng bánh răng ⚙️ ở góc phải).
  2. Chọn mục **JSON Model**.
  3. Nhấn **Copy to Clipboard** hoặc lưu thành file.
