# Kết quả kiểm thử Task 2 và Task 2.1

Ngày thực hiện: 10/11/2026. Môi trường kiểm thử: Windows, Python 3.13.6, Paho MQTT 2.2.0, pytest 9.2.0, Docker Desktop/Linux containers, Eclipse Mosquitto 2.0.22. Môi trường mục tiêu Python 3.12 trên Linux chưa được chạy trong phiên này.

**Kết quả mới nhất của Task 2.1: 102 passed, 1 skipped (103 tests), không có warning.** Xem bảng nghiệm thu Task 2.1 ở cuối tài liệu, [log đầy đủ](task21-test-output.txt) và [bằng chứng sensor health](edge-health-evidence.json). Các kết quả 26/51 tests bên dưới là các lần kiểm thử ở giai đoạn trước.

## Kết quả thực tế

**26 passed**: 7 bài kiểm thử Task 1 và 19 bài Task 2, trong đó có 3 integration tests kết nối với Mosquitto thật. Không có test bị bỏ qua khi bật cả hai biến `RUN_MQTT_INTEGRATION=1` và `RUN_MQTT_RESTART=1`.

| Tiêu chuẩn | Bằng chứng | Kết quả |
|---|---|---|
| Broker hoạt động | Docker Compose `up -d --wait` báo healthy; client kết nối thành công | Đạt |
| Ba cảm biến publish | Chạy CLI `main.py --interval 0.1 --count 2`, subscriber nhận 6 bản đo, sequence 1 và 2 ở từng topic | Đạt |
| Subscriber nhận đúng topic | Integration test đối chiếu tập ba topic, sensor_id và event_id đã gửi | Đạt |
| Payload đúng định dạng | Kiểm tra schema sáu trường; từ chối JSON hỏng, thiếu trường, timestamp lỗi, NaN, sequence không hợp lệ | Đạt |
| Phân biệt cảm biến | Đối chiếu sensor_id và unit với topic, từ chối định danh/đơn vị sai | Đạt |
| OFFLINE không sinh dữ liệu giả | Chuyển cả ba cảm biến OFFLINE sau khi đã nhận PUBACK, không nhận bản đo tiếp trong cửa sổ quan sát 1 giây | Đạt |
| Không phát lại bản đo cũ cho client mới | Subscriber mới đăng ký sau khi đã publish, không nhận bản retained trong cửa sổ quan sát 1 giây | Đạt |
| QoS 1 | Publish và subscribe QoS 1, subscriber thực nhận qos=1; publisher đợi PUBACK | Đạt |
| Mất kết nối và phục hồi | Dừng broker bằng Compose, cả hai client phát hiện DISCONNECTED; bản đo lúc ngắt bị log SKIPPED_DISCONNECTED; start broker, tự kết nối/subscribe lại và nhận đủ ba topic | Đạt |
| PUBACK lỗi/quá hạn | Unit tests giả lập lỗi trả về, timeout và exception; không báo PUBLISHED thành công | Đạt |

## Bằng chứng và tái hiện

- [mqtt-evidence.jsonl](mqtt-evidence.jsonl): ba bản tin thực nhận từ broker, chứa topic, QoS, thời điểm nhận và nguyên payload.
- [mqtt-test-output.txt](mqtt-test-output.txt): log đầy đủ của lần chạy 26 tests, gồm disconnect/reconnect thực tế. Các test dùng mock được ghi rõ theo tên test, tách với ba test có tiền tố `test_live_`.
- [mqtt.md](mqtt.md): lệnh cài đặt, chạy, kiểm thử tự động, demo bằng mosquitto_sub/pub và các giới hạn.

Lần kiểm thử MQTT ban đầu có một `PytestCacheWarning` do quyền ghi `.pytest_cache` khi chạy qua môi trường cấp quyền; không ảnh hưởng assertion hay kết quả MQTT. Kết quả mở rộng SQLite và xử lý Edge nằm bên dưới. Chưa chạy kiểm thử tải, TLS/authentication hoặc đồng bộ Server. Task 2 không đảm bảo giữ bản đo mới trong thời gian broker ngừng hoạt động.

## Task 2 mở rộng — Edge Gateway, SQLite và xử lý khi không có Server

Kết quả ở giai đoạn bổ sung Edge ban đầu: **51 passed, 1 skipped**, tổng cộng 52 tests. Có thêm 26 tests Edge (25 kiểm thử cục bộ và 1 bài tích hợp chạy Edge bằng tiến trình riêng qua Mosquitto thật). Test restart broker của phần MQTT được bỏ qua trong lần chạy này để tránh ngắt broker đang demo; lần chạy trước đã đạt và log còn trong `mqtt-test-output.txt`.

| Tiêu chí mở rộng | Bằng chứng | Kết quả |
|---|---|---|
| Nhận → kiểm tra → lưu → xử lý độc lập Server | Edge process kết nối Mosquitto; địa chỉ Server dùng cổng được giữ nhưng không có listener; vẫn ghi dữ liệu, cảnh báo và bơm | Đạt |
| SQLite lưu bền vững | WAL, synchronous FULL; ép tắt Edge process rồi đọc lại database và khởi động lại | Đạt |
| Giữ bản ghi chờ đồng bộ | Trước restart có 3 PENDING, sau restart và gửi thêm có 5 PENDING, SYNCED vẫn bằng 0 | Đạt |
| Cảnh báo cục bộ | Temperature 40°C, humidity 35% tạo HIGH_TEMPERATURE và LOW_HUMIDITY | Đạt |
| Bơm ảo và hysteresis | Soil 20% bật ON; khởi động lại vẫn ON; 32% giữ ON; 40% chuyển OFF; kiểm tra thêm biên 30% và 35% | Đạt |
| Chống trùng và xung đột ID | Payload trùng không lặp dữ liệu/tác động; cùng ID nhưng payload khác bị quarantine | Đạt |
| Dữ liệu lỗi có bằng chứng | JSON hỏng, sai trường/đơn vị/ID, ngoài dải, NaN/Infinity, thời gian sai, retained và quá kích thước đều được quarantine | Đạt |
| ACK sau commit | Tại thời điểm client.ack được gọi, kết nối SQLite khác đã đọc được cả telemetry và trạng thái bơm | Đạt |
| Lỗi lưu trữ không ACK | Giả lập lỗi ổ đĩa giữa giao dịch: rollback dữ liệu/tác động, ngắt MQTT và không ACK | Đạt |
| Dữ liệu cũ không đảo bơm | Lưu PENDING nhưng không điều khiển/cảnh báo theo bản đo quá cũ hoặc ngược thứ tự | Đạt |
| Demo CLI thực tế | Chạy edge_demo.py qua broker: thêm 5 bản hợp lệ, 2 cảnh báo, 2 lần chuyển bơm, 1 quarantine; bản gửi lại được nhận là DUPLICATE | Đạt |

Bằng chứng mới: [edge-evidence.json](edge-evidence.json), [edge-test-output.txt](edge-test-output.txt), hướng dẫn [edge.md](edge.md).

Kiểm thử chạy trên Windows/Python 3.13.6; bước kiểm thử crash/WAL dùng quyền ngoài sandbox và thư mục tạm riêng trong workspace để tránh vấn đề quyền file Temp của môi trường agent. Đây là kiểm thử crash tiến trình, không phải thử mất điện vật lý. Chưa chạy trên Linux/Python 3.12.

Giai đoạn này hoàn thành lưu SQLite tại Edge, ngưỡng/cảnh báo/bơm ảo và kiểm thử xử lý cục bộ không cần Server. Ở thời điểm đó chưa có Sensor Health Monitor hay API cập nhật SYNCED; các phần này đã được bổ sung trong Task 2.1 bên dưới.

## Nghiệm thu Task 2.1 hoàn chỉnh

Lần chạy mới nhất: **102 passed, 1 skipped trong 14.70 giây**, gồm 4 integration tests đã chạy qua Mosquitto thật. Test duy nhất được bỏ qua là `test_live_broker_restart_recovers` để không dừng broker đang demo; đã có bằng chứng đạt ở giai đoạn MQTT trước.

| Trạng thái | Tiêu chuẩn nghiệm thu | Bằng chứng |
|---|---|---|
| ✅ | Edge nhận được dữ liệu từ cả ba cảm biến | MQTT thật → tiến trình Edge → SQLite, đối chiếu sensor_id |
| ✅ | Phân loại dữ liệu hợp lệ/không hợp lệ | NORMAL/ANOMALY lưu telemetry; INVALID lưu quarantine; kiểm tra cả nhiệt độ thấp nhưng còn trong dải vật lý |
| ✅ | Lưu dữ liệu vào SQLite | Giao dịch commit; tồn tại sau crash và khởi động lại Edge |
| ✅ | Nhiệt độ vượt 35°C | HIGH_TEMPERATURE; giá trị đúng 35°C không phát cảnh báo này |
| ✅ | Độ ẩm không khí dưới 40% | LOW_HUMIDITY; đúng 40% không phát cảnh báo này |
| ✅ | Bơm bật khi độ ẩm đất dưới 30% | Soil 20%/29% chuyển ON |
| ✅ | Bơm tắt khi độ ẩm đất trên 35% | Soil 40%/36% chuyển OFF, giữ trạng thái tại 30%/35% và trong khoảng |
| ✅ | Phát hiện cảm biến không gửi dữ liệu | Timer thực chuyển ONLINE → STALE → OFFLINE khi không có bản tin mới; gửi lại bản đo mới phục hồi ONLINE |
| ✅ | Xử lý khi Server không hoạt động | MQTT, kiểm tra, SQLite, cảnh báo, bơm và health không phụ thuộc một Server đang chạy |

Các bổ sung đã kiểm chứng:

- Có `sensor_health.py`; cấu hình mặc định STALE=30s, OFFLINE=60s, kiểm tra mỗi 1s. Unit tests kiểm tra chính xác hai biên; integration test dùng 0.8s/1.6s để chạy nhanh, có log và snapshot SQLite tại từng trạng thái.
- Bản trùng event_id, dữ liệu lỗi và retained không gia hạn ONLINE; cảm biến chưa từng gửi không bị báo ONLINE giả. Health và lịch sử chuyển trạng thái lưu SQLite, được giữ sau khi mở lại database.
- `pending_batch()` chỉ đọc; `mark_synced()` chỉ chuyển các ID được Server xác nhận thuộc batch đã gửi. Kiểm tra ACK một phần, ACK lặp, ACK thiếu, sai ID, sai thời gian và giữ trạng thái sau mở lại SQLite. Đây là kiểm thử API lưu trữ cục bộ, không phải kiểm thử REST API Server.
- Nâng cấp schema database cũ tại chỗ: giữ payload gốc và PENDING, bổ sung classification, synced_at và các bảng health.
- Database mặc định đã được tạo tại `edge-gateway/edge.db`, đúng đầu ra bàn giao; `--status` hoạt động. Database là dữ liệu runtime, không commit lên Git.
- Hướng dẫn và checklist được cập nhật trong [edge.md](edge.md) và [README Edge](../edge-gateway/README.md).

Bằng chứng: [task21-test-output.txt](task21-test-output.txt), [edge-health-evidence.json](edge-health-evidence.json), [edge-evidence.json](edge-evidence.json).

**Task 2.1 đáp ứng 9/9 tiêu chuẩn trên môi trường đã kiểm thử.** HTTP sync worker, ACK từ Server thật và kiểm thử phục hồi uplink Edge–Server vẫn thuộc bước tích hợp Task 3; không tự đánh dấu SYNCED chỉ vì Edge đã nhận MQTT.
