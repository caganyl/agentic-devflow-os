#!/usr/bin/env python3
"""
DevFlow Target Safety Guard

PreToolUse hook for Claude Code. Reads the tool invocation from stdin as a
JSON object and blocks destructive or sensitive operations.

Exit codes:
    0  Allow — tool call proceeds
    2  Deny  — tool call is blocked; reason sent to Claude via stderr

SCOPE: This guard protects Claude Code tool calls (Bash, Write, Edit,
NotebookEdit) only. Commands typed directly in the user's terminal are NOT
intercepted. No network access, no credential access, no external processes.
Standard library only.

BOUNDARY ENFORCEMENT: When DEVFLOW_RUN_WORKTREE is set in the environment,
Write/Edit calls that resolve outside the managed run worktree are denied,
and Bash calls containing explicit cd/pushd/git -C/--work-tree/--git-dir
navigation to paths outside the worktree are denied. This is tool-call
enforcement and defense in depth — it is NOT an OS-level sandbox. Direct
terminal commands and subprocess execution are not intercepted by this guard.

POLICY PARITY: the decision logic between the SHARED GUARD POLICY markers is a
verbatim copy of scripts/devflow_guard_core.py (used by the Codex adapter).
The Claude plugin ships this file without that module, so the code is copied
rather than imported; a parity test keeps the two identical.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Iterable, Optional

# --- BEGIN SHARED GUARD POLICY ---------------------------------------------
# This block is kept byte-identical in scripts/devflow_guard_core.py (Codex
# adapter) and scripts/devflow_target_guard.py (Claude plugin, which ships
# without the core module). tests/test_hook_hardening_guard_parity.py checks
# that both copies match and that both guards decide one input table the same.

# `merge` is followed by (?![-\w]) rather than \b: a trailing \b also matches
# before a hyphen, so `git merge-base` — a read-only ancestry query, along with
# `git merge-tree` and `git merge-file` — was refused as if it were a merge.
# The lazy span never crosses | ; & or a newline, so it cannot bridge two
# separate commands. Tokenized checks below cover global options, wrappers and
# nested shells that these plain-text patterns cannot see.
_DANGEROUS_COMMAND_PATTERNS = (
    re.compile(r"\bgit\s+merge(?![-\w])"),
    re.compile(r"\bgit\s+(?:-[^\s]+\s+\S+\s+)+merge(?![-\w])"),
    re.compile(r"\bgit\b[^|;&\n]*?\bpush\b[^|;&\n]*(?:--force-with-lease\b|--force\b|\s-f\b)"),
    re.compile(r"\bgit\b[^|;&\n]*?\bbranch\b[^|;&\n]*(?:--delete|-[dD])\b"),
    re.compile(r"\bgit\b[^|;&\n]*?\breset\s+--(?:hard|soft|mixed|keep|merge)\b"),
    # clean-force in any flag position (-f, -fd, -ffdx) or as a separate
    # argument (-d -f), plus the long form. `-n` (dry run) stays allowed.
    re.compile(r"\bgit\b[^|;&\n]*?\bclean\b[^|;&\n]*?(?:\s-[a-zA-Z]*f|\s--force\b)"),
    re.compile(r"\bgit\s+checkout\s+--\s+\."),
    re.compile(r"\bgit\s+restore\s+\."),
)

_PROTECTED_PATH_PATTERNS = (
    re.compile(r"(^|[/\\])\.env(\.|$)", re.IGNORECASE),
    re.compile(r"(^|[/\\])credential[s]?([/\\.]|$)", re.IGNORECASE),
    re.compile(r"(^|[/\\])secret[s]?([/\\.]|$)", re.IGNORECASE),
    re.compile(r"(^|[/\\])\.mcp\.json$", re.IGNORECASE),
    re.compile(r"(^|[/\\])mcp\.json$", re.IGNORECASE),
    re.compile(r"(^|[/\\])mcp_config\.json$", re.IGNORECASE),
    re.compile(r"(^|[/\\])\.claude[/\\]settings\.json$", re.IGNORECASE),
    re.compile(r"(^|[/\\])\.claude[/\\]settings\.local\.json$", re.IGNORECASE),
    re.compile(r"(^|[/\\])\.claude[/\\]hooks[/\\]", re.IGNORECASE),
    re.compile(r"(^|[/\\])\.codex[/\\]hooks\.json$", re.IGNORECASE),
    re.compile(r"(^|[/\\])\.codex[/\\]config\.toml$", re.IGNORECASE),
    re.compile(r"(^|[/\\])hooks[/\\]hooks\.json$", re.IGNORECASE),
    # Canonical run state, scorecards, the run binding and the state-signing key
    # are written only by devflow_operations.py; delegation events only by the
    # SubagentStart/Stop recorder (a hook process, never a tool call). A forged
    # file in any of these would satisfy a gate it should not.
    re.compile(r"(^|[/\\])\.devflow[/\\]runs[/\\]", re.IGNORECASE),
    re.compile(r"(^|[/\\])\.devflow[/\\]reports[/\\]", re.IGNORECASE),
    re.compile(r"(^|[/\\])\.devflow[/\\]cache[/\\]state-signing\.key$", re.IGNORECASE),
    re.compile(r"(^|[/\\])\.devflow[/\\]project\.json$", re.IGNORECASE),
    re.compile(r"(^|[/\\])\.devflow[/\\]delegation-events([/\\]|$)", re.IGNORECASE),
    # Git configuration and hooks run code on later git commands.
    re.compile(r"(^|[/\\])\.git[/\\](?:[^/\\]+[/\\])*config(?:\.worktree)?$", re.IGNORECASE),
    re.compile(r"(^|[/\\])\.git[/\\](?:[^/\\]+[/\\])*hooks([/\\]|$)", re.IGNORECASE),
    # The guards themselves.
    re.compile(r"(^|[/\\])devflow_(?:target_guard|guard_core|codex_target_guard)\.py$", re.IGNORECASE),
)

# Used only when a command cannot be tokenized (unbalanced quotes): fall back
# to plain-text recursive-force rm detection instead of allowing.
_RM_FALLBACK_PATTERNS = (
    re.compile(r"\brm\s+-[a-zA-Z]*[rR][a-zA-Z]*[fF][a-zA-Z]*\b"),
    re.compile(r"\brm\s+-[a-zA-Z]*[fF][a-zA-Z]*[rR][a-zA-Z]*\b"),
    re.compile(r"\brm\b[^|;&\n]*\s-(?:-recursive\b|[a-zA-Z]*[rR])[^|;&\n]*\s-(?:-force\b|[a-zA-Z]*[fF])"),
    re.compile(r"\brm\b[^|;&\n]*\s-(?:-force\b|[a-zA-Z]*[fF])[^|;&\n]*\s-(?:-recursive\b|[a-zA-Z]*[rR])"),
)

_SHELL_PUNCTUATION = ";&|\n()`"
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_NESTED_COMMAND = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")
_MAX_NESTING = 4
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "mksh", "ash"})
_PRIVILEGE_WRAPPERS = frozenset({"sudo", "doas"})
_WRAPPERS = frozenset({
    "command", "builtin", "exec", "nohup", "time", "env", "nice", "timeout",
    "xargs", "stdbuf", "ionice", "!", "{", "if", "then", "else", "elif", "do",
    "while", "until",
})
_WRAPPER_VALUE_OPTIONS = {
    "env": frozenset({"-u", "--unset", "-C", "--chdir"}),
    "nice": frozenset({"-n", "--adjustment"}),
    "timeout": frozenset({"-s", "--signal", "-k", "--kill-after"}),
    "xargs": frozenset({"-I", "-n", "-P", "-d", "-L", "-s", "-E", "-a",
                        "--max-args", "--max-procs", "--delimiter",
                        "--max-lines", "--max-chars", "--eof", "--arg-file"}),
    "stdbuf": frozenset({"-i", "-o", "-e"}),
    "ionice": frozenset({"-c", "-n", "-p"}),
}
_GIT_VALUE_OPTIONS = frozenset({
    "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix",
    "--config-env",
})
_NAVIGATION_COMMANDS = frozenset({"cd", "pushd"})
_NAVIGATION_PREFIXES = frozenset({
    "{", "!", "if", "then", "else", "elif", "do", "while", "until", "time",
    "exec", "command", "builtin", "nohup",
})


def normalize_worktree(path: str | Path) -> Path:
    """Return an absolute, symlink-resolved managed worktree path."""
    if not isinstance(path, (str, Path)) or not str(path).strip():
        raise ValueError("managed worktree path is required")
    return Path(path).expanduser().resolve(strict=True)


def has_parent_traversal(path: str | Path) -> bool:
    """Return whether a lexical path contains an explicit parent component."""
    return ".." in Path(path).parts


def resolve_target_path(path: str | Path, worktree: str | Path) -> Path:
    """Resolve a target relative to worktree, following existing symlinks."""
    root = normalize_worktree(worktree)
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = root / target
    return target.resolve(strict=False)


def is_path_inside_worktree(path: str | Path, worktree: str | Path) -> bool:
    """Return whether the resolved target is the worktree or one of its children."""
    try:
        root = normalize_worktree(worktree)
        resolve_target_path(path, root).relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def is_protected_or_sensitive_path(path: str | Path) -> bool:
    """Detect protected state/configuration and credential-like path segments."""
    value = str(path)
    return any(pattern.search(value) for pattern in _PROTECTED_PATH_PATTERNS)


def _path_violation(path: object, worktree: str | Path) -> Optional[str]:
    """Classify a write target inside a managed worktree.

    Returns None (allowed) or one of "invalid", "traversal", "protected",
    "boundary". Any resolution failure is a boundary violation (fail closed).
    """
    if not isinstance(path, (str, Path)) or not str(path):
        return "invalid"
    if "\x00" in str(path) or "\n" in str(path) or "\r" in str(path):
        return "invalid"
    if has_parent_traversal(path):
        return "traversal"
    if is_protected_or_sensitive_path(path):
        return "protected"
    try:
        root = normalize_worktree(worktree)
        resolved_relative = resolve_target_path(path, root).relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return "boundary"
    if is_protected_or_sensitive_path(resolved_relative):
        return "protected"
    return None


def _shell_tokens(command: str) -> list[str]:
    """Tokenize shell text while retaining command separators."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=_SHELL_PUNCTUATION)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _is_command_separator(token: str) -> bool:
    return bool(token) and all(char in _SHELL_PUNCTUATION for char in token)


def _command_segments(tokens: list[str]) -> Iterable[list[str]]:
    """Yield shell command segments separated by control operators or newlines."""
    segment: list[str] = []
    for token in tokens:
        if _is_command_separator(token):
            if segment:
                yield segment
                segment = []
            continue
        segment.append(token)
    if segment:
        yield segment


def _nested_commands(command: str) -> list[str]:
    """Return the bodies of $(...) and backtick substitutions, quoted or not."""
    return [a or b for a, b in _NESTED_COMMAND.findall(command)]


def _short_flag_has(args: list[str], letters: str) -> bool:
    return any(
        arg.startswith("-") and not arg.startswith("--")
        and any(char in arg[1:] for char in letters)
        for arg in args
    )


def _skip_wrapper(name: str, rest: list[str]) -> list[str]:
    value_options = _WRAPPER_VALUE_OPTIONS.get(name, frozenset())
    index = 0
    while index < len(rest):
        token = rest[index]
        if name == "env" and _ASSIGNMENT.match(token):
            index += 1
            continue
        if token == "--":
            index += 1
            break
        if token.startswith("-") and token != "-":
            index += 2 if token in value_options else 1
            continue
        break
    rest = rest[index:]
    if name == "timeout" and rest:
        rest = rest[1:]
    return rest


def _unwrap(segment: list[str]) -> tuple[list[str], bool]:
    """Strip assignments and wrapper commands; report privilege escalation."""
    while segment:
        head = segment[0]
        name = Path(head).name
        if _ASSIGNMENT.match(head):
            segment = segment[1:]
        elif name in _PRIVILEGE_WRAPPERS:
            return segment, True
        elif head in _WRAPPERS or name in _WRAPPERS:
            segment = _skip_wrapper(name or head, segment[1:])
        else:
            break
    return segment, False


def _is_recursive_force_rm(segment: list[str]) -> bool:
    """Detect recursive-force options when ``rm`` is the segment executable."""
    if not segment or Path(segment[0]).name != "rm":
        return False

    recursive = False
    force = False
    for token in segment[1:]:
        if token == "--":
            break
        if token == "--recursive":
            recursive = True
        elif token == "--force":
            force = True
        elif token.startswith("-") and not token.startswith("--"):
            options = token[1:]
            recursive = recursive or "r" in options or "R" in options
            force = force or "f" in options
    return recursive and force


def _git_subcommand(args: list[str]) -> tuple[Optional[str], list[str]]:
    """Skip git global options (-C x, -c k=v, --git-dir=.., --no-pager ...)."""
    index = 0
    while index < len(args):
        token = args[index]
        if token in _GIT_VALUE_OPTIONS:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        return token, args[index + 1:]
    return None, []


def _git_is_dangerous(args: list[str]) -> bool:
    sub, rest = _git_subcommand(args)
    if sub is None:
        return False
    positional = [arg for arg in rest if not arg.startswith("-")]
    if sub == "merge":
        return True
    if sub == "push":
        if any(arg in ("--force", "--mirror", "--delete", "--prune")
               or arg.startswith(("--force-with-lease", "--force-if-includes"))
               for arg in rest):
            return True
        if _short_flag_has(rest, "fd"):
            return True
        # +refspec force-updates, :refspec deletes the remote branch.
        return any(arg.startswith(("+", ":")) for arg in positional)
    if sub == "branch":
        return "--delete" in rest or _short_flag_has(rest, "dD")
    if sub == "reset":
        return any(arg in ("--hard", "--soft", "--mixed", "--keep", "--merge") for arg in rest)
    if sub == "clean":
        return "--force" in rest or _short_flag_has(rest, "f")
    if sub == "checkout":
        return "--force" in rest or _short_flag_has(rest, "f") or "." in positional
    if sub == "switch":
        return (any(arg in ("--force", "--discard-changes") for arg in rest)
                or _short_flag_has(rest, "f"))
    if sub == "restore":
        return "." in positional or ":/" in positional
    return False


def _shell_c_script(args: list[str]) -> Optional[str]:
    """Return the script string of `bash -c '<script>'`, if any."""
    has_c = False
    index = 0
    while index < len(args):
        token = args[index]
        if token in ("-o", "+o", "-O", "+O"):
            index += 2
            continue
        if token.startswith("--"):
            index += 1
            continue
        if token.startswith("-") and len(token) > 1:
            has_c = has_c or "c" in token[1:]
            index += 1
            continue
        return token if has_c else None
    return None


def _segment_is_dangerous(segment: list[str], depth: int) -> bool:
    segment, privileged = _unwrap(segment)
    if privileged:
        return True
    if not segment:
        return False
    name = Path(segment[0]).name
    if name == "rm":
        return _is_recursive_force_rm(segment)
    if name == "git":
        return _git_is_dangerous(segment[1:])
    if name in _SHELLS:
        script = _shell_c_script(segment[1:])
        return script is not None and _command_is_dangerous(script, depth + 1)
    if name == "eval":
        return _command_is_dangerous(" ".join(segment[1:]), depth + 1)
    if name == "find":
        for index, token in enumerate(segment):
            if token in ("-exec", "-execdir", "-ok", "-okdir"):
                inner: list[str] = []
                for arg in segment[index + 1:]:
                    if arg in (";", "+"):
                        break
                    inner.append(arg)
                if _segment_is_dangerous(inner, depth + 1):
                    return True
    return False


def _command_is_dangerous(command: str, depth: int = 0) -> bool:
    """Decide whether a shell command is destructive (plain text + tokens)."""
    if depth > _MAX_NESTING:
        return True
    if any(pattern.search(command) for pattern in _DANGEROUS_COMMAND_PATTERNS):
        return True
    for inner in _nested_commands(command):
        if _command_is_dangerous(inner, depth + 1):
            return True
    try:
        tokens = _shell_tokens(command)
    except ValueError:
        return any(pattern.search(command) for pattern in _RM_FALLBACK_PATTERNS)
    return any(_segment_is_dangerous(segment, depth) for segment in _command_segments(tokens))


def _navigation_paths(tokens: list[str]) -> Iterable[str]:
    command_start = True
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if _is_command_separator(token):
            command_start = True
            index += 1
            continue

        if command_start and (token in _NAVIGATION_PREFIXES or _ASSIGNMENT.match(token)):
            index += 1
            continue

        if command_start and token in _NAVIGATION_COMMANDS:
            if (index + 1 >= len(tokens) or tokens[index + 1].startswith("-")
                    or _is_command_separator(tokens[index + 1])):
                raise ValueError("ambiguous cd target")
            yield tokens[index + 1]
            command_start = False
            index += 2
            continue

        if command_start and Path(token).name == "git":
            cursor = index + 1
            while cursor < len(tokens) and not _is_command_separator(tokens[cursor]):
                git_token = tokens[cursor]
                if git_token in ("-C", "--work-tree", "--git-dir"):
                    if cursor + 1 >= len(tokens):
                        raise ValueError("missing Git navigation target")
                    yield tokens[cursor + 1]
                    cursor += 2
                    continue
                if git_token.startswith(("--work-tree=", "--git-dir=")):
                    value = git_token.partition("=")[2]
                    if not value:
                        raise ValueError("missing Git navigation target")
                    yield value
                cursor += 1
            command_start = False

        command_start = False
        index += 1


def _nested_shell_scripts(tokens: list[str]) -> list[str]:
    scripts = []
    for segment in _command_segments(tokens):
        segment, _ = _unwrap(segment)
        if not segment:
            continue
        name = Path(segment[0]).name
        if name in _SHELLS:
            script = _shell_c_script(segment[1:])
            if script is not None:
                scripts.append(script)
        elif name == "eval":
            scripts.append(" ".join(segment[1:]))
    return scripts


def _navigation_escapes(command: str, worktree: str | Path, depth: int = 0) -> bool:
    """Whether cd/pushd/git -C/--work-tree/--git-dir leave the worktree.

    Fails closed: unparseable commands, unresolved variables (other than
    $DEVFLOW_RUN_WORKTREE), `~`, `..` and bare `cd` all count as escapes.
    """
    if depth > _MAX_NESTING:
        return True
    try:
        root = normalize_worktree(worktree)
        tokens = _shell_tokens(command)
        for raw_path in _navigation_paths(tokens):
            expanded = raw_path.replace("$DEVFLOW_RUN_WORKTREE", str(root)).replace(
                "${DEVFLOW_RUN_WORKTREE}", str(root)
            )
            if "$" in expanded or "`" in expanded:
                return True
            if has_parent_traversal(expanded) or not is_path_inside_worktree(expanded, root):
                return True
    except (OSError, RuntimeError, ValueError):
        return True
    for inner in _nested_commands(command) + _nested_shell_scripts(tokens):
        if _navigation_escapes(inner, root, depth + 1):
            return True
    return False
# --- END SHARED GUARD POLICY -----------------------------------------------


# ---------------------------------------------------------------------------
# Run worktree boundary (activated only when DEVFLOW_RUN_WORKTREE is set)
# ---------------------------------------------------------------------------

_RUN_WORKTREE_RAW = os.environ.get("DEVFLOW_RUN_WORKTREE", "")

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

_FILE_TOOLS = ("Write", "Edit", "NotebookEdit")


def _check_bash(command: str) -> Optional[str]:
    return _DENY_BASH_MSG if _command_is_dangerous(command) else None


def _check_path(path: str) -> Optional[str]:
    return _DENY_PATH_MSG if is_protected_or_sensitive_path(path) else None


def _check_path_boundary(file_path: str, run_worktree: str | Path) -> Optional[str]:
    """
    Return a deny message if file_path is not a safe target inside run_worktree.

    Handles absolute external paths, ../ traversal, and symlink escape (the
    resolved target is checked against the protected-path list too). Any
    resolution failure denies (fail closed).
    """
    violation = _path_violation(file_path, run_worktree)
    if violation == "protected":
        return _DENY_PATH_MSG
    if violation:
        return _DENY_BOUNDARY_MSG
    return None


def _check_bash_boundary(command: str, run_worktree: str | Path) -> Optional[str]:
    """
    Return a deny message if the command navigates outside run_worktree via
    cd, pushd, git -C, git --work-tree or git --git-dir (also inside subshells,
    command substitutions and `bash -c`). Unresolved variables, `~` and `..`
    deny; $DEVFLOW_RUN_WORKTREE is expanded first so cd "$DEVFLOW_RUN_WORKTREE"
    is allowed.

    This is best-effort defense in depth — not an OS-level sandbox.
    """
    return _DENY_BASH_BOUNDARY_MSG if _navigation_escapes(command, run_worktree) else None


def _deny(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(2)


def main() -> None:
    # --- Input validation (fail-closed) ---
    raw = sys.stdin.read()
    if not raw.strip():
        _deny(_DENY_VALIDATION_MSG)

    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        _deny(_DENY_VALIDATION_MSG)

    if not isinstance(payload, dict):
        _deny(_DENY_VALIDATION_MSG)

    tool_name = payload.get("tool_name")
    if not isinstance(tool_name, str):
        _deny(_DENY_VALIDATION_MSG)

    # Unknown tool names pass through — hook matcher only fires for Bash and
    # the file-writing tools.
    if tool_name != "Bash" and tool_name not in _FILE_TOOLS:
        sys.exit(0)

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        _deny(_DENY_VALIDATION_MSG)

    if tool_name == "Bash":
        command = tool_input.get("command")
        if not isinstance(command, str):
            _deny(_DENY_VALIDATION_MSG)
        reason = _check_bash(command)
        if reason:
            _deny(reason)
        if _RUN_WORKTREE_RAW:
            reason = _check_bash_boundary(command, _RUN_WORKTREE_RAW)
            if reason:
                _deny(reason)

    else:
        # NotebookEdit carries its target as notebook_path.
        key = "notebook_path" if tool_name == "NotebookEdit" else "file_path"
        file_path = tool_input.get(key)
        if not isinstance(file_path, str):
            _deny(_DENY_VALIDATION_MSG)
        reason = _check_path(file_path)
        if reason:
            _deny(reason)
        if _RUN_WORKTREE_RAW:
            reason = _check_path_boundary(file_path, _RUN_WORKTREE_RAW)
            if reason:
                _deny(reason)

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - any internal error must deny, not allow
        _deny(_DENY_VALIDATION_MSG)
