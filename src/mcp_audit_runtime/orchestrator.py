"""
orchestrator.py — Lifecycle Orchestrator (ADR-007 §3)

Responsibility: Coordinate the canonical MCP audit lifecycle using
simulated_dispatch instead of a real MCP dispatch (REQ-003 scope).

Lifecycle steps implemented (ADR-007 §3):
  Step 2: Identity canonicalization
  Step 3: Policy/capability decision
  Step 4: PreToolUse canonical audit event build
  Step 5: Out-of-Band Writer + Durable Acknowledgment Gate
  Step 6: Dispatch decision (allow + ack → simulated dispatch; deny → terminal)
  Step 7: PostToolUse / PostToolUseFailure
  Step 8: Pre-dispatch error path (no dispatch, failure signal, no record claim)

Contract-level outcome mapping (ADR-007 "Contract-level outcome mapping"):
  - Unclassified identity:           outcome="blocked", failure_category="unclassified_tool_identity"
  - Capability/policy mismatch:      outcome="denied",  failure_category="capability_mismatch"
  - Policy allow + successful exec:  outcome="success", failure_category=null  (PostToolUse)
  - Policy allow + tool error:       outcome="failure", failure_category="tool_error" (PostToolUseFailure)
  - Pre-dispatch audit unavailable:  no persisted record claim; failure signal only
  - Post-dispatch audit failure:     dispatch not rolled back; audit_integrity_incident=True

BOUNDS:
  - simulated_dispatch is a local callable; no real MCP connection.
  - No recursive audit/enforcement loop.
  - Pre-dispatch audit failure → dispatch NEVER starts.
  - Post-dispatch audit failure → NO rollback, NO cancel, audit_integrity_incident=True.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .canonicalizer import canonicalize_identity
from .policy_gate import evaluate_policy
from .event_builder import build_event
from .writer import AuditWriter, FailureSignal
from ._constants import SENTINEL_MCP_SERVER, SENTINEL_MCP_TOOL


@dataclass
class LifecycleResult:
    """
    Result of a single run_lifecycle() invocation.

    Fields:
        dispatch_attempted:        True only if simulated_dispatch was called.
        pre_event_written:         True if PreToolUse event was durably acknowledged.
        post_event_written:        True if PostToolUse/Failure event was durably acknowledged.
        simulated_dispatch_output: Return value of simulated_dispatch (or None).
        dispatch_tool_failure:     True if simulated_dispatch raised an exception.
        failure_signal:            Non-None when a failure occurred (pre or post).
        audit_integrity_incident:  True if post-dispatch audit write failed.
        events_produced:           List of canonical event dicts successfully written.
    """
    dispatch_attempted: bool = False
    pre_event_written: bool = False
    post_event_written: bool = False
    simulated_dispatch_output: Any = None
    dispatch_tool_failure: bool = False
    failure_signal: Optional[FailureSignal] = None
    audit_integrity_incident: bool = False
    events_produced: list = field(default_factory=list)


def run_lifecycle(
    raw_server: str,
    raw_tool: str,
    agent_type: str,
    environment_scope: str,
    pre_event_id: str,
    post_event_id: str,
    timestamp: str,
    session_reference: str,
    operation_reference: str,
    sink,
    simulated_dispatch: Callable,
) -> LifecycleResult:
    """
    Run the canonical MCP audit lifecycle for one candidate tool call.

    Args:
        raw_server:          Raw MCP server string from the incoming call.
        raw_tool:            Raw MCP tool string from the incoming call.
        agent_type:          Canonical agent role making the call.
        environment_scope:   Caller's claimed environment scope.
        pre_event_id:        Unique ID for the PreToolUse event.
        post_event_id:       Unique ID for the PostToolUse/Failure event.
        timestamp:           ISO-8601 UTC timestamp string.
        session_reference:   Privacy-preserving session correlation reference.
        operation_reference: Privacy-preserving per-call correlation reference.
        sink:                Audit sink with write_event(event: dict) -> bool.
        simulated_dispatch:  Local callable; called only when allow + ack.

    Returns:
        LifecycleResult with all outcome fields populated.
    """
    writer = AuditWriter(sink)

    # Step 2: Canonicalize identity
    canonical_server, canonical_tool, entry, classified = canonicalize_identity(
        raw_server, raw_tool
    )

    # Step 3: Policy/capability decision
    policy_decision, failure_category = evaluate_policy(
        entry, agent_type, environment_scope, classified
    )

    # Determine action_class and effective environment_scope for the event
    action_class = entry["action_class"] if entry is not None else "other"
    event_env_scope = environment_scope if entry is not None else "n/a"

    # Determine outcome for PreToolUse
    if not classified:
        pre_outcome = "blocked"
    elif policy_decision == "deny":
        pre_outcome = "denied"
    else:
        pre_outcome = "success"

    # Step 4: Build PreToolUse canonical audit event
    try:
        pre_event = build_event(
            event_id=pre_event_id,
            timestamp=timestamp,
            session_reference=session_reference,
            operation_reference=operation_reference,
            agent_type=agent_type,
            event_phase="PreToolUse",
            mcp_server=canonical_server,
            mcp_tool=canonical_tool,
            action_class=action_class,
            environment_scope=event_env_scope,
            policy_decision=policy_decision,
            outcome=pre_outcome,
            failure_category=failure_category,
        )
    except Exception:
        # ADR-007 Step 8: builder error → no dispatch, failure signal, no record claim
        return LifecycleResult(
            failure_signal=writer.make_failure_signal("audit_unavailable"),
        )

    # Step 5: Durable write acknowledgment
    pre_written = writer.write_with_ack(pre_event)

    if not pre_written:
        # ADR-007 Step 8: pre-dispatch write failure → no dispatch, no record claim
        return LifecycleResult(
            failure_signal=writer.make_failure_signal("audit_unavailable"),
        )

    # Step 6: Dispatch decision
    if policy_decision == "deny":
        # Durable ack received, but policy denies → terminal deny/blocked
        # No dispatch. Pre-event was written.
        return LifecycleResult(
            pre_event_written=True,
            events_produced=[pre_event],
        )

    # Step 6a: Dispatch (only after durable ack + allow)
    dispatch_output = None
    tool_failure = False
    try:
        dispatch_output = simulated_dispatch()
    except Exception:
        tool_failure = True

    # Step 7: Build PostToolUse / PostToolUseFailure event
    if tool_failure:
        post_phase = "PostToolUseFailure"
        post_outcome = "failure"
        post_failure_cat = "tool_error"
    else:
        post_phase = "PostToolUse"
        post_outcome = "success"
        post_failure_cat = None

    try:
        post_event = build_event(
            event_id=post_event_id,
            timestamp=timestamp,
            session_reference=session_reference,
            operation_reference=operation_reference,
            agent_type=agent_type,
            event_phase=post_phase,
            mcp_server=canonical_server,
            mcp_tool=canonical_tool,
            action_class=action_class,
            environment_scope=event_env_scope,
            policy_decision="allow",
            outcome=post_outcome,
            failure_category=post_failure_cat,
        )
    except Exception:
        # Post-dispatch builder failure → audit integrity incident, no rollback
        return LifecycleResult(
            dispatch_attempted=True,
            pre_event_written=True,
            dispatch_tool_failure=tool_failure,
            simulated_dispatch_output=dispatch_output,
            failure_signal=writer.make_failure_signal("audit_unavailable"),
            audit_integrity_incident=True,
            events_produced=[pre_event],
        )

    # Write PostToolUse event
    post_written = writer.write_with_ack(post_event)

    if not post_written:
        # ADR-007 §3.1: post-dispatch write failure → incident, no rollback
        return LifecycleResult(
            dispatch_attempted=True,
            pre_event_written=True,
            post_event_written=False,
            dispatch_tool_failure=tool_failure,
            simulated_dispatch_output=dispatch_output,
            failure_signal=writer.make_failure_signal("audit_unavailable"),
            audit_integrity_incident=True,
            events_produced=[pre_event],
        )

    return LifecycleResult(
        dispatch_attempted=True,
        pre_event_written=True,
        post_event_written=True,
        dispatch_tool_failure=tool_failure,
        simulated_dispatch_output=dispatch_output,
        events_produced=[pre_event, post_event],
    )
