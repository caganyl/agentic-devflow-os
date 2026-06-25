"""
synthetic_audit_harness.py — REQ-001 Offline Synthetic Audit Lifecycle Harness

SCOPE: This module is TEST-ONLY, OFFLINE, and DETERMINISTIC.

It models the MCP audit lifecycle enforcement logic described in:
  - ADR-006-mcp-audit-logging-and-runtime-enforcement.md (Accepted)
  - MCP_AUDIT_EVENT_CONTRACT.md

This is NOT a production hook, NOT a real MCP client, NOT a real audit logger,
and NOT a capability-enforcement runtime. It purely validates that the
contract-defined logic (tool identity classification, closed 15-field schema,
sentinel model, lifecycle phase routing, capability gating) behaves correctly
using offline, deterministic, synthetic fixtures.

Constraints (must hold throughout this module):
  - No network calls of any kind.
  - No subprocess invocations.
  - No file reads or writes.
  - No environment variable or secret reads.
  - No datetime.now(), time.time(), uuid.uuid4(), or random.* calls.
  - No third-party imports; only Python standard library.
  - All fixture values are synthetic; no real MCP server names, endpoints,
    credentials, tools, PII, or URLs.

Determinism: given the same inputs, all functions in this module always produce
the same outputs.
"""

import hashlib
import re

# ---------------------------------------------------------------------------
# Contract constants — sourced from MCP_AUDIT_EVENT_CONTRACT.md
# ---------------------------------------------------------------------------

SCHEMA_VERSION: str = "1.0.0"
AUDIT_RECORD_VERSION: int = 1

# Closed 15-field schema (MCP_AUDIT_EVENT_CONTRACT.md — "Kapalı Payload Modeli")
REQUIRED_FIELDS: frozenset = frozenset({
    "schema_version",
    "event_id",
    "timestamp",
    "session_reference",
    "operation_reference",
    "agent_type",
    "event_phase",
    "mcp_server",
    "mcp_tool",
    "action_class",
    "environment_scope",
    "policy_decision",
    "outcome",
    "failure_category",
    "audit_record_version",
})

# Canonical agent_type closed set — sourced from AGENTS.md
# (MCP_AUDIT_EVENT_CONTRACT.md: "agent_type" must be one of the role identifiers
# defined in AGENTS.md. Values are kebab-case versions of the canonical role names.)
# M-001 (Security Red Team): validate_audit_event_schema() enforces this closed set;
# "unknown" and any other non-canonical value are rejected.
VALID_AGENT_TYPES: frozenset = frozenset({
    "delivery-lead",
    "product-analyst",
    "solution-architect",
    "contract-broker",
    "frontend-engineer",
    "backend-engineer",
    "database-engineer",
    "ai-data-engineer",
    "qa-automation",
    "security-red-team",
    "design-reviewer",
    "evalops-reviewer",
    "integration-release",
    "governance-operations-author",
})

# Canonical label format (ADR-006 §14; MCP_AUDIT_EVENT_CONTRACT.md
# "Canonical mcp_server / mcp_tool Etiket Formatı")
CANONICAL_LABEL_PATTERN: re.Pattern = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
CANONICAL_LABEL_MAX_LEN: int = 64

# Closed enum values (MCP_AUDIT_EVENT_CONTRACT.md — "Alanların İzinli Değerleri")
VALID_EVENT_PHASES: frozenset = frozenset({
    "PreToolUse",
    "PermissionRequest",
    "PermissionDenied",
    "PostToolUse",
    "PostToolUseFailure",
})

VALID_ACTION_CLASSES: frozenset = frozenset({
    "read",
    "write",
    "evidence_retrieval",
    "permission_check",
    "other",
})

VALID_ENVIRONMENT_SCOPES: frozenset = frozenset({
    "localhost",
    "preview",
    "staging",
    "production",
    "n/a",
})

VALID_POLICY_DECISIONS: frozenset = frozenset({
    "allow",
    "deny",
    "not_evaluated",
})

VALID_OUTCOMES: frozenset = frozenset({
    "success",
    "failure",
    "denied",
    "blocked",
})

# None is a valid value when outcome is not "failure" or "blocked"
VALID_FAILURE_CATEGORIES: frozenset = frozenset({
    "policy_violation",
    "capability_mismatch",
    "unclassified_tool_identity",
    "tool_error",
    "audit_unavailable",
    "unknown",
    None,
})

# Sentinel values for unknown/unclassified tool identity
# (ADR-006 §14; MCP_AUDIT_EVENT_CONTRACT.md "Tool Identity Sınıflandırması")
SENTINEL_MCP_SERVER: str = "unclassified"
SENTINEL_MCP_TOOL: str = "unclassified"
SENTINEL_POLICY_DECISION: str = "deny"
SENTINEL_FAILURE_CATEGORY: str = "unclassified_tool_identity"

# Explicitly prohibited field names that must never appear in an audit event
# (MCP_AUDIT_EVENT_CONTRACT.md "Yasak Alanlar")
PROHIBITED_FIELD_NAMES: frozenset = frozenset({
    "note", "notes", "message", "error_message", "details", "description",
    "context", "metadata", "debug", "raw_input", "raw_output", "prompt",
    "url", "header", "file_path", "exception", "reason", "token",
    "credential", "api_key", "secret", "pii", "tool_input", "tool_output",
})

# Synthetic forbidden value markers for AC-005 data-exclusion tests.
# These represent the categories of data that must never leak into audit events.
# These are TEST-ONLY synthetic strings; none of them are real data.
SYNTHETIC_FORBIDDEN_MARKERS: tuple = (
    "SYNTHETIC_INPUT_PAYLOAD",       # raw tool input simulation
    "SYNTHETIC_OUTPUT_PAYLOAD",      # raw tool output simulation
    "SYNTHETIC_PROMPT_TEXT",         # prompt content simulation
    "https://synthetic-test.invalid",  # URL simulation
    "Bearer SYNTHETIC_TOKEN_VALUE",  # Authorization header / token simulation
    "synthetic-user@test.invalid",   # PII (email) simulation
    "/synthetic/path/to/file.txt",   # file path simulation
    "SyntheticError: test_exception_text",  # exception/error text simulation
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

SCENARIO_PRE_TOOL_USE_ALLOWED: str = "pre_tool_use_allowed"
SCENARIO_PERMISSION_DENIED: str = "permission_denied"
SCENARIO_POST_TOOL_USE_SUCCESS: str = "post_tool_use_success"
SCENARIO_POST_TOOL_USE_FAILURE: str = "post_tool_use_failure"
SCENARIO_PARSER_FAILURE: str = "parser_failure"
SCENARIO_MALFORMED_PAYLOAD: str = "malformed_payload"
SCENARIO_AUDIT_UNAVAILABLE: str = "audit_unavailable"

# ---------------------------------------------------------------------------
# Synthetic test-only allowlist
#
# This allowlist uses deliberately synthetic MCP server and tool names.
# These names do NOT correspond to any real MCP server or production tool.
# They are labelled "example-*-mcp" to make their synthetic nature explicit.
#
# Format: (raw_server_string, raw_tool_string) -> capability entry
# ---------------------------------------------------------------------------

SYNTHETIC_TOOL_ALLOWLIST: dict = {
    ("example-notes-mcp", "search_sources"): {
        "mcp_server": "example-notes-mcp",
        "mcp_tool": "search_sources",
        "action_class": "evidence_retrieval",
        "environment_scope": "n/a",
        "allowed_agents": frozenset({
            "solution-architect",
            "qa-automation",
            "backend-engineer",
            "frontend-engineer",
        }),
    },
    ("example-notes-mcp", "retrieve_note"): {
        "mcp_server": "example-notes-mcp",
        "mcp_tool": "retrieve_note",
        "action_class": "read",
        "environment_scope": "n/a",
        "allowed_agents": frozenset({
            "solution-architect",
            "qa-automation",
        }),
    },
    ("example-browser-mcp", "navigate_page"): {
        "mcp_server": "example-browser-mcp",
        "mcp_tool": "navigate_page",
        "action_class": "read",
        "environment_scope": "localhost",
        "allowed_agents": frozenset({"qa-automation"}),
    },
    ("example-browser-mcp", "submit_form"): {
        "mcp_server": "example-browser-mcp",
        "mcp_tool": "submit_form",
        "action_class": "write",
        "environment_scope": "staging",
        "allowed_agents": frozenset({"qa-automation"}),
    },
}

# ---------------------------------------------------------------------------
# operation_reference derivation
#
# Produces a deterministic, collision-resistant operation_reference.
# Uses SHA-256 over explicit fixture parameters with null-byte separators
# to prevent concatenation collisions between adjacent fields.
# No random, no clock, no external state.
# (ADR-006 §16; MCP_AUDIT_EVENT_CONTRACT.md "operation_reference")
# ---------------------------------------------------------------------------

def derive_operation_reference(
    session_reference: str,
    raw_server: str,
    raw_tool: str,
    agent_type: str,
    sequence: int,
) -> str:
    """
    Produce a deterministic, collision-resistant operation_reference.

    All parameters are caller-supplied fixture values; no randomness or clock.
    Distinct (session_reference, raw_server, raw_tool, agent_type, sequence)
    tuples are guaranteed to produce distinct output (via SHA-256 preimage
    resistance) for distinct inputs.

    Args:
        session_reference: Fixed session correlation reference (from fixture).
        raw_server: Raw MCP server string (from fixture).
        raw_tool: Raw MCP tool string (from fixture).
        agent_type: Agent role string (from fixture).
        sequence: Integer sequence number distinguishing parallel operations.

    Returns:
        A string of the form "op-ref-<32-hex-chars>".
    """
    # Null-byte separators prevent cross-field collisions
    preimage = (
        f"{session_reference}\x00{raw_server}\x00"
        f"{raw_tool}\x00{agent_type}\x00{sequence}"
    )
    digest = hashlib.sha256(preimage.encode("utf-8")).hexdigest()
    return f"op-ref-{digest[:32]}"

# ---------------------------------------------------------------------------
# Tool identity classification
# (ADR-006 §14; MCP_AUDIT_EVENT_CONTRACT.md "Tool Identity Sınıflandırması")
# ---------------------------------------------------------------------------

def classify_tool_identity(
    raw_server: str,
    raw_tool: str,
) -> tuple:
    """
    Classify a (raw_server, raw_tool) pair against the synthetic allowlist.

    Returns a 4-tuple:
        (canonical_server, canonical_tool, entry_or_None, classified_bool)

    If the pair is found in SYNTHETIC_TOOL_ALLOWLIST:
        - classified_bool = True
        - canonical_server / canonical_tool = allowlist canonical values
        - entry_or_None = the full allowlist entry dict

    If the pair is NOT found (unknown / allowlist-dışı):
        - classified_bool = False
        - canonical_server = SENTINEL_MCP_SERVER ("unclassified")
        - canonical_tool   = SENTINEL_MCP_TOOL   ("unclassified")
        - entry_or_None    = None
        NOTE: The original raw_server / raw_tool strings are NOT returned
        and must NOT be written to any audit field.
    """
    entry = SYNTHETIC_TOOL_ALLOWLIST.get((raw_server, raw_tool))
    if entry is not None:
        return entry["mcp_server"], entry["mcp_tool"], entry, True
    return SENTINEL_MCP_SERVER, SENTINEL_MCP_TOOL, None, False

# ---------------------------------------------------------------------------
# Capability check
# (ADR-005 §5; ADR-006 §5)
# ---------------------------------------------------------------------------

def check_capability(
    entry: dict,
    agent_type: str,
    environment_scope: str,
) -> tuple:
    """
    Check whether agent_type is permitted to invoke this tool in this environment.

    Returns (allowed: bool, failure_category: str | None).
    failure_category is "capability_mismatch" when not allowed, else None.
    """
    if agent_type not in entry["allowed_agents"]:
        return False, "capability_mismatch"
    # Environment scope check:
    # If allowlist scope is "n/a", any caller-provided scope is accepted.
    # Otherwise, the provided scope must exactly match the allowlist scope.
    allowlist_scope = entry["environment_scope"]
    if allowlist_scope != "n/a" and environment_scope != allowlist_scope:
        return False, "capability_mismatch"
    return True, None

# ---------------------------------------------------------------------------
# Audit event builder — closed 15-field schema
# ---------------------------------------------------------------------------

def _build_audit_event(
    event_id: str,
    timestamp: str,
    session_reference: str,
    operation_reference: str,
    agent_type: str,
    event_phase: str,
    mcp_server: str,
    mcp_tool: str,
    action_class: str,
    environment_scope: str,
    policy_decision: str,
    outcome: str,
    failure_category,  # str | None
) -> dict:
    """
    Build a closed 15-field audit event dict.

    The returned dict contains EXACTLY the 15 required fields defined in
    MCP_AUDIT_EVENT_CONTRACT.md. No extra fields are added. No raw data,
    no serbest metin (free-text) fields, no forbidden values.

    All enum parameters must be members of their respective VALID_* sets.
    This function does not validate inputs; callers are responsible for
    supplying valid enum values. Schema validation is available via
    validate_audit_event_schema().
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "timestamp": timestamp,
        "session_reference": session_reference,
        "operation_reference": operation_reference,
        "agent_type": agent_type,
        "event_phase": event_phase,
        "mcp_server": mcp_server,
        "mcp_tool": mcp_tool,
        "action_class": action_class,
        "environment_scope": environment_scope,
        "policy_decision": policy_decision,
        "outcome": outcome,
        "failure_category": failure_category,
        "audit_record_version": AUDIT_RECORD_VERSION,
    }

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

class SyntheticLifecycleResult:
    """
    Result of processing a synthetic lifecycle scenario.

    Attributes:
        events (list[dict]):        Produced audit event dicts (each exactly
                                    15 fields per the closed schema).
        dispatch_attempted (bool):  True only when the harness simulated an
                                    external MCP dispatch (i.e., the tool
                                    actually started executing). False in all
                                    deny / blocked / permission-denied paths.
        lifecycle_phases (list[str]): event_phase values from produced events,
                                    in order.
    """

    def __init__(self, events: list, dispatch_attempted: bool) -> None:
        self.events: list = events
        self.dispatch_attempted: bool = dispatch_attempted
        self.lifecycle_phases: list = [e["event_phase"] for e in events]

    def __repr__(self) -> str:
        return (
            f"SyntheticLifecycleResult("
            f"phases={self.lifecycle_phases!r}, "
            f"dispatch_attempted={self.dispatch_attempted!r})"
        )

# ---------------------------------------------------------------------------
# Main processing function
# ---------------------------------------------------------------------------

def process_synthetic_payload(
    raw_payload: object,
    scenario: str = SCENARIO_PRE_TOOL_USE_ALLOWED,
) -> "SyntheticLifecycleResult":
    """
    Process a synthetic payload through the MCP audit lifecycle.

    This function implements the enforcement logic model defined in ADR-006
    and MCP_AUDIT_EVENT_CONTRACT.md using entirely synthetic fixtures.

    IMPORTANT CONSTRAINTS:
      - No network calls.
      - No subprocess calls.
      - No file I/O.
      - No environment reads.
      - No datetime.now() / random / uuid4().
      - Fully deterministic: same inputs always produce the same output.

    Args:
        raw_payload: The incoming payload dict (may be non-dict for H1,
                     or missing fields for H2). The harness only reads the
                     following keys: event_id, timestamp, session_reference,
                     operation_reference, agent_type, raw_mcp_server,
                     raw_mcp_tool, environment_scope. All other keys are
                     ignored; their values never appear in output events.
        scenario:    One of the SCENARIO_* constants controlling lifecycle
                     routing after successful identity classification and
                     capability checks.

    Returns:
        SyntheticLifecycleResult with events list and dispatch_attempted flag.

    Lifecycle routing summary:
      H1 (parser_failure):     raw_payload is not a dict → deny, blocked
      H2 (malformed_payload):  dict is missing required payload keys → deny, blocked
      H4 (audit_unavailable):  simulated audit sink failure → deny, blocked
      Unclassified identity:   not in allowlist → sentinel deny, blocked
      Capability mismatch:     agent/env not permitted → deny, denied
      PermissionDenied:        user/config denies → deny, denied
                               (PostToolUse/PostToolUseFailure NOT produced)
      PostToolUseFailure:      tool ran but failed → allow, failure
                               (PermissionDenied NOT produced; dispatch=True)
      PostToolUseSuccess:      tool ran successfully → allow, success
      PreToolUseAllowed:       policy allows, audit gate passed → allow, success
    """

    # ------------------------------------------------------------------
    # Step 0a: Parser failure — raw_payload is not a dict (H1)
    # ------------------------------------------------------------------
    if not isinstance(raw_payload, dict) or scenario == SCENARIO_PARSER_FAILURE:
        # Cannot parse the payload at all.
        # Produce a deny/blocked event with sentinel identity.
        # dispatch_attempted = False (no external call was made).
        # M-001: Never use "unknown" as agent_type; it is not a canonical AGENTS.md role.
        # In H1, the payload cannot be parsed at all, so no agent identity can be
        # extracted from it. Use the canonical harness context agent ("qa-automation")
        # as the trusted synthetic fixture context for this test-only harness.
        event = _build_audit_event(
            event_id="synthetic-evt-parser-failure",
            timestamp="2026-06-25T00:00:00Z",
            session_reference="synthetic-session-parser-failure",
            operation_reference="op-ref-synthetic-parser-failure",
            agent_type="qa-automation",
            event_phase="PreToolUse",
            mcp_server=SENTINEL_MCP_SERVER,
            mcp_tool=SENTINEL_MCP_TOOL,
            action_class="other",
            environment_scope="n/a",
            policy_decision="deny",
            outcome="blocked",
            failure_category=SENTINEL_FAILURE_CATEGORY,
        )
        return SyntheticLifecycleResult(events=[event], dispatch_attempted=False)

    # ------------------------------------------------------------------
    # Step 0b: Malformed payload — dict is present but missing required keys (H2)
    # ------------------------------------------------------------------
    if scenario == SCENARIO_MALFORMED_PAYLOAD:
        required_payload_keys = {"raw_mcp_server", "raw_mcp_tool", "agent_type"}
        missing_keys = required_payload_keys - set(raw_payload.keys())
        if missing_keys:
            # Required payload fields are absent — cannot safely classify identity.
            # M-001: Do not copy agent_type from an untrusted/malformed payload.
            # In H2, the payload is structurally malformed; even if an agent_type
            # key is present, its value cannot be trusted. Use the canonical harness
            # context agent ("qa-automation") as the designated synthetic agent
            # context for this test-only harness.
            event = _build_audit_event(
                event_id=raw_payload.get("event_id", "synthetic-evt-malformed"),
                timestamp=raw_payload.get("timestamp", "2026-06-25T00:00:00Z"),
                session_reference=raw_payload.get(
                    "session_reference", "synthetic-session-malformed"
                ),
                operation_reference=raw_payload.get(
                    "operation_reference", "op-ref-synthetic-malformed"
                ),
                agent_type="qa-automation",
                event_phase="PreToolUse",
                mcp_server=SENTINEL_MCP_SERVER,
                mcp_tool=SENTINEL_MCP_TOOL,
                action_class="other",
                environment_scope="n/a",
                policy_decision="deny",
                outcome="blocked",
                failure_category=SENTINEL_FAILURE_CATEGORY,
            )
            return SyntheticLifecycleResult(events=[event], dispatch_attempted=False)

    # ------------------------------------------------------------------
    # Extract common fields from payload
    # (Only these specific keys are ever read; other keys are ignored.)
    # ------------------------------------------------------------------
    event_id: str = raw_payload.get("event_id", "synthetic-evt-default")
    timestamp: str = raw_payload.get("timestamp", "2026-06-25T00:00:00Z")
    session_reference: str = raw_payload.get(
        "session_reference", "synthetic-session-default"
    )
    operation_reference: str = raw_payload.get(
        "operation_reference", "op-ref-synthetic-default"
    )
    agent_type: str = raw_payload.get("agent_type", "unknown")
    raw_server: str = raw_payload.get("raw_mcp_server", "")
    raw_tool: str = raw_payload.get("raw_mcp_tool", "")
    environment_scope: str = raw_payload.get("environment_scope", "n/a")

    # ------------------------------------------------------------------
    # Step 0c: Audit unavailable — simulate audit sink failure (H4)
    # ------------------------------------------------------------------
    if scenario == SCENARIO_AUDIT_UNAVAILABLE:
        # The audit sink is unavailable; dispatch is blocked.
        # (ADR-006 §6, §15; MCP_AUDIT_EVENT_CONTRACT.md "Audit Unavailable Davranışı")
        event = _build_audit_event(
            event_id=event_id,
            timestamp=timestamp,
            session_reference=session_reference,
            operation_reference=operation_reference,
            agent_type=agent_type,
            event_phase="PreToolUse",
            mcp_server=SENTINEL_MCP_SERVER,
            mcp_tool=SENTINEL_MCP_TOOL,
            action_class="other",
            environment_scope="n/a",
            policy_decision="deny",
            outcome="blocked",
            failure_category="audit_unavailable",
        )
        return SyntheticLifecycleResult(events=[event], dispatch_attempted=False)

    # ------------------------------------------------------------------
    # Step 1: Tool identity classification
    # (ADR-006 §14; MCP_AUDIT_EVENT_CONTRACT.md "Tool Identity Sınıflandırması")
    # The raw_server / raw_tool strings are classified against the allowlist.
    # If unclassified, sentinel values are used; raw strings are NOT written
    # to any audit field.
    # ------------------------------------------------------------------
    canonical_server, canonical_tool, entry, classified = classify_tool_identity(
        raw_server, raw_tool
    )

    if not classified:
        # Unknown / allowlist-dışı tool identity → sentinel model
        # Ham runtime string'i (raw_server, raw_tool) hiçbir alana yazılmaz.
        event = _build_audit_event(
            event_id=event_id,
            timestamp=timestamp,
            session_reference=session_reference,
            operation_reference=operation_reference,
            agent_type=agent_type,
            event_phase="PreToolUse",
            mcp_server=SENTINEL_MCP_SERVER,   # NOT raw_server
            mcp_tool=SENTINEL_MCP_TOOL,       # NOT raw_tool
            action_class="other",
            environment_scope="n/a",
            policy_decision=SENTINEL_POLICY_DECISION,
            outcome="blocked",
            failure_category=SENTINEL_FAILURE_CATEGORY,
        )
        return SyntheticLifecycleResult(events=[event], dispatch_attempted=False)

    # ------------------------------------------------------------------
    # Step 2: Capability check — agent / tool / environment
    # (ADR-005 §5; ADR-006 §5)
    # ------------------------------------------------------------------
    allowed, cap_failure = check_capability(entry, agent_type, environment_scope)
    if not allowed:
        event = _build_audit_event(
            event_id=event_id,
            timestamp=timestamp,
            session_reference=session_reference,
            operation_reference=operation_reference,
            agent_type=agent_type,
            event_phase="PreToolUse",
            mcp_server=canonical_server,
            mcp_tool=canonical_tool,
            action_class=entry["action_class"],
            environment_scope=environment_scope,
            policy_decision="deny",
            outcome="denied",
            failure_category=cap_failure,
        )
        return SyntheticLifecycleResult(events=[event], dispatch_attempted=False)

    # ------------------------------------------------------------------
    # Step 3: Lifecycle routing — capability checks passed
    # ------------------------------------------------------------------

    if scenario == SCENARIO_PERMISSION_DENIED:
        # User/config permission denied the action before execution.
        # Tool NEVER runs → PostToolUse and PostToolUseFailure are NOT produced.
        # (ADR-006 §2 item 3; MCP_AUDIT_EVENT_CONTRACT.md "Event Türleri")
        event = _build_audit_event(
            event_id=event_id,
            timestamp=timestamp,
            session_reference=session_reference,
            operation_reference=operation_reference,
            agent_type=agent_type,
            event_phase="PermissionDenied",
            mcp_server=canonical_server,
            mcp_tool=canonical_tool,
            action_class=entry["action_class"],
            environment_scope=environment_scope,
            policy_decision="deny",
            outcome="denied",
            failure_category="policy_violation",
        )
        return SyntheticLifecycleResult(events=[event], dispatch_attempted=False)

    if scenario == SCENARIO_POST_TOOL_USE_FAILURE:
        # Tool execution began (dispatch_attempted=True) but failed.
        # PermissionDenied is NOT produced; this is a distinct lifecycle path.
        # (ADR-006 §2 item 6; MCP_AUDIT_EVENT_CONTRACT.md "Event Türleri")
        event = _build_audit_event(
            event_id=event_id,
            timestamp=timestamp,
            session_reference=session_reference,
            operation_reference=operation_reference,
            agent_type=agent_type,
            event_phase="PostToolUseFailure",
            mcp_server=canonical_server,
            mcp_tool=canonical_tool,
            action_class=entry["action_class"],
            environment_scope=environment_scope,
            policy_decision="allow",
            outcome="failure",
            failure_category="tool_error",
        )
        return SyntheticLifecycleResult(events=[event], dispatch_attempted=True)

    if scenario == SCENARIO_POST_TOOL_USE_SUCCESS:
        # Tool execution began and completed successfully.
        event = _build_audit_event(
            event_id=event_id,
            timestamp=timestamp,
            session_reference=session_reference,
            operation_reference=operation_reference,
            agent_type=agent_type,
            event_phase="PostToolUse",
            mcp_server=canonical_server,
            mcp_tool=canonical_tool,
            action_class=entry["action_class"],
            environment_scope=environment_scope,
            policy_decision="allow",
            outcome="success",
            failure_category=None,
        )
        return SyntheticLifecycleResult(events=[event], dispatch_attempted=True)

    # Default: SCENARIO_PRE_TOOL_USE_ALLOWED
    # Policy/capability checks passed; audit gate passed; dispatch is cleared.
    # (ADR-006 §15 "TOCTOU Kapanışı" — in real runtime, dispatch occurs only
    # after durable write acknowledgment; in this synthetic harness we confirm
    # the pre-conditions are met without simulating actual dispatch.)
    event = _build_audit_event(
        event_id=event_id,
        timestamp=timestamp,
        session_reference=session_reference,
        operation_reference=operation_reference,
        agent_type=agent_type,
        event_phase="PreToolUse",
        mcp_server=canonical_server,
        mcp_tool=canonical_tool,
        action_class=entry["action_class"],
        environment_scope=environment_scope,
        policy_decision="allow",
        outcome="success",
        failure_category=None,
    )
    # dispatch_attempted=False: PreToolUse phase has not yet dispatched.
    return SyntheticLifecycleResult(events=[event], dispatch_attempted=False)

# ---------------------------------------------------------------------------
# Schema validation utility
# ---------------------------------------------------------------------------

def validate_audit_event_schema(event: dict) -> list:
    """
    Validate a produced audit event dict against the closed 15-field schema.

    Returns a list of violation strings. An empty list means the event is
    schema-compliant. This function checks:
      1. Field count equals exactly 15.
      2. All 15 required fields are present.
      3. No extra (prohibited) fields are present.
      4. All enum fields contain values from their closed enum sets.
      5. mcp_server and mcp_tool match the canonical label format.
      6. No prohibited field names are present.

    Args:
        event: The audit event dict to validate.

    Returns:
        List of violation description strings (empty = valid).
    """
    violations: list = []

    if not isinstance(event, dict):
        violations.append(f"Event is not a dict: {type(event).__name__!r}")
        return violations

    # 1. Field count
    field_count = len(event)
    if field_count != 15:
        violations.append(
            f"Field count: {field_count}, expected exactly 15"
        )

    # 2. Missing required fields
    missing = REQUIRED_FIELDS - set(event.keys())
    for field in sorted(missing):
        violations.append(f"Missing required field: {field!r}")

    # 3. Extra / prohibited fields (anything beyond the 15)
    extra = set(event.keys()) - REQUIRED_FIELDS
    for field in sorted(extra):
        violations.append(f"Extra field not in closed schema: {field!r}")

    # 4. Prohibited field names (even if somehow listed in event)
    for field in sorted(PROHIBITED_FIELD_NAMES & set(event.keys())):
        violations.append(f"Prohibited field name present: {field!r}")

    # 5. Enum value validation
    # M-001: agent_type must be a canonical role identifier from AGENTS.md.
    # "unknown" and any value not in VALID_AGENT_TYPES are schema violations.
    _check_enum(violations, event, "agent_type", VALID_AGENT_TYPES)
    _check_enum(violations, event, "event_phase", VALID_EVENT_PHASES)
    _check_enum(violations, event, "action_class", VALID_ACTION_CLASSES)
    _check_enum(violations, event, "environment_scope", VALID_ENVIRONMENT_SCOPES)
    _check_enum(violations, event, "policy_decision", VALID_POLICY_DECISIONS)
    _check_enum(violations, event, "outcome", VALID_OUTCOMES)
    _check_enum(violations, event, "failure_category", VALID_FAILURE_CATEGORIES)

    # 6. Canonical label format for mcp_server and mcp_tool
    for field in ("mcp_server", "mcp_tool"):
        if field in event:
            val = event[field]
            if not isinstance(val, str):
                violations.append(
                    f"Field {field!r} must be a string, got {type(val).__name__!r}"
                )
            # L-003: "unclassified" (SENTINEL_MCP_SERVER / SENTINEL_MCP_TOOL) already
            # satisfies the canonical format regex (^[a-z0-9][a-z0-9._-]{0,63}$):
            # it starts with 'u' and consists entirely of lowercase ASCII letters.
            # No sentinel bypass condition is needed; the regex covers it directly.
            elif not CANONICAL_LABEL_PATTERN.match(val):
                violations.append(
                    f"Field {field!r} value {val!r} does not match "
                    f"canonical format {CANONICAL_LABEL_PATTERN.pattern!r}"
                )
            elif isinstance(val, str) and len(val) > CANONICAL_LABEL_MAX_LEN:
                violations.append(
                    f"Field {field!r} value exceeds {CANONICAL_LABEL_MAX_LEN} characters"
                )

    return violations


def _check_enum(violations: list, event: dict, field: str, valid_set: frozenset) -> None:
    """Helper: check that event[field] is a member of valid_set."""
    if field in event and event[field] not in valid_set:
        violations.append(
            f"Field {field!r} has invalid value {event[field]!r}; "
            f"must be one of {sorted(str(v) for v in valid_set if v is not None)}"
        )

# ---------------------------------------------------------------------------
# Forbidden value check utility (AC-005)
# ---------------------------------------------------------------------------

def check_for_forbidden_values(
    event: dict,
    forbidden_markers: tuple,
) -> list:
    """
    Check that none of the forbidden marker strings appear as (partial) values
    in any field of the audit event dict.

    This function checks all field values in the event. If a marker string
    appears anywhere within a field's string representation, it is reported as
    a violation.

    Args:
        event:             The audit event dict to inspect.
        forbidden_markers: Tuple of marker strings that must not appear.

    Returns:
        List of (marker, field_name, field_value) tuples for each violation found.
        An empty list means no forbidden data was detected.
    """
    violations: list = []
    for marker in forbidden_markers:
        if not isinstance(marker, str):
            continue
        for field_name, field_value in event.items():
            if field_value is None:
                continue
            # Check string values directly; convert others to str for inspection
            value_str: str = (
                field_value if isinstance(field_value, str) else str(field_value)
            )
            if marker in value_str:
                violations.append((marker, field_name, field_value))
    return violations
