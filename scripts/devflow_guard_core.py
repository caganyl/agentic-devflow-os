#!/usr/bin/env python3
"""Runtime-neutral policy primitives for DevFlow tool-call guards.

This module knows nothing about hook event or response JSON schemas.  It
provides path, patch, and shell-policy checks that adapters can compose.
Standard library only.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Iterable, Optional


DENY_DANGEROUS_COMMAND = (
    "DevFlow guard: destructive or unsafe shell operation blocked by policy."
)
DENY_PROTECTED_PATH = (
    "DevFlow guard: write or edit to protected path blocked by policy."
)
DENY_PATH_BOUNDARY = (
    "DevFlow guard: write or edit outside the managed run worktree is blocked by policy."
)
DENY_PATH_TRAVERSAL = (
    "DevFlow guard: parent path traversal is blocked by policy."
)
DENY_SHELL_BOUNDARY = (
    "DevFlow guard: shell navigation outside the managed run worktree is blocked by policy."
)
DENY_PATCH = "DevFlow guard: malformed or ambiguous patch blocked by policy."


class PatchValidationError(ValueError):
    """Raised when apply_patch input cannot be interpreted unambiguously."""


_DANGEROUS_COMMAND_PATTERNS = (
    re.compile(r"\bgit\s+merge\b"),
    re.compile(r"\bgit\s+(?:-[^\s]+\s+\S+\s+)+merge\b"),
    re.compile(r"\bgit\s+push\b[^|;&\n]*(?:--force-with-lease\b|--force\b|\s-f\b)"),
    re.compile(r"\bgit\b[^|;&\n]*?\bpush\b[^|;&\n]*(?:--force-with-lease\b|--force\b|\s-f\b)"),
    re.compile(r"\bgit\s+branch\b[^|;&\n]*(?:--delete|-[dD])\b"),
    re.compile(r"\bgit\b[^|;&\n]*?\bbranch\b[^|;&\n]*(?:--delete|-[dD])\b"),
    re.compile(r"\bgit\s+reset\s+--(?:hard|soft|mixed)\b"),
    re.compile(r"\bgit\b[^|;&\n]*?\breset\s+--(?:hard|soft|mixed)\b"),
    re.compile(r"\bgit\s+clean\s+-[^\s]*f\b"),
    re.compile(r"\bgit\b[^|;&\n]*?\bclean\s+-[^\s]*f\b"),
    re.compile(r"\bgit\s+checkout\s+--\s+\."),
    re.compile(r"\bgit\s+restore\s+\."),
)

_PROTECTED_PATH_PATTERNS = (
    re.compile(r"(^|[/\\])\.env(\.|$)"),
    re.compile(r"(^|[/\\])credential[s]?([/\\.]|$)", re.IGNORECASE),
    re.compile(r"(^|[/\\])secret[s]?([/\\.]|$)", re.IGNORECASE),
    re.compile(r"(^|[/\\])\.mcp\.json$"),
    re.compile(r"(^|[/\\])mcp\.json$"),
    re.compile(r"(^|[/\\])mcp_config\.json$"),
    re.compile(r"(^|[/\\])\.claude[/\\]settings\.json$"),
    re.compile(r"(^|[/\\])\.claude[/\\]settings\.local\.json$"),
    re.compile(r"(^|[/\\])\.claude[/\\]hooks[/\\]"),
    re.compile(r"(^|[/\\])\.codex[/\\]hooks\.json$"),
    re.compile(r"(^|[/\\])\.codex[/\\]config\.toml$"),
    re.compile(r"(^|[/\\])hooks[/\\]hooks\.json$"),
    re.compile(r"(^|[/\\])\.devflow[/\\]runs[/\\]"),
    re.compile(r"(^|[/\\])\.devflow[/\\]reports[/\\]"),
)

_PATCH_FILE_HEADER = re.compile(
    r"^\*\*\* (Add File|Update File|Delete File|Move to): (.+)$"
)


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
    root = normalize_worktree(worktree)
    try:
        resolve_target_path(path, root).relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def is_protected_or_sensitive_path(path: str | Path) -> bool:
    """Detect protected state/configuration and credential-like path segments."""
    value = str(path)
    return any(pattern.search(value) for pattern in _PROTECTED_PATH_PATTERNS)


def validate_target_path(path: str | Path, worktree: str | Path) -> Optional[str]:
    """Return a fixed denial reason, or ``None`` when a target is permitted."""
    if not isinstance(path, (str, Path)) or not str(path):
        return DENY_PATCH
    if "\x00" in str(path) or "\n" in str(path) or "\r" in str(path):
        return DENY_PATCH
    if has_parent_traversal(path):
        return DENY_PATH_TRAVERSAL
    if is_protected_or_sensitive_path(path):
        return DENY_PROTECTED_PATH
    try:
        root = normalize_worktree(worktree)
        resolved_relative = resolve_target_path(path, root).relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return DENY_PATH_BOUNDARY
    if is_protected_or_sensitive_path(resolved_relative):
        return DENY_PROTECTED_PATH
    return None


def dangerous_command_reason(command: str) -> Optional[str]:
    """Return a fixed denial for destructive Git/shell commands."""
    if not isinstance(command, str):
        return DENY_DANGEROUS_COMMAND
    if any(pattern.search(command) for pattern in _DANGEROUS_COMMAND_PATTERNS):
        return DENY_DANGEROUS_COMMAND
    try:
        if any(_is_recursive_force_rm(segment) for segment in _command_segments(
            _shell_tokens(command)
        )):
            return DENY_DANGEROUS_COMMAND
    except ValueError:
        pass
    return None


def _shell_tokens(command: str) -> list[str]:
    """Tokenize shell text while retaining command separators."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _is_command_separator(token: str) -> bool:
    return bool(token) and all(char in ";&|\n" for char in token)


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


def _navigation_paths(tokens: list[str]) -> Iterable[str]:
    command_start = True
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if _is_command_separator(token):
            command_start = True
            index += 1
            continue

        if command_start and token == "cd":
            if index + 1 >= len(tokens) or tokens[index + 1].startswith("-"):
                raise ValueError("ambiguous cd target")
            yield tokens[index + 1]
            command_start = False
            index += 2
            continue

        if command_start and token == "git":
            cursor = index + 1
            while cursor < len(tokens) and not _is_command_separator(tokens[cursor]):
                git_token = tokens[cursor]
                if git_token == "-C" or git_token == "--work-tree":
                    if cursor + 1 >= len(tokens):
                        raise ValueError("missing Git navigation target")
                    yield tokens[cursor + 1]
                    cursor += 2
                    continue
                if git_token.startswith("--work-tree="):
                    value = git_token.partition("=")[2]
                    if not value:
                        raise ValueError("missing Git work-tree target")
                    yield value
                cursor += 1
            command_start = False

        command_start = False
        index += 1


def shell_navigation_reason(command: str, worktree: str | Path) -> Optional[str]:
    """Validate explicit ``cd``, ``git -C`` and ``git --work-tree`` targets."""
    try:
        root = normalize_worktree(worktree)
        tokens = _shell_tokens(command)
        for raw_path in _navigation_paths(tokens):
            expanded = raw_path.replace("$DEVFLOW_RUN_WORKTREE", str(root)).replace(
                "${DEVFLOW_RUN_WORKTREE}", str(root)
            )
            if "$" in expanded or "`" in expanded:
                return DENY_SHELL_BOUNDARY
            if has_parent_traversal(expanded) or not is_path_inside_worktree(expanded, root):
                return DENY_SHELL_BOUNDARY
    except (OSError, RuntimeError, ValueError):
        return DENY_SHELL_BOUNDARY
    return None


def parse_apply_patch_paths(patch_text: str) -> list[str]:
    """Extract every source/destination path from a well-formed apply_patch.

    Unknown headers, misplaced/duplicate moves, missing boundaries, and patches
    without a file operation fail closed.
    """
    if not isinstance(patch_text, str) or not patch_text:
        raise PatchValidationError(DENY_PATCH)
    lines = patch_text.splitlines()
    if len(lines) < 3 or lines[0] != "*** Begin Patch" or lines[-1] != "*** End Patch":
        raise PatchValidationError(DENY_PATCH)

    paths: list[str] = []
    current_operation: Optional[str] = None
    move_seen = False
    for line in lines[1:-1]:
        match = _PATCH_FILE_HEADER.fullmatch(line)
        if match:
            operation, path = match.groups()
            if path != path.strip() or not path or "\x00" in path:
                raise PatchValidationError(DENY_PATCH)
            if operation == "Move to":
                if current_operation != "Update File" or move_seen:
                    raise PatchValidationError(DENY_PATCH)
                move_seen = True
            else:
                current_operation = operation
                move_seen = False
            paths.append(path)
            continue
        if line.startswith("*** "):
            raise PatchValidationError(DENY_PATCH)

    if not paths or current_operation is None:
        raise PatchValidationError(DENY_PATCH)
    return paths


def validate_apply_patch(patch_text: str, worktree: str | Path) -> Optional[str]:
    """Validate every affected path in a multi-file apply_patch payload."""
    try:
        paths = parse_apply_patch_paths(patch_text)
    except PatchValidationError:
        return DENY_PATCH
    for path in paths:
        reason = validate_target_path(path, worktree)
        if reason:
            return reason
    return None
