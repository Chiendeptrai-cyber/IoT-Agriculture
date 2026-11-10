# Kết quả kiểm thử Task 2 — MQTT

Ngày thực hiện: 10/11/2026. Môi trường kiểm thử: Windows, Python 3.13.6, Paho MQTT 2.2.0, pytest 9.2.0, Docker Desktop/Linux containers, Eclipse Mosquitto 2.0.22. Môi trường mục tiêu Python 3.12 trên Linux chưa được chạy trong phiên này.

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

Lần kiểm thử đầy đủ có một `PytestCacheWarning` do quyền ghi `.pytest_cache` khi chạy qua môi trường cấp quyền; không ảnh hưởng assertion hay kết quả MQTT. Chưa chạy kiểm thử tải, TLS/authentication, lưu SQLite, xử lý Edge hoặc đồng bộ Server. Task 2 không đảm bảo giữ bản đo mới trong thời gian broker ngừng hoạt động.
