# Task 1: Sensor Simulator cho 3 cảm biến IoT

Xem tài liệu chi tiết và hướng dẫn sử dụng trong thư mục [`sensor-simulator/README.md`](file:///c:/Users/admin/Desktop/cnnt/sensor-simulator/README.md).

## Quick Start:
```bash
# Cài đặt thư viện:
pip install -r sensor-simulator/requirements.txt

# Chạy kịch bản demo kiểm thử 3 cảm biến & chuyển đổi chế độ:
python sensor-simulator/main.py --demo --interval 1

# Chạy hệ thống 3 cảm biến định kỳ mỗi 10s:
python sensor-simulator/main.py

# Chạy bộ unit test kiểm tra toàn bộ tiêu chuẩn nghiệm thu:
python -m pytest tests/test_simulator.py -v
```
