"""
event_builder.py — Canonical Audit Event Builder (ADR-007 §2.3)

Responsibility: Build exactly the closed 15-field audit event dict defined
in MCP_AUDIT_EVENT_CONTRACT.md. No extra fields are added. Raw input/output,
prompt, URL, path, token, secret, header, exception text, and free text are
never accepted.

Bounds (ADR-007 §2.3):
  - Exactly 15 fields per the closed schema.
  - mcp_server and mcp_tool receive only canonical labels or "unclassified".
  - All enum fields must be members of their closed enum sets.
  - validate_event() reports violations without raising; callers decide action.
"""

from ._constants import (
    SCHEMA_VERSION,
    AUDIT_RECORD_VERSION,
    REQUIRED_FIELDS,
    VALID_AGENT_TYPES,
    VALID_EVENT_PHASES,
    VALID_ACTION_CLASSES,
    VALID_ENVIRONMENT_SCOPES,
    VALID_POLICY_DECISIONS,
    VALID_OUTCOMES,
    VALID_FAILURE_CATEGORIES,
    PROHIBITED_FIELD_NAMES,
    CANONICAL_LABEL_PATTERN,
    CANONICAL_LABEL_MAX_LEN,
)


def build_event(
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
    Build a closed 15-field canonical audit event dict.

    Returns a dict with exactly the 15 required fields. No extra fields.
    Callers are responsible for supplying valid enum values.
    Use validate_event() to check the result before writing.

    Raises ValueError if any enum field contains an invalid value.
    """
    _require_enum("agent_type", agent_type, VALID_AGENT_TYPES)
    _require_enum("event_phase", event_phase, VALID_EVENT_PHASES)
    _require_enum("action_class", action_class, VALID_ACTION_CLASSES)
    _require_enum("environment_scope", environment_scope, VALID_ENVIRONMENT_SCOPES)
    _require_enum("policy_decision", policy_decision, VALID_POLICY_DECISIONS)
    _require_enum("outcome", outcome, VALID_OUTCOMES)
    _require_enum("failure_category", failure_category, VALID_FAILURE_CATEGORIES)
    _require_canonical_label("mcp_server", mcp_server)
    _require_canonical_label("mcp_tool", mcp_tool)

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


def validate_event(event: dict) -> list:
    """
    Validate an audit event dict against the closed 15-field schema.

    Returns a list of violation strings. Empty list = schema-compliant.
    """
    violations: list = []

    if not isinstance(event, dict):
        violations.append(f"Event is not a dict: {type(event).__name__!r}")
        return violations

    field_count = len(event)
    if field_count != 15:
        violations.append(f"Field count: {field_count}, expected exactly 15")

    missing = REQUIRED_FIELDS - set(event.keys())
    for field in sorted(missing):
        violations.append(f"Missing required field: {field!r}")

    extra = set(event.keys()) - REQUIRED_FIELDS
    for field in sorted(extra):
        violations.append(f"Extra field not in closed schema: {field!r}")

    for field in sorted(PROHIBITED_FIELD_NAMES & set(event.keys())):
        violations.append(f"Prohibited field name present: {field!r}")

    _check_enum(violations, event, "agent_type", VALID_AGENT_TYPES)
    _check_enum(violations, event, "event_phase", VALID_EVENT_PHASES)
    _check_enum(violations, event, "action_class", VALID_ACTION_CLASSES)
    _check_enum(violations, event, "environment_scope", VALID_ENVIRONMENT_SCOPES)
    _check_enum(violations, event, "policy_decision", VALID_POLICY_DECISIONS)
    _check_enum(violations, event, "outcome", VALID_OUTCOMES)
    _check_enum(violations, event, "failure_category", VALID_FAILURE_CATEGORIES)

    for field in ("mcp_server", "mcp_tool"):
        if field in event:
            val = event[field]
            if not isinstance(val, str):
                violations.append(
                    f"Field {field!r} must be a string, got {type(val).__name__!r}"
                )
            elif not CANONICAL_LABEL_PATTERN.match(val):
                violations.append(
                    f"Field {field!r} value {val!r} does not match canonical format"
                )
            elif len(val) > CANONICAL_LABEL_MAX_LEN:
                violations.append(
                    f"Field {field!r} value exceeds {CANONICAL_LABEL_MAX_LEN} characters"
                )

    return violations


def _require_enum(field: str, value, valid_set: frozenset) -> None:
    if value not in valid_set:
        raise ValueError(
            f"Invalid value for {field!r}: {value!r}. "
            f"Must be one of: {sorted(str(v) for v in valid_set if v is not None)}"
        )


def _require_canonical_label(field: str, value: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"Field {field!r} must be a string")
    if not CANONICAL_LABEL_PATTERN.match(value):
        raise ValueError(
            f"Field {field!r} value {value!r} does not match canonical format"
        )
    if len(value) > CANONICAL_LABEL_MAX_LEN:
        raise ValueError(
            f"Field {field!r} value exceeds {CANONICAL_LABEL_MAX_LEN} characters"
        )


def _check_enum(violations: list, event: dict, field: str, valid_set: frozenset) -> None:
    if field in event and event[field] not in valid_set:
        violations.append(
            f"Field {field!r} has invalid value {event[field]!r}"
        )
