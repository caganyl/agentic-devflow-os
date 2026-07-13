#!/usr/bin/env python3
"""Codex PreToolUse adapter for the DevFlow semantic guard policy.

The hook reads one event from stdin.  It is defense in depth: it does not
replace the managed Git worktree, Codex OS sandbox, or operations approval
gate, and PreToolUse is not claimed to intercept every execution path.

Codex CLI 0.144.3 locally exposes the structured PreToolUse denial schema
used below.  If structured output cannot be emitted, the adapter falls back
to exit code 2 and a fixed stderr reason.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import NoReturn, Optional

from devflow_guard_core import (
    DENY_PATCH,
    dangerous_command_reason,
    normalize_worktree,
    shell_navigation_reason,
    validate_apply_patch,
    validate_target_path,
)


DENY_VALIDATION = "DevFlow guard: hook input validation failed; tool call blocked by policy."
DENY_BRANCH = "DevFlow guard: managed run branch verification failed; tool call blocked by policy."


def _fallback_deny(reason: str) -> NoReturn:
    print(reason, file=sys.stderr)
    raise SystemExit(2)


def _deny(reason: str) -> NoReturn:
    response = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    try:
        sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
        sys.stdout.flush()
    except (BrokenPipeError, OSError, TypeError, ValueError):
        _fallback_deny(reason)
    raise SystemExit(0)


def _managed_worktree() -> Path:
    raw = os.environ.get("DEVFLOW_RUN_WORKTREE")
    if not raw:
        _deny(DENY_VALIDATION)
    try:
        return normalize_worktree(raw)
    except (OSError, RuntimeError, ValueError):
        _deny(DENY_VALIDATION)


def _verify_branch_when_configured(worktree: Path) -> Optional[str]:
    expected = os.environ.get("DEVFLOW_RUN_BRANCH")
    if not expected:
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(worktree), "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return DENY_BRANCH
    if result.returncode != 0 or result.stdout.strip() != expected:
        return DENY_BRANCH
    return None


def _command_text(tool_input: dict) -> Optional[str]:
    command = tool_input.get("command")
    return command if isinstance(command, str) else None


def _patch_text(tool_input: dict) -> Optional[str]:
    for key in ("command", "patch"):
        value = tool_input.get(key)
        if isinstance(value, str):
            return value
    return None


def main() -> None:
    raw = sys.stdin.read()
    if not raw.strip():
        _deny(DENY_VALIDATION)
    try:
        event = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        _deny(DENY_VALIDATION)
    if not isinstance(event, dict):
        _deny(DENY_VALIDATION)

    tool_name = event.get("tool_name")
    if not isinstance(tool_name, str):
        _deny(DENY_VALIDATION)
    if tool_name not in {"apply_patch", "Bash", "bash", "Edit", "Write"}:
        raise SystemExit(0)

    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        _deny(DENY_VALIDATION)
    worktree = _managed_worktree()
    branch_reason = _verify_branch_when_configured(worktree)
    if branch_reason:
        _deny(branch_reason)

    reason: Optional[str]
    if tool_name == "apply_patch":
        patch = _patch_text(tool_input)
        reason = DENY_PATCH if patch is None else validate_apply_patch(patch, worktree)
    elif tool_name in {"Bash", "bash"}:
        command = _command_text(tool_input)
        if command is None:
            _deny(DENY_VALIDATION)
        reason = dangerous_command_reason(command)
        if reason is None:
            reason = shell_navigation_reason(command, worktree)
    else:
        path = tool_input.get("file_path", tool_input.get("path"))
        if not isinstance(path, str):
            _deny(DENY_VALIDATION)
        reason = validate_target_path(path, worktree)

    if reason:
        _deny(reason)
    raise SystemExit(0)


if __name__ == "__main__":
    main()

