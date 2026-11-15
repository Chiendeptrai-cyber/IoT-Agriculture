"""Sync Manager for Edge Gateway.

Handles HTTP REST API batch synchronization of buffered telemetry records to the Central Server.
Implements:
- Server reachability check
- Batch telemetry transmission via POST /api/v1/telemetry/batch
- Server ACK parsing and atomic local state transition (PENDING -> SYNCED)
- Retry mechanism with exponential backoff on timeout and connection failures
- Duplicate prevention ensuring idempotent at-least-once delivery without logical duplication
- Background worker thread with clean start/stop lifecycle
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import requests

from buffer_manager import BufferManager, database_status
from settings import DEFAULT_DB_PATH, load_config

LOG = logging.getLogger("edge_gateway.sync")


@dataclass
class SyncResult:
    """Outcome of a single batch synchronization cycle."""
    success: bool
    synced: int
    acknowledged: List[str] = field(default_factory=list)
    duplicates: int = 0
    rejected: int = 0
    remaining_pending: int = 0
    error: Optional[str] = None
    status_code: Optional[int] = None
    retry_after: Optional[float] = None


class SyncManager:
    """Durable synchronization worker that pushes Edge telemetry to Server."""

    def __init__(
        self,
        buffer: BufferManager,
        config: Optional[Dict[str, Any]] = None,
        server_url: Optional[str] = None,
        health_url: Optional[str] = None,
        gateway_id: str = "GW-001",
        batch_size: int = 100,
        interval: float = 5.0,
        timeout: float = 5.0,
        initial_backoff: float = 1.0,
        max_backoff: float = 30.0,
        backoff_factor: float = 2.0,
        session: Optional[requests.Session] = None,
    ):
        self.buffer = buffer
        self.config = config or {}
        sync_cfg = self.config.get("sync", {})

        self.server_url = (
            server_url
            or os.getenv("SERVER_BATCH_URL")
            or sync_cfg.get("server_url", "http://127.0.0.1:8000/api/v1/telemetry/batch")
        )
        self.health_url = (
            health_url
            or os.getenv("SERVER_HEALTH_URL")
            or sync_cfg.get("health_url", "http://127.0.0.1:8000/api/v1/health")
        )
        self.gateway_id = os.getenv("GATEWAY_ID") or sync_cfg.get("gateway_id", gateway_id)
        
        raw_batch = sync_cfg.get("batch_size", batch_size)
        if isinstance(raw_batch, bool) or not isinstance(raw_batch, int) or not (1 <= raw_batch <= 1000):
            raise ValueError("batch_size must be an integer between 1 and 1000")
        self.batch_size = raw_batch

        self.interval = float(sync_cfg.get("interval_seconds", interval))
        self.timeout = float(sync_cfg.get("timeout_seconds", timeout))
        self.initial_backoff = float(sync_cfg.get("retry_initial_backoff", initial_backoff))
        self.max_backoff = float(sync_cfg.get("retry_max_backoff", max_backoff))
        self.backoff_factor = float(sync_cfg.get("retry_backoff_factor", backoff_factor))

        if self.initial_backoff <= 0 or self.max_backoff < self.initial_backoff or self.backoff_factor <= 1.0:
            raise ValueError("Invalid backoff parameters: must satisfy 0 < initial <= max and factor > 1.0")

        self.session = session or requests.Session()
        self._owns_session = session is None

        # State tracking
        self.current_backoff = self.initial_backoff
        self.consecutive_failures = 0
        self.total_synced = 0
        self.total_batches = 0
        self.last_sync_time: Optional[str] = None
        self.last_error: Optional[str] = None
        self.is_running = False

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def check_server_health(self) -> bool:
        """Check whether the central Server API is online and accepting requests."""
        try:
            resp = self.session.get(self.health_url, timeout=self.timeout)
            return resp.status_code == 200
        except (requests.exceptions.RequestException, OSError):
            return False

    def sync_batch(self, limit: Optional[int] = None) -> SyncResult:
        """Fetch one batch of PENDING records from SQLite and push to Server via HTTP REST.
        
        Handles ACK processing, exponential backoff updates, and atomic status transitions.
        """
        with self._lock:
            effective_limit = limit or self.batch_size
            records = self.buffer.pending_batch(limit=effective_limit)
            
            if not records:
                pending_count = self.buffer.get_pending_count()
                return SyncResult(
                    success=True,
                    synced=0,
                    acknowledged=[],
                    duplicates=0,
                    rejected=0,
                    remaining_pending=pending_count,
                    status_code=200,
                )

            sent_event_ids = [r["event_id"] for r in records]
            payload = {
                "gateway_id": self.gateway_id,
                "records": records,
            }

            try:
                resp = self.session.post(
                    self.server_url,
                    json=payload,
                    timeout=self.timeout,
                    headers={"Content-Type": "application/json"},
                )

                if resp.status_code == 200:
                    body = resp.json()
                    ack_ids = body.get("acknowledged_event_ids", [])
                    duplicates = body.get("duplicates", 0)
                    rejected = body.get("rejected", 0)

                    # Atomically update local SQLite status to SYNCED
                    synced_count = self.buffer.mark_synced(
                        ack_ids,
                        sent_event_ids=sent_event_ids,
                        acknowledged_at=datetime.now(timezone.utc),
                    )

                    self.total_synced += synced_count
                    self.total_batches += 1
                    self.last_sync_time = datetime.now(timezone.utc).isoformat()
                    self.consecutive_failures = 0
                    self.current_backoff = self.initial_backoff
                    self.last_error = None
                    remaining_pending = self.buffer.get_pending_count()

                    LOG.info(
                        "SYNC SUCCESS: sent=%d, acknowledged=%d (new=%d, duplicates=%d), remaining_pending=%d",
                        len(sent_event_ids),
                        len(ack_ids),
                        synced_count,
                        duplicates,
                        remaining_pending,
                    )

                    if rejected > 0:
                        LOG.warning(
                            "SYNC WARNING: server rejected %d records: %s",
                            rejected,
                            body.get("rejected_records", []),
                        )

                    return SyncResult(
                        success=True,
                        synced=synced_count,
                        acknowledged=ack_ids,
                        duplicates=duplicates,
                        rejected=rejected,
                        remaining_pending=remaining_pending,
                        status_code=200,
                    )

                elif resp.status_code in (502, 503, 504):
                    # Transient Server outage (e.g. database temporarily unavailable)
                    self._apply_failure()
                    retry_hdr = resp.headers.get("Retry-After")
                    if retry_hdr and retry_hdr.isdigit():
                        self.current_backoff = max(self.current_backoff, float(retry_hdr))

                    err_msg = f"Server transient error HTTP {resp.status_code}: {resp.text[:200]}"
                    self.last_error = err_msg
                    LOG.warning("SYNC RETRYABLE ERROR: %s (backoff=%.1fs)", err_msg, self.current_backoff)
                    return SyncResult(
                        success=False,
                        synced=0,
                        remaining_pending=self.buffer.get_pending_count(),
                        error=err_msg,
                        status_code=resp.status_code,
                        retry_after=self.current_backoff,
                    )

                else:
                    # Non-200 non-5xx (e.g. 400 Bad Request, 422 Unprocessable)
                    self._apply_failure()
                    err_msg = f"Server HTTP {resp.status_code}: {resp.text[:200]}"
                    self.last_error = err_msg
                    LOG.error("SYNC CLIENT/SERVER ERROR: %s", err_msg)
                    return SyncResult(
                        success=False,
                        synced=0,
                        remaining_pending=self.buffer.get_pending_count(),
                        error=err_msg,
                        status_code=resp.status_code,
                        retry_after=self.current_backoff,
                    )

            except requests.exceptions.Timeout as exc:
                self._apply_failure()
                err_msg = f"Request timeout after {self.timeout}s: {exc}"
                self.last_error = err_msg
                LOG.warning("SYNC TIMEOUT: %s (backoff=%.1fs)", err_msg, self.current_backoff)
                return SyncResult(
                    success=False,
                    synced=0,
                    remaining_pending=self.buffer.get_pending_count(),
                    error=err_msg,
                    retry_after=self.current_backoff,
                )

            except (requests.exceptions.ConnectionError, OSError) as exc:
                self._apply_failure()
                err_msg = f"Network connection failed: {exc}"
                self.last_error = err_msg
                LOG.warning("SYNC CONNECTION REFUSED / OFFLINE: %s (backoff=%.1fs)", err_msg, self.current_backoff)
                return SyncResult(
                    success=False,
                    synced=0,
                    remaining_pending=self.buffer.get_pending_count(),
                    error=err_msg,
                    retry_after=self.current_backoff,
                )

            except Exception as exc:
                self._apply_failure()
                err_msg = f"Unexpected sync error ({type(exc).__name__}): {exc}"
                self.last_error = err_msg
                LOG.exception("SYNC UNEXPECTED ERROR: %s", err_msg)
                return SyncResult(
                    success=False,
                    synced=0,
                    remaining_pending=self.buffer.get_pending_count(),
                    error=err_msg,
                    retry_after=self.current_backoff,
                )

    def _apply_failure(self):
        """Increase backoff using exponential scale on failure."""
        self.consecutive_failures += 1
        self.current_backoff = min(
            self.max_backoff,
            self.initial_backoff * (self.backoff_factor ** (self.consecutive_failures - 1)),
        )

    def sync_all(self, max_batches: int = 1000) -> Dict[str, Any]:
        """Flush all pending records until buffer is empty or an error occurs."""
        batches = 0
        total_synced = 0
        total_dups = 0
        total_rej = 0

        while batches < max_batches:
            if self.buffer.get_pending_count() == 0:
                break
            result = self.sync_batch()
            if not result.success:
                return {
                    "success": False,
                    "batches": batches,
                    "total_synced": total_synced,
                    "remaining_pending": result.remaining_pending,
                    "error": result.error,
                }
            batches += 1
            total_synced += result.synced
            total_dups += result.duplicates
            total_rej += result.rejected
            if result.synced == 0 and result.remaining_pending == 0:
                break

        return {
            "success": True,
            "batches": batches,
            "total_synced": total_synced,
            "duplicates": total_dups,
            "rejected": total_rej,
            "remaining_pending": self.buffer.get_pending_count(),
        }

    def start(self):
        """Start the background synchronization thread."""
        with self._lock:
            if self.is_running:
                return
            self.is_running = True
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._worker_loop, name="EdgeSyncWorker", daemon=True)
            self._thread.start()
            LOG.info("Edge Sync Manager started (target: %s, interval: %.1fs)", self.server_url, self.interval)

    def stop(self, timeout: float = 3.0):
        """Stop the background synchronization thread cleanly."""
        with self._lock:
            if not self.is_running:
                return
            self.is_running = False
            self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

        if self._owns_session:
            self.session.close()

        LOG.info("Edge Sync Manager stopped.")

    def _worker_loop(self):
        """Continuous background thread draining pending buffer records."""
        while not self._stop_event.is_set():
            pending = self.buffer.get_pending_count()
            if pending > 0:
                result = self.sync_batch()
                if result.success:
                    if result.remaining_pending > 0:
                        # More records waiting: yield briefly and continue draining immediately
                        if self._stop_event.wait(0.05):
                            break
                        continue
                    else:
                        # Drained completely: sleep standard interval
                        if self._stop_event.wait(self.interval):
                            break
                else:
                    # Failed: sleep exponential backoff time
                    if self._stop_event.wait(self.current_backoff):
                        break
            else:
                # Buffer empty: sleep standard interval
                if self._stop_event.wait(self.interval):
                    break

    def status(self) -> Dict[str, Any]:
        """Inspect current synchronizer state."""
        return {
            "server_url": self.server_url,
            "gateway_id": self.gateway_id,
            "batch_size": self.batch_size,
            "interval_seconds": self.interval,
            "timeout_seconds": self.timeout,
            "is_running": self.is_running,
            "consecutive_failures": self.consecutive_failures,
            "current_backoff_seconds": self.current_backoff,
            "total_synced": self.total_synced,
            "total_batches": self.total_batches,
            "pending_count": self.buffer.get_pending_count(),
            "synced_count": self.buffer.get_synced_count(),
            "last_sync_time": self.last_sync_time,
            "last_error": self.last_error,
        }


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path(os.getenv("EDGE_DB_PATH", str(DEFAULT_DB_PATH))))
    parser.add_argument("--server", default=os.getenv("SERVER_BATCH_URL", "http://127.0.0.1:8000/api/v1/telemetry/batch"))
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--once", action="store_true", help="Sync all pending records and exit")
    parser.add_argument("--status", action="store_true", help="Print sync status and exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    buffer = BufferManager(args.db)
    sync = SyncManager(buffer, server_url=args.server, batch_size=args.batch_size, interval=args.interval)

    try:
        if args.status:
            print(json.dumps(sync.status(), indent=2))
            return

        if args.once:
            print("Flushing pending records to server...")
            result = sync.sync_all()
            print(json.dumps(result, indent=2))
            return

        print(f"Starting continuous SyncManager pushing to {args.server}...")
        sync.start()
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        sync.stop()
        buffer.close()


if __name__ == "__main__":
    main()
