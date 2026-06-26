"""
sqlite_sink.py — SQLite Local Audit Sink (ADR-007 §2.4 + §4)

Responsibility: Store canonical audit events in a local SQLite database with
application-level append-only enforcement (triggers) and a SHA-256 hash chain
for integrity ordering.

Design choices:
  - PRAGMA synchronous=FULL: every commit is forced to stable storage before
    returning. This is the basis for application-level durable acknowledgment.
  - Schema triggers block normal application-level UPDATE and DELETE on the
    audit_events table. DROP TABLE and sqlite3 direct writes remain possible
    because this is a local file; external anchoring would be required for
    true tamper-evidence (ADR-007 §4 Kriter 1).
  - Hash chain: each row stores prev_hash (previous row's chain_hash, or
    "genesis" for the first row) and chain_hash = SHA-256(prev_hash + JSON
    payload). This enables ordering verification but is NOT tamper-proof
    without an external checkpoint (ADR-007 §6 item 5).
  - Database path is a caller parameter; tests must use tempfile.mkdtemp().
  - No default audit database is written inside the repository.

SECURITY LIMITS (must be documented per task):
  - SQLite transaction acknowledgment is application-level only. Physical
    durability is subject to OS and hardware guarantees.
  - Triggers block application-level UPDATE/DELETE; they do not prevent
    direct file manipulation, sqlite3 shell access, or DROP TABLE.
  - The hash chain detects ordering anomalies but is not cryptographically
    anchored; it does not satisfy ADR-007 §4 Kriter 1 for production use.
"""

import hashlib
import json
import sqlite3


_DDL_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS audit_events (
    row_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    schema_version      TEXT    NOT NULL,
    event_id            TEXT    NOT NULL UNIQUE,
    timestamp           TEXT    NOT NULL,
    session_reference   TEXT    NOT NULL,
    operation_reference TEXT    NOT NULL,
    agent_type          TEXT    NOT NULL,
    event_phase         TEXT    NOT NULL,
    mcp_server          TEXT    NOT NULL,
    mcp_tool            TEXT    NOT NULL,
    action_class        TEXT    NOT NULL,
    environment_scope   TEXT    NOT NULL,
    policy_decision     TEXT    NOT NULL,
    outcome             TEXT    NOT NULL,
    failure_category    TEXT,
    audit_record_version INTEGER NOT NULL,
    prev_hash           TEXT    NOT NULL,
    chain_hash          TEXT    NOT NULL
)
"""

_DDL_TRIGGER_NO_UPDATE = """
CREATE TRIGGER IF NOT EXISTS prevent_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events: updates are not permitted');
END
"""

_DDL_TRIGGER_NO_DELETE = """
CREATE TRIGGER IF NOT EXISTS prevent_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events: deletes are not permitted');
END
"""

_INSERT_SQL = """
INSERT INTO audit_events (
    schema_version, event_id, timestamp, session_reference,
    operation_reference, agent_type, event_phase, mcp_server, mcp_tool,
    action_class, environment_scope, policy_decision, outcome,
    failure_category, audit_record_version, prev_hash, chain_hash
) VALUES (
    :schema_version, :event_id, :timestamp, :session_reference,
    :operation_reference, :agent_type, :event_phase, :mcp_server, :mcp_tool,
    :action_class, :environment_scope, :policy_decision, :outcome,
    :failure_category, :audit_record_version, :prev_hash, :chain_hash
)
"""

GENESIS_HASH: str = "genesis"


class AuditSink:
    """
    SQLite-backed local audit sink.

    Not thread-safe; intended for single-writer use within one process.
    For production use, a process-level OS permission model and external
    anchoring would be required (ADR-007 §6 items 3-5).
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        with self._conn:
            self._conn.execute(_DDL_CREATE_TABLE)
            self._conn.execute(_DDL_TRIGGER_NO_UPDATE)
            self._conn.execute(_DDL_TRIGGER_NO_DELETE)

    def write_event(self, event: dict) -> bool:
        """
        Write a canonical 15-field audit event to the SQLite database.

        Computes prev_hash and chain_hash, then inserts within a transaction.
        Returns True on successful commit (application-level durable ack).
        Returns False on any error; does not raise.

        The caller (AuditWriter) treats True as the durable write acknowledgment
        required by ADR-007 §2.5 and §3 Step 5.
        """
        try:
            prev_hash = self._get_last_chain_hash()
            chain_hash = self._compute_chain_hash(prev_hash, event)
            row = dict(event)
            row["prev_hash"] = prev_hash
            row["chain_hash"] = chain_hash
            with self._conn:
                self._conn.execute(_INSERT_SQL, row)
            return True
        except Exception:
            return False

    def _get_last_chain_hash(self) -> str:
        cursor = self._conn.execute(
            "SELECT chain_hash FROM audit_events ORDER BY row_id DESC LIMIT 1"
        )
        row = cursor.fetchone()
        return row[0] if row else GENESIS_HASH

    @staticmethod
    def _compute_chain_hash(prev_hash: str, event: dict) -> str:
        payload = json.dumps(event, sort_keys=True, default=str)
        preimage = prev_hash + payload
        return hashlib.sha256(preimage.encode("utf-8")).hexdigest()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
