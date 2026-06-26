"""
canonicalizer.py — MCP Tool Identity Canonicalizer (ADR-007 §2.1)

Responsibility: Convert incoming raw (mcp_server, mcp_tool) pair to a
canonical label via the local allowlist. If classification fails, return
the fixed sentinel values ("unclassified", "unclassified").

Bounds (ADR-007 §2.1):
  - Raw strings are NEVER persisted, logged, or passed to any other component.
  - Sentinel values are returned only on classification failure.
  - Built-in Claude tools must NOT pass through this component.
  - Only canonical lowercase ASCII labels (^[a-z0-9][a-z0-9._-]{0,63}$) are
    produced as non-sentinel output.
"""

from ._constants import (
    SENTINEL_MCP_SERVER,
    SENTINEL_MCP_TOOL,
    CANONICAL_LABEL_PATTERN,
    CANONICAL_LABEL_MAX_LEN,
)
from ._allowlist import TOOL_ALLOWLIST


def canonicalize_identity(
    raw_server: str,
    raw_tool: str,
) -> tuple:
    """
    Classify a (raw_server, raw_tool) pair against the local allowlist.

    Returns a 4-tuple:
        (canonical_server, canonical_tool, entry_or_None, classified: bool)

    On success (pair found in allowlist):
        - classified = True
        - canonical_server/canonical_tool = allowlist canonical labels
        - entry_or_None = the full allowlist entry dict

    On failure (pair not in allowlist, or format invalid):
        - classified = False
        - canonical_server = "unclassified"  (SENTINEL_MCP_SERVER)
        - canonical_tool   = "unclassified"  (SENTINEL_MCP_TOOL)
        - entry_or_None    = None
        NOTE: raw_server and raw_tool are NOT returned under any condition.
    """
    if not isinstance(raw_server, str) or not isinstance(raw_tool, str):
        return SENTINEL_MCP_SERVER, SENTINEL_MCP_TOOL, None, False

    entry = TOOL_ALLOWLIST.get((raw_server, raw_tool))
    if entry is None:
        return SENTINEL_MCP_SERVER, SENTINEL_MCP_TOOL, None, False

    canonical_server = entry["mcp_server"]
    canonical_tool = entry["mcp_tool"]

    if not _is_valid_canonical_label(canonical_server):
        return SENTINEL_MCP_SERVER, SENTINEL_MCP_TOOL, None, False
    if not _is_valid_canonical_label(canonical_tool):
        return SENTINEL_MCP_SERVER, SENTINEL_MCP_TOOL, None, False

    return canonical_server, canonical_tool, entry, True


def _is_valid_canonical_label(label: str) -> bool:
    if not isinstance(label, str):
        return False
    if len(label) > CANONICAL_LABEL_MAX_LEN:
        return False
    return bool(CANONICAL_LABEL_PATTERN.match(label))
