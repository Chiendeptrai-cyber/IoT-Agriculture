"""Network Simulation Scenarios for Task 6 and Acceptance Criteria KT3.

Executes end-to-end scenarios validating:
1. Server Offline: Edge keeps receiving sensor data, persists to SQLite, triggers thresholds/pump, marks PENDING.
2. Server Recovery: Network restored, Edge automatically syncs batches via REST API, receives ACK, updates to SYNCED.
3. Duplicate Prevention: Resending same events returns ACKs without creating duplicate server records.
4. Retry & Exponential Backoff: Transient failures double the backoff delay up to maximum limit.
5. Zero Loss & Zero Remaining Pending: After recovery, all records are SYNCED, pending count == 0.
"""

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional
import uuid

import requests
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "edge-gateway"))
sys.path.insert(0, str(ROOT / "sensor-simulator"))
sys.path.insert(0, str(ROOT))

from buffer_manager import BufferManager, database_status
from connection_controller import ConnectionController, ConnectionState, ConnectionSimulationAdapter
from mqtt_client import EdgeGateway
from server.database import build_engine
from server.main import Settings as ServerSettings, create_app
from settings import load_config, sensor_routes
from sync_manager import SyncManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
LOG = logging.getLogger("scenarios")


class MockInfluxStore:
    """In-memory InfluxDB mock for standalone scenario verification."""
    def __init__(self):
        self.rows = []
        self.is_healthy = True

    def write(self, record, gateway_id, received_at):
        self.rows.append((record, gateway_id, received_at))

    def healthy(self):
        return self.is_healthy

    def close(self):
        pass


def make_test_environment(tmp_path: Path):
    """Instantiate a local Edge Buffer, Server API client, and Network Controller."""
    db_path = tmp_path / "scenario_edge.db"
    buffer = BufferManager(db_path)
    config = load_config()

    controller = ConnectionController(state_file=tmp_path / ".sim_state.json")
    controller.connect()

    # Central Server in-memory instance
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

    # Mount connection controller adapter to a custom requests Session
    session = requests.Session()
    adapter = controller.create_adapter()

    # Hook TestClient into the session for fast, robust in-process execution
    class TestClientAdapter(ConnectionSimulationAdapter):
        def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
            # First check network cut via controller
            status = self.controller.status()
            state = status["state"]
            if state == ConnectionState.OFFLINE:
                raise requests.exceptions.ConnectionError(
                    f"Simulated network outage (Connection refused): {status['reason']}"
                )
            elif state == ConnectionState.TIMEOUT:
                raise requests.exceptions.Timeout(
                    f"Simulated network timeout (Packet drop): {status['reason']}"
                )
            elif state == ConnectionState.SERVER_ERROR:
                resp = requests.models.Response()
                resp.status_code = 503
                resp.reason = "Service Unavailable (Simulated)"
                resp.headers["Retry-After"] = "2"
                resp._content = b'{"detail": "Database unavailable (simulated)"}'
                return resp

            # If online, dispatch to FastAPI TestClient
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

    test_adapter = TestClientAdapter(controller)
    session.mount("http://127.0.0.1:8000", test_adapter)
    session.mount("http://localhost:8000", test_adapter)

    sync_mgr = SyncManager(
        buffer=buffer,
        config=config,
        server_url="http://127.0.0.1:8000/api/v1/telemetry/batch",
        health_url="http://127.0.0.1:8000/api/v1/health",
        session=session,
    )

    gateway = EdgeGateway(buffer, config)

    def cleanup():
        sync_mgr.stop()
        buffer.close()
        test_client.__exit__(None, None, None)
        server_engine.dispose()

    return {
        "buffer": buffer,
        "config": config,
        "controller": controller,
        "sync_manager": sync_mgr,
        "gateway": gateway,
        "mock_influx": mock_influx,
        "test_client": test_client,
        "cleanup": cleanup,
    }


def make_reading(kind="temperature", value=29.5, seq=1):
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


def run_server_offline_and_sync_recovery_scenario(env: Dict[str, Any]) -> Dict[str, Any]:
    """Execute Scenario 1: Offline Edge operation followed by full recovery and sync.
    
    Validates KT3 acceptance criteria:
    - Edge receives and stores data in SQLite while Server is down
    - Edge evaluates thresholds and virtual pump offline
    - Unsynced records marked PENDING
    - Server comes back online, Edge automatically syncs all records
    - ACK received and records marked SYNCED
    - Zero data loss, zero duplicate records, 0 PENDING remaining
    """
    buffer: BufferManager = env["buffer"]
    controller: ConnectionController = env["controller"]
    sync_mgr: SyncManager = env["sync_manager"]
    gateway: EdgeGateway = env["gateway"]

    LOG.info("=== SCENARIO 1: Server Offline & Recovery Synchronization ===")

    # 1. Sever connection between Edge and Server
    LOG.info("Step 1: Severing Edge -> Server connection (Simulating Server Outage)...")
    controller.disconnect(reason="Planned server power outage / cable disconnection")
    assert not controller.is_online(), "Controller must be offline"

    # Verify sync attempt fails cleanly while offline
    pre_result = sync_mgr.sync_batch()
    assert pre_result.success is True and pre_result.synced == 0, "Empty buffer returns 0 synced"

    # 2. Sensor sends readings to Edge (Sensor -> Edge remains active)
    LOG.info("Step 2: Streaming sensor readings to Edge while Server is offline...")
    test_events = [
        ("temperature", 40.0, 1),   # HIGH_TEMPERATURE alert (> 35)
        ("humidity", 35.0, 1),      # LOW_HUMIDITY alert (< 40)
        ("soil_moisture", 22.0, 1), # LOW_SOIL_MOISTURE (< 30) -> triggers Pump ON
        ("soil_moisture", 32.0, 2), # In hysteresis range (30-35) -> Pump stays ON
        ("soil_moisture", 38.0, 3), # Sufficient moisture (> 35) -> triggers Pump OFF
    ]

    stored_event_ids = []
    for kind, val, seq in test_events:
        topic, event = make_reading(kind, val, seq)
        res = gateway.process(topic, json.dumps(event).encode())
        assert res["status"] == "STORED", f"Reading must be stored in SQLite, got {res}"
        assert res["sync_status"] == "PENDING", f"Reading must be marked PENDING, got {res}"
        stored_event_ids.append(event["event_id"])

    # 3. Verify Edge local state during Server outage
    LOG.info("Step 3: Verifying Edge local state while Server remains offline...")
    offline_status = database_status(buffer.path)
    assert offline_status["total"] == len(test_events), "All events must be in SQLite"
    assert offline_status["pending"] == len(test_events), "All events must be PENDING"
    assert offline_status["synced"] == 0, "Zero events can be SYNCED while server is offline"
    assert offline_status["alerts"] == 2, f"Must have recorded 2 alerts, got {offline_status['alerts']}"
    assert offline_status["device_actions"] == 2, f"Must have recorded 2 pump actions (ON then OFF)"
    assert offline_status["pump"]["state"] == "OFF", "Pump must end in OFF state after 38% moisture"

    # 4. Attempt sync while offline: must gracefully fail with backoff without losing data
    LOG.info("Step 4: Edge attempts sync while Server is offline (testing retry & backoff)...")
    fail_result = sync_mgr.sync_batch()
    assert fail_result.success is False, "Sync must fail while server is offline"
    assert fail_result.synced == 0, "No records can be marked synced on failure"
    assert buffer.get_pending_count() == len(test_events), "No records can be lost on sync failure"
    assert sync_mgr.consecutive_failures == 1, "Consecutive failures must increment"
    assert sync_mgr.current_backoff >= sync_mgr.initial_backoff, "Backoff must be at least initial backoff"

    # Second failure should increase backoff
    fail_result2 = sync_mgr.sync_batch()
    assert fail_result2.success is False
    assert sync_mgr.consecutive_failures == 2
    assert sync_mgr.current_backoff > sync_mgr.initial_backoff, "Backoff must increase on repeated failure"

    # 5. Restore connection
    LOG.info("Step 5: Restoring Edge -> Server network connection...")
    controller.connect(reason="Server online, network link restored")
    assert controller.is_online(), "Controller must be online"

    # 6. Perform synchronization after recovery
    LOG.info("Step 6: Executing synchronization following network recovery...")
    sync_summary = sync_mgr.sync_all()
    assert sync_summary["success"] is True, f"Sync all must succeed, got {sync_summary}"
    assert sync_summary["total_synced"] == len(test_events), (
        f"Expected {len(test_events)} synced, got {sync_summary['total_synced']}"
    )

    # 7. Verify final states at Edge and Server
    LOG.info("Step 7: Validating post-sync integrity across Edge and Server...")
    final_edge = database_status(buffer.path)
    assert final_edge["pending"] == 0, f"Pending count must be 0 after sync, got {final_edge['pending']}"
    assert final_edge["synced"] == len(test_events), f"Synced count must equal total, got {final_edge['synced']}"
    assert final_edge["total"] == len(test_events)

    # Verify Server received every record
    assert len(env["mock_influx"].rows) == len(test_events), "InfluxDB must receive all records"

    LOG.info("SCENARIO 1 PASSED: 100%% data integrity preserved, 0 pending records remaining.")
    return {
        "status": "PASSED",
        "scenario": "server_offline_and_sync_recovery",
        "events_tested": len(test_events),
        "offline_pending": offline_status["pending"],
        "post_sync_pending": final_edge["pending"],
        "post_sync_synced": final_edge["synced"],
        "alerts_triggered": offline_status["alerts"],
        "pump_actions": offline_status["device_actions"],
    }


def run_duplicate_prevention_scenario(env: Dict[str, Any]) -> Dict[str, Any]:
    """Execute Scenario 2: Resending already-synced batch must not create duplicate records."""
    buffer: BufferManager = env["buffer"]
    sync_mgr: SyncManager = env["sync_manager"]
    gateway: EdgeGateway = env["gateway"]

    LOG.info("=== SCENARIO 2: Duplicate Prevention & Idempotency ===")

    # Generate and store 1 event
    topic, event = make_reading("temperature", 30.0, seq=10)
    gateway.process(topic, json.dumps(event).encode())

    # Sync first time
    res1 = sync_mgr.sync_batch()
    assert res1.success is True and res1.synced == 1
    assert res1.duplicates == 0

    # Simulate resending the exact same payload (e.g. ACK dropped on return path)
    payload = {"gateway_id": "GW-001", "records": [event]}
    raw_resp = sync_mgr.session.post(sync_mgr.server_url, json=payload).json()

    assert raw_resp["received"] == 1
    assert raw_resp["accepted"] == 0
    assert raw_resp["duplicates"] == 1
    assert raw_resp["acknowledged_event_ids"] == [event["event_id"]], "Duplicate must still be acknowledged"

    LOG.info("SCENARIO 2 PASSED: Duplicate successfully acknowledged without duplicate creation.")
    return {
        "status": "PASSED",
        "scenario": "duplicate_prevention",
        "duplicate_event_id": event["event_id"],
        "server_duplicates_detected": raw_resp["duplicates"],
    }


def run_retry_exponential_backoff_scenario(env: Dict[str, Any]) -> Dict[str, Any]:
    """Execute Scenario 3: Verify backoff delay increases exponentially on repeated failures."""
    buffer: BufferManager = env["buffer"]
    controller: ConnectionController = env["controller"]
    sync_mgr: SyncManager = env["sync_manager"]
    gateway: EdgeGateway = env["gateway"]

    LOG.info("=== SCENARIO 3: Retry Mechanism with Exponential Backoff ===")

    topic, event = make_reading("humidity", 50.0, seq=20)
    gateway.process(topic, json.dumps(event).encode())

    controller.disconnect(reason="Extended outage test")
    backoffs = []

    for attempt in range(4):
        res = sync_mgr.sync_batch()
        assert res.success is False
        backoffs.append(sync_mgr.current_backoff)
        LOG.info("Attempt %d: consecutive_failures=%d, backoff=%.1fs", attempt + 1, sync_mgr.consecutive_failures, sync_mgr.current_backoff)

    # Verify backoff increased monotonically
    assert backoffs[0] == sync_mgr.initial_backoff
    assert backoffs[1] == sync_mgr.initial_backoff * sync_mgr.backoff_factor
    assert backoffs[2] == sync_mgr.initial_backoff * (sync_mgr.backoff_factor ** 2)
    assert backoffs[3] == sync_mgr.initial_backoff * (sync_mgr.backoff_factor ** 3)

    # Reconnect and verify backoff resets to initial upon success
    controller.connect(reason="Backoff reset test")
    res_ok = sync_mgr.sync_batch()
    assert res_ok.success is True
    assert sync_mgr.consecutive_failures == 0
    assert sync_mgr.current_backoff == sync_mgr.initial_backoff

    LOG.info("SCENARIO 3 PASSED: Exponential backoff verified and cleanly reset.")
    return {
        "status": "PASSED",
        "scenario": "retry_exponential_backoff",
        "backoff_progression": backoffs,
        "reset_backoff": sync_mgr.current_backoff,
    }


def run_all_scenarios() -> Dict[str, Any]:
    """Run full test scenario suite."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        env = make_test_environment(Path(tmp_dir))
        try:
            r1 = run_server_offline_and_sync_recovery_scenario(env)
            r2 = run_duplicate_prevention_scenario(env)
            r3 = run_retry_exponential_backoff_scenario(env)
            return {
                "overall_status": "ALL_PASSED",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "results": [r1, r2, r3],
            }
        finally:
            env["cleanup"]()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=["all", "offline-recovery", "duplicate", "backoff"], default="all")
    parser.add_argument("--evidence", type=Path, default=None, help="Save scenario evidence JSON to file")
    args = parser.parse_args()

    results = {}
    with tempfile.TemporaryDirectory() as tmp_dir:
        env = make_test_environment(Path(tmp_dir))
        try:
            if args.scenario in ("all", "offline-recovery"):
                results["offline_recovery"] = run_server_offline_and_sync_recovery_scenario(env)
            if args.scenario in ("all", "duplicate"):
                results["duplicate"] = run_duplicate_prevention_scenario(env)
            if args.scenario in ("all", "backoff"):
                results["backoff"] = run_retry_exponential_backoff_scenario(env)
        finally:
            env["cleanup"]()

    print("\n" + "=" * 60)
    print("SCENARIO EXECUTION SUMMARY")
    print("=" * 60)
    print(json.dumps(results, indent=2))

    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nEvidence saved to: {args.evidence}")


if __name__ == "__main__":
    main()
