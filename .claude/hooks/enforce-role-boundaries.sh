#!/usr/bin/env bash
set -euo pipefail

INPUT="$(cat)"
if ! command -v jq >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1; then
  printf '%s\n' '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Role-boundary protection: a required tool (jq or python3) is not on PATH, so role boundaries cannot be enforced. The operation is blocked (fail-closed). Install the missing tool to proceed."
  }
}'
  exit 0
fi


TOOL_NAME="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty')"
AGENT_TYPE="$(printf '%s' "$INPUT" | jq -r '.agent_type // empty')"

# agent_type is plugin-scoped for plugin subagents (e.g.
# devflow-plugin:backend-engineer), which is what `launch --plugin-dir`
# produces. The role matchers below use bare names, so strip a leading
# "<plugin>:" scope. Bare names carry no colon and are unaffected. Without
# this, every role check silently no-matched for plugin-launched agents.
AGENT_TYPE="${AGENT_TYPE##*:}"
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
    design-reviewer|governance-operations-author|adr-reviewer|\
    architecture-analyst|docs-writer)
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
  local managed_flag=()

  if [[ "$branch" =~ ^req-([0-9]{3,})-.+$ ]]; then
    req_digits="${BASH_REMATCH[1]}"
  elif [[ "$branch" == devflow/run-* ]] && [ -n "${DEVFLOW_RUN_BRANCH:-}" ] && [ "$branch" = "$DEVFLOW_RUN_BRANCH" ]; then
    # Managed run (launch): the branch is devflow/run-*, so the REQ binding
    # comes from the signed run state written by create-run/launch --req-id.
    # Agents cannot write .devflow/runs/ (target guard), so this binding is
    # not agent-controlled.
    local run_req
    run_req="$(python3 - "$ROOT" <<'PYREQ'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
try:
    project = json.loads((root / ".devflow" / "project.json").read_text(encoding="utf-8"))
    run_id = project.get("current_run_id") or ""
    run = json.loads((root / ".devflow" / "runs" / f"{run_id}.json").read_text(encoding="utf-8"))
    print(run.get("req_id") or "")
except (OSError, ValueError):
    print("")
PYREQ
)"
    if [[ ! "$run_req" =~ ^REQ-([0-9]{3,})$ ]]; then
      deny "Ownership-manifest protection: this managed run ($branch) is not bound to a REQ, so implementer agents cannot write. Restart the run with 'launch --req-id REQ-NNN' after a human approves docs/ownership/REQ-NNN.json. Report this as a blocker to the human; do not loop back to revising ADRs, requirements or contracts."
      return 1
    fi
    req_digits="${BASH_REMATCH[1]}"
    managed_flag=(--managed-run)
  else
    deny "Ownership-manifest protection: implementer agents may write only on a branch matching req-XXX-kisa-aciklama or on the active managed run branch (DEVFLOW_RUN_BRANCH). Current branch: ${branch:-detached-or-unknown}. Report this as a blocker; do not loop back to design documents."
    return 1
  fi

  manifest_path="$ROOT/docs/ownership/REQ-${req_digits}.json"

  if [ ! -f "$manifest_path" ]; then
    deny "Ownership-manifest protection: approved manifest not found for branch $branch. Expected: docs/ownership/REQ-${req_digits}.json"
    return 1
  fi

  if ! target_path="$(repository_relative_path "$file_path")"; then
    deny "Ownership-manifest protection: target path is outside the repository and cannot be authorized: $file_path"
    return 1
  fi

  local ownership_validator="$ROOT/scripts/validate_ownership_manifest.py"
  if [ -n "${DEVFLOW_PLUGIN_ROOT:-}" ] && [ -f "$DEVFLOW_PLUGIN_ROOT/scripts/validate_ownership_manifest.py" ]; then
    ownership_validator="$DEVFLOW_PLUGIN_ROOT/scripts/validate_ownership_manifest.py"
  fi

  if ! authorization_error="$(
    python3 "$ownership_validator" \
      --manifest "$manifest_path" \
      --root "$ROOT" \
      --branch "$branch" \
      ${managed_flag[@]+"${managed_flag[@]}"} \
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

  # External-system writes need human approval (autonomy-gates.md). Reading PR
  # review comments is fine; replying, resolving, reviewing, commenting or
  # creating issues is not something a governed agent does on its own.
  if printf '%s' "$command" | grep -Eiq \
    '(^|[[:space:];|&])gh[[:space:]]+(pr|issue)[[:space:]]+(comment|review|close|reopen|edit|create|ready|lock|delete|transfer)([[:space:];|&]|$)'; then
    return 0
  fi

  if printf '%s' "$command" | grep -Eiq '(^|[[:space:];|&])gh[[:space:]]+api([[:space:]]|$)' \
    && printf '%s' "$command" | grep -Eiq '(-X|--method)[[:space:]=]*(POST|PUT|PATCH|DELETE)|(^|[[:space:]])(-f|-F|--field|--raw-field|--input)([[:space:]=]|$)'; then
    return 0
  fi

  if printf '%s' "$command" | grep -Eiq 'agent-reviews' \
    && printf '%s' "$command" | grep -Eiq -- '--(reply|resolve|watch)([[:space:]=]|$)'; then
    return 0
  fi

  # Active attack tooling (DAST/pentest) runs only by a human against staging.
  if printf '%s' "$command" | grep -Eiq '(^|[[:space:];|&/])strix([[:space:];|&]|$)'; then
    return 0
  fi

  # Stream merges and discards (2>&1, >&2, 2>/dev/null, >/dev/null) do not
  # write files. Strip them before the redirect check so ordinary test
  # commands such as `dotnet test 2>&1 | tail -50` are not denied and retried.
  local redirect_probe
  redirect_probe="$(printf '%s' "$command" | sed -E 's/[0-9]?>&[0-9]//g; s/[0-9]?>[[:space:]]*\/dev\/null//g')"
  if [[ "$redirect_probe" == *">"* || "$redirect_probe" == *"<"* ]]; then
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


# ---------------------------------------------------------------------------
# ADR loop breaker (design phase convergence)
#
# Deterministic limits so the design phase cannot loop forever:
#   - An ADR whose Status is Accepted/Superseded/Rejected is frozen.
#   - After DEVFLOW_ADR_MAX_REVIEW_ROUNDS (default 2) review files exist for an
#     ADR, solution-architect may no longer revise it; a human decides.
#   - An ADR may not grow beyond DEVFLOW_ADR_MAX_CHARS (default 12000 chars).
#   - Only adr-reviewer writes docs/architecture/adr/reviews/, one immutable
#     file per round: ADR-NNN-review-<round>.md, containing a VERDICT line.
# Prints a deny reason on stdout when the write must be blocked.
# ---------------------------------------------------------------------------
adr_gate_reason() {
  HOOK_INPUT="$INPUT" python3 - "$ROOT" "$AGENT_TYPE" <<'PYADR'
import json, os, re, sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
agent = sys.argv[2]
max_rounds = int(os.environ.get("DEVFLOW_ADR_MAX_REVIEW_ROUNDS", "2"))
max_chars = int(os.environ.get("DEVFLOW_ADR_MAX_CHARS", "12000"))

data = json.loads(os.environ.get("HOOK_INPUT", "{}"))
tool = data.get("tool_name", "")
ti = data.get("tool_input") or {}
raw = Path(ti.get("file_path", "")).expanduser()
target = (raw if raw.is_absolute() else root / raw).resolve()
try:
    rel = target.relative_to(root).as_posix()
except ValueError:
    sys.exit(0)

adr_dir = "docs/architecture/adr/"
review_dir = adr_dir + "reviews/"
if not rel.startswith(adr_dir):
    sys.exit(0)

def reviews_for(adr_id):
    d = root / review_dir
    if not d.is_dir():
        return []
    return sorted(d.glob(f"{adr_id}-review-*.md"))

# --- review files -----------------------------------------------------------
if rel.startswith(review_dir):
    if agent != "adr-reviewer":
        print(f"ADR loop breaker: only adr-reviewer may write {review_dir}. "
              f"{agent} cannot review or rewrite reviews.")
        sys.exit(0)
    m = re.fullmatch(r"(ADR-\d{3,})-review-(\d+)\.md", Path(rel).name)
    if not m:
        print("ADR loop breaker: review file name must be ADR-NNN-review-<round>.md.")
        sys.exit(0)
    adr_id, rnd = m.group(1), int(m.group(2))
    if target.exists():
        print(f"ADR loop breaker: {rel} already exists; review rounds are immutable.")
        sys.exit(0)
    if rnd > max_rounds:
        print(f"ADR loop breaker: {adr_id} already had {max_rounds} review rounds. "
              "Stop and hand the decision to the human; do not start another round.")
        sys.exit(0)
    if rnd != len(reviews_for(adr_id)) + 1:
        print(f"ADR loop breaker: next review round for {adr_id} must be "
              f"{len(reviews_for(adr_id)) + 1}, got {rnd}.")
        sys.exit(0)
    if tool == "Write":
        content = ti.get("content", "")
        if not re.search(r"^VERDICT:\s*(APPROVE|APPROVE_WITH_NOTES|BLOCK)\s*$", content, re.M):
            print("ADR loop breaker: review must contain a line "
                  "'VERDICT: APPROVE | APPROVE_WITH_NOTES | BLOCK'.")
            sys.exit(0)
    sys.exit(0)

# --- ADR documents ----------------------------------------------------------
m = re.fullmatch(r"(ADR-\d{3,})[^/]*\.md", Path(rel).name)
if not m or "/" in rel[len(adr_dir):]:
    sys.exit(0)
adr_id = m.group(1)

if agent != "solution-architect":
    sys.exit(0)

existing = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
status = re.search(r"^##\s*Status\s*\n+\s*([A-Za-z]+)", existing, re.M)
if status and status.group(1) in ("Accepted", "Superseded", "Rejected"):
    print(f"ADR loop breaker: {adr_id} is {status.group(1)} and frozen. Record "
          "implementation-time deviations in the handoff/PR or propose a new ADR "
          "that supersedes it; do not edit this one.")
    sys.exit(0)

done = len(reviews_for(adr_id))
if done >= max_rounds:
    print(f"ADR loop breaker: {adr_id} already had {done} review rounds "
          f"(limit {max_rounds}). Further revision needs a human decision; "
          "report the open BLOCKERs and stop.")
    sys.exit(0)

if tool == "Write":
    new_len = len(ti.get("content", ""))
elif tool == "Edit":
    old_s, new_s = ti.get("old_string", ""), ti.get("new_string", "")
    if ti.get("replace_all"):
        new_len = len(existing.replace(old_s, new_s))
    else:
        new_len = len(existing) - len(old_s) + len(new_s)
else:
    new_len = len(existing)
if new_len > max_chars and new_len > len(existing):
    print(f"ADR loop breaker: {adr_id} would be {new_len} chars (budget {max_chars}). "
          "Keep the ADR to the decision; move details to the contract, the "
          "implementation or a follow-up ADR. Shrinking edits are allowed.")
    sys.exit(0)
PYADR
}


# ---------------------------------------------------------------------------
# Architecture profile gate
#
# docs/architecture/profile/ holds the project's architecture profile. Agents
# may draft it, but only a human marks it confirmed, and a confirmed profile is
# frozen for agents (implementers treat it as rules).
# ---------------------------------------------------------------------------
profile_gate_reason() {
  HOOK_INPUT="$INPUT" python3 - "$ROOT" "$AGENT_TYPE" <<'PYPROF'
import json, os, re, sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
agent = sys.argv[2]
data = json.loads(os.environ.get("HOOK_INPUT", "{}"))
ti = data.get("tool_input") or {}
raw = Path(ti.get("file_path", "")).expanduser()
target = (raw if raw.is_absolute() else root / raw).resolve()
try:
    rel = target.relative_to(root).as_posix()
except ValueError:
    sys.exit(0)
if not rel.startswith("docs/architecture/profile/"):
    sys.exit(0)

def status_of(text, is_json):
    if is_json:
        try:
            return str((json.loads(text) or {}).get("status", "")).lower()
        except ValueError:
            m = re.search(r'"status"\s*:\s*"(\w+)"', text)
            return m.group(1).lower() if m else ""
    m = re.search(r"^\W*Status\W*:\s*\**\s*(\w+)", text, re.M | re.I)
    return m.group(1).lower() if m else ""

is_json = rel.endswith(".json")
existing = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
if existing and status_of(existing, is_json) == "confirmed":
    print("Architecture profile gate: the profile is confirmed by a human and frozen "
          "for agents. Report drift or a proposed change instead of editing it.")
    sys.exit(0)
if data.get("tool_name") == "Write":
    new = ti.get("content", "")
else:
    new = existing.replace(ti.get("old_string", ""), ti.get("new_string", ""), 1)
if status_of(new, is_json) == "confirmed":
    print("Architecture profile gate: only a human may set status: confirmed. "
          "Leave the profile as draft and list the open questions.")
PYPROF
}

# ---------------------------------------------------------------------------
# docs-writer gate
#
# README.md files may be written anywhere outside generated/protected trees.
# Source files may only be edited (never rewritten) and the edit must change
# comments only: with comments and whitespace removed, old and new text must be
# identical. Everything else is denied.
# ---------------------------------------------------------------------------
docs_writer_reason() {
  HOOK_INPUT="$INPUT" python3 - "$ROOT" <<'PYDOCS'
import json, os, re, sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
data = json.loads(os.environ.get("HOOK_INPUT", "{}"))
tool = data.get("tool_name", "")
ti = data.get("tool_input") or {}
raw = Path(ti.get("file_path", "")).expanduser()
target = (raw if raw.is_absolute() else root / raw).resolve()
try:
    rel = target.relative_to(root).as_posix()
except ValueError:
    print("docs-writer: target is outside the repository."); sys.exit(0)

parts = set(rel.split("/")[:-1])
blocked_dirs = {"node_modules", "bin", "obj", ".git", ".devflow", ".claude", ".next", "dist", "build"}
if parts & blocked_dirs or rel.startswith(("docs/ownership/", "docs/architecture/adr/",
                                           "docs/architecture/profile/", "docs/contracts/")):
    print(f"docs-writer: {rel} is in a protected or generated area."); sys.exit(0)

if Path(rel).name.lower() == "readme.md":
    sys.exit(0)

SOURCE = {".cs", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
if Path(rel).suffix.lower() not in SOURCE:
    print("docs-writer may write README.md files and add comments to source files only."); sys.exit(0)
if tool != "Edit":
    print("docs-writer: use Edit with a small old_string/new_string for source files; "
          "rewriting a source file with Write is not allowed."); sys.exit(0)

JSX_COMMENT = re.compile(r"\{\s*/\*.*?\*/\s*\}", re.S)

def strip_comments(text):
    text = JSX_COMMENT.sub("", text)
    out, i, n, quote = [], 0, len(text), None
    while i < n:
        ch = text[i]
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 2; continue
            if ch == quote:
                quote = None
            i += 1; continue
        if ch in "\"'`":
            quote = ch; out.append(ch); i += 1; continue
        if text.startswith("//", i):
            j = text.find("\n", i); i = n if j == -1 else j; continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2); i = n if j == -1 else j + 2; continue
        out.append(ch); i += 1
    return re.sub(r"\s+", "", "".join(out))

old_s, new_s = ti.get("old_string", ""), ti.get("new_string", "")
if strip_comments(old_s) != strip_comments(new_s):
    print("docs-writer: this edit changes code, not only comments. docs-writer may add "
          "or update comments only; report code issues instead of fixing them.")
PYDOCS
}

analyst_command_allowed() {
  local command="$1" sentinel="__DEVFLOW_ARCH_SCAN__" script
  command="${command//\"\$\{DEVFLOW_ARCH_SCAN_SCRIPT\}\"/$sentinel}"
  command="${command//\"\$DEVFLOW_ARCH_SCAN_SCRIPT\"/$sentinel}"
  command="${command//\$\{DEVFLOW_ARCH_SCAN_SCRIPT\}/$sentinel}"
  command="${command//\$DEVFLOW_ARCH_SCAN_SCRIPT/$sentinel}"
  # The script must be the first argument to python3 and must be the real
  # scanner: otherwise `python3 -c "<code>" devflow_arch_scan.py` or a planted
  # look-alike file would give the analyst arbitrary code execution.
  if [[ "$command" =~ ^python3[[:space:]]+([^[:space:]]+)([[:space:]]+[^\;\&\|\<\>\`\$]*)?$ ]]; then
    script="${BASH_REMATCH[1]}"
    case "$script" in
      "$sentinel"|scripts/devflow_arch_scan.py|./scripts/devflow_arch_scan.py)
        return 0
        ;;
    esac
    if [ -n "${DEVFLOW_ARCH_SCAN_SCRIPT:-}" ] && [ "$script" = "$DEVFLOW_ARCH_SCAN_SCRIPT" ]; then
      return 0
    fi
  fi
  security_command_is_non_mutating "$1"
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

    ADR_GATE_REASON="$(adr_gate_reason)"
    if [ -n "$ADR_GATE_REASON" ]; then
      deny "$ADR_GATE_REASON"
      exit 0
    fi

    PROFILE_GATE_REASON="$(profile_gate_reason)"
    if [ -n "$PROFILE_GATE_REASON" ]; then
      deny "$PROFILE_GATE_REASON"
      exit 0
    fi

    if [ "$AGENT_TYPE" = "docs-writer" ]; then
      DOCS_REASON="$(docs_writer_reason)"
      if [ -n "$DOCS_REASON" ]; then
        deny "Role-boundary protection: $DOCS_REASON"
      fi
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
      adr-reviewer)
        ALLOWED_PATHS=("docs/architecture/adr/reviews")
        ;;
      architecture-analyst)
        ALLOWED_PATHS=(
          "docs/architecture/profile/ARCHITECTURE_PROFILE.md"
          "docs/architecture/profile/architecture-profile.json"
        )
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
      product-analyst|solution-architect|contract-broker|design-reviewer|governance-operations-author|adr-reviewer)
        deny "Role-boundary protection: $AGENT_TYPE has no Bash authority. Use documented read/write tools only."
        exit 0
        ;;
      architecture-analyst)
        if ! analyst_command_allowed "$COMMAND"; then
          deny "Role-boundary protection: architecture-analyst may run only the DevFlow architecture scanner (python3 .../devflow_arch_scan.py ...) or single non-mutating inspection commands."
        fi
        exit 0
        ;;
      docs-writer)
        if ! security_command_is_non_mutating "$COMMAND"; then
          deny "Role-boundary protection: docs-writer may run only single, non-mutating inspection commands (git diff/log/show, ls, grep, cat...)."
        fi
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
      deny "Role-boundary protection: governed agents cannot run Git mutation, destructive filesystem, dependency-install, merge, deployment, migration, permission, redirected-write, external-system write (PR/issue comments, replies, resolves) or active attack tooling Bash commands. Prepare the change and hand it to the human."
      exit 0
    fi
    ;;
esac

exit 0
