# Tính dung lượng và năng lực

## Tốc độ phát sinh

Giả định 3 sensor, mỗi sensor gửi 1 event sau mỗi 10 giây:

- 3 × 6 = 18 event/phút.
- 3 × 360 = 1.080 event/giờ.
- 3 × 8.640 = 25.920 event/ngày.
- Với chu kỳ liên tục 30 ngày: 777.600 event.

Nếu interval thay đổi, số event tỷ lệ nghịch với interval: sensor_count × 86.400 / interval_seconds.

## Đo trên Edge SQLite thật

Đo trong container edge-gateway ngày 16/11/2026 bằng scripts/task8_capacity_report.py trên volume /data/edge.db:

| Chỉ số | Kết quả quan sát |
| --- | ---: |
| Telemetry trong SQLite | 1.478 |
| SEN-001 / SEN-002 / SEN-003 | 488 / 474 / 516 |
| Pending / Synced | 0 / 1.478 |
| SQLite page size / page count | 4.096 B / 190 |
| Page allocation | 778.240 B |
| File chính / WAL / SHM đang hoạt động | 745.472 / 4.140.632 / 32.768 B |
| Tổng file SQLite đang hoạt động | 4.918.872 B |
| Page allocation trung bình mỗi telemetry | 526,55 B/event |
| JSON payload trung bình / lớn nhất | 139,78 / 168 B |
| Độ trễ nhận Edge đến SYNCED, mẫu | 1.478 |
| Mean / median / P95 / max sync delay | 2.852,20 / 2.247,92 / 4.910,69 / 121.457,86 ms |

WAL vẫn đang được sử dụng trong lúc simulator ghi dữ liệu; vì vậy tổng file hoạt động có thể lớn hơn file chính. Page allocation trên mỗi event được dùng cho phép chiếu tuyến tính, không coi WAL hiện thời là kích thước ổn định mỗi bản ghi. Độ trễ đo bao gồm thời gian chờ/retry nếu có, không phải benchmark thuần tốc độ HTTP.

## Phép chiếu 30 ngày

Dùng số đo SQLite 590,15 B/event:

- 777.600 × 526,55 ≈ 409.444.806 B, xấp xỉ 391 MiB cho page allocation telemetry.
- Dự phòng hệ số 2 cho chỉ mục, metadata, WAL và biến động: khoảng 819 MB (781 MiB); nên bố trí ít nhất 1 GiB cho volume Edge trong cấu hình mô phỏng 30 ngày.
- InfluxDB/PostgreSQL volume hiện đo lần lượt khoảng 34,3 MB và 65,9 MB, nhưng chưa thể ngoại suy thành định mức ổn định do có index, WAL, series cardinality và retention.

Đây là ước lượng theo dữ liệu mẫu chạy thực, không phải giới hạn cứng hoặc benchmark stress test. Bucket InfluxDB hiện không khai báo retention; dung lượng dài hạn cần chính sách dọn dữ liệu rõ ràng.

## Đo lại

Trên host khi file SQLite được mount sẵn: **python scripts/task8_capacity_report.py --db edge-gateway/edge.db**. Trong Compose: pipe scripts/task8_capacity_report.py vào **docker compose --env-file .env.example --profile normal exec -T edge-gateway python3 - --db /data/edge.db**. Script chỉ đọc database, không sửa dữ liệu.
