#!/usr/bin/env bash
# devflow-hook-hardening: v1
set -euo pipefail

# Fail closed. Claude Code blocks a tool call only on exit 2 or a deny JSON;
# any other non-zero exit (a jq parse error, a Python exception inside a gate
# under `set -e`) would let the call through. Convert every unexpected exit
# status into exit 2. Intentional allow (exit 0, no output) and intentional
# deny (deny JSON, exit 0) are unaffected.
devflow_fail_closed() {
  local status=$?
  if [ "$status" -ne 0 ] && [ "$status" -ne 2 ]; then
    printf '%s\n' "DevFlow hook internal error (enforce-role-boundaries.sh, status $status); denying for safety." >&2
    exit 2
  fi
}
trap devflow_fail_closed EXIT

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

if ! printf '%s' "$INPUT" | jq -e 'type == "object"' >/dev/null 2>&1; then
  printf '%s\n' "Role-boundary protection: hook input is not a JSON object; denying for safety." >&2
  exit 2
fi

# DevFlow Ofis telemetrisi: reddi canlı ofis görünümüne not düşer. Yalnızca
# kayıt; karar vermez, çıktı üretmez ve hiçbir hata reddi etkilemez.
devflow_office_note() {
  local here recorder
  here="$(cd "$(dirname "$0")" 2>/dev/null && pwd -P)" || return 0
  for recorder in "$here/../scripts/devflow_office_recorder.py" "$here/../../scripts/devflow_office_recorder.py"; do
    if [ -f "$recorder" ]; then
      (printf '%s' "$INPUT" | python3 "$recorder" --deny "$1" "$2") >/dev/null 2>&1 || true
      return 0
    fi
  done
  return 0
}

deny() {
  local reason="$1"

  jq -n --arg reason "$reason" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $reason
    }
  }'
  devflow_office_note "enforce-role-boundaries" "$reason"
}

# Numeric budgets come from the environment; a malformed value must not crash
# a gate into a non-blocking exit or silently disable it.
for budget_var in DEVFLOW_ADR_MAX_REVIEW_ROUNDS DEVFLOW_ADR_MAX_CHARS DEVFLOW_ADR_MAX_NEW_PER_BRANCH DEVFLOW_DOC_MAX_CHARS; do
  eval "budget_value=\${$budget_var:-}"
  if [ -n "$budget_value" ] && ! [[ "$budget_value" =~ ^[0-9]+$ ]]; then
    deny "Role-boundary protection: $budget_var must be a non-negative integer. Fix the environment; the operation is blocked until then."
    exit 0
  fi
done

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

if [ -z "$ROOT" ]; then
  exit 0
fi

# Scripts shipped with the plugin take precedence over the target's scripts/.
devflow_script() {
  local name="$1"
  if [ -n "${DEVFLOW_PLUGIN_ROOT:-}" ] && [ -f "$DEVFLOW_PLUGIN_ROOT/scripts/$name" ]; then
    printf '%s' "$DEVFLOW_PLUGIN_ROOT/scripts/$name"
  else
    printf '%s' "$ROOT/scripts/$name"
  fi
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

# Print the REQ id bound to the current managed run, or nothing. The binding
# is trusted only when the run state carries a valid HMAC signature from
# devflow_operations.py (read_run_state) and names this branch; a hand-written
# or copied .devflow/runs/*.json is treated as unbound.
managed_run_req() {
  local branch="$1"
  python3 - "$ROOT" "$branch" "$(devflow_script devflow_operations.py)" 2>/dev/null <<'PYREQ' || true
import importlib.util, json, re, sys
from pathlib import Path

root, branch, ops_path = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])


def done(value=""):
    print(value)
    raise SystemExit(0)


try:
    project = json.loads((root / ".devflow" / "project.json").read_text(encoding="utf-8"))
    run_id = project.get("current_run_id") if isinstance(project, dict) else None
except (OSError, ValueError):
    done()
if not isinstance(run_id, str) or not re.fullmatch(r"RUN-\d{3,}", run_id):
    done()
run_path = root / ".devflow" / "runs" / f"{run_id}.json"
if not ops_path.is_file() or not run_path.is_file():
    done()
spec = importlib.util.spec_from_file_location("devflow_operations_hook", ops_path)
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)
# Never create a signing key from a hook: no key means nothing was signed.
if not ops.state_key_path(root).is_file():
    done()
try:
    state = ops.read_run_state(root, run_path)
except SystemExit:
    done()
if not isinstance(state, dict):
    done()
if state.get("branch_name") and state.get("branch_name") != branch:
    done()
req_id = state.get("req_id")
done(req_id if isinstance(req_id, str) else "")
PYREQ
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
    local run_req
    run_req="$(managed_run_req "$branch")"
    if [[ ! "$run_req" =~ ^REQ-([0-9]{3,})$ ]]; then
      deny "Ownership-manifest protection: this managed run ($branch) is not bound to a REQ (or its run state failed signature verification), so implementer agents cannot write. Restart the run with 'launch --req-id REQ-NNN' after a human approves docs/ownership/REQ-NNN.json. Report this as a blocker to the human; do not loop back to revising ADRs, requirements or contracts."
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

  local ownership_validator
  ownership_validator="$(devflow_script validate_ownership_manifest.py)"

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

# ---------------------------------------------------------------------------
# Bash policy (tokenized)
#
# BEST EFFORT ONLY. Filtering shell text cannot be complete: quoting, globbing,
# variables and interpreters offer endless spellings of the same operation.
# The real boundary is permissions.deny in .claude/settings.json plus the
# isolated run worktree; these checks catch the common and accidental cases.
#
# Prints OK when the command passes; anything else (including a crash) is
# treated as blocked by the callers.
#   mode "governed": mutations for governed agents (git by path / with global
#                    options, shells with -c, eval, sed -i, dd of=, ln,
#                    install, find -delete/-exec <mutation>, \cmd aliases,
#                    redirects outside quotes)
#   mode "readonly": governed checks plus write/exec side doors of the
#                    read-only allowlist (npm audit fix, git --output,
#                    rg --pre, semgrep --autofix, sed w, ...)
# ---------------------------------------------------------------------------
bash_policy_verdict() {
  python3 - "$1" "$2" <<'PYBASH'
import re, shlex, sys
from pathlib import Path

mode, command = sys.argv[1], sys.argv[2]

PUNCT = ";&|\n()`"
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
NESTED = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "mksh", "ash"}
WRAPPERS = {"command", "builtin", "exec", "nohup", "time", "env", "nice", "timeout",
            "xargs", "stdbuf", "ionice", "!", "{", "if", "then", "else", "elif", "do",
            "while", "until"}
WRAPPER_VALUE_OPTIONS = {
    "env": {"-u", "--unset", "-C", "--chdir"},
    "nice": {"-n", "--adjustment"},
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
    "xargs": {"-I", "-n", "-P", "-d", "-L", "-s", "-E", "-a", "--max-args",
              "--max-procs", "--delimiter", "--max-lines", "--max-chars", "--eof",
              "--arg-file"},
    "stdbuf": {"-i", "-o", "-e"},
    "ionice": {"-c", "-n", "-p"},
}
GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace",
                     "--super-prefix", "--config-env"}
GIT_MUTATING = {"add", "commit", "push", "merge", "rebase", "reset", "clean", "revert",
                "switch", "checkout", "branch", "worktree", "tag"}
MUTATING = {"rm", "rmdir", "unlink", "shred", "mv", "cp", "mkdir", "touch", "tee",
            "truncate", "chmod", "chown", "chgrp", "ln", "install"}
FIND_WRITES = {"-delete", "-fprint", "-fprint0", "-fprintf", "-fls"}
SED_WRITE = re.compile(r"(?:^|[;{}\n/0-9$!,])[ \t]*(?:[wW][ \t]+\S|e(?:[ \t]|$))")
PKG = {"npm", "pnpm", "bun", "yarn"}


class Block(Exception):
    pass


def tokens(text):
    lexer = shlex.shlex(text, posix=True, punctuation_chars=PUNCT)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def segments(toks):
    seg = []
    for tok in toks:
        if tok and all(c in PUNCT for c in tok):
            if seg:
                yield seg
            seg = []
        else:
            seg.append(tok)
    if seg:
        yield seg


def skip_wrapper(name, rest):
    values = WRAPPER_VALUE_OPTIONS.get(name, set())
    i = 0
    while i < len(rest):
        t = rest[i]
        if name == "env" and ASSIGN.match(t):
            i += 1
            continue
        if t == "--":
            i += 1
            break
        if t.startswith("-") and t != "-":
            i += 2 if t in values else 1
            continue
        break
    rest = rest[i:]
    if name == "timeout" and rest:
        rest = rest[1:]
    return rest


def unwrap(seg):
    while seg:
        name = Path(seg[0]).name or seg[0]
        if ASSIGN.match(seg[0]):
            seg = seg[1:]
        elif name in ("sudo", "doas"):
            raise Block()
        elif name in WRAPPERS or seg[0] in WRAPPERS:
            seg = skip_wrapper(name, seg[1:])
        else:
            break
    return seg


def git_sub(args):
    i = 0
    while i < len(args):
        t = args[i]
        if t in GIT_VALUE_OPTIONS:
            i += 2
            continue
        if t.startswith("-"):
            i += 1
            continue
        return t, args[i + 1:]
    return None, []


def short_has(args, letters):
    return any(a.startswith("-") and not a.startswith("--") and any(c in a[1:] for c in letters)
               for a in args)


def shell_has_c(args):
    for a in args:
        if a.startswith("-") and not a.startswith("--") and "c" in a[1:]:
            return True
        if not a.startswith(("-", "+")):
            return False
    return False


def sed_writes(args):
    scripts, i, explicit = [], 0, False
    while i < len(args):
        a = args[i]
        if a == "--in-place" or a.startswith("--in-place="):
            return True
        if a in ("-e", "--expression"):
            if i + 1 < len(args):
                scripts.append(args[i + 1])
            explicit = True
            i += 2
            continue
        if a.startswith("--expression="):
            scripts.append(a.partition("=")[2])
            explicit = True
        elif a in ("-f", "--file"):
            return True  # script file: cannot inspect
        elif a.startswith("-") and not a.startswith("--") and len(a) > 1:
            if "i" in a[1:]:
                return True
        elif not a.startswith("-") and not explicit and not scripts:
            scripts.append(a)
        i += 1
    return any(SED_WRITE.search(s) for s in scripts)


def check_segment(seg, depth):
    seg = unwrap(seg)
    if not seg:
        return
    head = seg[0]
    name = Path(head).name
    args = seg[1:]
    if name == "git":
        sub, rest = git_sub(args)
        if sub in GIT_MUTATING:
            raise Block()
        if mode == "readonly":
            if any(a.startswith(("--output", "--open-files-in-pager", "--ext-diff")) for a in rest):
                raise Block()
            if sub == "grep" and any(a == "-O" or a.startswith("-O") for a in rest):
                raise Block()
        return
    if name in MUTATING:
        raise Block()
    if name in SHELLS and shell_has_c(args):
        raise Block()
    if name == "eval":
        raise Block()
    if name == "sed" and sed_writes(args):
        raise Block()
    if name == "perl" and short_has(args, "i"):
        raise Block()
    if name == "dd" and any(a.startswith("of=") for a in args):
        raise Block()
    if name == "find":
        if any(a in FIND_WRITES for a in args):
            raise Block()
        for i, a in enumerate(args):
            if a in ("-exec", "-execdir", "-ok", "-okdir"):
                inner = []
                for b in args[i + 1:]:
                    if b in (";", "+"):
                        break
                    inner.append(b)
                check_segment(inner, depth + 1)
        return
    if mode == "readonly":
        if name in PKG and "audit" in args and ("fix" in args or "--fix" in args):
            raise Block()
        if name in ("rg", "grep") and any(a == "--pre" or a.startswith("--pre=") for a in args):
            raise Block()
        if name in ("semgrep", "bandit", "trivy", "pip-audit") and any(
                a in ("--autofix", "--fix", "-o") or a.startswith(("--output", "--autofix", "--fix"))
                for a in args):
            raise Block()


def strip_quoted(text):
    text = re.sub(r"'[^']*'", "''", text)
    return re.sub(r'"(?:[^"\\]|\\.)*"', '""', text)


def check(text, depth=0):
    if depth > 4:
        raise Block()
    # Leading-backslash alias bypass (\rm, \git ...).
    if re.search(r"(?:^|[\s;&|(`])\\[A-Za-z]", text):
        raise Block()
    for a, b in NESTED.findall(text):
        check(a or b, depth + 1)
    # Redirects write files; stream merges and /dev/null discards do not.
    # Quoted text (git log --format='%h -> %s') is not a redirect.
    probe = strip_quoted(text)
    probe = re.sub(r"[0-9]?>&[0-9]-?", "", probe)
    probe = re.sub(r"[0-9]?>[ \t]*/dev/null", "", probe)
    if ">" in probe or "<" in probe:
        raise Block()
    try:
        toks = tokens(text)
    except ValueError:
        raise Block()
    for seg in segments(toks):
        check_segment(seg, depth)


try:
    check(command)
except Block:
    print("BLOCK")
else:
    print("OK")
PYBASH
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

  # Tokenized checks: git by path or with global options, shell -c, eval,
  # in-place edits, link/install/dd writes, find -delete, \cmd aliases and
  # redirects outside quotes.
  local verdict
  verdict="$(bash_policy_verdict governed "$command" || true)"
  if [ "$verdict" != "OK" ]; then
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
      ;;
    *)
      return 1
      ;;
  esac

  local verdict
  verdict="$(bash_policy_verdict readonly "$command" || true)"
  [ "$verdict" = "OK" ]
}


# ---------------------------------------------------------------------------
# ADR loop breaker (design phase convergence)
#
# Deterministic limits so the design phase cannot loop forever. Applies to
# every agent and to the main session (empty agent_type):
#   - ADR files live only in docs/architecture/adr/ (reviews in reviews/);
#     ADR-named files in other adr/ subfolders or docs/decisions/ are denied.
#   - An ADR whose Status is Accepted/Superseded/Rejected/Withdrawn/Deprecated
#     is frozen. The only allowed edit is retiring it: changing the status
#     value to Superseded/Withdrawn/Deprecated (optionally "by ADR-NNN").
#   - After DEVFLOW_ADR_MAX_REVIEW_ROUNDS (default 2) review files exist for an
#     ADR, it may no longer be revised; a human decides.
#   - A branch may add at most DEVFLOW_ADR_MAX_NEW_PER_BRANCH (default 1) new
#     ADR files, so a capped decision is not reopened under a new number.
#   - An ADR may not grow beyond DEVFLOW_ADR_MAX_CHARS (default 12000 chars).
#   - Only adr-reviewer writes docs/architecture/adr/reviews/, one immutable
#     file per round: ADR-NNN-review-<round>.md, containing a VERDICT line.
# Prints a deny reason on stdout when the write must be blocked.
# ---------------------------------------------------------------------------
adr_gate_reason() {
  HOOK_INPUT="$INPUT" python3 - "$ROOT" "$AGENT_TYPE" <<'PYADR'
import json, os, re, subprocess, sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
agent = sys.argv[2]
who = agent or "the main session"
max_rounds = int(os.environ.get("DEVFLOW_ADR_MAX_REVIEW_ROUNDS") or "2")
max_chars = int(os.environ.get("DEVFLOW_ADR_MAX_CHARS") or "12000")
max_new = int(os.environ.get("DEVFLOW_ADR_MAX_NEW_PER_BRANCH") or "1")

data = json.loads(os.environ.get("HOOK_INPUT", "{}"))
tool = data.get("tool_name", "")
ti = data.get("tool_input") or {}
raw = Path(ti.get("file_path") or ti.get("notebook_path") or "").expanduser()
target = (raw if raw.is_absolute() else root / raw).resolve()
try:
    rel = target.relative_to(root).as_posix()
except ValueError:
    sys.exit(0)

adr_dir = "docs/architecture/adr/"
review_dir = adr_dir + "reviews/"
ADR_NAMED = re.compile(r"adr-?\d+", re.I)
ADR_DOC = re.compile(r"(ADR-\d{3,})[^/]*\.md")
FROZEN = {"accepted", "superseded", "rejected", "withdrawn", "deprecated"}
RETIRED = {"superseded", "withdrawn", "deprecated"}
STATUS_PATTERNS = (
    # ## Status\n\nAccepted   (value on the next non-blank line)
    re.compile(r"^#{1,6}[ \t]*status[ \t]*:?[ \t]*\n(?:[ \t]*\n)*[ \t]*(?:[-*+][ \t]+)?"
               r"(?:\*\*|__)?[ \t]*([A-Za-z]+)", re.I | re.M),
    # - **Status:** Accepted | **Status**: Accepted | Status: Accepted | ## Status: Accepted
    re.compile(r"^[ \t]*(?:#{1,6}[ \t]*)?(?:[-*+][ \t]+)?(?:\*\*|__)?[ \t]*status[ \t]*"
               r"(?:\*\*|__)?[ \t]*:[ \t]*(?:\*\*|__)?[ \t]*([A-Za-z]+)", re.I | re.M),
)
SUPERSEDED_BY = re.compile(
    r"^\s*[(\[,;:—–-]*\s*(?:superseded\s+)?by\s+\[?ADR-?\d+[^\s)\]]*\]?"
    r"(?:\([^)\s]*\))?\)?", re.I)
VERDICT = re.compile(
    r"^[ \t]*(?:\*\*)?VERDICT(?:\*\*)?[ \t]*:[ \t]*(?:\*\*)?[ \t]*"
    r"(APPROVE_WITH_NOTES|APPROVE|BLOCK)[ \t]*(?:\*\*)?[ \t]*$", re.M)


def deny(message):
    print(message)
    sys.exit(0)


# --- ADR location ------------------------------------------------------------
if ADR_NAMED.search(target.name):
    under_adr = rel.startswith(adr_dir)
    nested = under_adr and "/" in rel[len(review_dir if rel.startswith(review_dir) else adr_dir):]
    if rel.startswith("docs/decisions/") or nested:
        deny(f"ADR loop breaker: ADR documents live only directly in {adr_dir} (reviews "
             f"directly in {review_dir}); {rel} is not an ADR location. Do not open a "
             "parallel ADR elsewhere; stop and report to the human.")

if not rel.startswith(adr_dir):
    sys.exit(0)


def reviews_for(adr_id):
    d = root / review_dir
    if not d.is_dir():
        return []
    return sorted(d.glob(f"{adr_id}-review-*.md"))


# --- review files ------------------------------------------------------------
if rel.startswith(review_dir):
    if agent != "adr-reviewer":
        deny(f"ADR loop breaker: only adr-reviewer may write {review_dir}. "
             f"{who} cannot review or rewrite reviews.")
    m = re.fullmatch(r"(ADR-\d{3,})-review-(\d+)\.md", target.name)
    if not m:
        deny("ADR loop breaker: review file name must be ADR-NNN-review-<round>.md.")
    adr_id, rnd = m.group(1), int(m.group(2))
    if target.exists():
        deny(f"ADR loop breaker: {rel} already exists; review rounds are immutable.")
    if rnd > max_rounds:
        deny(f"ADR loop breaker: {adr_id} already had {max_rounds} review rounds. "
             "Stop and hand the decision to the human; do not start another round.")
    if rnd != len(reviews_for(adr_id)) + 1:
        deny(f"ADR loop breaker: next review round for {adr_id} must be "
             f"{len(reviews_for(adr_id)) + 1}, got {rnd}.")
    if tool == "Write" and not VERDICT.search(ti.get("content", "")):
        deny("ADR loop breaker: review must contain a line "
             "'VERDICT: APPROVE | APPROVE_WITH_NOTES | BLOCK'.")
    sys.exit(0)

# --- ADR documents -----------------------------------------------------------
m = ADR_DOC.fullmatch(target.name)
if not m:
    if ADR_NAMED.search(target.name):
        deny(f"ADR loop breaker: ADR file name must be ADR-NNN-<slug>.md; got {target.name}.")
    sys.exit(0)
adr_id = m.group(1)


def status_match(text):
    found = [mt for mt in (p.search(text) for p in STATUS_PATTERNS) if mt]
    return min(found, key=lambda mt: mt.start(1)) if found else None


def is_retire_edit(existing):
    """Only the status value changes, to Superseded/Withdrawn/Deprecated."""
    if tool != "Edit":
        return False
    old_s, new_s = ti.get("old_string", ""), ti.get("new_string", "")
    if not old_s or old_s not in existing:
        return False
    new_text = existing.replace(old_s, new_s) if ti.get("replace_all") else existing.replace(old_s, new_s, 1)
    mt = status_match(existing)
    if mt is None:
        return False
    a, b = existing.split("\n"), new_text.split("\n")
    if len(a) != len(b):
        return False
    changed = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
    line = existing.count("\n", 0, mt.start(1))
    if changed != [line]:
        return False
    col_start = mt.start(1) - (existing.rfind("\n", 0, mt.start(1)) + 1)
    col_end = col_start + len(mt.group(1))
    old_line, new_line = a[line], b[line]
    if new_line[:col_start] != old_line[:col_start]:
        return False
    word = re.match(r"[A-Za-z]+", new_line[col_start:])
    if not word or word.group(0).lower() not in RETIRED:
        return False
    old_rest = old_line[col_end:]
    new_rest = new_line[col_start + len(word.group(0)):]
    return new_rest == old_rest or SUPERSEDED_BY.sub("", new_rest, count=1) == old_rest


def git(*args):
    try:
        return subprocess.run(["git", "-C", str(root), "-c", "core.quotepath=off", *args],
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None


def adrs_added_on_branch():
    """ADR files this branch added vs. the default branch, or None to skip."""
    branch_result = git("branch", "--show-current")
    branch = branch_result.stdout.strip() if branch_result and branch_result.returncode == 0 else ""
    base_ref = None
    for ref in ("origin/HEAD", "origin/main", "main", "master"):
        r = git("rev-parse", "--verify", "--quiet", ref + "^{commit}")
        if r is not None and r.returncode == 0 and r.stdout.strip():
            base_ref = ref
            break
    if base_ref is None:
        return None
    default_name = base_ref.split("/")[-1]
    if base_ref == "origin/HEAD":
        r = git("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
        if r is not None and r.returncode == 0:
            default_name = r.stdout.strip().split("/", 1)[-1]
    if branch and branch == default_name:
        return None
    mb = git("merge-base", "HEAD", base_ref)
    if mb is None or mb.returncode != 0 or not mb.stdout.strip():
        return None
    names = set()
    added = git("diff", "--name-only", "--no-renames", "--diff-filter=A", mb.stdout.strip(), "--", adr_dir)
    untracked = git("ls-files", "--others", "--exclude-standard", "--", adr_dir)
    for r in (added, untracked):
        if r is not None and r.returncode == 0:
            names.update(line for line in r.stdout.splitlines() if line)
    return sum(1 for n in names
               if not n.startswith(review_dir) and re.fullmatch(r"ADR-?\d+[^/]*\.md", Path(n).name, re.I))


existing = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
status = status_match(existing)
if status and status.group(1).lower() in FROZEN:
    if is_retire_edit(existing):
        sys.exit(0)
    deny(f"ADR loop breaker: {adr_id} is {status.group(1)} and frozen. Record "
         "implementation-time deviations in the handoff/PR or propose a new ADR "
         "that supersedes it; do not edit this one. (Retiring it by changing only "
         "the status to Superseded/Withdrawn/Deprecated is allowed.)")

done = len(reviews_for(adr_id))
if done >= max_rounds:
    deny(f"ADR loop breaker: {adr_id} already had {done} review rounds "
         f"(limit {max_rounds}). Further revision needs a human decision; "
         "report the open BLOCKERs and stop.")

if not target.exists():
    added = adrs_added_on_branch()
    if added is not None and added >= max_new:
        deny(f"ADR loop breaker: this branch already added {added} ADR file(s) "
             f"(limit {max_new}, DEVFLOW_ADR_MAX_NEW_PER_BRANCH). Stop and report to the "
             "human; do not open a new ADR for the same decision.")

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
    deny(f"ADR loop breaker: {adr_id} would be {new_len} chars (budget {max_chars}). "
         "Keep the ADR to the decision; move details to the contract, the "
         "implementation or a follow-up ADR. Shrinking edits are allowed.")
PYADR
}

# ---------------------------------------------------------------------------
# Document size budget (handoffs and requirements)
#
# Mirrors the ADR budget: a Write/Edit that makes docs/handoffs/*.md or
# docs/product/requirements/*.md exceed DEVFLOW_DOC_MAX_CHARS (default 8000)
# characters is denied when it grows the file. Shrinking edits are allowed.
# ---------------------------------------------------------------------------
doc_budget_reason() {
  HOOK_INPUT="$INPUT" python3 - "$ROOT" <<'PYDOC'
import json, os, sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
max_chars = int(os.environ.get("DEVFLOW_DOC_MAX_CHARS") or "8000")
data = json.loads(os.environ.get("HOOK_INPUT", "{}"))
tool = data.get("tool_name", "")
ti = data.get("tool_input") or {}
raw = Path(ti.get("file_path") or ti.get("notebook_path") or "").expanduser()
target = (raw if raw.is_absolute() else root / raw).resolve()
try:
    rel = target.relative_to(root).as_posix()
except ValueError:
    sys.exit(0)
if not rel.endswith(".md") or not rel.startswith(("docs/handoffs/", "docs/product/requirements/")):
    sys.exit(0)

existing = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
if tool == "Write":
    new_len = len(ti.get("content", ""))
elif tool == "Edit":
    old_s, new_s = ti.get("old_string", ""), ti.get("new_string", "")
    new_len = (len(existing.replace(old_s, new_s)) if ti.get("replace_all")
               else len(existing) - len(old_s) + len(new_s))
else:
    new_len = len(existing)
if new_len > max_chars and new_len > len(existing):
    print(f"Document budget: {rel} would be {new_len} chars (budget {max_chars}). Keep "
          "handoffs to the latest state and next steps, and requirements to the "
          "behaviour and acceptance criteria; move detail elsewhere. Shrinking edits "
          "are allowed.")
PYDOC
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
raw = Path(ti.get("file_path") or ti.get("notebook_path") or "").expanduser()
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
# README.md files may be written anywhere outside generated/protected trees,
# and handoffs under docs/handoffs/ may be written in full (subject to the
# document budget). Source files may only be edited (never rewritten) and the
# edit must change comments only: with comments and whitespace removed, old and
# new text must be identical. Everything else is denied.
# ---------------------------------------------------------------------------
docs_writer_reason() {
  HOOK_INPUT="$INPUT" python3 - "$ROOT" <<'PYDOCS'
import json, os, re, sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
data = json.loads(os.environ.get("HOOK_INPUT", "{}"))
tool = data.get("tool_name", "")
ti = data.get("tool_input") or {}
raw = Path(ti.get("file_path") or ti.get("notebook_path") or "").expanduser()
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

if rel.startswith("docs/handoffs/") and rel.endswith(".md"):
    sys.exit(0)

SOURCE = {".cs", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
if Path(rel).suffix.lower() not in SOURCE:
    print("docs-writer may write README.md files and docs/handoffs/*.md, and add comments "
          "to source files only."); sys.exit(0)
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

# Read-only DevFlow code map queries ($DEVFLOW_CODE_MAP_SCRIPT affected|
# explain|path|query|status). `build` writes the map and is not allowed here.
# Single command only, and only the script DEVFLOW_CODE_MAP_SCRIPT names.
code_map_read_allowed() {
  local command="$1" sentinel="__DEVFLOW_CODE_MAP__" script sub
  case "$command" in
    *$'\n'*|*$'\r'*|*";"*|*"&"*|*"|"*|*'`'*|*'$('*)
      return 1
      ;;
  esac
  command="${command//\"\$\{DEVFLOW_CODE_MAP_SCRIPT\}\"/$sentinel}"
  command="${command//\"\$DEVFLOW_CODE_MAP_SCRIPT\"/$sentinel}"
  command="${command//\$\{DEVFLOW_CODE_MAP_SCRIPT\}/$sentinel}"
  command="${command//\$DEVFLOW_CODE_MAP_SCRIPT/$sentinel}"
  if [[ "$command" =~ ^python3[[:space:]]+([^[:space:]]+)[[:space:]]+([a-z]+)([[:space:]]+[^\;\&\|\<\>\`\$]*)?$ ]]; then
    script="${BASH_REMATCH[1]}"
    sub="${BASH_REMATCH[2]}"
    case "$sub" in
      affected|explain|path|query|status) ;;
      *) return 1 ;;
    esac
    # Only the plugin's own copy: a relative scripts/devflow_code_map.py could
    # be a file planted in the target repo. The env var is set by
    # session-start.sh / launch from the plugin root.
    if [ "$script" = "$sentinel" ]; then
      return 0
    fi
    if [ -n "${DEVFLOW_CODE_MAP_SCRIPT:-}" ] && [ "$script" = "$DEVFLOW_CODE_MAP_SCRIPT" ]; then
      return 0
    fi
    if [ -n "${DEVFLOW_PLUGIN_ROOT:-}" ] && [ "$script" = "$DEVFLOW_PLUGIN_ROOT/scripts/devflow_code_map.py" ]; then
      return 0
    fi
  fi
  return 1
}

analyst_command_allowed() {
  local command="$1" sentinel="__DEVFLOW_ARCH_SCAN__" script
  # A single command only: no newline/CR injection, chaining, pipes or
  # substitutions (the scanner regex below would otherwise accept a second
  # command after a newline).
  case "$command" in
    *$'\n'*|*$'\r'*|*";"*|*"&"*|*"|"*|*'`'*|*'$('*)
      return 1
      ;;
  esac
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
  Edit|Write|NotebookEdit)
    # NotebookEdit carries its target as notebook_path.
    FILE_PATH="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty')"

    # Main session (no agent_type): only the design-convergence gates apply.
    if [ -z "$AGENT_TYPE" ]; then
      if [ -n "$FILE_PATH" ]; then
        ADR_GATE_REASON="$(adr_gate_reason)"
        if [ -n "$ADR_GATE_REASON" ]; then
          deny "$ADR_GATE_REASON"
          exit 0
        fi
        DOC_BUDGET_REASON="$(doc_budget_reason)"
        if [ -n "$DOC_BUDGET_REASON" ]; then
          deny "$DOC_BUDGET_REASON"
          exit 0
        fi
      fi
      exit 0
    fi

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

    DOC_BUDGET_REASON="$(doc_budget_reason)"
    if [ -n "$DOC_BUDGET_REASON" ]; then
      deny "$DOC_BUDGET_REASON"
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
        if ! analyst_command_allowed "$COMMAND" && ! code_map_read_allowed "$COMMAND"; then
          deny "Role-boundary protection: architecture-analyst may run only the DevFlow architecture scanner (python3 .../devflow_arch_scan.py ...), read-only code map queries (python3 .../devflow_code_map.py affected|explain|path|query|status ...) or single non-mutating inspection commands."
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
        if code_map_read_allowed "$COMMAND"; then
          exit 0
        fi
        if ! security_command_is_non_mutating "$COMMAND"; then
          deny "Role-boundary protection: security-red-team may run only single, non-mutating inspection or scanning commands (including read-only code map queries). Use Read/Grep/Glob for other inspection."
          exit 0
        fi
        ;;
    esac

    if bash_has_blocked_operation "$COMMAND"; then
      deny "Role-boundary protection: governed agents cannot run Git mutation, destructive filesystem, dependency-install, merge, deployment, migration, permission, redirected-write, nested-shell, external-system write (PR/issue comments, replies, resolves) or active attack tooling Bash commands. Prepare the change and hand it to the human."
      exit 0
    fi
    ;;
esac

exit 0
