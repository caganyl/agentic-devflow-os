"""
policy_gate.py — Policy and Capability Gate (ADR-007 §2.2)

Responsibility: Evaluate canonical tool identity against agent identity,
tool capability, and environment boundary to produce an allow/deny decision
and the corresponding failure_category.

Bounds (ADR-007 §2.2):
  - Operates independently from Canonical Audit Event Builder and Durable
    Acknowledgment Gate.
  - Produces only "allow" or "deny"; no audit writing, no storage.
  - If entry is None (unclassified identity), the result is mandatory "deny"
    with failure_category "unclassified_tool_identity".
  - Capability mismatch (agent not in allowed_agents, or wrong environment)
    → failure_category "capability_mismatch".
  - Policy violation (explicitly prohibited action) → failure_category
    "policy_violation". Reserved for future rule-engine integration; current
    allowlist uses absence from allowed_agents to model prohibition.
"""

from ._constants import VALID_AGENT_TYPES


def evaluate_policy(
    entry,            # dict | None — from canonicalizer; None = unclassified
    agent_type: str,
    environment_scope: str,
    classified: bool,
) -> tuple:
    """
    Evaluate whether this call should be allowed or denied.

    Args:
        entry:             Allowlist entry dict, or None if unclassified.
        agent_type:        Caller's agent role (must be a valid AGENTS.md role).
        environment_scope: Caller's claimed environment scope.
        classified:        True if the tool identity was successfully classified.

    Returns:
        (policy_decision: str, failure_category: str | None)
        policy_decision is "allow" or "deny".
        failure_category is None when policy_decision is "allow".
    """
    if not classified or entry is None:
        return "deny", "unclassified_tool_identity"

    if agent_type not in entry["allowed_agents"]:
        return "deny", "capability_mismatch"

    allowlist_scope = entry["environment_scope"]
    if allowlist_scope != "n/a" and environment_scope != allowlist_scope:
        return "deny", "capability_mismatch"

    return "allow", None
