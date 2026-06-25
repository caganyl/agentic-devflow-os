"""
test_synthetic_audit_lifecycle.py — REQ-001 Synthetic Audit Lifecycle Tests

SCOPE: This test module is TEST-ONLY, OFFLINE, and DETERMINISTIC.

Validates REQ-001 acceptance criteria AC-001 through AC-011 using the
synthetic_audit_harness module. All values are synthetic fixtures; no real
MCP servers, endpoints, credentials, hooks, or network access are involved.

AC coverage:
  AC-001  Known tool identity → canonical classification
  AC-002  Unknown / allowlist-dışı identity → sentinel model, no ham string leak
  AC-003  PermissionDenied vs PostToolUseFailure lifecycle path separation
  AC-004  Closed 15-field schema validation
  AC-005  Forbidden data exclusion (raw input, prompt, URL, token, PII, path, error)
  AC-006  operation_reference collision-resistance (parallel operations)
  AC-007  Error scenarios → deny/blocked (H1 parser, H2 malformed, H3 capability, H4 audit)
  AC-008  Offline and deterministic execution
  AC-009  No real MCP dependency
  AC-010  Explicit PASS/FAIL assertion per scenario
  AC-011  Test evidence record (this suite IS the evidence; human review required)

Run command:
    python -m unittest tests.mcp_hook_lifecycle.test_synthetic_audit_lifecycle -v
Or from repo root:
    python -m unittest discover -s tests/mcp_hook_lifecycle -p "test_*.py" -v

IMPORTANT: Passing this suite does NOT grant permission for a real MCP
connection. Real MCP connection requires separate human maintainer approval
per SEC-ADR-005-MCP-CONNECTION-PRECONDITIONS.md and REQ-001 §Human Approval Gates.
"""

import unittest

from .synthetic_audit_harness import (
    # Schema constants
    REQUIRED_FIELDS,
    SENTINEL_MCP_SERVER,
    SENTINEL_MCP_TOOL,
    SENTINEL_POLICY_DECISION,
    SENTINEL_FAILURE_CATEGORY,
    VALID_AGENT_TYPES,
    VALID_EVENT_PHASES,
    VALID_ACTION_CLASSES,
    VALID_ENVIRONMENT_SCOPES,
    VALID_POLICY_DECISIONS,
    VALID_OUTCOMES,
    VALID_FAILURE_CATEGORIES,
    CANONICAL_LABEL_PATTERN,
    CANONICAL_LABEL_MAX_LEN,
    SYNTHETIC_FORBIDDEN_MARKERS,
    # Scenario constants
    SCENARIO_PRE_TOOL_USE_ALLOWED,
    SCENARIO_PERMISSION_DENIED,
    SCENARIO_POST_TOOL_USE_SUCCESS,
    SCENARIO_POST_TOOL_USE_FAILURE,
    SCENARIO_PARSER_FAILURE,
    SCENARIO_MALFORMED_PAYLOAD,
    SCENARIO_AUDIT_UNAVAILABLE,
    # Functions
    derive_operation_reference,
    classify_tool_identity,
    check_capability,
    process_synthetic_payload,
    validate_audit_event_schema,
    check_for_forbidden_values,
    # Data
    SYNTHETIC_TOOL_ALLOWLIST,
)

# ===========================================================================
# Shared synthetic fixtures
#
# All fixtures use synthetic constant values.
# No real server names, tools, endpoints, credentials, PII, or URLs.
# ===========================================================================

# A known allowlisted tool identity (exists in SYNTHETIC_TOOL_ALLOWLIST)
FIXTURE_KNOWN_TOOL_ALLOWED = {
    "event_id": "test-evt-ac001-001",
    "timestamp": "2026-06-25T10:00:00Z",
    "session_reference": "test-session-ac001",
    "operation_reference": "op-ref-ac001-001",
    "agent_type": "qa-automation",
    "raw_mcp_server": "example-notes-mcp",
    "raw_mcp_tool": "search_sources",
    "environment_scope": "n/a",
}

# An unknown / allowlist-dışı tool identity
FIXTURE_UNKNOWN_TOOL = {
    "event_id": "test-evt-ac002-001",
    "timestamp": "2026-06-25T10:01:00Z",
    "session_reference": "test-session-ac002",
    "operation_reference": "op-ref-ac002-001",
    "agent_type": "qa-automation",
    "raw_mcp_server": "unknown-synthetic-mcp-server",   # NOT in allowlist
    "raw_mcp_tool": "undocumented-synthetic-tool",       # NOT in allowlist
    "environment_scope": "n/a",
}

# PermissionDenied scenario: known tool, allowed agent → user denies permission
FIXTURE_PERMISSION_DENIED = {
    "event_id": "test-evt-ac003-perm-001",
    "timestamp": "2026-06-25T10:02:00Z",
    "session_reference": "test-session-ac003",
    "operation_reference": "op-ref-ac003-perm-001",
    "agent_type": "qa-automation",
    "raw_mcp_server": "example-notes-mcp",
    "raw_mcp_tool": "search_sources",
    "environment_scope": "n/a",
}

# PostToolUseFailure scenario: known tool, allowed agent → execution fails
FIXTURE_POST_TOOL_USE_FAILURE = {
    "event_id": "test-evt-ac003-fail-001",
    "timestamp": "2026-06-25T10:03:00Z",
    "session_reference": "test-session-ac003-fail",
    "operation_reference": "op-ref-ac003-fail-001",
    "agent_type": "qa-automation",
    "raw_mcp_server": "example-notes-mcp",
    "raw_mcp_tool": "retrieve_note",
    "environment_scope": "n/a",
}

# AC-005: fixture with forbidden values in simulation fields.
# The harness MUST NOT propagate any _sim_* field value to the output event.
# These marker values represent different categories of prohibited data.
FIXTURE_WITH_FORBIDDEN_VALUES = {
    "event_id": "test-evt-ac005-001",
    "timestamp": "2026-06-25T10:04:00Z",
    "session_reference": "test-session-ac005",
    "operation_reference": "op-ref-ac005-001",
    "agent_type": "qa-automation",
    "raw_mcp_server": "example-notes-mcp",
    "raw_mcp_tool": "search_sources",
    "environment_scope": "n/a",
    # Simulation fields — present in raw payload but must NOT leak into event:
    "_sim_raw_tool_input": "SYNTHETIC_INPUT_PAYLOAD",
    "_sim_raw_tool_output": "SYNTHETIC_OUTPUT_PAYLOAD",
    "_sim_prompt": "SYNTHETIC_PROMPT_TEXT",
    "_sim_url": "https://synthetic-test.invalid/path",
    "_sim_auth_header": "Bearer SYNTHETIC_TOKEN_VALUE",
    "_sim_pii": "synthetic-user@test.invalid",
    "_sim_file_path": "/synthetic/path/to/file.txt",
    "_sim_exception": "SyntheticError: test_exception_text",
}

# AC-006: Two parallel operations sharing the same session
_SESSION_PARALLEL = "test-session-ac006-parallel"
_OP_REF_PARALLEL_A = derive_operation_reference(
    _SESSION_PARALLEL, "example-notes-mcp", "search_sources", "qa-automation", 1
)
_OP_REF_PARALLEL_B = derive_operation_reference(
    _SESSION_PARALLEL, "example-notes-mcp", "retrieve_note", "qa-automation", 2
)

FIXTURE_PARALLEL_OP_A = {
    "event_id": "test-evt-ac006-opa-001",
    "timestamp": "2026-06-25T10:05:00Z",
    "session_reference": _SESSION_PARALLEL,
    "operation_reference": _OP_REF_PARALLEL_A,
    "agent_type": "qa-automation",
    "raw_mcp_server": "example-notes-mcp",
    "raw_mcp_tool": "search_sources",
    "environment_scope": "n/a",
}

FIXTURE_PARALLEL_OP_B = {
    "event_id": "test-evt-ac006-opb-001",
    "timestamp": "2026-06-25T10:05:01Z",
    "session_reference": _SESSION_PARALLEL,
    "operation_reference": _OP_REF_PARALLEL_B,
    "agent_type": "qa-automation",
    "raw_mcp_server": "example-notes-mcp",
    "raw_mcp_tool": "retrieve_note",
    "environment_scope": "n/a",
}

# AC-007 H1: Parser failure — not a dict
FIXTURE_H1_PARSER_FAILURE = "not-a-dict: this simulates a malformed PreToolUse payload"

# AC-007 H2: Malformed payload — dict missing required keys
FIXTURE_H2_MALFORMED = {
    "event_id": "test-evt-h2-001",
    "timestamp": "2026-06-25T10:06:00Z",
    "session_reference": "test-session-h2",
    "operation_reference": "op-ref-h2-001",
    # raw_mcp_server and raw_mcp_tool are deliberately absent
    # to simulate a malformed PreToolUse payload (AC-007 H2)
}

# AC-007 H3: Capability mismatch — agent not permitted for this tool
FIXTURE_H3_CAPABILITY_MISMATCH = {
    "event_id": "test-evt-h3-001",
    "timestamp": "2026-06-25T10:07:00Z",
    "session_reference": "test-session-h3",
    "operation_reference": "op-ref-h3-001",
    "agent_type": "backend-engineer",      # NOT in allowed_agents for navigate_page
    "raw_mcp_server": "example-browser-mcp",
    "raw_mcp_tool": "navigate_page",        # only allowed for qa-automation
    "environment_scope": "production",      # also wrong scope (allowlist: localhost)
}

# AC-007 H4: Audit unavailable
FIXTURE_H4_AUDIT_UNAVAILABLE = {
    "event_id": "test-evt-h4-001",
    "timestamp": "2026-06-25T10:08:00Z",
    "session_reference": "test-session-h4",
    "operation_reference": "op-ref-h4-001",
    "agent_type": "qa-automation",
    "raw_mcp_server": "example-notes-mcp",
    "raw_mcp_tool": "search_sources",
    "environment_scope": "n/a",
}

# L-001: Isolated environment scope mismatch fixture.
#
# This is SEPARATE from FIXTURE_H3_CAPABILITY_MISMATCH (which tests agent identity
# mismatch: backend-engineer not in allowed_agents).
#
# L-001 tests the case where:
#   - agent_type: "qa-automation"  → CORRECT agent (in allowed_agents for navigate_page)
#   - tool:  example-browser-mcp / navigate_page  (allowlist scope: localhost)
#   - environment_scope: "production"  → WRONG scope (mismatch with allowlist "localhost")
#
# The agent identity check passes; the scope check drives the capability_mismatch deny.
# policy_decision: "deny", outcome: "denied"/"blocked", failure_category: "capability_mismatch",
# dispatch_attempted: False.
FIXTURE_L001_ENV_SCOPE_MISMATCH = {
    "event_id": "test-evt-l001-001",
    "timestamp": "2026-06-25T10:09:00Z",
    "session_reference": "test-session-l001",
    "operation_reference": "op-ref-l001-001",
    "agent_type": "qa-automation",            # correct agent for navigate_page
    "raw_mcp_server": "example-browser-mcp",
    "raw_mcp_tool": "navigate_page",           # allowlist scope: localhost
    "environment_scope": "production",         # wrong scope → capability_mismatch
}


# ===========================================================================
# AC-001 — Known Tool Identity Classification
# ===========================================================================

class TestAC001KnownToolIdentity(unittest.TestCase):
    """
    AC-001: Allowlist'teki bir MCP tool identity, doğru canonical etiketle
    sınıflandırılır.

    Given:  A PreToolUse payload containing a known (server, tool) pair from
            SYNTHETIC_TOOL_ALLOWLIST.
    When:   The payload is processed by the harness.
    Then:   - mcp_server and mcp_tool in the audit event are NOT "unclassified".
            - They match the canonical labels from the allowlist.
            - Both values match the canonical label format (^[a-z0-9][a-z0-9._-]{0,63}$).
            - policy_decision is NOT "deny" and NOT "not_evaluated".
            - The raw payload strings are not blindly copied; they come from
              the canonical allowlist map.
    """

    def setUp(self) -> None:
        self.result = process_synthetic_payload(
            FIXTURE_KNOWN_TOOL_ALLOWED, SCENARIO_PRE_TOOL_USE_ALLOWED
        )
        self.event = self.result.events[0]

    def test_ac001_exactly_one_event_produced(self) -> None:
        """AC-001: Processing a known tool identity produces exactly one audit event."""
        self.assertEqual(
            len(self.result.events),
            1,
            msg=f"Expected 1 event, got {len(self.result.events)}",
        )

    def test_ac001_mcp_server_is_not_unclassified(self) -> None:
        """AC-001: mcp_server is the canonical allowlist label, not 'unclassified'."""
        actual = self.event["mcp_server"]
        self.assertNotEqual(
            actual,
            SENTINEL_MCP_SERVER,
            msg=f"Expected canonical mcp_server, got sentinel {actual!r}",
        )

    def test_ac001_mcp_tool_is_not_unclassified(self) -> None:
        """AC-001: mcp_tool is the canonical allowlist label, not 'unclassified'."""
        actual = self.event["mcp_tool"]
        self.assertNotEqual(
            actual,
            SENTINEL_MCP_TOOL,
            msg=f"Expected canonical mcp_tool, got sentinel {actual!r}",
        )

    def test_ac001_mcp_server_matches_allowlist_canonical_value(self) -> None:
        """AC-001: mcp_server matches the expected canonical value from allowlist."""
        expected = "example-notes-mcp"
        actual = self.event["mcp_server"]
        self.assertEqual(
            actual,
            expected,
            msg=f"mcp_server: expected {expected!r}, got {actual!r}",
        )

    def test_ac001_mcp_tool_matches_allowlist_canonical_value(self) -> None:
        """AC-001: mcp_tool matches the expected canonical value from allowlist."""
        expected = "search_sources"
        actual = self.event["mcp_tool"]
        self.assertEqual(
            actual,
            expected,
            msg=f"mcp_tool: expected {expected!r}, got {actual!r}",
        )

    def test_ac001_mcp_server_canonical_format(self) -> None:
        """AC-001: mcp_server matches the canonical label format."""
        val = self.event["mcp_server"]
        self.assertTrue(
            CANONICAL_LABEL_PATTERN.match(val),
            msg=(
                f"mcp_server {val!r} does not match canonical format "
                f"{CANONICAL_LABEL_PATTERN.pattern!r}"
            ),
        )
        self.assertLessEqual(
            len(val),
            CANONICAL_LABEL_MAX_LEN,
            msg=f"mcp_server {val!r} exceeds {CANONICAL_LABEL_MAX_LEN} characters",
        )

    def test_ac001_mcp_tool_canonical_format(self) -> None:
        """AC-001: mcp_tool matches the canonical label format."""
        val = self.event["mcp_tool"]
        self.assertTrue(
            CANONICAL_LABEL_PATTERN.match(val),
            msg=(
                f"mcp_tool {val!r} does not match canonical format "
                f"{CANONICAL_LABEL_PATTERN.pattern!r}"
            ),
        )
        self.assertLessEqual(
            len(val),
            CANONICAL_LABEL_MAX_LEN,
            msg=f"mcp_tool {val!r} exceeds {CANONICAL_LABEL_MAX_LEN} characters",
        )

    def test_ac001_policy_decision_is_not_deny(self) -> None:
        """AC-001: Successful classification does not produce policy_decision='deny'."""
        actual = self.event["policy_decision"]
        self.assertNotEqual(
            actual,
            "deny",
            msg=f"Expected policy_decision != 'deny' for known allowed tool; got {actual!r}",
        )

    def test_ac001_policy_decision_is_not_not_evaluated(self) -> None:
        """AC-001: Successful classification does not produce policy_decision='not_evaluated'."""
        actual = self.event["policy_decision"]
        self.assertNotEqual(
            actual,
            "not_evaluated",
            msg=f"Expected policy_decision to be evaluated; got {actual!r}",
        )

    def test_ac001_canonical_label_produced_from_allowlist_not_blindcopy(self) -> None:
        """AC-001: Canonical label comes from allowlist map, not from raw payload blindcopy."""
        # Verify by checking the classify_tool_identity function independently
        raw_server = FIXTURE_KNOWN_TOOL_ALLOWED["raw_mcp_server"]
        raw_tool = FIXTURE_KNOWN_TOOL_ALLOWED["raw_mcp_tool"]
        canonical_server, canonical_tool, entry, classified = classify_tool_identity(
            raw_server, raw_tool
        )
        self.assertTrue(
            classified,
            msg=f"Expected ({raw_server!r}, {raw_tool!r}) to be classified",
        )
        self.assertIsNotNone(entry, msg="Entry should not be None for classified tool")
        # The event's mcp_server must equal the allowlist entry's canonical value
        self.assertEqual(
            self.event["mcp_server"],
            entry["mcp_server"],
            msg="mcp_server in event does not match allowlist canonical value",
        )
        self.assertEqual(
            self.event["mcp_tool"],
            entry["mcp_tool"],
            msg="mcp_tool in event does not match allowlist canonical value",
        )


# ===========================================================================
# AC-002 — Unknown / Allowlist-Dışı Tool Identity → Sentinel Model
# ===========================================================================

class TestAC002UnknownToolIdentitySentinel(unittest.TestCase):
    """
    AC-002: Allowlist dışındaki bir tool identity, ham string persist
    edilmeden sentinel değerlerle reddedilir.

    Given:  A PreToolUse payload with a server/tool pair NOT in the allowlist.
    When:   The payload is processed.
    Then:   - mcp_server == "unclassified"
            - mcp_tool == "unclassified"
            - policy_decision == "deny"
            - failure_category == "unclassified_tool_identity"
            - outcome == "blocked" or "denied"
            - The raw unknown strings do NOT appear in any audit event field.
            - dispatch_attempted == False
    """

    def setUp(self) -> None:
        self.raw_server = FIXTURE_UNKNOWN_TOOL["raw_mcp_server"]
        self.raw_tool = FIXTURE_UNKNOWN_TOOL["raw_mcp_tool"]
        self.result = process_synthetic_payload(
            FIXTURE_UNKNOWN_TOOL, SCENARIO_PRE_TOOL_USE_ALLOWED
        )
        self.event = self.result.events[0]

    def test_ac002_mcp_server_is_sentinel(self) -> None:
        """AC-002: mcp_server is the sentinel value 'unclassified'."""
        self.assertEqual(
            self.event["mcp_server"],
            SENTINEL_MCP_SERVER,
            msg=(
                f"Expected mcp_server={SENTINEL_MCP_SERVER!r}, "
                f"got {self.event['mcp_server']!r}"
            ),
        )

    def test_ac002_mcp_tool_is_sentinel(self) -> None:
        """AC-002: mcp_tool is the sentinel value 'unclassified'."""
        self.assertEqual(
            self.event["mcp_tool"],
            SENTINEL_MCP_TOOL,
            msg=(
                f"Expected mcp_tool={SENTINEL_MCP_TOOL!r}, "
                f"got {self.event['mcp_tool']!r}"
            ),
        )

    def test_ac002_policy_decision_is_deny(self) -> None:
        """AC-002: policy_decision is 'deny' for unclassified identity."""
        self.assertEqual(
            self.event["policy_decision"],
            SENTINEL_POLICY_DECISION,
            msg=(
                f"Expected policy_decision={SENTINEL_POLICY_DECISION!r}, "
                f"got {self.event['policy_decision']!r}"
            ),
        )

    def test_ac002_failure_category_is_unclassified_tool_identity(self) -> None:
        """AC-002: failure_category is 'unclassified_tool_identity' for unknown identity."""
        self.assertEqual(
            self.event["failure_category"],
            SENTINEL_FAILURE_CATEGORY,
            msg=(
                f"Expected failure_category={SENTINEL_FAILURE_CATEGORY!r}, "
                f"got {self.event['failure_category']!r}"
            ),
        )

    def test_ac002_outcome_is_blocked_or_denied(self) -> None:
        """AC-002: outcome is 'blocked' or 'denied' for unclassified identity."""
        actual = self.event["outcome"]
        self.assertIn(
            actual,
            {"blocked", "denied"},
            msg=f"Expected outcome in {{'blocked', 'denied'}}, got {actual!r}",
        )

    def test_ac002_raw_server_string_not_in_event(self) -> None:
        """AC-002: The raw unknown server string does NOT appear in any event field."""
        for field_name, field_value in self.event.items():
            if isinstance(field_value, str):
                self.assertNotIn(
                    self.raw_server,
                    field_value,
                    msg=(
                        f"Raw server string {self.raw_server!r} leaked into "
                        f"event field {field_name!r}: {field_value!r}"
                    ),
                )

    def test_ac002_raw_tool_string_not_in_event(self) -> None:
        """AC-002: The raw unknown tool string does NOT appear in any event field."""
        for field_name, field_value in self.event.items():
            if isinstance(field_value, str):
                self.assertNotIn(
                    self.raw_tool,
                    field_value,
                    msg=(
                        f"Raw tool string {self.raw_tool!r} leaked into "
                        f"event field {field_name!r}: {field_value!r}"
                    ),
                )

    def test_ac002_dispatch_not_attempted(self) -> None:
        """AC-002: External dispatch is NOT attempted for unclassified identity."""
        self.assertFalse(
            self.result.dispatch_attempted,
            msg="dispatch_attempted must be False for unclassified tool identity",
        )

    def test_ac002_classify_function_returns_not_classified(self) -> None:
        """AC-002: classify_tool_identity returns classified=False for unknown pair."""
        _, _, entry, classified = classify_tool_identity(self.raw_server, self.raw_tool)
        self.assertFalse(
            classified,
            msg=(
                f"classify_tool_identity({self.raw_server!r}, {self.raw_tool!r}) "
                f"should return classified=False"
            ),
        )
        self.assertIsNone(
            entry,
            msg="entry should be None for unclassified tool",
        )


# ===========================================================================
# AC-003 — PermissionDenied vs PostToolUseFailure Lifecycle Path Separation
# ===========================================================================

class TestAC003LifecyclePathSeparation(unittest.TestCase):
    """
    AC-003: PermissionDenied and PostToolUseFailure are separate, non-reducible
    lifecycle paths. Scenario A (PermissionDenied) must NOT produce PostToolUse
    or PostToolUseFailure events. Scenario B (PostToolUseFailure) must NOT produce
    PermissionDenied events.

    Scenario A (PermissionDenied):
        Tool is permitted by policy but denied by user/config permission.
        Tool NEVER runs. PostToolUse and PostToolUseFailure are NOT produced.

    Scenario B (PostToolUseFailure):
        Tool ran (dispatch_attempted=True) but execution failed.
        PermissionDenied is NOT produced.
    """

    def setUp(self) -> None:
        self.result_a = process_synthetic_payload(
            FIXTURE_PERMISSION_DENIED, SCENARIO_PERMISSION_DENIED
        )
        self.result_b = process_synthetic_payload(
            FIXTURE_POST_TOOL_USE_FAILURE, SCENARIO_POST_TOOL_USE_FAILURE
        )
        self.event_a = self.result_a.events[0]
        self.event_b = self.result_b.events[0]

    # --- Scenario A: PermissionDenied ---

    def test_ac003_scenario_a_event_phase_is_permission_denied(self) -> None:
        """AC-003 Scenario A: event_phase is 'PermissionDenied'."""
        self.assertEqual(
            self.event_a["event_phase"],
            "PermissionDenied",
            msg=f"Expected event_phase='PermissionDenied', got {self.event_a['event_phase']!r}",
        )

    def test_ac003_scenario_a_outcome_is_denied(self) -> None:
        """AC-003 Scenario A: outcome is 'denied' (tool never ran)."""
        self.assertEqual(
            self.event_a["outcome"],
            "denied",
            msg=f"Expected outcome='denied', got {self.event_a['outcome']!r}",
        )

    def test_ac003_scenario_a_policy_decision_is_deny(self) -> None:
        """AC-003 Scenario A: policy_decision is 'deny'."""
        self.assertEqual(
            self.event_a["policy_decision"],
            "deny",
            msg=f"Expected policy_decision='deny', got {self.event_a['policy_decision']!r}",
        )

    def test_ac003_scenario_a_no_post_tool_use_phase(self) -> None:
        """AC-003 Scenario A: PostToolUse event is NOT produced."""
        self.assertNotIn(
            "PostToolUse",
            self.result_a.lifecycle_phases,
            msg=(
                "PostToolUse must NOT appear in PermissionDenied lifecycle; "
                f"got phases: {self.result_a.lifecycle_phases!r}"
            ),
        )

    def test_ac003_scenario_a_no_post_tool_use_failure_phase(self) -> None:
        """AC-003 Scenario A: PostToolUseFailure event is NOT produced."""
        self.assertNotIn(
            "PostToolUseFailure",
            self.result_a.lifecycle_phases,
            msg=(
                "PostToolUseFailure must NOT appear in PermissionDenied lifecycle; "
                f"got phases: {self.result_a.lifecycle_phases!r}"
            ),
        )

    def test_ac003_scenario_a_dispatch_not_attempted(self) -> None:
        """AC-003 Scenario A: External dispatch is NOT attempted (tool never ran)."""
        self.assertFalse(
            self.result_a.dispatch_attempted,
            msg="dispatch_attempted must be False in PermissionDenied scenario",
        )

    # --- Scenario B: PostToolUseFailure ---

    def test_ac003_scenario_b_event_phase_is_post_tool_use_failure(self) -> None:
        """AC-003 Scenario B: event_phase is 'PostToolUseFailure'."""
        self.assertEqual(
            self.event_b["event_phase"],
            "PostToolUseFailure",
            msg=(
                f"Expected event_phase='PostToolUseFailure', "
                f"got {self.event_b['event_phase']!r}"
            ),
        )

    def test_ac003_scenario_b_outcome_is_failure(self) -> None:
        """AC-003 Scenario B: outcome is 'failure' (tool ran but failed)."""
        self.assertEqual(
            self.event_b["outcome"],
            "failure",
            msg=f"Expected outcome='failure', got {self.event_b['outcome']!r}",
        )

    def test_ac003_scenario_b_no_permission_denied_phase(self) -> None:
        """AC-003 Scenario B: PermissionDenied event is NOT produced."""
        self.assertNotIn(
            "PermissionDenied",
            self.result_b.lifecycle_phases,
            msg=(
                "PermissionDenied must NOT appear in PostToolUseFailure lifecycle; "
                f"got phases: {self.result_b.lifecycle_phases!r}"
            ),
        )

    def test_ac003_scenario_b_dispatch_was_attempted(self) -> None:
        """AC-003 Scenario B: External dispatch WAS attempted (tool started running)."""
        self.assertTrue(
            self.result_b.dispatch_attempted,
            msg="dispatch_attempted must be True in PostToolUseFailure scenario (tool ran)",
        )

    def test_ac003_lifecycle_paths_have_different_event_phases(self) -> None:
        """AC-003: The two lifecycle scenarios produce different event_phase values."""
        self.assertNotEqual(
            self.event_a["event_phase"],
            self.event_b["event_phase"],
            msg=(
                "PermissionDenied and PostToolUseFailure scenarios must produce "
                "different event_phase values (lifecycle paths must not merge)"
            ),
        )


# ===========================================================================
# AC-004 — Closed 15-Field Schema Validation
# ===========================================================================

class TestAC004ClosedSchemaValidation(unittest.TestCase):
    """
    AC-004: Every produced audit event has exactly 15 fields — no fewer,
    no more. All 15 required fields are present; no extra fields exist.
    failure_category is present (may be None) even when outcome is not
    'failure' or 'blocked', so the field count stays at 15.
    """

    # Scenarios to validate — one event each
    _SCENARIO_FIXTURES = [
        ("PreToolUseAllowed", FIXTURE_KNOWN_TOOL_ALLOWED, SCENARIO_PRE_TOOL_USE_ALLOWED),
        ("PermissionDenied", FIXTURE_PERMISSION_DENIED, SCENARIO_PERMISSION_DENIED),
        ("PostToolUseSuccess", FIXTURE_KNOWN_TOOL_ALLOWED, SCENARIO_POST_TOOL_USE_SUCCESS),
        ("PostToolUseFailure", FIXTURE_POST_TOOL_USE_FAILURE, SCENARIO_POST_TOOL_USE_FAILURE),
        ("UnknownIdentity", FIXTURE_UNKNOWN_TOOL, SCENARIO_PRE_TOOL_USE_ALLOWED),
        ("ParserFailure", FIXTURE_H1_PARSER_FAILURE, SCENARIO_PARSER_FAILURE),
        ("MalformedPayload", FIXTURE_H2_MALFORMED, SCENARIO_MALFORMED_PAYLOAD),
        ("AuditUnavailable", FIXTURE_H4_AUDIT_UNAVAILABLE, SCENARIO_AUDIT_UNAVAILABLE),
    ]

    def _assert_schema_valid(self, label: str, event: dict) -> None:
        """Helper: validate a single event and assert no violations."""
        violations = validate_audit_event_schema(event)
        self.assertEqual(
            violations,
            [],
            msg=(
                f"Schema violations in {label!r} event: {violations!r}\n"
                f"Event fields: {sorted(event.keys())!r}"
            ),
        )

    def test_ac004_field_count_is_15_for_pre_tool_use_allowed(self) -> None:
        """AC-004: PreToolUse (allowed) event has exactly 15 fields."""
        result = process_synthetic_payload(FIXTURE_KNOWN_TOOL_ALLOWED, SCENARIO_PRE_TOOL_USE_ALLOWED)
        event = result.events[0]
        self.assertEqual(
            len(event),
            15,
            msg=f"Expected 15 fields, got {len(event)}: {sorted(event.keys())!r}",
        )

    def test_ac004_all_required_fields_present_for_known_tool(self) -> None:
        """AC-004: All 15 required fields are present in a known-tool event."""
        result = process_synthetic_payload(FIXTURE_KNOWN_TOOL_ALLOWED, SCENARIO_PRE_TOOL_USE_ALLOWED)
        event = result.events[0]
        missing = REQUIRED_FIELDS - set(event.keys())
        self.assertEqual(
            missing,
            set(),
            msg=f"Missing required fields: {sorted(missing)!r}",
        )

    def test_ac004_failure_category_present_even_when_null(self) -> None:
        """AC-004: failure_category field is present (not absent) even when None."""
        result = process_synthetic_payload(FIXTURE_KNOWN_TOOL_ALLOWED, SCENARIO_PRE_TOOL_USE_ALLOWED)
        event = result.events[0]
        self.assertIn(
            "failure_category",
            event,
            msg="failure_category must be present as a key (even if None)",
        )
        # Field count must still be 15 (not 14)
        self.assertEqual(
            len(event),
            15,
            msg=(
                f"Field count dropped to {len(event)} when failure_category is None; "
                "expected 15"
            ),
        )

    def test_ac004_no_extra_fields_in_any_scenario(self) -> None:
        """AC-004: No scenario produces audit events with fields beyond the 15."""
        for label, fixture, scenario in self._SCENARIO_FIXTURES:
            with self.subTest(scenario=label):
                result = process_synthetic_payload(fixture, scenario)
                for event in result.events:
                    extra = set(event.keys()) - REQUIRED_FIELDS
                    self.assertEqual(
                        extra,
                        set(),
                        msg=(
                            f"Scenario {label!r}: extra fields found: {sorted(extra)!r}"
                        ),
                    )

    def test_ac004_schema_valid_for_all_scenarios(self) -> None:
        """AC-004: validate_audit_event_schema() reports zero violations for all scenarios."""
        for label, fixture, scenario in self._SCENARIO_FIXTURES:
            with self.subTest(scenario=label):
                result = process_synthetic_payload(fixture, scenario)
                for event in result.events:
                    self._assert_schema_valid(label, event)

    def test_ac004_prohibited_field_names_absent(self) -> None:
        """AC-004: Fields like 'note', 'error_message', 'prompt', 'url', etc. are absent."""
        prohibited_samples = {
            "note", "notes", "message", "error_message", "details",
            "description", "context", "metadata", "debug", "prompt",
            "url", "header", "file_path", "exception", "raw_input",
            "raw_output", "tool_input", "tool_output", "reason",
        }
        for label, fixture, scenario in self._SCENARIO_FIXTURES:
            with self.subTest(scenario=label):
                result = process_synthetic_payload(fixture, scenario)
                for event in result.events:
                    present = prohibited_samples & set(event.keys())
                    self.assertEqual(
                        present,
                        set(),
                        msg=(
                            f"Scenario {label!r}: prohibited field names found: "
                            f"{sorted(present)!r}"
                        ),
                    )


# ===========================================================================
# AC-005 — Forbidden Data Exclusion
# ===========================================================================

class TestAC005ForbiddenDataExclusion(unittest.TestCase):
    """
    AC-005: Audit events must not contain raw tool input/output, prompt, URL,
    Authorization header, token/secret, PII, file path, or exception text —
    even when the raw payload contains such (synthetic) values in additional
    fields.

    The harness extracts only the 8 known payload keys; all other payload
    fields are ignored. The resulting event contains only the closed 15-field
    schema with enum/canonical values.
    """

    def setUp(self) -> None:
        self.result = process_synthetic_payload(
            FIXTURE_WITH_FORBIDDEN_VALUES, SCENARIO_PRE_TOOL_USE_ALLOWED
        )
        self.event = self.result.events[0]

    def test_ac005_no_synthetic_input_payload_in_event(self) -> None:
        """AC-005: 'SYNTHETIC_INPUT_PAYLOAD' (raw tool input sim) not in any event field."""
        violations = check_for_forbidden_values(self.event, ("SYNTHETIC_INPUT_PAYLOAD",))
        self.assertEqual(
            violations,
            [],
            msg=f"Raw tool input marker leaked into event: {violations!r}",
        )

    def test_ac005_no_synthetic_output_payload_in_event(self) -> None:
        """AC-005: 'SYNTHETIC_OUTPUT_PAYLOAD' (raw tool output sim) not in any event field."""
        violations = check_for_forbidden_values(self.event, ("SYNTHETIC_OUTPUT_PAYLOAD",))
        self.assertEqual(
            violations,
            [],
            msg=f"Raw tool output marker leaked into event: {violations!r}",
        )

    def test_ac005_no_synthetic_prompt_in_event(self) -> None:
        """AC-005: 'SYNTHETIC_PROMPT_TEXT' (prompt content sim) not in any event field."""
        violations = check_for_forbidden_values(self.event, ("SYNTHETIC_PROMPT_TEXT",))
        self.assertEqual(
            violations,
            [],
            msg=f"Prompt content marker leaked into event: {violations!r}",
        )

    def test_ac005_no_synthetic_url_in_event(self) -> None:
        """AC-005: Synthetic URL marker not in any event field."""
        violations = check_for_forbidden_values(
            self.event, ("https://synthetic-test.invalid",)
        )
        self.assertEqual(
            violations,
            [],
            msg=f"URL marker leaked into event: {violations!r}",
        )

    def test_ac005_no_bearer_token_in_event(self) -> None:
        """AC-005: 'Bearer SYNTHETIC_TOKEN_VALUE' (auth header sim) not in any event field."""
        violations = check_for_forbidden_values(
            self.event, ("Bearer SYNTHETIC_TOKEN_VALUE",)
        )
        self.assertEqual(
            violations,
            [],
            msg=f"Auth header/token marker leaked into event: {violations!r}",
        )

    def test_ac005_no_pii_in_event(self) -> None:
        """AC-005: Synthetic PII (email sim) not in any event field."""
        violations = check_for_forbidden_values(
            self.event, ("synthetic-user@test.invalid",)
        )
        self.assertEqual(
            violations,
            [],
            msg=f"PII marker leaked into event: {violations!r}",
        )

    def test_ac005_no_file_path_in_event(self) -> None:
        """AC-005: Synthetic file path not in any event field."""
        violations = check_for_forbidden_values(
            self.event, ("/synthetic/path/to/file.txt",)
        )
        self.assertEqual(
            violations,
            [],
            msg=f"File path marker leaked into event: {violations!r}",
        )

    def test_ac005_no_exception_text_in_event(self) -> None:
        """AC-005: Synthetic exception text not in any event field."""
        violations = check_for_forbidden_values(
            self.event, ("SyntheticError: test_exception_text",)
        )
        self.assertEqual(
            violations,
            [],
            msg=f"Exception text leaked into event: {violations!r}",
        )

    def test_ac005_all_forbidden_markers_absent(self) -> None:
        """AC-005: None of the SYNTHETIC_FORBIDDEN_MARKERS appear in the event (batch check)."""
        violations = check_for_forbidden_values(self.event, SYNTHETIC_FORBIDDEN_MARKERS)
        self.assertEqual(
            violations,
            [],
            msg=(
                f"Forbidden data markers found in event: {violations!r}\n"
                f"Event: {self.event!r}"
            ),
        )

    def test_ac005_event_fields_contain_only_schema_values(self) -> None:
        """AC-005: The event contains exactly 15 schema fields and no serbest metin fields."""
        schema_violations = validate_audit_event_schema(self.event)
        self.assertEqual(
            schema_violations,
            [],
            msg=f"Schema violations: {schema_violations!r}",
        )


# ===========================================================================
# AC-006 — operation_reference Collision-Resistance
# ===========================================================================

class TestAC006OperationReferenceCollisionResistance(unittest.TestCase):
    """
    AC-006: Parallel operations in the same session have different, non-colliding
    operation_reference values. Each operation's lifecycle events carry only that
    operation's reference.
    """

    def setUp(self) -> None:
        self.result_a = process_synthetic_payload(
            FIXTURE_PARALLEL_OP_A, SCENARIO_PRE_TOOL_USE_ALLOWED
        )
        self.result_b = process_synthetic_payload(
            FIXTURE_PARALLEL_OP_B, SCENARIO_PRE_TOOL_USE_ALLOWED
        )
        self.event_a = self.result_a.events[0]
        self.event_b = self.result_b.events[0]

    def test_ac006_derive_different_op_refs_for_different_sequences(self) -> None:
        """AC-006: derive_operation_reference produces different values for different sequences."""
        session = "test-session-ac006-derive"
        op_ref_1 = derive_operation_reference(session, "example-notes-mcp", "search_sources", "qa-automation", 1)
        op_ref_2 = derive_operation_reference(session, "example-notes-mcp", "search_sources", "qa-automation", 2)
        self.assertNotEqual(
            op_ref_1,
            op_ref_2,
            msg=(
                f"operation_reference for sequence=1 and sequence=2 must differ; "
                f"both produced {op_ref_1!r}"
            ),
        )

    def test_ac006_parallel_op_refs_are_different(self) -> None:
        """AC-006: The two parallel operation_references do not collide."""
        self.assertNotEqual(
            _OP_REF_PARALLEL_A,
            _OP_REF_PARALLEL_B,
            msg=(
                f"Parallel operation_references must differ; "
                f"A={_OP_REF_PARALLEL_A!r}, B={_OP_REF_PARALLEL_B!r}"
            ),
        )

    def test_ac006_event_a_carries_op_ref_a(self) -> None:
        """AC-006: Operation A's event carries operation_reference A (not B)."""
        self.assertEqual(
            self.event_a["operation_reference"],
            _OP_REF_PARALLEL_A,
            msg=(
                f"Event A expected operation_reference={_OP_REF_PARALLEL_A!r}, "
                f"got {self.event_a['operation_reference']!r}"
            ),
        )

    def test_ac006_event_b_carries_op_ref_b(self) -> None:
        """AC-006: Operation B's event carries operation_reference B (not A)."""
        self.assertEqual(
            self.event_b["operation_reference"],
            _OP_REF_PARALLEL_B,
            msg=(
                f"Event B expected operation_reference={_OP_REF_PARALLEL_B!r}, "
                f"got {self.event_b['operation_reference']!r}"
            ),
        )

    def test_ac006_event_a_does_not_carry_op_ref_b(self) -> None:
        """AC-006: Operation A's event does NOT carry operation_reference B (no cross-contamination)."""
        self.assertNotEqual(
            self.event_a["operation_reference"],
            _OP_REF_PARALLEL_B,
            msg="Operation A's event must not carry Operation B's operation_reference",
        )

    def test_ac006_event_b_does_not_carry_op_ref_a(self) -> None:
        """AC-006: Operation B's event does NOT carry operation_reference A (no cross-contamination)."""
        self.assertNotEqual(
            self.event_b["operation_reference"],
            _OP_REF_PARALLEL_A,
            msg="Operation B's event must not carry Operation A's operation_reference",
        )

    def test_ac006_both_share_same_session_reference(self) -> None:
        """AC-006: Both parallel operations share the same session_reference."""
        self.assertEqual(
            self.event_a["session_reference"],
            _SESSION_PARALLEL,
            msg="Event A should carry the shared session_reference",
        )
        self.assertEqual(
            self.event_b["session_reference"],
            _SESSION_PARALLEL,
            msg="Event B should carry the shared session_reference",
        )

    def test_ac006_derive_is_deterministic(self) -> None:
        """AC-006: derive_operation_reference is deterministic (same input → same output)."""
        ref1 = derive_operation_reference("s", "srv", "tool", "agent", 7)
        ref2 = derive_operation_reference("s", "srv", "tool", "agent", 7)
        self.assertEqual(
            ref1,
            ref2,
            msg="derive_operation_reference must be deterministic",
        )

    def test_ac006_op_ref_format_starts_with_prefix(self) -> None:
        """AC-006: derive_operation_reference output starts with 'op-ref-' prefix."""
        ref = derive_operation_reference("s", "srv", "tool", "agent", 1)
        self.assertTrue(
            ref.startswith("op-ref-"),
            msg=f"operation_reference should start with 'op-ref-', got {ref!r}",
        )


# ===========================================================================
# AC-007 — Error Scenarios → Deny / Blocked
# ===========================================================================

class TestAC007ErrorScenariosDenyBlocked(unittest.TestCase):
    """
    AC-007: Parser failure (H1), malformed payload (H2), capability mismatch (H3),
    and audit unavailable (H4) all produce deny/blocked outcomes without external
    dispatch. Each produces the correct failure_category enum value.
    """

    # --- H1: Parser failure ---

    def test_ac007_h1_parser_failure_produces_blocked_outcome(self) -> None:
        """AC-007 H1: Non-dict payload produces outcome='blocked'."""
        result = process_synthetic_payload(FIXTURE_H1_PARSER_FAILURE, SCENARIO_PARSER_FAILURE)
        event = result.events[0]
        self.assertEqual(
            event["outcome"],
            "blocked",
            msg=f"H1: Expected outcome='blocked', got {event['outcome']!r}",
        )

    def test_ac007_h1_parser_failure_produces_deny_decision(self) -> None:
        """AC-007 H1: Non-dict payload produces policy_decision='deny'."""
        result = process_synthetic_payload(FIXTURE_H1_PARSER_FAILURE, SCENARIO_PARSER_FAILURE)
        event = result.events[0]
        self.assertEqual(
            event["policy_decision"],
            "deny",
            msg=f"H1: Expected policy_decision='deny', got {event['policy_decision']!r}",
        )

    def test_ac007_h1_parser_failure_category_is_unclassified_tool_identity(self) -> None:
        """AC-007 H1: failure_category is exactly 'unclassified_tool_identity'.

        M-002 (Security Red Team): Use exact assertEqual instead of a broad assertIn
        to prevent alternative enum values from being silently accepted.
        Parser failure cannot classify tool identity → sentinel failure_category applies.
        """
        result = process_synthetic_payload(FIXTURE_H1_PARSER_FAILURE, SCENARIO_PARSER_FAILURE)
        event = result.events[0]
        self.assertEqual(
            event["failure_category"],
            "unclassified_tool_identity",
            msg=(
                f"H1: failure_category must be exactly 'unclassified_tool_identity', "
                f"got {event['failure_category']!r}"
            ),
        )

    def test_ac007_h1_no_raw_error_text_in_event(self) -> None:
        """AC-007 H1: No raw exception/error text appears in any event field."""
        result = process_synthetic_payload(FIXTURE_H1_PARSER_FAILURE, SCENARIO_PARSER_FAILURE)
        event = result.events[0]
        # The raw_payload was a plain string; verify it didn't leak
        for field_name, field_value in event.items():
            if isinstance(field_value, str):
                self.assertNotIn(
                    "not-a-dict",
                    field_value,
                    msg=(
                        f"H1: Raw payload string leaked into event field "
                        f"{field_name!r}: {field_value!r}"
                    ),
                )

    def test_ac007_h1_dispatch_not_attempted(self) -> None:
        """AC-007 H1: External dispatch is NOT attempted after parser failure."""
        result = process_synthetic_payload(FIXTURE_H1_PARSER_FAILURE, SCENARIO_PARSER_FAILURE)
        self.assertFalse(
            result.dispatch_attempted,
            msg="H1: dispatch_attempted must be False after parser failure",
        )

    def test_ac007_h1_schema_valid(self) -> None:
        """AC-007 H1: The denial event still conforms to the closed 15-field schema."""
        result = process_synthetic_payload(FIXTURE_H1_PARSER_FAILURE, SCENARIO_PARSER_FAILURE)
        violations = validate_audit_event_schema(result.events[0])
        self.assertEqual(violations, [], msg=f"H1 schema violations: {violations!r}")

    # --- H2: Malformed payload ---

    def test_ac007_h2_malformed_payload_produces_blocked_outcome(self) -> None:
        """AC-007 H2: Payload missing required keys produces outcome='blocked'."""
        result = process_synthetic_payload(FIXTURE_H2_MALFORMED, SCENARIO_MALFORMED_PAYLOAD)
        event = result.events[0]
        self.assertEqual(
            event["outcome"],
            "blocked",
            msg=f"H2: Expected outcome='blocked', got {event['outcome']!r}",
        )

    def test_ac007_h2_malformed_payload_produces_deny_decision(self) -> None:
        """AC-007 H2: Payload missing required keys produces policy_decision='deny'."""
        result = process_synthetic_payload(FIXTURE_H2_MALFORMED, SCENARIO_MALFORMED_PAYLOAD)
        event = result.events[0]
        self.assertEqual(
            event["policy_decision"],
            "deny",
            msg=f"H2: Expected policy_decision='deny', got {event['policy_decision']!r}",
        )

    def test_ac007_h2_failure_category_is_unclassified_tool_identity(self) -> None:
        """AC-007 H2: failure_category is exactly 'unclassified_tool_identity'.

        M-002 (Security Red Team): Use exact assertEqual instead of a broad assertIn
        to prevent alternative enum values from being silently accepted.
        Malformed payload cannot classify tool identity → sentinel failure_category applies.
        """
        result = process_synthetic_payload(FIXTURE_H2_MALFORMED, SCENARIO_MALFORMED_PAYLOAD)
        event = result.events[0]
        self.assertEqual(
            event["failure_category"],
            "unclassified_tool_identity",
            msg=(
                f"H2: failure_category must be exactly 'unclassified_tool_identity', "
                f"got {event['failure_category']!r}"
            ),
        )

    def test_ac007_h2_dispatch_not_attempted(self) -> None:
        """AC-007 H2: External dispatch is NOT attempted after malformed payload."""
        result = process_synthetic_payload(FIXTURE_H2_MALFORMED, SCENARIO_MALFORMED_PAYLOAD)
        self.assertFalse(
            result.dispatch_attempted,
            msg="H2: dispatch_attempted must be False after malformed payload",
        )

    def test_ac007_h2_schema_valid(self) -> None:
        """AC-007 H2: The denial event conforms to the closed 15-field schema."""
        result = process_synthetic_payload(FIXTURE_H2_MALFORMED, SCENARIO_MALFORMED_PAYLOAD)
        violations = validate_audit_event_schema(result.events[0])
        self.assertEqual(violations, [], msg=f"H2 schema violations: {violations!r}")

    # --- H3: Capability mismatch ---

    def test_ac007_h3_capability_mismatch_produces_denied_outcome(self) -> None:
        """AC-007 H3: Agent not permitted for tool produces outcome='denied'."""
        result = process_synthetic_payload(FIXTURE_H3_CAPABILITY_MISMATCH, SCENARIO_PRE_TOOL_USE_ALLOWED)
        event = result.events[0]
        self.assertIn(
            event["outcome"],
            {"denied", "blocked"},
            msg=f"H3: Expected outcome in {{'denied','blocked'}}, got {event['outcome']!r}",
        )

    def test_ac007_h3_capability_mismatch_produces_deny_decision(self) -> None:
        """AC-007 H3: Capability mismatch produces policy_decision='deny'."""
        result = process_synthetic_payload(FIXTURE_H3_CAPABILITY_MISMATCH, SCENARIO_PRE_TOOL_USE_ALLOWED)
        event = result.events[0]
        self.assertEqual(
            event["policy_decision"],
            "deny",
            msg=f"H3: Expected policy_decision='deny', got {event['policy_decision']!r}",
        )

    def test_ac007_h3_failure_category_is_capability_mismatch(self) -> None:
        """AC-007 H3: failure_category is 'capability_mismatch'."""
        result = process_synthetic_payload(FIXTURE_H3_CAPABILITY_MISMATCH, SCENARIO_PRE_TOOL_USE_ALLOWED)
        event = result.events[0]
        self.assertEqual(
            event["failure_category"],
            "capability_mismatch",
            msg=(
                f"H3: Expected failure_category='capability_mismatch', "
                f"got {event['failure_category']!r}"
            ),
        )

    def test_ac007_h3_dispatch_not_attempted(self) -> None:
        """AC-007 H3: External dispatch is NOT attempted after capability mismatch."""
        result = process_synthetic_payload(FIXTURE_H3_CAPABILITY_MISMATCH, SCENARIO_PRE_TOOL_USE_ALLOWED)
        self.assertFalse(
            result.dispatch_attempted,
            msg="H3: dispatch_attempted must be False after capability mismatch",
        )

    def test_ac007_h3_schema_valid(self) -> None:
        """AC-007 H3: The denial event conforms to the closed 15-field schema."""
        result = process_synthetic_payload(FIXTURE_H3_CAPABILITY_MISMATCH, SCENARIO_PRE_TOOL_USE_ALLOWED)
        violations = validate_audit_event_schema(result.events[0])
        self.assertEqual(violations, [], msg=f"H3 schema violations: {violations!r}")

    # --- H4: Audit unavailable ---

    def test_ac007_h4_audit_unavailable_produces_blocked_outcome(self) -> None:
        """AC-007 H4: Simulated audit sink failure produces outcome='blocked'."""
        result = process_synthetic_payload(FIXTURE_H4_AUDIT_UNAVAILABLE, SCENARIO_AUDIT_UNAVAILABLE)
        event = result.events[0]
        self.assertEqual(
            event["outcome"],
            "blocked",
            msg=f"H4: Expected outcome='blocked', got {event['outcome']!r}",
        )

    def test_ac007_h4_audit_unavailable_produces_deny_decision(self) -> None:
        """AC-007 H4: Simulated audit sink failure produces policy_decision='deny'."""
        result = process_synthetic_payload(FIXTURE_H4_AUDIT_UNAVAILABLE, SCENARIO_AUDIT_UNAVAILABLE)
        event = result.events[0]
        self.assertEqual(
            event["policy_decision"],
            "deny",
            msg=f"H4: Expected policy_decision='deny', got {event['policy_decision']!r}",
        )

    def test_ac007_h4_failure_category_is_audit_unavailable(self) -> None:
        """AC-007 H4: failure_category is 'audit_unavailable'."""
        result = process_synthetic_payload(FIXTURE_H4_AUDIT_UNAVAILABLE, SCENARIO_AUDIT_UNAVAILABLE)
        event = result.events[0]
        self.assertEqual(
            event["failure_category"],
            "audit_unavailable",
            msg=(
                f"H4: Expected failure_category='audit_unavailable', "
                f"got {event['failure_category']!r}"
            ),
        )

    def test_ac007_h4_dispatch_not_attempted(self) -> None:
        """AC-007 H4: External dispatch is NOT attempted when audit is unavailable."""
        result = process_synthetic_payload(FIXTURE_H4_AUDIT_UNAVAILABLE, SCENARIO_AUDIT_UNAVAILABLE)
        self.assertFalse(
            result.dispatch_attempted,
            msg="H4: dispatch_attempted must be False when audit is unavailable",
        )

    def test_ac007_h4_schema_valid(self) -> None:
        """AC-007 H4: The blocked event conforms to the closed 15-field schema."""
        result = process_synthetic_payload(FIXTURE_H4_AUDIT_UNAVAILABLE, SCENARIO_AUDIT_UNAVAILABLE)
        violations = validate_audit_event_schema(result.events[0])
        self.assertEqual(violations, [], msg=f"H4 schema violations: {violations!r}")


# ===========================================================================
# AC-008 — Offline and Deterministic Execution
# ===========================================================================

class TestAC008OfflineDeterministic(unittest.TestCase):
    """
    AC-008: The test suite runs fully offline (no network) and is deterministic.
    Running the same fixture twice must produce identical results.
    No timestamp, random, or external-state dependency.
    """

    def test_ac008_same_fixture_produces_same_event_twice(self) -> None:
        """AC-008: Identical fixture → identical audit event on two separate calls."""
        result_1 = process_synthetic_payload(FIXTURE_KNOWN_TOOL_ALLOWED, SCENARIO_PRE_TOOL_USE_ALLOWED)
        result_2 = process_synthetic_payload(FIXTURE_KNOWN_TOOL_ALLOWED, SCENARIO_PRE_TOOL_USE_ALLOWED)
        self.assertEqual(
            result_1.events,
            result_2.events,
            msg=(
                "Two calls with the same fixture must produce identical events; "
                f"got:\n  run1: {result_1.events!r}\n  run2: {result_2.events!r}"
            ),
        )

    def test_ac008_same_fixture_produces_same_dispatch_flag_twice(self) -> None:
        """AC-008: Identical fixture → identical dispatch_attempted on two separate calls."""
        result_1 = process_synthetic_payload(FIXTURE_KNOWN_TOOL_ALLOWED, SCENARIO_PERMISSION_DENIED)
        result_2 = process_synthetic_payload(FIXTURE_KNOWN_TOOL_ALLOWED, SCENARIO_PERMISSION_DENIED)
        self.assertEqual(
            result_1.dispatch_attempted,
            result_2.dispatch_attempted,
            msg=(
                "dispatch_attempted must be identical for same fixture; "
                f"got {result_1.dispatch_attempted!r} vs {result_2.dispatch_attempted!r}"
            ),
        )

    def test_ac008_same_fixture_for_error_scenarios_is_deterministic(self) -> None:
        """AC-008: Error scenarios (H1-H4) are deterministic over two calls."""
        error_cases = [
            (FIXTURE_H1_PARSER_FAILURE, SCENARIO_PARSER_FAILURE),
            (FIXTURE_H2_MALFORMED, SCENARIO_MALFORMED_PAYLOAD),
            (FIXTURE_H3_CAPABILITY_MISMATCH, SCENARIO_PRE_TOOL_USE_ALLOWED),
            (FIXTURE_H4_AUDIT_UNAVAILABLE, SCENARIO_AUDIT_UNAVAILABLE),
        ]
        for fixture, scenario in error_cases:
            with self.subTest(scenario=scenario):
                r1 = process_synthetic_payload(fixture, scenario)
                r2 = process_synthetic_payload(fixture, scenario)
                self.assertEqual(
                    r1.events,
                    r2.events,
                    msg=(
                        f"Scenario {scenario!r} is not deterministic; "
                        f"run1={r1.events!r}, run2={r2.events!r}"
                    ),
                )

    def test_ac008_derive_operation_reference_is_deterministic(self) -> None:
        """AC-008: derive_operation_reference with same inputs produces same output."""
        args = ("sess-abc", "example-notes-mcp", "search_sources", "qa-automation", 42)
        ref_1 = derive_operation_reference(*args)
        ref_2 = derive_operation_reference(*args)
        self.assertEqual(
            ref_1,
            ref_2,
            msg=f"derive_operation_reference is not deterministic: {ref_1!r} vs {ref_2!r}",
        )

    def test_ac008_no_import_of_network_modules(self) -> None:
        """AC-008: The harness module does not import network or subprocess modules."""
        from . import synthetic_audit_harness as harness_module
        module_names = set(dir(harness_module))
        # These names should not be importable attributes of the harness
        network_indicators = {"socket", "urllib", "requests", "http", "subprocess", "os"}
        leaked = network_indicators & module_names
        self.assertEqual(
            leaked,
            set(),
            msg=(
                f"Harness module exposes potential network/subprocess attributes: "
                f"{sorted(leaked)!r}"
            ),
        )


# ===========================================================================
# AC-009 — No Real MCP Dependency
# ===========================================================================

class TestAC009NoRealMCPDependency(unittest.TestCase):
    """
    AC-009: The test suite runs without any real MCP server, credential,
    hook config, endpoint, or Claude Code hook runtime.
    Fixtures contain only synthetic values — no real API keys, PII, or URLs.
    """

    def test_ac009_harness_importable_with_stdlib_only(self) -> None:
        """AC-009: The harness module can be imported using only stdlib."""
        # If this import succeeds, no non-stdlib dependency is required
        from . import synthetic_audit_harness  # noqa: F401
        # Reaching here means import succeeded without external packages

    def test_ac009_process_payload_succeeds_without_hook_config(self) -> None:
        """AC-009: process_synthetic_payload runs without .claude/hooks/ or .claude/settings.json."""
        # No hook file access, no settings file access; the call must succeed
        result = process_synthetic_payload(FIXTURE_KNOWN_TOOL_ALLOWED, SCENARIO_PRE_TOOL_USE_ALLOWED)
        self.assertIsNotNone(result, msg="process_synthetic_payload should return a result")
        self.assertTrue(len(result.events) > 0, msg="At least one event should be produced")

    def test_ac009_no_real_server_name_in_allowlist(self) -> None:
        """AC-009: All allowlist entries use explicitly synthetic server names (example-*-mcp)."""
        for (server, tool) in SYNTHETIC_TOOL_ALLOWLIST.keys():
            self.assertTrue(
                server.startswith("example-"),
                msg=(
                    f"Allowlist entry ({server!r}, {tool!r}) uses a server name that "
                    f"does not start with 'example-'; may be a real server name"
                ),
            )

    def test_ac009_fixture_event_ids_are_synthetic(self) -> None:
        """AC-009: Fixture event_id values begin with 'test-' prefix (synthetic markers)."""
        for fixture in [
            FIXTURE_KNOWN_TOOL_ALLOWED,
            FIXTURE_UNKNOWN_TOOL,
            FIXTURE_PERMISSION_DENIED,
            FIXTURE_POST_TOOL_USE_FAILURE,
            FIXTURE_WITH_FORBIDDEN_VALUES,
            FIXTURE_PARALLEL_OP_A,
            FIXTURE_PARALLEL_OP_B,
            FIXTURE_H2_MALFORMED,
            FIXTURE_H3_CAPABILITY_MISMATCH,
            FIXTURE_H4_AUDIT_UNAVAILABLE,
        ]:
            event_id = fixture.get("event_id", "")
            self.assertTrue(
                event_id.startswith("test-"),
                msg=(
                    f"Fixture event_id {event_id!r} does not start with 'test-'; "
                    f"verify it does not contain a real ID"
                ),
            )

    def test_ac009_no_real_credentials_in_fixtures(self) -> None:
        """AC-009: No real credential, API key, or token markers in any fixture."""
        real_credential_indicators = [
            "sk-",           # typical API key prefix
            "ghp_",          # GitHub personal access token
            "xoxb-",         # Slack token
            "eyJhbGci",      # JWT token base64 prefix
            "AIzaSy",        # Google API key
            "AKIA",          # AWS access key
        ]
        all_fixtures = [
            FIXTURE_KNOWN_TOOL_ALLOWED,
            FIXTURE_UNKNOWN_TOOL,
            FIXTURE_PERMISSION_DENIED,
            FIXTURE_POST_TOOL_USE_FAILURE,
            FIXTURE_WITH_FORBIDDEN_VALUES,
            FIXTURE_PARALLEL_OP_A,
            FIXTURE_PARALLEL_OP_B,
            FIXTURE_H2_MALFORMED,
            FIXTURE_H3_CAPABILITY_MISMATCH,
            FIXTURE_H4_AUDIT_UNAVAILABLE,
        ]
        for fixture in all_fixtures:
            for key, value in fixture.items():
                if isinstance(value, str):
                    for indicator in real_credential_indicators:
                        self.assertNotIn(
                            indicator,
                            value,
                            msg=(
                                f"Potential real credential indicator {indicator!r} "
                                f"found in fixture field {key!r}: {value!r}"
                            ),
                        )


# ===========================================================================
# AC-010 — Explicit PASS/FAIL Assertion
# ===========================================================================

class TestAC010ExplicitPassFailAssertion(unittest.TestCase):
    """
    AC-010: Every test scenario produces an explicit PASS or FAIL result.
    No SKIP, PENDING, or ambiguous outcomes are acceptable.

    This class verifies that the assertion helpers used throughout this
    suite are programmatic comparisons (assertEqual, assertNotEqual,
    assertIn, assertNotIn, assertTrue, assertFalse, assertEqual with [])
    rather than human-interpreted checks.
    """

    def test_ac010_validate_audit_event_schema_returns_empty_list_on_valid_event(self) -> None:
        """AC-010: validate_audit_event_schema returns [] for a valid event (PASS=empty list)."""
        result = process_synthetic_payload(FIXTURE_KNOWN_TOOL_ALLOWED, SCENARIO_PRE_TOOL_USE_ALLOWED)
        violations = validate_audit_event_schema(result.events[0])
        self.assertIsInstance(violations, list, msg="validate_audit_event_schema must return a list")
        self.assertEqual(
            violations,
            [],
            msg=f"Expected no violations for valid event; got: {violations!r}",
        )

    def test_ac010_validate_audit_event_schema_returns_violations_for_extra_field(self) -> None:
        """AC-010: validate_audit_event_schema returns violations list for an invalid event (FAIL=non-empty)."""
        # Construct an event with an extra forbidden field
        result = process_synthetic_payload(FIXTURE_KNOWN_TOOL_ALLOWED, SCENARIO_PRE_TOOL_USE_ALLOWED)
        bad_event = dict(result.events[0])
        bad_event["note"] = "this field is forbidden"  # extra field
        violations = validate_audit_event_schema(bad_event)
        self.assertGreater(
            len(violations),
            0,
            msg=f"Expected at least one violation for event with extra field; got: {violations!r}",
        )

    def test_ac010_check_for_forbidden_values_returns_empty_on_clean_event(self) -> None:
        """AC-010: check_for_forbidden_values returns [] when no forbidden data is present."""
        result = process_synthetic_payload(FIXTURE_KNOWN_TOOL_ALLOWED, SCENARIO_PRE_TOOL_USE_ALLOWED)
        violations = check_for_forbidden_values(result.events[0], SYNTHETIC_FORBIDDEN_MARKERS)
        self.assertEqual(
            violations,
            [],
            msg=f"Expected no forbidden value violations; got: {violations!r}",
        )

    def test_ac010_check_for_forbidden_values_detects_leak(self) -> None:
        """AC-010: check_for_forbidden_values detects a forbidden marker when injected."""
        # Construct an event that has a forbidden value
        result = process_synthetic_payload(FIXTURE_KNOWN_TOOL_ALLOWED, SCENARIO_PRE_TOOL_USE_ALLOWED)
        bad_event = dict(result.events[0])
        # Overwrite a field with a forbidden marker (simulating a data leak bug)
        bad_event["agent_type"] = "SYNTHETIC_INPUT_PAYLOAD"
        violations = check_for_forbidden_values(bad_event, ("SYNTHETIC_INPUT_PAYLOAD",))
        self.assertGreater(
            len(violations),
            0,
            msg="check_for_forbidden_values should detect the injected forbidden marker",
        )

    def test_ac010_each_main_ac_scenario_produces_at_least_one_event(self) -> None:
        """AC-010: Each primary AC scenario produces at least one audit event (PASS evidence)."""
        scenarios = [
            (FIXTURE_KNOWN_TOOL_ALLOWED, SCENARIO_PRE_TOOL_USE_ALLOWED, "AC001_known_tool"),
            (FIXTURE_UNKNOWN_TOOL, SCENARIO_PRE_TOOL_USE_ALLOWED, "AC002_unknown_tool"),
            (FIXTURE_PERMISSION_DENIED, SCENARIO_PERMISSION_DENIED, "AC003a_perm_denied"),
            (FIXTURE_POST_TOOL_USE_FAILURE, SCENARIO_POST_TOOL_USE_FAILURE, "AC003b_post_fail"),
            (FIXTURE_KNOWN_TOOL_ALLOWED, SCENARIO_PRE_TOOL_USE_ALLOWED, "AC004_schema"),
            (FIXTURE_WITH_FORBIDDEN_VALUES, SCENARIO_PRE_TOOL_USE_ALLOWED, "AC005_forbidden"),
            (FIXTURE_PARALLEL_OP_A, SCENARIO_PRE_TOOL_USE_ALLOWED, "AC006_parallel_a"),
            (FIXTURE_PARALLEL_OP_B, SCENARIO_PRE_TOOL_USE_ALLOWED, "AC006_parallel_b"),
            (FIXTURE_H1_PARSER_FAILURE, SCENARIO_PARSER_FAILURE, "AC007_h1"),
            (FIXTURE_H2_MALFORMED, SCENARIO_MALFORMED_PAYLOAD, "AC007_h2"),
            (FIXTURE_H3_CAPABILITY_MISMATCH, SCENARIO_PRE_TOOL_USE_ALLOWED, "AC007_h3"),
            (FIXTURE_H4_AUDIT_UNAVAILABLE, SCENARIO_AUDIT_UNAVAILABLE, "AC007_h4"),
        ]
        for fixture, scenario, label in scenarios:
            with self.subTest(label=label):
                result = process_synthetic_payload(fixture, scenario)
                self.assertGreater(
                    len(result.events),
                    0,
                    msg=f"{label}: Expected at least one event, got 0",
                )


# ===========================================================================
# AC-011 — Test Evidence Record
# ===========================================================================

class TestAC011TestEvidenceRecord(unittest.TestCase):
    """
    AC-011: This test class documents the evidence record produced by running
    this suite and validates the meta-requirements around evidence generation.

    NOTE: This class itself constitutes part of the evidence record.
    The actual evidence is the output of running this test suite with -v flag.
    Human maintainer must review the output and explicitly confirm
    "synthetic validation complete" before any real MCP connection is opened.

    Running:
        python -m unittest tests.mcp_hook_lifecycle.test_synthetic_audit_lifecycle -v

    This suite DOES NOT grant permission for real MCP connection.
    See: SEC-ADR-005-MCP-CONNECTION-PRECONDITIONS.md and REQ-001 §Human Approval Gates.
    """

    # Expected AC items that this suite covers
    EXPECTED_AC_COVERAGE = {
        "AC-001", "AC-002", "AC-003", "AC-004", "AC-005",
        "AC-006", "AC-007", "AC-008", "AC-009", "AC-010", "AC-011",
    }

    # Test classes in this module mapped to AC IDs
    _AC_TO_CLASS = {
        "AC-001": "TestAC001KnownToolIdentity",
        "AC-002": "TestAC002UnknownToolIdentitySentinel",
        "AC-003": "TestAC003LifecyclePathSeparation",
        "AC-004": "TestAC004ClosedSchemaValidation",
        "AC-005": "TestAC005ForbiddenDataExclusion",
        "AC-006": "TestAC006OperationReferenceCollisionResistance",
        "AC-007": "TestAC007ErrorScenariosDenyBlocked",
        "AC-008": "TestAC008OfflineDeterministic",
        "AC-009": "TestAC009NoRealMCPDependency",
        "AC-010": "TestAC010ExplicitPassFailAssertion",
        "AC-011": "TestAC011TestEvidenceRecord",
    }

    def test_ac011_all_ac_items_have_a_test_class(self) -> None:
        """AC-011: A test class exists for each of AC-001 through AC-011."""
        import sys
        current_module = sys.modules[__name__]
        for ac_id, class_name in self._AC_TO_CLASS.items():
            cls = getattr(current_module, class_name, None)
            self.assertIsNotNone(
                cls,
                msg=f"{ac_id}: Expected test class {class_name!r} not found in module",
            )
            self.assertTrue(
                issubclass(cls, unittest.TestCase),
                msg=f"{ac_id}: {class_name!r} is not a unittest.TestCase subclass",
            )

    def test_ac011_harness_is_test_only_and_offline(self) -> None:
        """AC-011: Evidence that the harness is test-only and offline."""
        # Verify the harness module docstring declares its scope
        from . import synthetic_audit_harness as harness_module
        docstring = harness_module.__doc__ or ""
        self.assertIn(
            "TEST-ONLY",
            docstring,
            msg="Harness module docstring must contain 'TEST-ONLY' scope declaration",
        )
        self.assertIn(
            "OFFLINE",
            docstring,
            msg="Harness module docstring must contain 'OFFLINE' scope declaration",
        )

    def test_ac011_no_real_credentials_in_harness_module(self) -> None:
        """AC-011: The harness module source contains no real credential markers."""
        import inspect
        from . import synthetic_audit_harness as harness_module
        source = inspect.getsource(harness_module)
        real_credential_indicators = [
            "sk-",
            "ghp_",
            "xoxb-",
            "AKIA",
            "AIzaSy",
            "eyJhbGci",
        ]
        for indicator in real_credential_indicators:
            self.assertNotIn(
                indicator,
                source,
                msg=(
                    f"Potential real credential indicator {indicator!r} found in "
                    f"harness module source; verify this is not a real credential"
                ),
            )

    def test_ac011_evidence_scope_note_present_in_suite_docstring(self) -> None:
        """AC-011: This module's docstring contains the human-review requirement note."""
        module_doc = __doc__ or ""
        self.assertIn(
            "human maintainer",
            module_doc.lower(),
            msg=(
                "Test suite docstring must contain a note requiring human maintainer "
                "review before any real MCP connection"
            ),
        )

    def test_ac011_suite_does_not_claim_real_mcp_connection_approval(self) -> None:
        """AC-011: Passing this suite does NOT grant real MCP connection approval."""
        module_doc = __doc__ or ""
        # The docstring must disclaim automatic connection approval
        disclaimer_phrases = [
            "does not grant permission",
            "does not grant",
            "NOT grant",
        ]
        found = any(phrase.lower() in module_doc.lower() for phrase in disclaimer_phrases)
        self.assertTrue(
            found,
            msg=(
                "Test suite docstring must explicitly disclaim that passing tests "
                "does not grant real MCP connection permission"
            ),
        )

    def test_ac011_all_lifecycle_scenarios_produce_schema_valid_events(self) -> None:
        """AC-011: End-to-end: all primary scenarios produce schema-valid events (final evidence)."""
        all_scenarios = [
            ("known_tool_pre", FIXTURE_KNOWN_TOOL_ALLOWED, SCENARIO_PRE_TOOL_USE_ALLOWED),
            ("known_tool_post_success", FIXTURE_KNOWN_TOOL_ALLOWED, SCENARIO_POST_TOOL_USE_SUCCESS),
            ("permission_denied", FIXTURE_PERMISSION_DENIED, SCENARIO_PERMISSION_DENIED),
            ("post_tool_failure", FIXTURE_POST_TOOL_USE_FAILURE, SCENARIO_POST_TOOL_USE_FAILURE),
            ("unknown_identity", FIXTURE_UNKNOWN_TOOL, SCENARIO_PRE_TOOL_USE_ALLOWED),
            ("parser_failure", FIXTURE_H1_PARSER_FAILURE, SCENARIO_PARSER_FAILURE),
            ("malformed_payload", FIXTURE_H2_MALFORMED, SCENARIO_MALFORMED_PAYLOAD),
            ("capability_mismatch", FIXTURE_H3_CAPABILITY_MISMATCH, SCENARIO_PRE_TOOL_USE_ALLOWED),
            ("audit_unavailable", FIXTURE_H4_AUDIT_UNAVAILABLE, SCENARIO_AUDIT_UNAVAILABLE),
            ("parallel_op_a", FIXTURE_PARALLEL_OP_A, SCENARIO_PRE_TOOL_USE_ALLOWED),
            ("parallel_op_b", FIXTURE_PARALLEL_OP_B, SCENARIO_PRE_TOOL_USE_ALLOWED),
            ("forbidden_values", FIXTURE_WITH_FORBIDDEN_VALUES, SCENARIO_PRE_TOOL_USE_ALLOWED),
        ]
        for label, fixture, scenario in all_scenarios:
            with self.subTest(label=label):
                result = process_synthetic_payload(fixture, scenario)
                self.assertGreater(
                    len(result.events),
                    0,
                    msg=f"{label}: No events produced",
                )
                for event in result.events:
                    violations = validate_audit_event_schema(event)
                    self.assertEqual(
                        violations,
                        [],
                        msg=(
                            f"{label}: Schema violations: {violations!r}\n"
                            f"Event: {event!r}"
                        ),
                    )


# ===========================================================================
# M-001 — agent_type Closed-Set Validation (Security Red Team)
# ===========================================================================

class TestM001AgentTypeValidation(unittest.TestCase):
    """
    M-001 (Security Red Team): validate_audit_event_schema() must enforce a
    closed set for agent_type derived from AGENTS.md canonical role identifiers.

    "unknown" is NOT a canonical role identifier and must be rejected.
    H1 (parser failure) and H2 (malformed payload) events must contain a
    contract-valid agent_type sourced from trusted synthetic harness context,
    not copied from untrusted/malformed payload input.

    Constraints verified:
      - VALID_AGENT_TYPES does not contain "unknown".
      - An event with agent_type="unknown" fails schema validation.
      - H1 parser failure event has a canonical agent_type.
      - H2 malformed payload event has a canonical agent_type.
      - Both H1 and H2 denial events pass full schema validation.
    """

    def test_m001_unknown_is_not_in_valid_agent_types(self) -> None:
        """M-001: 'unknown' must NOT be in the canonical VALID_AGENT_TYPES closed set."""
        self.assertNotIn(
            "unknown",
            VALID_AGENT_TYPES,
            msg=(
                "'unknown' is not a canonical AGENTS.md role and must not be "
                "in VALID_AGENT_TYPES"
            ),
        )

    def test_m001_qa_automation_is_in_valid_agent_types(self) -> None:
        """M-001: 'qa-automation' is a canonical role and must be in VALID_AGENT_TYPES."""
        self.assertIn(
            "qa-automation",
            VALID_AGENT_TYPES,
            msg="'qa-automation' must be present in VALID_AGENT_TYPES",
        )

    def test_m001_unknown_agent_type_fails_schema_validation(self) -> None:
        """M-001: An event with agent_type='unknown' must fail schema validation."""
        result = process_synthetic_payload(
            FIXTURE_KNOWN_TOOL_ALLOWED, SCENARIO_PRE_TOOL_USE_ALLOWED
        )
        bad_event = dict(result.events[0])
        bad_event["agent_type"] = "unknown"
        violations = validate_audit_event_schema(bad_event)
        self.assertGreater(
            len(violations),
            0,
            msg=(
                "An event with agent_type='unknown' must produce at least one "
                "schema violation (not a canonical AGENTS.md role)"
            ),
        )
        agent_violations = [v for v in violations if "agent_type" in v]
        self.assertGreater(
            len(agent_violations),
            0,
            msg=(
                f"Expected a violation specifically about agent_type='unknown'; "
                f"got violations: {violations!r}"
            ),
        )

    def test_m001_canonical_agent_type_passes_schema_validation(self) -> None:
        """M-001: An event with a canonical agent_type='qa-automation' passes agent_type check."""
        result = process_synthetic_payload(
            FIXTURE_KNOWN_TOOL_ALLOWED, SCENARIO_PRE_TOOL_USE_ALLOWED
        )
        event = result.events[0]
        # Confirm fixture uses a canonical agent_type
        self.assertIn(
            event["agent_type"],
            VALID_AGENT_TYPES,
            msg=f"Fixture agent_type {event['agent_type']!r} must be canonical",
        )
        violations = validate_audit_event_schema(event)
        agent_violations = [v for v in violations if "agent_type" in v]
        self.assertEqual(
            agent_violations,
            [],
            msg=(
                f"Canonical agent_type {event['agent_type']!r} must not produce "
                f"agent_type violations; got: {agent_violations!r}"
            ),
        )

    def test_m001_h1_parser_failure_event_has_valid_agent_type(self) -> None:
        """M-001: H1 parser failure event contains a contract-valid agent_type from VALID_AGENT_TYPES."""
        result = process_synthetic_payload(FIXTURE_H1_PARSER_FAILURE, SCENARIO_PARSER_FAILURE)
        event = result.events[0]
        self.assertIn(
            event["agent_type"],
            VALID_AGENT_TYPES,
            msg=(
                f"H1 parser failure event must have a canonical agent_type "
                f"(from VALID_AGENT_TYPES); got {event['agent_type']!r}"
            ),
        )

    def test_m001_h2_malformed_payload_event_has_valid_agent_type(self) -> None:
        """M-001: H2 malformed payload event contains a contract-valid agent_type from VALID_AGENT_TYPES."""
        result = process_synthetic_payload(FIXTURE_H2_MALFORMED, SCENARIO_MALFORMED_PAYLOAD)
        event = result.events[0]
        self.assertIn(
            event["agent_type"],
            VALID_AGENT_TYPES,
            msg=(
                f"H2 malformed payload event must have a canonical agent_type "
                f"(not copied from untrusted payload); got {event['agent_type']!r}"
            ),
        )

    def test_m001_h1_schema_valid_with_canonical_agent_type(self) -> None:
        """M-001: H1 denial event passes full schema validation (agent_type is canonical)."""
        result = process_synthetic_payload(FIXTURE_H1_PARSER_FAILURE, SCENARIO_PARSER_FAILURE)
        violations = validate_audit_event_schema(result.events[0])
        self.assertEqual(
            violations,
            [],
            msg=(
                f"H1 denial event must be fully schema-valid after M-001 fix; "
                f"violations: {violations!r}"
            ),
        )

    def test_m001_h2_schema_valid_with_canonical_agent_type(self) -> None:
        """M-001: H2 denial event passes full schema validation (agent_type is canonical)."""
        result = process_synthetic_payload(FIXTURE_H2_MALFORMED, SCENARIO_MALFORMED_PAYLOAD)
        violations = validate_audit_event_schema(result.events[0])
        self.assertEqual(
            violations,
            [],
            msg=(
                f"H2 denial event must be fully schema-valid after M-001 fix; "
                f"violations: {violations!r}"
            ),
        )


# ===========================================================================
# L-001 — Isolated Environment Scope Mismatch (Security Red Team)
# ===========================================================================

class TestL001EnvironmentScopeMismatch(unittest.TestCase):
    """
    L-001 (Security Red Team): Isolated environment scope mismatch test.

    This test is SEPARATE from TestAC007ErrorScenariosDenyBlocked.test_ac007_h3_*,
    which tests agent identity mismatch (backend-engineer not in allowed_agents).

    L-001 verifies the scope-driven capability_mismatch path:
      - agent_type:  "qa-automation"          (CORRECT — in allowed_agents for navigate_page)
      - tool:        example-browser-mcp / navigate_page  (allowlist scope: localhost)
      - environment_scope: "production"        (WRONG — does not match allowlist "localhost")

    The agent identity check passes. The environment scope check fails.
    Expected outcome: policy_decision="deny", failure_category="capability_mismatch" (exact),
    dispatch_attempted=False.
    """

    def setUp(self) -> None:
        self.result = process_synthetic_payload(
            FIXTURE_L001_ENV_SCOPE_MISMATCH, SCENARIO_PRE_TOOL_USE_ALLOWED
        )
        self.event = self.result.events[0]

    def test_l001_policy_decision_is_deny(self) -> None:
        """L-001: Environment scope mismatch produces policy_decision='deny'."""
        self.assertEqual(
            self.event["policy_decision"],
            "deny",
            msg=(
                f"L-001: Expected policy_decision='deny' for environment scope mismatch, "
                f"got {self.event['policy_decision']!r}"
            ),
        )

    def test_l001_outcome_is_denied_or_blocked(self) -> None:
        """L-001: Environment scope mismatch produces outcome 'denied' or 'blocked'."""
        self.assertIn(
            self.event["outcome"],
            {"denied", "blocked"},
            msg=(
                f"L-001: Expected outcome in {{'denied', 'blocked'}} for scope mismatch, "
                f"got {self.event['outcome']!r}"
            ),
        )

    def test_l001_failure_category_is_capability_mismatch_exact(self) -> None:
        """L-001: Environment scope mismatch produces failure_category='capability_mismatch' (exact assertion)."""
        self.assertEqual(
            self.event["failure_category"],
            "capability_mismatch",
            msg=(
                f"L-001: Expected failure_category exactly 'capability_mismatch', "
                f"got {self.event['failure_category']!r}"
            ),
        )

    def test_l001_dispatch_not_attempted(self) -> None:
        """L-001: External dispatch is NOT attempted when environment scope mismatches."""
        self.assertFalse(
            self.result.dispatch_attempted,
            msg="L-001: dispatch_attempted must be False for environment scope mismatch",
        )

    def test_l001_agent_is_in_allowed_agents(self) -> None:
        """L-001: The agent ('qa-automation') IS in allowed_agents for the tool — it is the scope that fails."""
        entry = SYNTHETIC_TOOL_ALLOWLIST.get(("example-browser-mcp", "navigate_page"))
        self.assertIsNotNone(
            entry,
            msg="navigate_page must exist in SYNTHETIC_TOOL_ALLOWLIST",
        )
        self.assertIn(
            "qa-automation",
            entry["allowed_agents"],
            msg=(
                "L-001: 'qa-automation' must be in allowed_agents for navigate_page; "
                "the test is about scope mismatch, not agent mismatch"
            ),
        )

    def test_l001_scope_mismatch_is_the_cause(self) -> None:
        """L-001: Allowlist scope ('localhost') and fixture scope ('production') differ — scope is the cause."""
        entry = SYNTHETIC_TOOL_ALLOWLIST.get(("example-browser-mcp", "navigate_page"))
        allowlist_scope = entry["environment_scope"]
        fixture_scope = FIXTURE_L001_ENV_SCOPE_MISMATCH["environment_scope"]
        self.assertEqual(
            allowlist_scope,
            "localhost",
            msg=f"navigate_page allowlist scope must be 'localhost', got {allowlist_scope!r}",
        )
        self.assertEqual(
            fixture_scope,
            "production",
            msg=f"L-001 fixture environment_scope must be 'production', got {fixture_scope!r}",
        )
        self.assertNotEqual(
            allowlist_scope,
            fixture_scope,
            msg=(
                f"L-001: Allowlist scope {allowlist_scope!r} and fixture scope "
                f"{fixture_scope!r} must differ (this is the scope mismatch being tested)"
            ),
        )

    def test_l001_scenario_distinct_from_h3_agent_mismatch(self) -> None:
        """L-001: L-001 (scope mismatch) is structurally distinct from H3 (agent mismatch)."""
        h3_result = process_synthetic_payload(
            FIXTURE_H3_CAPABILITY_MISMATCH, SCENARIO_PRE_TOOL_USE_ALLOWED
        )
        h3_event = h3_result.events[0]
        # Both produce capability_mismatch, but through different gate failures
        self.assertEqual(
            self.event["failure_category"],
            "capability_mismatch",
            msg="L-001 event must have failure_category='capability_mismatch'",
        )
        self.assertEqual(
            h3_event["failure_category"],
            "capability_mismatch",
            msg="H3 event must have failure_category='capability_mismatch'",
        )
        # L-001: correct agent (qa-automation); H3: wrong agent (backend-engineer)
        self.assertEqual(
            self.event["agent_type"],
            "qa-automation",
            msg=(
                "L-001 event agent_type must be 'qa-automation' "
                "(the agent IS in allowed_agents; scope is the cause)"
            ),
        )
        self.assertNotEqual(
            h3_event["agent_type"],
            "qa-automation",
            msg=(
                "H3 event must NOT use 'qa-automation' — H3 tests agent identity "
                "mismatch, not scope mismatch"
            ),
        )

    def test_l001_schema_valid(self) -> None:
        """L-001: The capability_mismatch event from scope path conforms to the closed 15-field schema."""
        violations = validate_audit_event_schema(self.event)
        self.assertEqual(
            violations,
            [],
            msg=f"L-001 scope mismatch event must be schema-valid; violations: {violations!r}",
        )


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
