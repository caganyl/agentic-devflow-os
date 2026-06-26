"""
mcp_audit_runtime — Local Canonical MCP Audit Runtime Foundation (REQ-003)

Local experimental foundation for the canonical MCP audit runtime defined
in ADR-007. Uses simulated_dispatch instead of real MCP connections.

IMPORTANT LIMITS:
  - No real MCP connection.
  - No network calls, tokens, credentials, or external services.
  - SQLite durable acknowledgment is application-level only; not tamper-proof
    without external anchoring.
  - Completing REQ-003 does NOT close any No-Go gate in SEC-ADR-005.
"""

from .canonicalizer import canonicalize_identity
from .policy_gate import evaluate_policy
from .event_builder import build_event, validate_event
from .sqlite_sink import AuditSink
from .writer import AuditWriter, FailureSignal
from .orchestrator import LifecycleResult, run_lifecycle

__all__ = [
    "canonicalize_identity",
    "evaluate_policy",
    "build_event",
    "validate_event",
    "AuditSink",
    "AuditWriter",
    "FailureSignal",
    "LifecycleResult",
    "run_lifecycle",
]
