"""Durable local telemetry, alert and virtual actuator storage. No Server needed."""

from datetime import datetime
import json
from pathlib import Path
import sqlite3
import threading

from data_validator import classify_event, event_time, utc_now
from settings import sensor_routes
from threshold_engine import evaluate


class EventConflict(ValueError):
    """An event ID was reused for a different logical measurement."""


class BufferManager:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.connection = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS telemetry (
                event_id TEXT PRIMARY KEY,
                sensor_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                value REAL NOT NULL,
                unit TEXT NOT NULL,
                topic TEXT NOT NULL,
                payload TEXT NOT NULL,
                received_at TEXT NOT NULL,
                processed_at TEXT NOT NULL,
                control_applied INTEGER NOT NULL,
                sync_status TEXT NOT NULL DEFAULT 'PENDING'
                    CHECK(sync_status IN ('PENDING', 'SYNCED'))
            );
            CREATE INDEX IF NOT EXISTS idx_pending ON telemetry(sync_status, received_at);
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY,
                event_id TEXT NOT NULL REFERENCES telemetry(event_id),
                kind TEXT NOT NULL,
                value REAL NOT NULL,
                threshold REAL NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(event_id, kind)
            );
            CREATE TABLE IF NOT EXISTS device_state (
                device_id TEXT PRIMARY KEY,
                state TEXT NOT NULL CHECK(state IN ('ON', 'OFF')),
                last_event_id TEXT REFERENCES telemetry(event_id),
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS device_actions (
                id INTEGER PRIMARY KEY,
                event_id TEXT NOT NULL UNIQUE REFERENCES telemetry(event_id),
                previous_state TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sensor_watermarks (
                sensor_id TEXT PRIMARY KEY,
                measured_at REAL NOT NULL,
                sequence INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS quarantine (
                id INTEGER PRIMARY KEY,
                topic TEXT NOT NULL,
                payload BLOB NOT NULL,
                reason TEXT NOT NULL,
                received_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sensor_health (
                sensor_id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('ONLINE', 'STALE', 'OFFLINE')),
                last_received_at TEXT,
                monitoring_since TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sensor_health_events (
                id INTEGER PRIMARY KEY,
                sensor_id TEXT NOT NULL REFERENCES sensor_health(sensor_id),
                previous_state TEXT NOT NULL,
                state TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        with self.connection:
            # Add columns without removing existing telemetry or pending records.
            columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(telemetry)")}
            if "classification" not in columns:
                self.connection.execute(
                    "ALTER TABLE telemetry ADD COLUMN classification TEXT CHECK(classification IN ('NORMAL','ANOMALY'))"
                )
            if "synced_at" not in columns:
                self.connection.execute("ALTER TABLE telemetry ADD COLUMN synced_at TEXT")
            quarantine_columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(quarantine)")}
            if "classification" not in quarantine_columns:
                self.connection.execute("ALTER TABLE quarantine ADD COLUMN classification TEXT NOT NULL DEFAULT 'INVALID'")
            self.connection.execute(
                "INSERT OR IGNORE INTO device_state VALUES ('pump', 'OFF', NULL, ?)",
                (utc_now().isoformat(),),
            )
            now = utc_now().isoformat()
            for topic, (sensor_id, _) in sensor_routes().items():
                last_received = self.connection.execute(
                    "SELECT MAX(received_at) FROM telemetry WHERE sensor_id=?", (sensor_id,)
                ).fetchone()[0]
                self.connection.execute(
                    "INSERT OR IGNORE INTO sensor_health VALUES (?,?, 'STALE', ?,?,?)",
                    (sensor_id, topic, last_received, now, now),
                )

    def configure(self, config):
        """Classify legacy records once using the current threshold configuration."""
        with self.lock, self.connection:
            for row in self.connection.execute("SELECT event_id,topic,payload FROM telemetry WHERE classification IS NULL").fetchall():
                classification = classify_event(row["topic"], json.loads(row["payload"]), config)
                self.connection.execute("UPDATE telemetry SET classification=? WHERE event_id=?", (classification, row["event_id"]))

    def _transition_health(self, row, state, reason, now):
        if state == row["state"]:
            return None
        changed_at = now.isoformat()
        self.connection.execute(
            "UPDATE sensor_health SET state=?,updated_at=? WHERE sensor_id=?", (state, changed_at, row["sensor_id"])
        )
        self.connection.execute(
            "INSERT INTO sensor_health_events(sensor_id,previous_state,state,reason,created_at) VALUES (?,?,?,?,?)",
            (row["sensor_id"], row["state"], state, reason, changed_at),
        )
        return {"sensor_id": row["sensor_id"], "previous_state": row["state"], "state": state, "reason": reason}

    def check_sensor_health(self, monitor, *, now=None):
        now = now or utc_now()
        changes = []
        with self.lock, self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            rows = self.connection.execute("SELECT * FROM sensor_health ORDER BY sensor_id").fetchall()
            for row in rows:
                last_received = datetime.fromisoformat(row["last_received_at"]) if row["last_received_at"] else None
                state = monitor.classify(last_received, datetime.fromisoformat(row["monitoring_since"]), now=now)
                reference = last_received or datetime.fromisoformat(row["monitoring_since"])
                elapsed = max(0, (now - reference).total_seconds())
                reason = f"no new valid reading for {elapsed:.1f}s" if last_received else f"never received valid data; monitored for {elapsed:.1f}s"
                change = self._transition_health(row, state, reason, now)
                if change:
                    changes.append(change)
        return changes

    def store(self, topic, event, config, *, now=None):
        now = now or utc_now()
        received_at = now.isoformat()
        payload = json.dumps(event, sort_keys=True, ensure_ascii=False, allow_nan=False)
        classification = classify_event(topic, event, config)
        with self.lock, self.connection:
            # The reading and all local effects commit or roll back together.
            self.connection.execute("BEGIN IMMEDIATE")
            previous = self.connection.execute(
                "SELECT topic, payload,classification FROM telemetry WHERE event_id=?", (event["event_id"],)
            ).fetchone()
            if previous:
                if previous["topic"] != topic or previous["payload"] != payload:
                    raise EventConflict("event_id already exists with different payload")
                return {"status": "DUPLICATE", "event_id": event["event_id"], "classification": previous["classification"]}
            measured_at = event_time(event)
            watermark = self.connection.execute(
                "SELECT measured_at, sequence FROM sensor_watermarks WHERE sensor_id=?", (event["sensor_id"],)
            ).fetchone()
            is_newer = watermark is None or (measured_at.timestamp(), event["sequence"]) > (
                watermark["measured_at"], watermark["sequence"]
            )
            fresh = (now - measured_at).total_seconds() <= config["control_max_age_seconds"]
            apply_control = is_newer and fresh
            self.connection.execute(
                """INSERT INTO telemetry
                (event_id,sensor_id,timestamp,sequence,value,unit,topic,payload,received_at,processed_at,control_applied,classification)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (event["event_id"], event["sensor_id"], event["timestamp"], event["sequence"],
                 event["value"], event["unit"], topic, payload, received_at, received_at, int(apply_control), classification),
            )
            health = self.connection.execute("SELECT * FROM sensor_health WHERE sensor_id=?", (event["sensor_id"],)).fetchone()
            health_change = self._transition_health(health, "ONLINE", "new valid reading received", now)
            self.connection.execute(
                "UPDATE sensor_health SET last_received_at=?,updated_at=? WHERE sensor_id=?",
                (received_at, received_at, event["sensor_id"]),
            )
            pump = self.connection.execute("SELECT state FROM device_state WHERE device_id='pump'").fetchone()[0]
            alerts, next_pump = [], pump
            if is_newer:
                self.connection.execute(
                    "INSERT OR REPLACE INTO sensor_watermarks VALUES (?,?,?)",
                    (event["sensor_id"], measured_at.timestamp(), event["sequence"]),
                )
            if apply_control:
                alerts, next_pump = evaluate(topic, event["value"], pump, config["thresholds"])
                for kind, threshold in alerts:
                    self.connection.execute(
                        "INSERT INTO alerts(event_id,kind,value,threshold,created_at) VALUES (?,?,?,?,?)",
                        (event["event_id"], kind, event["value"], threshold, received_at),
                    )
                if next_pump != pump:
                    self.connection.execute(
                        "INSERT INTO device_actions(event_id,previous_state,state,created_at) VALUES (?,?,?,?)",
                        (event["event_id"], pump, next_pump, received_at),
                    )
                    self.connection.execute(
                        "UPDATE device_state SET state=?,last_event_id=?,updated_at=? WHERE device_id='pump'",
                        (next_pump, event["event_id"], received_at),
                    )
        return {"status": "STORED", "event_id": event["event_id"], "sync_status": "PENDING",
                "control_applied": apply_control, "alerts": [kind for kind, _ in alerts],
                "pump": next_pump, "pump_changed": next_pump != pump,
                "classification": classification, "health_change": health_change}

    def quarantine(self, topic, payload, reason, *, max_bytes=65536):
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT INTO quarantine(topic,payload,reason,received_at) VALUES (?,?,?,?)",
                (topic, payload[:int(max_bytes)], reason[:2000], utc_now().isoformat()),
            )

    def pending_batch(self, limit=100):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("Batch limit must be between 1 and 1000")
        with self.lock:
            rows = self.connection.execute(
                "SELECT payload FROM telemetry WHERE sync_status='PENDING' ORDER BY received_at,event_id LIMIT ?",
                (limit,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def mark_synced(self, acknowledged_event_ids, *, sent_event_ids, acknowledged_at=None):
        """Apply explicit durable Server acknowledgements for a previously sent batch.

        Counts or an HTTP 200 alone are not sufficient. The future sync worker
        must validate Server acknowledgement semantics before calling this method.
        """
        def ids(values):
            if not isinstance(values, (list, tuple, set)) or len(values) > 1000:
                raise ValueError("Expected at most 1000 event IDs")
            if any(not isinstance(value, str) or not value for value in values):
                raise ValueError("Event IDs must be nonempty strings")
            return set(values)
        acknowledged = ids(acknowledged_event_ids)
        sent = ids(sent_event_ids)
        if not acknowledged <= sent:
            raise ValueError("Server acknowledged an event outside the sent batch")
        if not acknowledged:
            return 0
        acknowledged_at = utc_now() if acknowledged_at is None else acknowledged_at
        if not isinstance(acknowledged_at, datetime) or acknowledged_at.utcoffset() is None:
            raise ValueError("Acknowledgement time must be a datetime with timezone")
        placeholders = ",".join("?" for _ in acknowledged)
        parameters = sorted(acknowledged)
        with self.lock, self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            known = {row[0] for row in self.connection.execute(
                f"SELECT event_id FROM telemetry WHERE event_id IN ({placeholders})", parameters
            )}
            if known != acknowledged:
                raise ValueError("Server acknowledged an event missing from the local buffer")
            result = self.connection.execute(
                f"UPDATE telemetry SET sync_status='SYNCED',synced_at=? WHERE event_id IN ({placeholders}) AND sync_status='PENDING'",
                [acknowledged_at.isoformat(), *parameters],
            )
            return result.rowcount

    def close(self):
        with self.lock:
            self.connection.close()


def database_status(path):
    """Query an existing DB, allowing SQLite to recover WAL after a crash."""
    path = Path(path).resolve()
    connection = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(telemetry)")}
        counts = dict(connection.execute("SELECT sync_status,COUNT(*) FROM telemetry GROUP BY sync_status"))
        pump = dict(connection.execute("SELECT * FROM device_state WHERE device_id='pump'").fetchone())
        return {
            "database": str(path), "total": sum(counts.values()),
            "pending": counts.get("PENDING", 0), "synced": counts.get("SYNCED", 0),
            "alerts": connection.execute("SELECT COUNT(*) FROM alerts").fetchone()[0],
            "quarantined": connection.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0],
            "device_actions": connection.execute("SELECT COUNT(*) FROM device_actions").fetchone()[0],
            "classifications": (
                dict(connection.execute("SELECT COALESCE(classification,'UNCLASSIFIED'),COUNT(*) FROM telemetry GROUP BY classification"))
                if "classification" in columns else {"UNCLASSIFIED": sum(counts.values())}
            ),
            "pump": pump,
            "sensors": [dict(row) for row in connection.execute(
                "SELECT sensor_id,COUNT(*) AS records,MAX(sequence) AS max_sequence FROM telemetry GROUP BY sensor_id"
            )],
            "recent_alerts": [dict(row) for row in connection.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT 5")],
            "recent_actions": [dict(row) for row in connection.execute("SELECT * FROM device_actions ORDER BY id DESC LIMIT 5")],
            "sensor_health": [dict(row) for row in connection.execute("SELECT * FROM sensor_health ORDER BY sensor_id")] if "sensor_health" in tables else [],
            "recent_health_events": [dict(row) for row in connection.execute("SELECT * FROM sensor_health_events ORDER BY id DESC LIMIT 10")] if "sensor_health_events" in tables else [],
        }
    finally:
        connection.close()
