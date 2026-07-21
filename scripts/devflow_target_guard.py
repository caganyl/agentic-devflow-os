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

BOUNDARY ENFORCEMENT: When DEVFLOW_RUN_WORKTREE is set in the environment,
Write/Edit calls that resolve outside the managed run worktree are denied,
and Bash calls containing explicit cd/git -C/--work-tree navigation to paths
outside the worktree are denied. This is tool-call enforcement and defense
in depth — it is NOT an OS-level sandbox. Direct terminal commands and
subprocess execution are not intercepted by this guard.
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Run worktree boundary (activated only when DEVFLOW_RUN_WORKTREE is set)
# ---------------------------------------------------------------------------

_RUN_WORKTREE: Optional[Path] = None
_raw_run_worktree = os.environ.get("DEVFLOW_RUN_WORKTREE", "")
if _raw_run_worktree:
    try:
        _RUN_WORKTREE = Path(_raw_run_worktree).resolve()
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Blocked Bash patterns
# ---------------------------------------------------------------------------

_BASH_BLOCK_PATTERNS = [
    # git merge (direct). (?![-\w]) instead of \b: a trailing \b also matches
    # before a hyphen, so `git merge-base` — a read-only ancestry query, along
    # with `git merge-tree` and `git merge-file` — was refused as if it were a
    # merge. The lookahead keeps `git merge` blocked and lets the hyphenated
    # plumbing commands through.
    re.compile(r"\bgit\s+merge(?![-\w])"),
    # git merge via global flags (e.g. git -C /path merge, git -c k=v merge)
    re.compile(r"\bgit\s+(?:-[^\s]+\s+\S+\s+)+merge(?![-\w])"),
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

# ---------------------------------------------------------------------------
# Bash navigation boundary patterns (used only when _RUN_WORKTREE is set)
# Matches explicit path-changing forms; simple relative paths are not checked.
# ---------------------------------------------------------------------------

# cd <path> — captures the path argument after cd
_CD_PATH_RE = re.compile(r'\bcd\s+([^\s;&|><\n]+)')
# git -C <path> — captures path after -C flag
_GIT_C_PATH_RE = re.compile(r'\bgit\b[^|;&\n]*\s-C\s+([^\s;&|><\n]+)')
# git --work-tree <path> — space form
_GIT_WT_SPACE_RE = re.compile(r'\bgit\b[^|;&\n]*--work-tree\s+([^\s;&|><\n]+)')
# git --work-tree=<path> — equals form
_GIT_WT_EQ_RE = re.compile(r'\bgit\b[^|;&\n]*--work-tree=([^\s;&|><\n]+)')

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
_DENY_BOUNDARY_MSG = (
    "DevFlow guard: write or edit outside the managed run worktree is blocked by policy."
)
_DENY_BASH_BOUNDARY_MSG = (
    "DevFlow guard: shell navigation outside the managed run worktree is blocked by policy."
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


def _strip_shell_quotes(s: str) -> str:
    """Strip surrounding single or double quotes from a shell argument."""
    if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        return s[1:-1]
    return s


def _expand_run_worktree_var(s: str, run_worktree: Path) -> str:
    """Replace $DEVFLOW_RUN_WORKTREE with the actual run worktree path string."""
    return s.replace("$DEVFLOW_RUN_WORKTREE", str(run_worktree))


def _check_path_boundary(file_path: str, run_worktree: Path) -> Optional[str]:
    """
    Return a deny message if file_path resolves outside run_worktree.

    Handles absolute external paths, ../ traversal, and symlink escape via
    Path.resolve() which follows symlinks. Empty paths are not checked.
    """
    if not file_path:
        return None
    try:
        resolved = Path(file_path).resolve()
        try:
            resolved.relative_to(run_worktree)
        except ValueError:
            return _DENY_BOUNDARY_MSG
    except Exception:
        pass  # Unresolvable path — don't block
    return None


def _check_bash_boundary(command: str, run_worktree: Path) -> Optional[str]:
    """
    Return a deny message if the command attempts to navigate outside
    run_worktree via cd, git -C, or git --work-tree.

    Only absolute paths and paths containing '..' are checked; simple relative
    paths (no '..' and not absolute) are skipped because their effective CWD
    is unknown at hook-call time. $DEVFLOW_RUN_WORKTREE is expanded before
    the check so that cd "$DEVFLOW_RUN_WORKTREE" is always allowed.

    This is best-effort defense in depth — not an OS-level sandbox.
    """
    nav_patterns = [_CD_PATH_RE, _GIT_C_PATH_RE, _GIT_WT_SPACE_RE, _GIT_WT_EQ_RE]
    for pattern in nav_patterns:
        for m in pattern.finditer(command):
            raw = _strip_shell_quotes(m.group(1))
            raw = _expand_run_worktree_var(raw, run_worktree)
            # Skip unresolvable shell variables
            if raw.startswith("$") or "${" in raw:
                continue
            path_obj = Path(raw)
            # Only check absolute paths or paths with explicit ../ traversal
            if not path_obj.is_absolute() and ".." not in raw:
                continue
            try:
                resolved = path_obj.resolve()
                resolved.relative_to(run_worktree)
            except ValueError:
                return _DENY_BASH_BOUNDARY_MSG
            except Exception:
                pass
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
        if _RUN_WORKTREE is not None:
            reason = _check_bash_boundary(command, _RUN_WORKTREE)
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
        if _RUN_WORKTREE is not None:
            reason = _check_path_boundary(file_path, _RUN_WORKTREE)
            if reason:
                print(reason, file=sys.stderr)
                sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
