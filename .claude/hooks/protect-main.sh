#!/usr/bin/env bash
set -euo pipefail

INPUT="$(cat)"
CWD="$(printf '%s' "$INPUT" | jq -r '.cwd // empty')"

if [ -z "$CWD" ]; then
  CWD="${CLAUDE_PROJECT_DIR:-$PWD}"
fi

ROOT="$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null || true)"

if [ -z "$ROOT" ]; then
  exit 0
fi

BRANCH="$(git -C "$ROOT" branch --show-current 2>/dev/null || true)"

if [ "$BRANCH" != "main" ]; then
  exit 0
fi

jq -n '{
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "deny",
    permissionDecisionReason: "Main branch read-only protection: this Claude session started on main and cannot run Bash commands, edit files, create branches, or create worktrees. Ask the user to start an isolated worktree from a normal terminal, for example: claude --worktree feature-name"
  }
}'
