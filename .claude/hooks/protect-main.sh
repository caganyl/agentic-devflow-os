#!/usr/bin/env bash
set -euo pipefail

INPUT="$(cat)"
TOOL_NAME="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty')"
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

deny() {
  local reason="$1"

  jq -n --arg reason "$reason" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $reason
    }
  }'
}

case "$TOOL_NAME" in
  Edit|Write)
    deny "Main branch protection: Claude cannot edit or create files on main. Create a feature branch or isolated worktree first."
    exit 0
    ;;
  Bash)
    COMMAND="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty')"

    if echo "$COMMAND" | grep -Eiq '(^|[[:space:];|&])git[[:space:]]+(add|commit|push|merge|rebase|reset|clean|revert|tag)([[:space:];|&]|$)' \
      || echo "$COMMAND" | grep -Eiq '(^|[[:space:];|&])(rm|mv|cp|mkdir|touch|tee|truncate)([[:space:];|&]|$)|sed[[:space:]]+-i|perl[[:space:]]+-pi' \
      || echo "$COMMAND" | grep -Eiq '(^|[[:space:];|&])(npm|pnpm|bun|yarn)[[:space:]]+(install|add|remove|update|upgrade)([[:space:];|&]|$)' \
      || [[ "$COMMAND" == *">"* ]]; then
      deny "Main branch protection: potentially mutating Bash command blocked. Create a feature branch or isolated worktree first."
      exit 0
    fi
    ;;
esac

exit 0
