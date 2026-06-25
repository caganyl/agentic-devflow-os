#!/usr/bin/env bash
set -euo pipefail

INPUT="$(cat)"
TOOL_NAME="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty')"

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

is_sensitive_path() {
  local path="$1"

  case "$path" in
    */.env|*/.env.local|*/.env.development|*/.env.production|*/.env.test|*/.env.staging)
      return 0
      ;;
    */secrets/*|*/config/credentials.json|*.pem|*.key|*.p12|*.pfx)
      return 0
      ;;
    */.claude/settings.json|*/.claude/hooks/*)
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

    if is_sensitive_path "$FILE_PATH"; then
      deny "Sensitive-path protection: Claude cannot modify or create secrets, environment files, credentials, Claude settings or hook scripts."
      exit 0
    fi
    ;;
  Bash)
    COMMAND="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty')"

    if [[ "$COMMAND" == *"secrets/"* ]] \
      || [[ "$COMMAND" == *"credentials.json"* ]] \
      || [[ "$COMMAND" == *".pem"* ]] \
      || [[ "$COMMAND" == *".key"* ]] \
      || [[ "$COMMAND" == *".p12"* ]] \
      || [[ "$COMMAND" == *".pfx"* ]] \
      || [[ "$COMMAND" == *".claude/settings.json"* ]] \
      || [[ "$COMMAND" == *".claude/hooks/"* ]] \
      || { [[ "$COMMAND" == *".env"* ]] && [[ "$COMMAND" != *".env.example"* ]]; }; then
      deny "Sensitive-path protection: command references a protected credential, environment or Claude guardrail path."
      exit 0
    fi
    ;;
esac

exit 0
