"""
_constants.py — Closed contract constants for the canonical MCP audit runtime.

Sourced from MCP_AUDIT_EVENT_CONTRACT.md (canonical source of truth).
These constants mirror the closed enum definitions from the contract.
Must not diverge from MCP_AUDIT_EVENT_CONTRACT.md without a schema_version bump.
"""

import re

SCHEMA_VERSION: str = "1.0.0"
AUDIT_RECORD_VERSION: int = 1

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

# None is valid when outcome is not "failure" or "blocked"
VALID_FAILURE_CATEGORIES: frozenset = frozenset({
    "policy_violation",
    "capability_mismatch",
    "unclassified_tool_identity",
    "tool_error",
    "audit_unavailable",
    "unknown",
    None,
})

SENTINEL_MCP_SERVER: str = "unclassified"
SENTINEL_MCP_TOOL: str = "unclassified"

# Canonical label format (ADR-006 §14; MCP_AUDIT_EVENT_CONTRACT.md)
CANONICAL_LABEL_PATTERN: re.Pattern = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
CANONICAL_LABEL_MAX_LEN: int = 64

# Field names that must never appear in any audit event payload
PROHIBITED_FIELD_NAMES: frozenset = frozenset({
    "note", "notes", "message", "error_message", "details", "description",
    "context", "metadata", "debug", "raw_input", "raw_output", "prompt",
    "url", "header", "file_path", "exception", "reason", "token",
    "credential", "api_key", "secret", "pii", "tool_input", "tool_output",
})
