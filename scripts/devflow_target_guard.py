#!/usr/bin/env python3
"""
DevFlow Target Safety Guard

PreToolUse hook for Claude Code. Reads the tool invocation from stdin as a
JSON object and blocks destructive or sensitive operations.

Exit codes:
    0  Allow — tool call proceeds
    2  Deny  — tool call is blocked; reason sent to Claude via stderr

SCOPE: This guard protects Claude Code tool calls (Bash, Write, Edit) only.
Commands typed directly in the user's terminal are NOT intercepted.
No network access, no credential access, no external processes.
Standard library only.
"""

import json
import re
import sys
from typing import Optional

# ---------------------------------------------------------------------------
# Blocked Bash patterns
# ---------------------------------------------------------------------------

_BASH_BLOCK_PATTERNS = [
    # git merge (direct)
    re.compile(r"\bgit\s+merge\b"),
    # git merge via global flags (e.g. git -C /path merge, git -c k=v merge)
    re.compile(r"\bgit\s+(?:-[^\s]+\s+\S+\s+)+merge\b"),
    # git push with any force variant (flag anywhere after 'push')
    re.compile(r"\bgit\s+push\b[^|;&\n]*(?:--force-with-lease\b|--force\b|\s-f\b)"),
    # git branch delete (short: -d/-D; long: --delete)
    re.compile(r"\bgit\s+branch\b[^|;&\n]*(?:--delete|-[dD])\b"),
    # git reset
    re.compile(r"\bgit\s+reset\s+--hard\b"),
    re.compile(r"\bgit\s+reset\s+--soft\b"),
    re.compile(r"\bgit\s+reset\s+--mixed\b"),
    # git clean
    re.compile(r"\bgit\s+clean\s+-f\b"),
    # git checkout -- .
    re.compile(r"\bgit\s+checkout\s+--\s+\."),
    # git restore .
    re.compile(r"\bgit\s+restore\s+\."),
    # rm with combined force+recursive flags, short form (any order)
    re.compile(r"\brm\s+-[a-zA-Z]*[rR][a-zA-Z]*[fF][a-zA-Z]*\b"),  # -rf, -Rf, -rfv …
    re.compile(r"\brm\s+-[a-zA-Z]*[fF][a-zA-Z]*[rR][a-zA-Z]*\b"),  # -fr, -Fr, -frv …
    # rm with long-form --recursive and --force flags (any order)
    re.compile(r"\brm\b[^|;&\n]*--(?:recursive|force)\b[^|;&\n]*--(?:force|recursive)\b"),
]

# ---------------------------------------------------------------------------
# Protected path patterns (Write / Edit)
# ---------------------------------------------------------------------------

_PATH_BLOCK_PATTERNS = [
    # .env, .env.local, .env.production, etc.
    re.compile(r"(^|[/\\])\.env(\.|$)"),
    re.compile(r"(^|[/\\])\.env$"),
    # credential / credentials as a path segment
    re.compile(r"(^|[/\\])credential[s]?([/\\.]|$)", re.IGNORECASE),
    # secret / secrets as a path segment
    re.compile(r"(^|[/\\])secret[s]?([/\\.]|$)", re.IGNORECASE),
    # MCP config files
    re.compile(r"(^|[/\\])\.mcp\.json$"),
    re.compile(r"(^|[/\\])mcp\.json$"),
    re.compile(r"(^|[/\\])mcp_config\.json$"),
    # Claude settings
    re.compile(r"(^|[/\\])\.claude[/\\]settings\.json$"),
    re.compile(r"(^|[/\\])\.claude[/\\]settings\.local\.json$"),
    # Claude hooks directory (any file inside .claude/hooks/)
    re.compile(r"(^|[/\\])\.claude[/\\]hooks[/\\]"),
    # Canonical run state — must only be written via devflow_operations.py CLI
    re.compile(r"(^|[/\\])\.devflow[/\\]runs[/\\]"),
    # Canonical scorecard/report — must only be written via devflow_operations.py CLI
    re.compile(r"(^|[/\\])\.devflow[/\\]reports[/\\]"),
]

# Fixed deny messages — must NOT echo user-supplied data
_DENY_BASH_MSG = (
    "DevFlow guard: destructive or unsafe shell operation blocked by policy."
)
_DENY_PATH_MSG = (
    "DevFlow guard: write or edit to protected path blocked by policy."
)
_DENY_VALIDATION_MSG = (
    "DevFlow guard: hook input validation failed; tool call blocked by policy."
)


def _check_bash(command: str) -> Optional[str]:
    for pattern in _BASH_BLOCK_PATTERNS:
        if pattern.search(command):
            return _DENY_BASH_MSG
    return None


def _check_path(path: str) -> Optional[str]:
    for pattern in _PATH_BLOCK_PATTERNS:
        if pattern.search(path):
            return _DENY_PATH_MSG
    return None


def main() -> None:
    # --- Input validation (fail-closed) ---
    raw = sys.stdin.read()
    if not raw.strip():
        print(_DENY_VALIDATION_MSG, file=sys.stderr)
        sys.exit(2)

    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        print(_DENY_VALIDATION_MSG, file=sys.stderr)
        sys.exit(2)

    if not isinstance(payload, dict):
        print(_DENY_VALIDATION_MSG, file=sys.stderr)
        sys.exit(2)

    tool_name = payload.get("tool_name")
    if not isinstance(tool_name, str):
        print(_DENY_VALIDATION_MSG, file=sys.stderr)
        sys.exit(2)

    # Unknown tool names pass through — hook matcher only fires for Bash/Write/Edit
    if tool_name not in ("Bash", "Write", "Edit"):
        sys.exit(0)

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        print(_DENY_VALIDATION_MSG, file=sys.stderr)
        sys.exit(2)

    if tool_name == "Bash":
        command = tool_input.get("command")
        if not isinstance(command, str):
            print(_DENY_VALIDATION_MSG, file=sys.stderr)
            sys.exit(2)
        reason = _check_bash(command)
        if reason:
            print(reason, file=sys.stderr)
            sys.exit(2)

    elif tool_name in ("Write", "Edit"):
        file_path = tool_input.get("file_path")
        if not isinstance(file_path, str):
            print(_DENY_VALIDATION_MSG, file=sys.stderr)
            sys.exit(2)
        reason = _check_path(file_path)
        if reason:
            print(reason, file=sys.stderr)
            sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
