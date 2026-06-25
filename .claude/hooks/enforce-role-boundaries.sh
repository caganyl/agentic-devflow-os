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
    design-reviewer|governance-operations-author)
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


is_implementer_agent() {
  case "$1" in
    frontend-engineer|backend-engineer|database-engineer|qa-automation|ai-data-engineer)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

repository_relative_path() {
  local raw_path="$1"

  python3 - "$ROOT" "$raw_path" <<'PYTHON'
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve(strict=False)
raw = Path(sys.argv[2]).expanduser()
target = raw if raw.is_absolute() else root / raw
target = target.resolve(strict=False)

try:
    print(target.relative_to(root).as_posix())
except ValueError:
    raise SystemExit(1)
PYTHON
}

authorize_implementer_write() {
  local file_path="$1"
  local branch req_digits manifest_path target_path authorization_error

  branch="$(git -C "$ROOT" branch --show-current 2>/dev/null || true)"

  if [[ ! "$branch" =~ ^req-([0-9]{3,})-.+$ ]]; then
    deny "Ownership-manifest protection: implementer agents may write only on a branch matching req-XXX-kisa-aciklama. Current branch: ${branch:-detached-or-unknown}"
    return 1
  fi

  req_digits="${BASH_REMATCH[1]}"
  manifest_path="$ROOT/docs/ownership/REQ-${req_digits}.json"

  if [ ! -f "$manifest_path" ]; then
    deny "Ownership-manifest protection: approved manifest not found for branch $branch. Expected: docs/ownership/REQ-${req_digits}.json"
    return 1
  fi

  if ! target_path="$(repository_relative_path "$file_path")"; then
    deny "Ownership-manifest protection: target path is outside the repository and cannot be authorized: $file_path"
    return 1
  fi

  if ! authorization_error="$(
    python3 "$ROOT/scripts/validate_ownership_manifest.py" \
      --manifest "$manifest_path" \
      --root "$ROOT" \
      --branch "$branch" \
      --authorize-agent "$AGENT_TYPE" \
      --target "$target_path" \
      2>&1
  )"; then
    authorization_error="$(printf '%s' "$authorization_error" | tr '\n' ' ' | tr -s ' ')"
    deny "Ownership-manifest protection: ${authorization_error:-manifest authorization failed}"
    return 1
  fi

  return 0
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

    if is_implementer_agent "$AGENT_TYPE"; then
      authorize_implementer_write "$FILE_PATH" || exit 0
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
      governance-operations-author)
        ALLOWED_PATHS=(
          "docs/operations"
          "docs/templates"
          "docs/ownership/README.md"
          "docs/ownership/REGISTRY_BRANCH_RUNBOOK.md"
        )
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
      product-analyst|solution-architect|contract-broker|design-reviewer|governance-operations-author)
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
