# Task 6 & Tiêu Chuẩn Nghiệm Thu KT3: Cơ Chế Lưu Đệm và Đồng Bộ Dữ Liệu Khi Mất Kết Nối

Tài liệu đặc tả kiến trúc, cơ chế hoạt động, hướng dẫn vận hành và kết quả kiểm thử cho **Task 6: Xây dựng cơ chế lưu đệm và đồng bộ dữ liệu khi mất kết nối** (Tiêu chuẩn nghiệm thu KT3).

---

## 1. Mục tiêu & Ý nghĩa Kiến trúc

Trong mô hình **Edge Computing**, đường truyền mạng giữa biên (Edge Gateway) và trung tâm (Central Server) không đảm bảo liên tục 100%. Khi kết nối mạng bị gián đoạn:
- **Tính tự chủ (Edge Autonomy)**: Edge Gateway phải tiếp tục thu thập dữ liệu từ cảm biến qua MQTT QoS 1, lưu trữ bền vững tại cơ sở dữ liệu cục bộ SQLite, thực hiện phân tích ngưỡng (Threshold Engine) và điều khiển máy bơm nước ảo (Virtual Pump Controller) độc lập, không bị phụ thuộc vào Server.
- **Tính toàn vẹn (Fault Tolerance & Zero Data Loss)**: Toàn bộ bản ghi đo đạc phát sinh trong thời gian mất mạng phải được đánh dấu trạng thái `PENDING`.
- **Tự động phục hồi (Automatic Synchronization & Recovery)**: Khi mạng được khôi phục, Sync Manager tự động phát hiện, gửi dữ liệu theo batch qua HTTP REST API, nhận ACK xác nhận từ Server và chuyển trạng thái bản ghi sang `SYNCED`.
- **Chống trùng lặp (Idempotency & Duplicate Prevention)**: Mỗi sự kiện mang một `event_id` duy nhất (`EVT-...`). Khi xảy ra truyền lại (retry) do mất gói tin phản hồi trên đường truyền, Server nhận diện trùng lặp, trả ACK mà không tạo bản ghi logic trùng lặp trong cơ sở dữ liệu (PostgreSQL/InfluxDB).
- **Cơ chế Retry & Exponential Backoff**: Xử lý timeout và lỗi kết nối mạng với thuật toán lùi thời gian cấp số nhân để tránh gây quá tải hệ thống khi mạng chập chờn.

---

## 2. Luồng Dữ liệu & Kiến trúc Đồng bộ (Data Flow)

```mermaid
flowchart TD
    subgraph SENSORS ["Sensor Simulators (IoT Field)"]
        S1["SEN-001 (Temperature)"]
        S2["SEN-002 (Humidity)"]
        S3["SEN-003 (Soil Moisture)"]
    end

    subgraph MQTT_BROKER ["Local MQTT Broker"]
        MB["Mosquitto (Port 1883)"]
    end

    subgraph EDGE ["Edge Gateway (Local Edge Device)"]
        EG["EdgeGateway (MQTT Subscriber)"]
        VAL["Data Validator & Classifier"]
        TH["Threshold & Pump Controller"]
        DB[("SQLite Local Buffer (edge.db)\n• PENDING / SYNCED\n• WAL Mode & Full Sync")]
        SM["Sync Manager (Background Worker)\n• Exponential Backoff\n• Batch Partitioning (1-1000)"]
    end

    subgraph SIMULATOR ["Network Simulator"]
        NC["Connection Controller\n(ONLINE / OFFLINE / TIMEOUT / 503)"]
    end

    subgraph SERVER ["Central Server API & Storage"]
        API["FastAPI (/api/v1/telemetry/batch)"]
        PG[("PostgreSQL\n(ingested_events ledger)")]
        INF[("InfluxDB v2\n(sensor_readings time-series)")]
    end

    S1 -->|MQTT QoS 1| MB
    S2 -->|MQTT QoS 1| MB
    S3 -->|MQTT QoS 1| MB
    MB -->|Deliver| EG
    EG --> VAL
    VAL -->|Valid| TH
    TH -->|Atomic Transaction| DB
    DB -.->|Query PENDING batch| SM
    SM -->|HTTP POST| NC
    NC -->|When ONLINE| API
    NC -.->|When OFFLINE: Drop / Refuse| SM
    API -->|Persist Ledger| PG
    API -->|Write Time-series| INF
    API -->|Return ACK (acknowledged_event_ids)| SM
    SM -->|Update to SYNCED| DB
```

---

## 3. Cấu trúc Thư mục và Các Thành phần Bàn giao

```text
edge-gateway/
├── buffer_manager.py        # Quản lý SQLite WAL, phân biệt PENDING/SYNCED, truy vấn batch, cập nhật ACK
├── sync_manager.py          # HTTP REST API batch sync worker, retry & exponential backoff, lifecycle
├── mqtt_client.py           # Nhận telemetry MQTT QoS 1 và điều phối lưu đệm
├── data_validator.py        # Kiểm tra schema, dải đo vật lý và phân loại NORMAL/ANOMALY/INVALID
├── threshold_engine.py      # Đánh giá cảnh báo nhiệt độ cao, độ ẩm thấp
├── device_controller.py     # Hysteresis điều khiển máy bơm ảo (ON khi <30%, OFF khi >35%)
├── edge_config.yaml         # Cấu hình ngưỡng, dải đo và thông số sync (batch_size, backoff, URLs)
├── settings.py              # Load & validate cấu hình an toàn
└── main.py                  # Entrypoint khởi chạy Edge Gateway tích hợp Sync Manager tự động

network-simulator/
├── connection_controller.py # Bộ điều khiển mô phỏng trạng thái kết nối mạng (ONLINE, OFFLINE, TIMEOUT, 503, LATENCY)
└── scenarios.py             # Kịch bản kiểm thử tự động mô phỏng mất kết nối, phục hồi và nghiệm thu KT3

tests/
├── test_kt3.py              # Suite 8 bài kiểm thử nghiệm thu toàn diện cho KT3
├── test_buffer_sync.py      # Kiểm thử tầng lưu đệm, schema upgrade và ACK semantics
└── ...

docs/
├── kt3-evidence.json        # Bằng chứng kiểm thử tự động trước và sau khi khôi phục mạng
├── kt3-test-output.txt      # Log chi tiết thực thi test suite nghiệm thu KT3
└── task6-buffer-sync.md     # Tài liệu này
```

---

## 4. Chi tiết Kỹ thuật

### A. Local Buffer Management (`buffer_manager.py`)
- Cơ sở dữ liệu SQLite cấu hình ở chế độ `PRAGMA journal_mode=WAL` và `PRAGMA synchronous=FULL` để đảm bảo an toàn sau sự cố mất điện (power cut).
- Cột `sync_status` với ràng buộc `CHECK(sync_status IN ('PENDING', 'SYNCED'))`.
- Khi bản ghi mới được lưu qua hàm `store()`, trạng thái mặc định luôn là `PENDING`.
- Hàm `pending_batch(limit=100)` trích xuất danh sách các bản ghi chưa được đồng bộ theo thứ tự thời gian (`ORDER BY received_at, event_id LIMIT ?`).
- Hàm `mark_synced(acknowledged_event_ids, sent_event_ids=...)` nhận diện chính xác danh sách các ID đã được Server xác nhận (ACK). Kiểm tra nghiêm ngặt `acknowledged <= sent` và đảm bảo tính nhất quán (ACID transaction).

### B. Sync Manager (`sync_manager.py`)
- Kiểm tra tính sẵn sàng của Server qua `GET /api/v1/health`.
- Gom nhóm dữ liệu theo từng batch (mặc định 100 bản ghi, tối đa 1.000 bản ghi) và gửi qua `POST /api/v1/telemetry/batch`.
- Đọc `acknowledged_event_ids` từ phản hồi của Server và cập nhật cục bộ sang `SYNCED`.
- Hỗ trợ cả 3 chế độ vận hành:
  1. **Thread nền (Background Worker)**: Tự động chạy song song trong Edge Gateway, liên tục kiểm tra và đồng bộ khi có dữ liệu.
  2. **Đồng bộ một lần (`--once`)**: Dọn sạch bộ đệm theo yêu cầu hoặc trong scripts kiểm thử.
  3. **Kiểm tra trạng thái (`--status`)**: Xuất thống kê chi tiết dưới định dạng JSON.

### C. Retry Mechanism & Exponential Backoff
- Bắt và xử lý các ngoại lệ mạng:
  - `requests.exceptions.Timeout`: Quá thời gian chờ phản hồi từ Server.
  - `requests.exceptions.ConnectionError`: Mất kết nối mạng, Server tắt nguồn hoặc từ chối kết nối.
  - HTTP `502`, `503`, `504`: Server đang khởi động lại hoặc cơ sở dữ liệu tạm thời gián đoạn. Tuân thủ header `Retry-After`.
- Thuật toán Exponential Backoff:
  $$T_{backoff} = \min\left(T_{max}, T_{initial} \cdot f^{N - 1}\right)$$
  - $T_{initial} = 1.0\text{s}$, Hệ số nhân $f = 2.0$, $T_{max} = 30.0\text{s}$.
  - Sau mỗi lần gửi thất bại liên tiếp ($N$), thời gian chờ tăng gấp đôi: $1\text{s} \to 2\text{s} \to 4\text{s} \to 8\text{s} \to 16\text{s} \to 30\text{s}$.
  - Khi gửi thành công một batch, $N$ được đặt lại về 0 và $T_{backoff}$ phục hồi về $T_{initial}$ ngay lập tức.

### D. Duplicate Prevention (Chống Trùng Lặp)
- Mỗi bản ghi mang trường `event_id` duy nhất dạng `EVT-[A-Z0-9]{12}` phát sinh từ UUID4.
- Trong trường hợp Edge gửi dữ liệu lên Server thành công, nhưng gói tin phản hồi HTTP 200 bị thất lạc trên đường truyền mạng:
  - Edge sẽ thực hiện retry gửi lại batch chứa cùng các `event_id`.
  - Server tra cứu trong bảng `ingested_events` của PostgreSQL: phát hiện bản ghi đã tồn tại với cùng nội dung, tăng chỉ số `duplicates`, không ghi đè point mới vào InfluxDB, đồng thời đưa `event_id` vào danh sách `acknowledged_event_ids`.
  - Edge nhận được ACK và cập nhật bản ghi thành `SYNCED`.
  - Kết quả: Không bao giờ xảy ra tình trạng trùng lặp dữ liệu trên Server hoặc mất dữ liệu tại Edge.

### E. Network Simulator & Kịch bản Kiểm thử (`connection_controller.py` & `scenarios.py`)
- Cung cấp cơ chế mô phỏng mất kết nối:
  - Cắt đường truyền Edge $\to$ Server (`disconnect`, `set_timeout_mode`, `set_server_error_mode`).
  - Đường truyền Cảm biến $\to$ Edge qua Mosquitto MQTT hoàn toàn độc lập và không bị ảnh hưởng.
  - Phục hồi kết nối (`connect`).
- Script `scenarios.py` tự động hóa toàn diện 3 kịch bản lớn và xuất bằng chứng nghiệm thu ra `docs/kt3-evidence.json`.

---

## 5. Hướng Dẫn Vận Hành & Tái Hiện Kiểm Thử

### Bước 1: Chạy toàn bộ Test Suite với Pytest
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_kt3.py -v
```
**Kết quả**: 8/8 bài kiểm thử nghiệm thu KT3 vượt qua (100% Passed).

### Bước 2: Chạy Kịch bản Mô phỏng Mạng (Network Simulation Scenarios)
```powershell
.\.venv\Scripts\python.exe network-simulator/scenarios.py --scenario all --evidence docs/kt3-evidence.json
```
**Kết quả tóm tắt**:
```json
{
  "offline_recovery": {
    "status": "PASSED",
    "scenario": "server_offline_and_sync_recovery",
    "events_tested": 5,
    "offline_pending": 5,
    "post_sync_pending": 0,
    "post_sync_synced": 5,
    "alerts_triggered": 2,
    "pump_actions": 2
  },
  "duplicate": {
    "status": "PASSED",
    "scenario": "duplicate_prevention",
    "server_duplicates_detected": 1
  },
  "backoff": {
    "status": "PASSED",
    "scenario": "retry_exponential_backoff",
    "backoff_progression": [1.0, 2.0, 4.0, 8.0],
    "reset_backoff": 1.0
  }
}
```

### Bước 3: Vận hành Trực tiếp trên Hệ thống Thực tế
1. Khởi động Docker containers (Mosquitto, PostgreSQL, InfluxDB, Server API):
   ```powershell
   docker compose --env-file .env -f infrastructure/docker-compose.yml up -d --wait
   ```
2. Khởi chạy Edge Gateway với tính năng đồng bộ tự động:
   ```powershell
   .\.venv\Scripts\python.exe edge-gateway/main.py
   ```
3. Khởi chạy mô phỏng cảm biến phát sinh dữ liệu liên tục:
   ```powershell
   .\.venv\Scripts\python.exe sensor-simulator/main.py --interval 2 --count 10
   ```
4. Ngắt kết nối Server (mô phỏng mất mạng):
   ```powershell
   .\.venv\Scripts\python.exe network-simulator/connection_controller.py --disconnect
   ```
5. Kiểm tra trạng thái Edge: Dữ liệu vẫn được thu thập và tích lũy tại trạng thái `PENDING`:
   ```powershell
   .\.venv\Scripts\python.exe edge-gateway/main.py --status
   ```
6. Khôi phục kết nối Server:
   ```powershell
   .\.venv\Scripts\python.exe network-simulator/connection_controller.py --connect
   ```
7. Quan sát Sync Manager tự động đẩy toàn bộ dữ liệu, chuyển sang `SYNCED` và số lượng `PENDING` trở về 0.

---

## 6. Đối Chiếu Tiêu Chuẩn Nghiệm Thu KT3

| STT | Tiêu chuẩn nghiệm thu | Hiện thực & Minh chứng | Kết quả |
|---|---|---|---|
| 1 | Khi Server offline, Edge vẫn nhận dữ liệu | MQTT Subscriber tiếp tục nhận telemetry từ Mosquitto QoS 1 | **ĐẠT** |
| 2 | Edge vẫn lưu dữ liệu vào SQLite | Ghi nhận trong bảng `telemetry`, journal WAL an toàn | **ĐẠT** |
| 3 | Edge vẫn xử lý threshold và điều khiển máy bơm ảo | Cảnh báo lưu vào `alerts`, trạng thái bơm lưu vào `device_state` & `device_actions` | **ĐẠT** |
| 4 | Các bản ghi chưa đồng bộ có trạng thái PENDING | Kiểm tra `sync_status = 'PENDING'` trong mọi bản ghi đo offline | **ĐẠT** |
| 5 | Khi Server online trở lại, Edge tự động gửi dữ liệu | Sync Manager worker phát hiện server online và gửi batch qua REST API | **ĐẠT** |
| 6 | Chỉ đánh dấu SYNCED sau khi nhận ACK hợp lệ | `mark_synced()` kiểm tra `acknowledged_event_ids` khớp với `sent_event_ids` | **ĐẠT** |
| 7 | Không mất bản ghi đã được lưu thành công tại Edge | Số lượng bản ghi `total` trước và sau phục hồi không đổi | **ĐẠT** |
| 8 | Không tạo bản ghi logic trùng trên Server | Idempotency kiểm soát theo `event_id`, duplicates được nhận diện và ACK | **ĐẠT** |
| 9 | Sau khi đồng bộ hoàn tất, số bản ghi PENDING bằng 0 | Xác thực `pending == 0` và `synced == total` sau khi flush toàn bộ | **ĐẠT** |
