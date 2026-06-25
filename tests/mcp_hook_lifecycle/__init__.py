"""
tests/mcp_hook_lifecycle — REQ-001 Offline Synthetic Audit Lifecycle Test Package

SCOPE: This package is TEST-ONLY, OFFLINE, and DETERMINISTIC.

It validates the MCP audit lifecycle logic and contract compliance described in:
  - REQ-001-mcp-hook-lifecycle-synthetic-validation.md (Accepted)
  - AC-REQ-001-mcp-hook-lifecycle-synthetic-validation.md (Accepted)
  - ADR-006-mcp-audit-logging-and-runtime-enforcement.md (Accepted)
  - MCP_AUDIT_EVENT_CONTRACT.md

This package is NOT a production hook, NOT a real MCP client, and NOT a real
audit logger. It makes no network calls, subprocess calls, file I/O operations,
or environment secret reads. All values are synthetic fixtures; no real MCP
server names, endpoints, credentials, or tools are used.

Runs with Python standard library only (no third-party dependencies).

AC coverage: AC-001 through AC-011.
"""
