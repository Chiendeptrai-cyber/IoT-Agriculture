"""Acceptance Test Suite for Task 6 and Tiêu chuẩn nghiệm thu KT3:
Xây dựng cơ chế lưu đệm và đồng bộ dữ liệu khi mất kết nối.

Verifies:
1. Khi Server offline, Edge vẫn nhận dữ liệu từ cảm biến.
2. Edge vẫn lưu dữ liệu vào SQLite với sync_status='PENDING'.
3. Edge vẫn xử lý threshold và điều khiển máy bơm ảo độc lập.
4. Khi Server online trở lại, Edge tự động gửi dữ liệu theo batch.
5. Chỉ đánh dấu SYNCED sau khi nhận ACK hợp lệ từ Server.
6. Không mất bản ghi đã được lưu thành công tại Edge.
7. Không tạo bản ghi logic trùng trên Server (idempotency).
8. Sau khi đồng bộ hoàn tất, số bản ghi PENDING bằng 0.
9. Retry mechanism với exponential backoff khi gặp sự cố mạng hoặc timeout.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import uuid

import pytest
import requests
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "edge-gateway"))
sys.path.insert(0, str(ROOT / "sensor-simulator"))
sys.path.insert(0, str(ROOT / "network-simulator"))
sys.path.insert(0, str(ROOT))

from buffer_manager import BufferManager, database_status
from connection_controller import ConnectionController, ConnectionState, ConnectionSimulationAdapter
from mqtt_client import EdgeGateway
from server.database import build_engine
from server.main import Settings as ServerSettings, create_app
from server.models import IngestedEvent
from settings import load_config, sensor_routes
from sync_manager import SyncManager


class MockInfluxStore:
    def __init__(self):
        self.rows = []
        self.is_healthy = True

    def write(self, record, gateway_id, received_at):
        self.rows.append((record, gateway_id, received_at))

    def healthy(self):
        return self.is_healthy

    def close(self):
        pass


@pytest.fixture
def test_env(tmp_path):
    db_path = tmp_path / "test_kt3.db"
    buffer = BufferManager(db_path)
    config = load_config()

    controller = ConnectionController(state_file=tmp_path / ".sim_state.json")
    controller.connect()

    server_engine = build_engine("sqlite://")
    mock_influx = MockInfluxStore()
    server_settings = ServerSettings(
        _env_file=None,
        database_url="sqlite://",
        influx_url="http://mock-influx",
        influx_token="mock-token",
        influx_org="mock-org",
        influx_bucket="smart_agriculture",
    )
    server_app = create_app(settings=server_settings, engine=server_engine, influx_store=mock_influx)
    test_client = TestClient(server_app)
    test_client.__enter__()

    session = requests.Session()

    class TestClientAdapter(ConnectionSimulationAdapter):
        def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
            status = self.controller.status()
            state = status["state"]
            if state == ConnectionState.OFFLINE:
                raise requests.exceptions.ConnectionError(
                    f"Simulated network outage (Connection refused): {status['reason']}"
                )
            elif state == ConnectionState.TIMEOUT:
                raise requests.exceptions.Timeout(
                    f"Simulated network timeout: {status['reason']}"
                )
            elif state == ConnectionState.SERVER_ERROR:
                resp = requests.models.Response()
                resp.status_code = 503
                resp.reason = "Service Unavailable (Simulated)"
                resp.headers["Retry-After"] = "2"
                resp._content = b'{"detail": "Database unavailable (simulated)"}'
                return resp

            path = request.path_url
            headers = dict(request.headers)
            body = request.body

            if request.method == "POST":
                tc_resp = test_client.post(path, content=body, headers=headers)
            elif request.method == "GET":
                tc_resp = test_client.get(path, headers=headers)
            else:
                tc_resp = test_client.request(request.method, path, content=body, headers=headers)

            resp = requests.models.Response()
            resp.status_code = tc_resp.status_code
            resp.reason = tc_resp.reason_phrase
            resp._content = tc_resp.content
            resp.url = request.url
            resp.headers.update(tc_resp.headers)
            return resp

    adapter = TestClientAdapter(controller)
    session.mount("http://127.0.0.1:8000", adapter)
    session.mount("http://localhost:8000", adapter)

    sync_mgr = SyncManager(
        buffer=buffer,
        config=config,
        server_url="http://127.0.0.1:8000/api/v1/telemetry/batch",
        health_url="http://127.0.0.1:8000/api/v1/health",
        session=session,
        initial_backoff=1.0,
        max_backoff=16.0,
        backoff_factor=2.0,
    )
    gateway = EdgeGateway(buffer, config)

    yield {
        "buffer": buffer,
        "config": config,
        "controller": controller,
        "sync_manager": sync_mgr,
        "gateway": gateway,
        "mock_influx": mock_influx,
        "test_client": test_client,
        "server_engine": server_engine,
    }

    sync_mgr.stop()
    buffer.close()
    test_client.__exit__(None, None, None)
    server_engine.dispose()


def make_event(kind="temperature", value=29.5, seq=1):
    topic = f"farm/sensors/{kind}"
    sensor_id, unit = sensor_routes()[topic]
    return topic, {
        "event_id": f"EVT-{uuid.uuid4().hex[:12].upper()}",
        "sensor_id": sensor_id,
        "unit": unit,
        "value": float(value),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sequence": seq,
    }


def test_kt3_server_offline_edge_still_collects_and_evaluates_thresholds(test_env):
    """Tiêu chuẩn KT3.1, KT3.2, KT3.3, KT3.4:
    Khi Server offline:
    - Edge vẫn nhận dữ liệu từ cảm biến.
    - Edge vẫn lưu bản ghi vào SQLite.
    - Bản ghi chưa đồng bộ có sync_status='PENDING'.
    - Edge vẫn xử lý threshold và điều khiển máy bơm ảo.
    """
    buffer = test_env["buffer"]
    controller = test_env["controller"]
    gateway = test_env["gateway"]

    # 1. Server bị mất kết nối hoàn toàn
    controller.disconnect(reason="KT3: Server power cut")
    assert not controller.is_online()

    # 2. Cảm biến gửi dữ liệu tới Edge Gateway
    topic1, ev1 = make_event("temperature", 40.0, 1)  # Vượt ngưỡng cao 35°C
    topic2, ev2 = make_event("humidity", 35.0, 1)     # Dưới ngưỡng thấp 40%
    topic3, ev3 = make_event("soil_moisture", 25.0, 1) # Đất khô (< 30%) -> Bật bơm
    topic4, ev4 = make_event("soil_moisture", 38.0, 2) # Đất đủ ẩm (> 35%) -> Tắt bơm

    r1 = gateway.process(topic1, json.dumps(ev1).encode())
    r2 = gateway.process(topic2, json.dumps(ev2).encode())
    r3 = gateway.process(topic3, json.dumps(ev3).encode())
    r4 = gateway.process(topic4, json.dumps(ev4).encode())

    # 3. Kiểm tra lưu trữ và trạng thái PENDING
    assert r1["status"] == "STORED" and r1["sync_status"] == "PENDING"
    assert r2["status"] == "STORED" and r2["sync_status"] == "PENDING"
    assert r3["status"] == "STORED" and r3["sync_status"] == "PENDING"
    assert r4["status"] == "STORED" and r4["sync_status"] == "PENDING"

    status = database_status(buffer.path)
    assert status["total"] == 4
    assert status["pending"] == 4
    assert status["synced"] == 0

    # 4. Kiểm tra threshold và máy bơm ảo hoạt động độc lập tại Edge
    assert status["alerts"] == 2  # HIGH_TEMPERATURE and LOW_HUMIDITY
    assert status["device_actions"] == 2  # OFF->ON then ON->OFF
    assert status["pump"]["state"] == "OFF"


def test_kt3_server_recovery_automatic_sync_and_ack_processing(test_env):
    """Tiêu chuẩn KT3.5, KT3.6, KT3.7, KT3.9:
    Khi Server online trở lại:
    - Edge tự động gửi dữ liệu theo batch.
    - Chỉ đánh dấu SYNCED sau khi nhận ACK hợp lệ.
    - Không mất bản ghi đã lưu tại Edge.
    - Sau khi đồng bộ hoàn tất, số bản ghi PENDING bằng 0.
    """
    buffer = test_env["buffer"]
    controller = test_env["controller"]
    sync_mgr = test_env["sync_manager"]
    gateway = test_env["gateway"]
    mock_influx = test_env["mock_influx"]

    # 1. Offline stage: tích lũy 6 bản ghi
    controller.disconnect(reason="Network down")
    events = []
    for i in range(6):
        topic, ev = make_event("temperature", 28.0 + (i % 5), i + 1)
        gateway.process(topic, json.dumps(ev).encode())
        events.append(ev)

    assert buffer.get_pending_count() == 6
    assert buffer.get_synced_count() == 0

    # Sync thất bại khi offline, dữ liệu được bảo toàn nguyên vẹn
    res_fail = sync_mgr.sync_batch()
    assert res_fail.success is False
    assert buffer.get_pending_count() == 6

    # 2. Khôi phục kết nối
    controller.connect(reason="Network restored")
    assert controller.is_online()

    # 3. Thực hiện đồng bộ hóa toàn bộ
    sync_res = sync_mgr.sync_all()
    assert sync_res["success"] is True
    assert sync_res["total_synced"] == 6

    # 4. Nghiệm thu: PENDING == 0, SYNCED == 6
    assert buffer.get_pending_count() == 0
    assert buffer.get_synced_count() == 6
    assert database_status(buffer.path)["pending"] == 0
    assert database_status(buffer.path)["synced"] == 6

    # Xác nhận InfluxDB và PostgreSQL đã nhận đủ 6 bản ghi
    assert len(mock_influx.rows) == 6


def test_kt3_duplicate_prevention_idempotency(test_env):
    """Tiêu chuẩn KT3.8:
    Đảm bảo việc gửi lại không tạo bản ghi logic trùng trên Server.
    Server nhận diện event_id đã lưu, trả duplicate ACK, không ghi thêm bản ghi trùng.
    """
    buffer = test_env["buffer"]
    sync_mgr = test_env["sync_manager"]
    gateway = test_env["gateway"]
    mock_influx = test_env["mock_influx"]

    topic, ev = make_event("humidity", 65.0, 1)
    gateway.process(topic, json.dumps(ev).encode())

    # Sync lần 1
    res1 = sync_mgr.sync_batch()
    assert res1.success is True
    assert res1.synced == 1
    assert len(mock_influx.rows) == 1

    # Gửi lại chính bản ghi đó (mô phỏng Edge retry do mất gói tin phản hồi ACK)
    payload = {"gateway_id": "GW-001", "records": [ev]}
    resp = sync_mgr.session.post(sync_mgr.server_url, json=payload).json()

    assert resp["received"] == 1
    assert resp["accepted"] == 0
    assert resp["duplicates"] == 1
    assert resp["acknowledged_event_ids"] == [ev["event_id"]]

    # Số bản ghi vật lý trong InfluxDB không tăng lên 2
    assert len(mock_influx.rows) == 1


def test_kt3_exponential_backoff_and_reset(test_env):
    """Yêu cầu 1.C:
    Xử lý lỗi kết nối, retry khi gửi thất bại, sử dụng exponential backoff.
    """
    buffer = test_env["buffer"]
    controller = test_env["controller"]
    sync_mgr = test_env["sync_manager"]
    gateway = test_env["gateway"]

    topic, ev = make_event("soil_moisture", 50.0, 1)
    gateway.process(topic, json.dumps(ev).encode())

    # Ngắt mạng
    controller.disconnect(reason="Simulate outage for backoff verification")
    assert sync_mgr.consecutive_failures == 0
    assert sync_mgr.current_backoff == 1.0

    # Lần thử 1 thất bại -> backoff = 1.0s, failures = 1
    r1 = sync_mgr.sync_batch()
    assert r1.success is False
    assert sync_mgr.consecutive_failures == 1
    assert sync_mgr.current_backoff == 1.0

    # Lần thử 2 thất bại -> backoff = 2.0s, failures = 2
    r2 = sync_mgr.sync_batch()
    assert r2.success is False
    assert sync_mgr.consecutive_failures == 2
    assert sync_mgr.current_backoff == 2.0

    # Lần thử 3 thất bại -> backoff = 4.0s, failures = 3
    r3 = sync_mgr.sync_batch()
    assert r3.success is False
    assert sync_mgr.consecutive_failures == 3
    assert sync_mgr.current_backoff == 4.0

    # Khôi phục mạng và sync thành công -> backoff reset về initial_backoff (1.0s)
    controller.connect()
    r_ok = sync_mgr.sync_batch()
    assert r_ok.success is True
    assert sync_mgr.consecutive_failures == 0
    assert sync_mgr.current_backoff == 1.0


def test_kt3_timeout_handling(test_env):
    """Yêu cầu 1.C: Xử lý timeout kết nối."""
    buffer = test_env["buffer"]
    controller = test_env["controller"]
    sync_mgr = test_env["sync_manager"]
    gateway = test_env["gateway"]

    topic, ev = make_event("temperature", 25.0, 1)
    gateway.process(topic, json.dumps(ev).encode())

    # Thiết lập mô phỏng TIMEOUT
    controller.set_timeout_mode(reason="Simulated TCP drop")
    res = sync_mgr.sync_batch()

    assert res.success is False
    assert "timeout" in res.error.lower()
    assert buffer.get_pending_count() == 1


def test_kt3_server_503_service_unavailable(test_env):
    """Yêu cầu 1.C: Xử lý lỗi 503 từ Server và tuân thủ Retry-After."""
    buffer = test_env["buffer"]
    controller = test_env["controller"]
    sync_mgr = test_env["sync_manager"]
    gateway = test_env["gateway"]

    topic, ev = make_event("temperature", 26.0, 1)
    gateway.process(topic, json.dumps(ev).encode())

    controller.set_server_error_mode(reason="Simulate DB outage")
    res = sync_mgr.sync_batch()

    assert res.success is False
    assert res.status_code == 503
    assert sync_mgr.current_backoff >= 2.0  # Retry-After header respected


def test_kt3_batch_size_partitioning(test_env):
    """Yêu cầu 1.A & 1.C: Giới hạn kích thước batch và gửi nhiều đợt."""
    buffer = test_env["buffer"]
    sync_mgr = test_env["sync_manager"]
    gateway = test_env["gateway"]

    # Đặt batch_size = 3
    sync_mgr.batch_size = 3

    # Lưu 7 bản ghi vào buffer
    for i in range(7):
        topic, ev = make_event("temperature", 25.0 + i, i + 1)
        gateway.process(topic, json.dumps(ev).encode())

    assert buffer.get_pending_count() == 7

    # Batch 1: gửi 3
    b1 = sync_mgr.sync_batch()
    assert b1.success is True and b1.synced == 3
    assert b1.remaining_pending == 4

    # Batch 2: gửi 3
    b2 = sync_mgr.sync_batch()
    assert b2.success is True and b2.synced == 3
    assert b2.remaining_pending == 1

    # Batch 3: gửi 1 còn lại
    b3 = sync_mgr.sync_batch()
    assert b3.success is True and b3.synced == 1
    assert b3.remaining_pending == 0


def test_kt3_unacknowledged_records_never_deleted_or_lost(test_env):
    """Tiêu chuẩn KT3.6, KT3.7:
    Không xóa dữ liệu chưa được xác nhận; bản ghi bị thiếu ACK vẫn ở PENDING.
    """
    buffer = test_env["buffer"]
    gateway = test_env["gateway"]

    topic1, ev1 = make_event("temperature", 30.0, 1)
    topic2, ev2 = make_event("temperature", 31.0, 2)
    gateway.process(topic1, json.dumps(ev1).encode())
    gateway.process(topic2, json.dumps(ev2).encode())

    # Giả định Server chỉ ACK ev1, không ACK ev2
    sent_ids = [ev1["event_id"], ev2["event_id"]]
    ack_ids = [ev1["event_id"]]

    updated = buffer.mark_synced(ack_ids, sent_event_ids=sent_ids)
    assert updated == 1

    # ev2 vẫn phải PENDING, không hề bị xóa
    assert buffer.get_pending_count() == 1
    assert buffer.get_synced_count() == 1
    pending_records = buffer.pending_batch()
    assert len(pending_records) == 1
    assert pending_records[0]["event_id"] == ev2["event_id"]


def test_kt3_partial_ack_keeps_unacknowledged_records_and_backs_off(test_env, monkeypatch):
    """A partial HTTP 200 ACK must retain pending rows and use retry backoff."""
    buffer = test_env["buffer"]
    gateway = test_env["gateway"]
    sync_mgr = test_env["sync_manager"]

    for seq in (1, 2):
        topic, event = make_event("temperature", 28.0 + seq, seq)
        gateway.process(topic, json.dumps(event).encode())

    sent_batches = []

    def partial_ack(_url, **kwargs):
        sent_ids = [record["event_id"] for record in kwargs["json"]["records"]]
        sent_batches.append(sent_ids)
        response = requests.Response()
        response.status_code = 200
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(
            {
                "received": len(sent_ids),
                "accepted": 1,
                "duplicates": 0,
                "rejected": len(sent_ids) - 1,
                "acknowledged_event_ids": [sent_ids[0]],
                "rejected_records": [],
            }
        ).encode("utf-8")
        return response

    class StopAfterBackoff:
        def __init__(self):
            self.waits = []

        def is_set(self):
            return False

        def wait(self, seconds):
            self.waits.append(seconds)
            return True

    stop_event = StopAfterBackoff()
    monkeypatch.setattr(sync_mgr.session, "post", partial_ack)
    monkeypatch.setattr(sync_mgr, "_stop_event", stop_event)

    sync_mgr._worker_loop()

    status = database_status(buffer.path)
    pending = buffer.pending_batch()
    assert len(sent_batches) == 1
    assert stop_event.waits == [1.0]
    assert status["synced"] == 1
    assert status["pending"] == 1
    assert len(pending) == 1
    assert pending[0]["event_id"] == sent_batches[0][1]
    assert sync_mgr.consecutive_failures == 1
    assert sync_mgr.current_backoff == 1.0
    assert "ACK was incomplete" in sync_mgr.last_error

    # The synchronous flush reports records acknowledged before a later partial ACK.
    topic, event = make_event("temperature", 32.0, 3)
    gateway.process(topic, json.dumps(event).encode())
    flush_result = sync_mgr.sync_all()
    assert flush_result["success"] is False
    assert flush_result["batches"] == 1
    assert flush_result["total_synced"] == 1
    assert flush_result["rejected"] == 1
    assert flush_result["remaining_pending"] == 1
    assert len(sent_batches) == 2
    assert sync_mgr.consecutive_failures == 2
    assert sync_mgr.current_backoff == 2.0
