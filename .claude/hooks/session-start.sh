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

PROFILE_MD="$ROOT/docs/architecture/profile/ARCHITECTURE_PROFILE.md"
if [ -f "$PROFILE_MD" ]; then
  PROFILE_STATUS="$(grep -m1 -iE '^[^A-Za-z]*Status[^A-Za-z]*:' "$PROFILE_MD" | sed -E 's/.*:[[:space:]]*\**[[:space:]]*([A-Za-z]+).*/\1/' || true)"
  echo "- Architecture profile: ${PROFILE_STATUS:-unknown} (docs/architecture/profile/)"
else
  echo "- Architecture profile: none (run the project-onboarding workflow before implementation)"
fi

# Make the read-only architecture scanner path available to Bash commands in
# plugin sessions that were not started through `launch`.
if [ -n "${CLAUDE_ENV_FILE:-}" ] && [ -z "${DEVFLOW_ARCH_SCAN_SCRIPT:-}" ] && [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] \
   && [ -f "${CLAUDE_PLUGIN_ROOT}/scripts/devflow_arch_scan.py" ]; then
  printf 'export DEVFLOW_ARCH_SCAN_SCRIPT=%q\n' "${CLAUDE_PLUGIN_ROOT}/scripts/devflow_arch_scan.py" >> "$CLAUDE_ENV_FILE" || true
fi

if [ -n "$LATEST_HANDOFF" ]; then
  echo "- Latest handoff: ${LATEST_HANDOFF#$ROOT/}"
else
  echo "- Latest handoff: none"
fi
