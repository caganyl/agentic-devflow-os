#!/usr/bin/env bash
set -euo pipefail

INPUT="$(cat)"

TOOL_NAME="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty')"
AGENT_TYPE="$(printf '%s' "$INPUT" | jq -r '.agent_type // empty')"
CWD="$(printf '%s' "$INPUT" | jq -r '.cwd // empty')"

if [ -z "$CWD" ]; then
  CWD="${CLAUDE_PROJECT_DIR:-$PWD}"
fi

ROOT="$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null || true)"

if [ -z "$ROOT" ] || [ -z "$AGENT_TYPE" ]; then
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

is_governed_agent() {
  case "$1" in
    delivery-lead|product-analyst|solution-architect|contract-broker|\
    frontend-engineer|backend-engineer|database-engineer|qa-automation|\
    security-red-team|integration-release|ai-data-engineer|evalops-reviewer|\
    design-reviewer)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

path_is_allowed() {
  local target="$1"
  shift

  python3 - "$target" "$ROOT" "$@" <<'PY'
from pathlib import Path
import sys

target_arg = Path(sys.argv[1]).expanduser()
root = Path(sys.argv[2]).resolve(strict=False)
allowed_rel_paths = sys.argv[3:]

target = target_arg if target_arg.is_absolute() else root / target_arg
target = target.resolve(strict=False)

for rel_path in allowed_rel_paths:
    allowed = (root / rel_path).resolve(strict=False)
    try:
        target.relative_to(allowed)
        raise SystemExit(0)
    except ValueError:
        pass

raise SystemExit(1)
PY
}

bash_has_blocked_operation() {
  local command="$1"

  if printf '%s' "$command" | grep -Eiq \
    '(^|[[:space:];|&])git([[:space:]]+-C[[:space:]]+[^[:space:];|&]+)*[[:space:]]+(add|commit|push|merge|rebase|reset|clean|revert|switch|checkout|branch|worktree|tag)([[:space:];|&]|$)'; then
    return 0
  fi

  if printf '%s' "$command" | grep -Eiq \
    '(^|[[:space:];|&])(rm|mv|cp|mkdir|touch|tee|truncate|chmod|chown)([[:space:];|&]|$)'; then
    return 0
  fi

  if printf '%s' "$command" | grep -Eiq \
    'sed[[:space:]]+-i|perl[[:space:]]+-pi|apply_patch|gh[[:space:]]+pr[[:space:]]+merge'; then
    return 0
  fi

  if printf '%s' "$command" | grep -Eiq \
    '(^|[[:space:];|&])(npm|pnpm|bun|yarn)[[:space:]]+(install|add|remove|update|upgrade|publish)([[:space:];|&]|$)'; then
    return 0
  fi

  if printf '%s' "$command" | grep -Eiq \
    '(^|[[:space:];|&])(pip|pip3|poetry)[[:space:]]+(install|uninstall|add|remove)([[:space:];|&]|$)'; then
    return 0
  fi

  if printf '%s' "$command" | grep -Eiq \
    '(terraform|tofu)[[:space:]]+(apply|destroy)|kubectl[[:space:]]+(apply|delete)|prisma[[:space:]]+migrate[[:space:]]+deploy'; then
    return 0
  fi

  if [[ "$command" == *">"* || "$command" == *"<"* ]]; then
    return 0
  fi

  return 1
}

security_command_is_non_mutating() {
  local command="$1"

  if [[ -z "$command" ]]; then
    return 1
  fi

  if [[ "$command" == *$'\n'* \
     || "$command" == *";"* \
     || "$command" == *"&&"* \
     || "$command" == *"||"* \
     || "$command" == *"|"* \
     || "$command" == *">"* \
     || "$command" == *"<"* \
     || "$command" == *'`'* \
     || "$command" == *'$('* \
     || "$command" == *" -exec "* \
     || "$command" == *" -delete"* ]]; then
    return 1
  fi

  case "$command" in
    git\ status*|git\ diff*|git\ log*|git\ show*|git\ grep*|\
    rg\ *|grep\ *|find\ *|ls*|sed\ -n*|head*|tail*|cat\ *|jq\ *|\
    npm\ audit*|pnpm\ audit*|bun\ audit*|pip-audit*|trivy\ fs*|\
    semgrep*|bandit*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

case "$TOOL_NAME" in
  Edit|Write)
    FILE_PATH="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty')"

    if [ -z "$FILE_PATH" ]; then
      deny "Role-boundary protection: governed agent attempted a file mutation without a file path."
      exit 0
    fi

    if [ "$AGENT_TYPE" = "delivery-lead" ]; then
      deny "Role-boundary protection: delivery-lead is planning-only and cannot create or edit files."
      exit 0
    fi

    case "$AGENT_TYPE" in
      product-analyst)
        ALLOWED_PATHS=("docs/product" "docs/decisions")
        ;;
      solution-architect)
        ALLOWED_PATHS=("docs/architecture" "docs/decisions")
        ;;
      contract-broker)
        ALLOWED_PATHS=("docs/contracts")
        ;;
      security-red-team)
        ALLOWED_PATHS=("docs/quality/security-reports")
        ;;
      integration-release)
        ALLOWED_PATHS=("docs/release" "docs/handoffs")
        ;;
      evalops-reviewer)
        ALLOWED_PATHS=(
          "evals/datasets/adversarial"
          "evals/datasets/regression"
          "evals/configs"
          "evals/results"
          "evals/scorecards"
          "docs/ai/evals"
          "docs/ai/model-decisions"
        )
        ;;
      design-reviewer)
        ALLOWED_PATHS=("design/reviews" "docs/quality/accessibility")
        ;;
      *)
        exit 0
        ;;
    esac

    if ! path_is_allowed "$FILE_PATH" "${ALLOWED_PATHS[@]}"; then
      deny "Role-boundary protection: $AGENT_TYPE may not write to $FILE_PATH. Use only the role's approved documentation or evaluation paths."
      exit 0
    fi
    ;;
  Bash)
    if ! is_governed_agent "$AGENT_TYPE"; then
      exit 0
    fi

    COMMAND="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty')"

    case "$AGENT_TYPE" in
      delivery-lead)
        deny "Role-boundary protection: delivery-lead is planning-only and cannot run Bash commands."
        exit 0
        ;;
      product-analyst|solution-architect|contract-broker|design-reviewer)
        deny "Role-boundary protection: $AGENT_TYPE has no Bash authority. Use documented read/write tools only."
        exit 0
        ;;
      security-red-team)
        if ! security_command_is_non_mutating "$COMMAND"; then
          deny "Role-boundary protection: security-red-team may run only single, non-mutating inspection or scanning commands. Use Read/Grep/Glob for other inspection."
          exit 0
        fi
        ;;
    esac

    if bash_has_blocked_operation "$COMMAND"; then
      deny "Role-boundary protection: governed agents cannot run Git mutation, destructive filesystem, dependency-install, merge, deployment, migration, permission or redirected-write Bash commands."
      exit 0
    fi
    ;;
esac

exit 0
