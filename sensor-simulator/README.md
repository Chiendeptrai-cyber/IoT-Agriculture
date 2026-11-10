# IoT Sensor Simulator (Task 1)

Hệ thống mô phỏng 3 cảm biến môi trường IoT phục vụ thu thập và sinh dữ liệu chuỗi thời gian (time-series) cho hệ thống IoT.

---

## 1. Cấu trúc thư mục bàn giao

```text
sensor-simulator/
├── temperature.py          # Mô phỏng cảm biến nhiệt độ SEN-001
├── humidity.py             # Mô phỏng cảm biến độ ẩm không khí SEN-002
├── soil_moisture.py        # Mô phỏng cảm biến độ ẩm đất SEN-003
├── simulator_config.yaml   # Tệp cấu hình các thông số và ngưỡng mô phỏng
├── sensor_base.py          # Lớp cơ sở (BaseSensor), Enum chế độ và JSON Schema validation
├── main.py                 # Điều phối chạy đồng thời cả 3 cảm biến & kịch bản demo
├── requirements.txt        # Các thư viện phụ thuộc (PyYAML, jsonschema, pytest)
└── README.md               # Tài liệu hướng dẫn chi tiết
```

---

## 2. Thiết kế JSON Schema chung

Tất cả các sự kiện phát ra từ bất kỳ cảm biến nào đều tuân thủ chặt chẽ định dạng JSON Schema chuẩn:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "SensorEvent",
  "type": "object",
  "required": ["event_id", "sensor_id", "timestamp", "sequence", "value", "unit"],
  "properties": {
    "event_id": {
      "type": "string",
      "pattern": "^EVT-[A-Za-z0-9_-]+$",
      "description": "Mã định danh duy nhất của mỗi sự kiện (không bao giờ trùng lặp)"
    },
    "sensor_id": {
      "type": "string",
      "pattern": "^SEN-[0-9]{3}$",
      "description": "Mã định danh của cảm biến (ví dụ: SEN-001)"
    },
    "timestamp": {
      "type": "string",
      "format": "date-time",
      "description": "Thời gian theo chuẩn ISO 8601 với múi giờ rõ ràng (ví dụ: 2026-11-10T14:45:30Z)"
    },
    "sequence": {
      "type": "integer",
      "minimum": 1,
      "description": "Số thứ tự tăng dần độc lập theo từng cảm biến"
    },
    "value": {
      "type": "number",
      "description": "Giá trị đo đạc mô phỏng"
    },
    "unit": {
      "type": "string",
      "description": "Đơn vị đo (C, %)"
    }
  },
  "additionalProperties": false
}
```

### Ví dụ dữ liệu đầu ra:
```json
{
  "event_id": "EVT-FCC52D3B3229",
  "sensor_id": "SEN-001",
  "timestamp": "2026-11-10T14:45:30Z",
  "sequence": 1,
  "value": 29.49,
  "unit": "C"
}
```

---

## 3. Cách hoạt động của từng cảm biến

Dữ liệu không phải là các giá trị ngẫu nhiên rời rạc mà biến thiên liên tục theo thời gian dựa trên mô hình **Mean-Reverting Random Walk (Ornstein-Uhlenbeck process)**:
$$\Delta X_t = \theta \cdot (\mu - X_{t-1}) + \epsilon_t, \quad \epsilon_t \sim \mathcal{N}(0, \sigma^2)$$

Trong đó:
- $\mu$: Giá trị trung bình mục tiêu của môi trường.
- $\theta$: Hệ số hoàn nguyên (reversion speed).
- $\sigma$: Độ biến thiên vi khí hậu tức thời (drift std).

### 3.1. Cảm biến nhiệt độ (Temperature Sensor)
- **ID:** `SEN-001`
- **Đơn vị:** `C` (Độ C)
- **Chu kỳ gửi:** Mặc định `10` giây.
- **Dải đo bình thường (NORMAL):** 20.0°C – 40.0°C (quanh mức 29.0°C). Biến thiên mượt mà giữa các chu kỳ.
- **Hành vi bất thường (ANOMALY):**
  - Đột biến quá nhiệt (55.0°C – 85.0°C, mô phỏng nguy cơ cháy hoặc sự cố nguồn nhiệt).
  - Đột ngột đóng băng (-10.0°C – 5.0°C, lỗi đầu dò/mạch điện).
  - Bước nhảy nhiệt bất thường (> 18°C trong 1 chu kỳ).

### 3.2. Cảm biến độ ẩm không khí (Air Humidity Sensor)
- **ID:** `SEN-002`
- **Đơn vị:** `%`
- **Chu kỳ gửi:** Mặc định `10` giây.
- **Dải đo bình thường (NORMAL):** 40.0% – 95.0% (quanh mức 70.0%).
- **Hành vi bất thường (ANOMALY):**
  - Quá bão hòa độ ẩm (> 99.0% tới 110.0%, lỗi bão hòa hơi nước).
  - Rơi thẳng xuống mức khô hạn cực đoan (2.0% – 12.0%, đứt dây tín hiệu).
  - Bước nhảy đột ngột $\pm 30\% - 45\%$.

### 3.3. Cảm biến độ ẩm đất (Soil Moisture Sensor)
- **ID:** `SEN-003`
- **Đơn vị:** `%`
- **Chu kỳ gửi:** Mặc định `10` giây.
- **Dải đo bình thường (NORMAL):** 30.0% – 80.0% (quanh mức 55.0%). Độ ẩm đất có quán tính vật lý cao, biến thiên chậm ($\sigma = 0.2$).
- **Hành vi bất thường (ANOMALY):**
  - Ngập úng cực độ (96.0% – 100.0%, đầu dò chìm trong vũng nước ngập).
  - Rút khỏi đất hoặc hở mạch (0.0% – 5.0%).
  - Bước nhảy đột ngột $\pm 25\% - 40\%$.

---

## 4. Ba chế độ hoạt động (Modes)

1. **`NORMAL` (Bình thường):**
   - Dữ liệu biến thiên mượt mà xung quanh mức kỳ vọng.
   - Sequence tăng dần từng bước: $1, 2, 3, \dots$
2. **`ANOMALY` (Bất thường):**
   - Sinh các giá trị vượt ngưỡng thực tế hoặc bước nhảy lớn đột ngột.
   - Sequence tiếp tục tăng để đảm bảo tính liên tục của dữ liệu cảnh báo.
3. **`OFFLINE` (Mất kết nối / Ngừng hoạt động):**
   - Cảm biến ngừng phát dữ liệu telemetry (không phát sinh JSON event).
   - Sequence được đóng băng giữ nguyên trạng thái, khi chuyển lại NORMAL sẽ tiếp tục tăng từ giá trị cũ.

---

## 5. Hướng dẫn chạy và kiểm tra trực tiếp trên Terminal

### 5.1. Cài đặt môi trường
```bash
pip install -r sensor-simulator/requirements.txt
```

### 5.2. Chạy từng cảm biến riêng lẻ
Mỗi cảm biến có thể chạy độc lập, cho phép tùy biến chu kỳ và chế độ qua tham số dòng lệnh:

```bash
# Chạy cảm biến nhiệt độ SEN-001 (chu kỳ mặc định 10 giây)
python sensor-simulator/temperature.py

# Chạy với chu kỳ 1 giây, tạo 5 bản ghi kiểm thử
python sensor-simulator/temperature.py --interval 1 --count 5

# Kiểm tra chế độ ANOMALY
python sensor-simulator/temperature.py --mode ANOMALY --count 3

# Kiểm tra chế độ OFFLINE
python sensor-simulator/temperature.py --mode OFFLINE --count 2

# Chạy cảm biến độ ẩm không khí SEN-002
python sensor-simulator/humidity.py --interval 2 --count 5

# Chạy cảm biến độ ẩm đất SEN-003
python sensor-simulator/soil_moisture.py --interval 2 --count 5
```

### 5.3. Chạy toàn bộ hệ thống 3 cảm biến song song
Sử dụng script điều phối `main.py`:

```bash
# Chạy cả 3 cảm biến đồng thời mỗi 10 giây
python sensor-simulator/main.py

# Chạy với chu kỳ tùy chỉnh (ví dụ 2 giây)
python sensor-simulator/main.py --interval 2
```

### 5.4. Chạy kịch bản Demo chuyển đổi trạng thái tự động
Để kiểm chứng trực quan tiêu chuẩn chuyển đổi giữa `NORMAL -> ANOMALY -> OFFLINE -> NORMAL`:

```bash
python sensor-simulator/main.py --demo --interval 1
```

---

## 6. Kiểm thử tự động (Unit Test Suite)

Tất cả 8 tiêu chuẩn nghiệm thu được tự động kiểm thử bằng `pytest`:

```bash
python -m pytest tests/test_simulator.py -v
```

Kết quả kiểm thử:
- `test_three_sensors_distinct_ids`: Kiểm tra đủ 3 ID phân biệt (SEN-001, SEN-002, SEN-003).
- `test_json_schema_compliance`: Kiểm tra 100% tuân thủ JSON Schema.
- `test_timestamp_validity_and_timezone`: Kiểm tra định dạng thời gian ISO 8601 và múi giờ.
- `test_sequence_monotonic_increment`: Kiểm tra sequence tăng dần theo từng cảm biến.
- `test_mode_transitions_normal_anomaly_offline`: Kiểm tra chuyển đổi 3 chế độ.
- `test_no_duplicate_event_ids`: Kiểm tra sinh 1,500 sự kiện đảm bảo không trùng lặp `event_id`.
- `test_smooth_continuous_drift`: Kiểm tra tính liên tục theo chuỗi thời gian của dữ liệu.
