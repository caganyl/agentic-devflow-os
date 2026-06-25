#!/usr/bin/env bash
set -euo pipefail

INPUT="$(cat)"
CWD="$(printf '%s' "$INPUT" | jq -r '.cwd // empty')"

if [ -z "$CWD" ]; then
  CWD="${CLAUDE_PROJECT_DIR:-$PWD}"
fi

ROOT="$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null || printf '%s' "$CWD")"
BRANCH="$(git -C "$ROOT" branch --show-current 2>/dev/null || true)"
STATUS="$(git -C "$ROOT" status --porcelain 2>/dev/null || true)"

LATEST_HANDOFF=""
if [ -d "$ROOT/docs/handoffs" ]; then
  LATEST_HANDOFF="$(ls -t "$ROOT"/docs/handoffs/*.md 2>/dev/null | grep -v '/README.md$' | head -n 1 || true)"
fi

echo "Agentic DevFlow session context"
echo "- Repository: $ROOT"
echo "- Branch: ${BRANCH:-detached-or-unknown}"

if [ -z "$STATUS" ]; then
  echo "- Working tree: clean"
else
  echo "- Working tree: has uncommitted changes"
fi

if [ "$BRANCH" = "main" ]; then
  echo "- MAIN PROTECTION ACTIVE: inspect, research and plan only. Create a feature branch or worktree before editing."
fi

if [ -n "$LATEST_HANDOFF" ]; then
  echo "- Latest handoff: ${LATEST_HANDOFF#$ROOT/}"
else
  echo "- Latest handoff: none"
fi
