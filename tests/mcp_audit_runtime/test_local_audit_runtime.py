"""
test_local_audit_runtime.py — REQ-003 Critical Scenario Tests

Tests the local canonical MCP audit runtime foundation (src/mcp_audit_runtime/).

AC coverage:
  AC-001  Canonical allow → PreToolUse written → dispatch runs → PostToolUse success
  AC-002  Unclassified identity → PreToolUse blocked → no dispatch
  AC-003  Capability mismatch → PreToolUse denied → no dispatch
  AC-004  Pre-dispatch writer failure → no dispatch; no persisted record claim
  AC-005  Tool execution failure → PostToolUseFailure + tool_error
  AC-006  Post-dispatch writer failure → no rollback; audit_integrity_incident
  AC-007  Forbidden raw fields absent from all produced events
  AC-008  SQLite schema triggers block application-level UPDATE and DELETE

Run command (from repo root):
    python -m unittest tests.mcp_audit_runtime.test_local_audit_runtime -v

IMPORTANT: Passing this suite does NOT close any No-Go gate in
SEC-ADR-005-MCP-CONNECTION-PRECONDITIONS.md. No real MCP connection is made.
"""

import sqlite3
import tempfile
import os
import unittest

from src.mcp_audit_runtime.canonicalizer import canonicalize_identity
from src.mcp_audit_runtime.policy_gate import evaluate_policy
from src.mcp_audit_runtime.event_builder import build_event, validate_event
from src.mcp_audit_runtime.sqlite_sink import AuditSink
from src.mcp_audit_runtime.writer import AuditWriter, FailureSignal
from src.mcp_audit_runtime.orchestrator import LifecycleResult, run_lifecycle
from src.mcp_audit_runtime._constants import (
    PROHIBITED_FIELD_NAMES,
    REQUIRED_FIELDS,
)

# ---------------------------------------------------------------------------
# Synthetic test fixtures — no real MCP servers, endpoints, credentials, PII
# ---------------------------------------------------------------------------

KNOWN_SERVER = "example-notes-mcp"
KNOWN_TOOL = "search_sources"
ALLOWED_AGENT = "solution-architect"
ALLOWED_ENV = "n/a"

RESTRICTED_TOOL = "retrieve_note"
DENIED_AGENT = "frontend-engineer"

UNKNOWN_SERVER = "unknown-server-xyz"
UNKNOWN_TOOL = "unknown-tool-xyz"

PRE_EVENT_ID = "test-pre-evt-001"
POST_EVENT_ID = "test-post-evt-001"
TIMESTAMP = "2026-06-26T00:00:00Z"
SESSION_REF = "test-session-ref-001"
OP_REF = "test-op-ref-001"

SYNTHETIC_FORBIDDEN_MARKERS = (
    "SYNTHETIC_INPUT_PAYLOAD",
    "SYNTHETIC_OUTPUT_PAYLOAD",
    "SYNTHETIC_PROMPT_TEXT",
    "https://synthetic-test.invalid",
    "Bearer SYNTHETIC_TOKEN_VALUE",
    "synthetic-user@test.invalid",
    "/synthetic/path/to/file.txt",
    "SyntheticError: test_exception_text",
)


# ---------------------------------------------------------------------------
# Helper: in-process sink that always fails writes (for AC-004, AC-006)
# ---------------------------------------------------------------------------

class _FailingSink:
    """Duck-typed sink whose write_event always returns False."""

    def write_event(self, event: dict) -> bool:
        return False


class _SuccessThenFailSink:
    """Sink that succeeds the first write then fails all subsequent writes."""

    def __init__(self, real_sink: AuditSink) -> None:
        self._real = real_sink
        self._write_count = 0

    def write_event(self, event: dict) -> bool:
        self._write_count += 1
        if self._write_count == 1:
            return self._real.write_event(event)
        return False


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _make_sink(tmp_dir: str, name: str = "audit.db") -> AuditSink:
    return AuditSink(os.path.join(tmp_dir, name))


def _run(sink, simulated_dispatch=None, raw_server=KNOWN_SERVER, raw_tool=KNOWN_TOOL,
         agent_type=ALLOWED_AGENT, env_scope=ALLOWED_ENV,
         pre_id=PRE_EVENT_ID, post_id=POST_EVENT_ID) -> LifecycleResult:
    if simulated_dispatch is None:
        simulated_dispatch = lambda: "ok"
    return run_lifecycle(
        raw_server=raw_server,
        raw_tool=raw_tool,
        agent_type=agent_type,
        environment_scope=env_scope,
        pre_event_id=pre_id,
        post_event_id=post_id,
        timestamp=TIMESTAMP,
        session_reference=SESSION_REF,
        operation_reference=OP_REF,
        sink=sink,
        simulated_dispatch=simulated_dispatch,
    )


def _check_no_forbidden_fields(test_case: unittest.TestCase, events: list) -> None:
    for event in events:
        # No extra fields beyond the closed 15
        test_case.assertEqual(len(event), 15, f"Event has {len(event)} fields, expected 15")
        extra = set(event.keys()) - REQUIRED_FIELDS
        test_case.assertFalse(extra, f"Extra fields in event: {extra}")
        # No prohibited field names
        for name in PROHIBITED_FIELD_NAMES:
            test_case.assertNotIn(name, event, f"Prohibited field {name!r} found in event")
        # No synthetic forbidden markers in any value
        for marker in SYNTHETIC_FORBIDDEN_MARKERS:
            for field_name, value in event.items():
                value_str = value if isinstance(value, str) else str(value)
                test_case.assertNotIn(
                    marker, value_str,
                    f"Forbidden marker {marker!r} found in field {field_name!r}"
                )


# ---------------------------------------------------------------------------
# AC-001: Canonical allow → PreToolUse + dispatch + PostToolUse success
# ---------------------------------------------------------------------------

class TestAC001CanonicalAllowLifecycle(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sink = _make_sink(self.tmp)

    def tearDown(self):
        self.sink.close()

    def test_canonical_allow_full_lifecycle(self):
        dispatch_called = []
        result = _run(self.sink, simulated_dispatch=lambda: dispatch_called.append(True) or "result")

        self.assertTrue(result.dispatch_attempted, "dispatch must be attempted")
        self.assertTrue(result.pre_event_written, "PreToolUse must be written")
        self.assertTrue(result.post_event_written, "PostToolUse must be written")
        self.assertFalse(result.dispatch_tool_failure, "no tool failure expected")
        self.assertIsNone(result.failure_signal, "no failure signal expected")
        self.assertFalse(result.audit_integrity_incident, "no audit incident expected")
        self.assertTrue(dispatch_called, "simulated_dispatch must have been called")

        events = result.events_produced
        self.assertEqual(len(events), 2, "exactly 2 events produced")

        pre = events[0]
        self.assertEqual(pre["event_phase"], "PreToolUse")
        self.assertEqual(pre["policy_decision"], "allow")
        self.assertEqual(pre["outcome"], "success")
        self.assertIsNone(pre["failure_category"])
        self.assertEqual(pre["mcp_server"], KNOWN_SERVER)
        self.assertEqual(pre["mcp_tool"], KNOWN_TOOL)

        post = events[1]
        self.assertEqual(post["event_phase"], "PostToolUse")
        self.assertEqual(post["policy_decision"], "allow")
        self.assertEqual(post["outcome"], "success")
        self.assertIsNone(post["failure_category"])
        self.assertEqual(post["mcp_server"], KNOWN_SERVER)
        self.assertEqual(post["mcp_tool"], KNOWN_TOOL)

        _check_no_forbidden_fields(self, events)


# ---------------------------------------------------------------------------
# AC-002: Unclassified identity → PreToolUse blocked → no dispatch
# ---------------------------------------------------------------------------

class TestAC002UnclassifiedIdentityBlocked(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sink = _make_sink(self.tmp)

    def tearDown(self):
        self.sink.close()

    def test_unclassified_identity_blocked(self):
        dispatch_called = []
        result = _run(
            self.sink,
            simulated_dispatch=lambda: dispatch_called.append(True),
            raw_server=UNKNOWN_SERVER,
            raw_tool=UNKNOWN_TOOL,
        )

        self.assertFalse(result.dispatch_attempted, "dispatch must NOT be attempted")
        self.assertTrue(result.pre_event_written, "PreToolUse must still be written")
        self.assertFalse(result.post_event_written, "no PostToolUse on deny")
        self.assertFalse(dispatch_called, "simulated_dispatch must NOT have been called")
        self.assertIsNone(result.failure_signal, "no failure signal when record was written")
        self.assertFalse(result.audit_integrity_incident)

        events = result.events_produced
        self.assertEqual(len(events), 1)
        pre = events[0]
        self.assertEqual(pre["event_phase"], "PreToolUse")
        self.assertEqual(pre["mcp_server"], "unclassified")
        self.assertEqual(pre["mcp_tool"], "unclassified")
        self.assertEqual(pre["policy_decision"], "deny")
        self.assertEqual(pre["outcome"], "blocked")
        self.assertEqual(pre["failure_category"], "unclassified_tool_identity")

        # Raw server/tool strings must NOT appear in any event field
        for field_name, value in pre.items():
            value_str = value if isinstance(value, str) else str(value)
            self.assertNotIn(UNKNOWN_SERVER, value_str,
                             f"Raw server string leaked into field {field_name!r}")
            self.assertNotIn(UNKNOWN_TOOL, value_str,
                             f"Raw tool string leaked into field {field_name!r}")

        _check_no_forbidden_fields(self, events)


# ---------------------------------------------------------------------------
# AC-003: Capability/policy mismatch → PreToolUse denied → no dispatch
# ---------------------------------------------------------------------------

class TestAC003CapabilityMismatchDenied(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sink = _make_sink(self.tmp)

    def tearDown(self):
        self.sink.close()

    def test_capability_mismatch_denied(self):
        dispatch_called = []
        result = _run(
            self.sink,
            simulated_dispatch=lambda: dispatch_called.append(True),
            raw_server=KNOWN_SERVER,
            raw_tool=RESTRICTED_TOOL,
            agent_type=DENIED_AGENT,
        )

        self.assertFalse(result.dispatch_attempted)
        self.assertTrue(result.pre_event_written)
        self.assertFalse(result.post_event_written)
        self.assertFalse(dispatch_called, "simulated_dispatch must NOT have been called")
        self.assertIsNone(result.failure_signal)

        events = result.events_produced
        self.assertEqual(len(events), 1)
        pre = events[0]
        self.assertEqual(pre["event_phase"], "PreToolUse")
        self.assertEqual(pre["mcp_server"], KNOWN_SERVER)
        self.assertEqual(pre["mcp_tool"], RESTRICTED_TOOL)
        self.assertEqual(pre["policy_decision"], "deny")
        self.assertEqual(pre["outcome"], "denied")
        self.assertEqual(pre["failure_category"], "capability_mismatch")

        _check_no_forbidden_fields(self, events)


# ---------------------------------------------------------------------------
# AC-004: Pre-dispatch writer failure → no dispatch; no persisted record claim
# ---------------------------------------------------------------------------

class TestAC004PreDispatchWriterFailure(unittest.TestCase):

    def test_predispatch_write_failure_blocks_dispatch(self):
        dispatch_called = []
        result = _run(
            _FailingSink(),
            simulated_dispatch=lambda: dispatch_called.append(True),
        )

        self.assertFalse(result.dispatch_attempted, "dispatch must NOT start after write failure")
        self.assertFalse(result.pre_event_written, "pre_event_written must be False")
        self.assertFalse(result.post_event_written)
        self.assertFalse(dispatch_called)
        self.assertIsNotNone(result.failure_signal, "failure signal must be produced")
        self.assertFalse(result.audit_integrity_incident,
                         "pre-dispatch failure is not a post-dispatch incident")
        self.assertEqual(len(result.events_produced), 0,
                         "no events claimed as written on pre-dispatch failure")

        # Failure signal must use a valid closed enum, no free text
        sig = result.failure_signal
        self.assertIsInstance(sig, FailureSignal)
        self.assertIn(sig.failure_category, {
            "audit_unavailable", "unknown",
            "policy_violation", "capability_mismatch",
            "unclassified_tool_identity", "tool_error",
        })


# ---------------------------------------------------------------------------
# AC-005: Tool execution failure → PostToolUseFailure + tool_error
# ---------------------------------------------------------------------------

class TestAC005ToolExecutionFailure(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sink = _make_sink(self.tmp)

    def tearDown(self):
        self.sink.close()

    def test_tool_failure_produces_post_tool_use_failure(self):
        def _failing_dispatch():
            raise RuntimeError("SyntheticError: test_exception_text")

        result = _run(self.sink, simulated_dispatch=_failing_dispatch)

        self.assertTrue(result.dispatch_attempted, "dispatch was attempted")
        self.assertTrue(result.pre_event_written)
        self.assertTrue(result.post_event_written)
        self.assertTrue(result.dispatch_tool_failure)
        self.assertIsNone(result.failure_signal)
        self.assertFalse(result.audit_integrity_incident)

        events = result.events_produced
        self.assertEqual(len(events), 2)

        post = events[1]
        self.assertEqual(post["event_phase"], "PostToolUseFailure")
        self.assertEqual(post["policy_decision"], "allow")
        self.assertEqual(post["outcome"], "failure")
        self.assertEqual(post["failure_category"], "tool_error")

        # Exception text must NOT appear in any event field
        for event in events:
            for field_name, value in event.items():
                value_str = value if isinstance(value, str) else str(value)
                self.assertNotIn("SyntheticError", value_str,
                                 f"Exception text leaked into {field_name!r}")
                self.assertNotIn("test_exception_text", value_str,
                                 f"Exception text leaked into {field_name!r}")

        _check_no_forbidden_fields(self, events)


# ---------------------------------------------------------------------------
# AC-006: Post-dispatch writer failure → no rollback, audit_integrity_incident
# ---------------------------------------------------------------------------

class TestAC006PostDispatchWriterFailure(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.real_sink = _make_sink(self.tmp)
        self.sink = _SuccessThenFailSink(self.real_sink)

    def tearDown(self):
        self.real_sink.close()

    def test_post_dispatch_failure_produces_incident_not_rollback(self):
        dispatch_called = []
        result = _run(
            self.sink,
            simulated_dispatch=lambda: dispatch_called.append(True) or "ok",
        )

        self.assertTrue(result.dispatch_attempted,
                        "dispatch was attempted (cannot be undone)")
        self.assertTrue(result.pre_event_written)
        self.assertFalse(result.post_event_written, "post-dispatch write failed")
        self.assertTrue(dispatch_called, "dispatch did run")
        self.assertTrue(result.audit_integrity_incident,
                        "post-dispatch write failure → audit_integrity_incident")
        self.assertIsNotNone(result.failure_signal)
        # Exactly one event in events_produced (the pre-event that was written)
        self.assertEqual(len(result.events_produced), 1)
        self.assertEqual(result.events_produced[0]["event_phase"], "PreToolUse")


# ---------------------------------------------------------------------------
# AC-007: Forbidden raw fields absent from all produced events
# ---------------------------------------------------------------------------

class TestAC007ForbiddenFieldsAbsent(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sink = _make_sink(self.tmp)

    def tearDown(self):
        self.sink.close()

    def _collect_events(self, **kwargs) -> list:
        result = _run(self.sink, **kwargs)
        return result.events_produced

    def test_allow_path_no_forbidden_fields(self):
        events = self._collect_events(simulated_dispatch=lambda: "ok")
        _check_no_forbidden_fields(self, events)

    def test_blocked_path_no_forbidden_fields(self):
        events = self._collect_events(raw_server=UNKNOWN_SERVER, raw_tool=UNKNOWN_TOOL)
        _check_no_forbidden_fields(self, events)

    def test_denied_path_no_forbidden_fields(self):
        events = self._collect_events(
            raw_server=KNOWN_SERVER, raw_tool=RESTRICTED_TOOL, agent_type=DENIED_AGENT
        )
        _check_no_forbidden_fields(self, events)

    def test_tool_failure_path_no_forbidden_fields(self):
        events = self._collect_events(simulated_dispatch=lambda: (_ for _ in ()).throw(RuntimeError("SyntheticError")))
        _check_no_forbidden_fields(self, events)

    def test_schema_validation_all_events(self):
        events_allow = self._collect_events(simulated_dispatch=lambda: "ok")
        events_blocked = self._collect_events(raw_server=UNKNOWN_SERVER, raw_tool=UNKNOWN_TOOL)
        for event in events_allow + events_blocked:
            violations = validate_event(event)
            self.assertFalse(violations, f"Schema violations: {violations}")


# ---------------------------------------------------------------------------
# AC-008: SQLite schema triggers block UPDATE and DELETE
# ---------------------------------------------------------------------------

class TestAC008SQLiteTriggers(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sink = _make_sink(self.tmp)
        self.db_path = os.path.join(self.tmp, "audit.db")

    def tearDown(self):
        self.sink.close()

    def _write_one_event(self):
        event = build_event(
            event_id="trigger-test-evt-001",
            timestamp=TIMESTAMP,
            session_reference=SESSION_REF,
            operation_reference=OP_REF,
            agent_type=ALLOWED_AGENT,
            event_phase="PreToolUse",
            mcp_server=KNOWN_SERVER,
            mcp_tool=KNOWN_TOOL,
            action_class="evidence_retrieval",
            environment_scope=ALLOWED_ENV,
            policy_decision="allow",
            outcome="success",
            failure_category=None,
        )
        self.assertTrue(self.sink.write_event(event), "Initial write must succeed")

    def test_update_trigger_raises(self):
        self._write_one_event()
        conn = sqlite3.connect(self.db_path)
        try:
            # RAISE(ABORT, ...) in SQLite triggers raises sqlite3.IntegrityError
            with self.assertRaises(sqlite3.DatabaseError) as ctx:
                conn.execute(
                    "UPDATE audit_events SET outcome = 'tampered' WHERE row_id = 1"
                )
                conn.commit()
            self.assertIn("not permitted", str(ctx.exception),
                          f"Expected 'not permitted' in: {ctx.exception}")
        finally:
            conn.close()

    def test_delete_trigger_raises(self):
        self._write_one_event()
        conn = sqlite3.connect(self.db_path)
        try:
            # RAISE(ABORT, ...) in SQLite triggers raises sqlite3.IntegrityError
            with self.assertRaises(sqlite3.DatabaseError) as ctx:
                conn.execute("DELETE FROM audit_events WHERE row_id = 1")
                conn.commit()
            self.assertIn("not permitted", str(ctx.exception),
                          f"Expected 'not permitted' in: {ctx.exception}")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
