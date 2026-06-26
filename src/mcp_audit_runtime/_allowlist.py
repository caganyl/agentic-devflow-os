"""
_allowlist.py — Local synthetic tool allowlist for the canonical MCP audit runtime.

This module defines the local mapping from (raw_server, raw_tool) pairs to
canonical entries used by the Identity Canonicalizer (ADR-007 §2.1).

IMPORTANT: All entries here use deliberately synthetic MCP server and tool
names ("example-*-mcp"). These do NOT correspond to any real MCP server,
production tool, endpoint, or credential. They exist only to exercise the
classification and capability-gating logic locally.

The allowlist structure mirrors MCP_AGENT_CAPABILITY_MATRIX.md policy, but
uses synthetic names because no real MCP server is connected (REQ-003 scope).

Real MCP server entries must NOT be added here until SEC-ADR-005-MCP-
CONNECTION-PRECONDITIONS.md No-Go gates are closed and human maintainer
approval is obtained.
"""

# Format: (raw_server_string, raw_tool_string) -> canonical capability entry
# Each entry contains:
#   mcp_server:       canonical label (^[a-z0-9][a-z0-9._-]{0,63}$)
#   mcp_tool:         canonical label
#   action_class:     closed enum value from MCP_AUDIT_EVENT_CONTRACT.md
#   environment_scope: closed enum value; "n/a" means any caller-supplied scope accepted
#   allowed_agents:   frozenset of canonical agent_type strings from AGENTS.md
#
# Explicitly prohibited actions are modelled by absence from allowed_agents.
# A separate "policy_violation" failure category is reserved for future
# rule-engine enforcement of explicitly prohibited actions beyond capability
# matrix checks.

TOOL_ALLOWLIST: dict = {
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
