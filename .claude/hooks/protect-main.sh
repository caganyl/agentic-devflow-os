#!/usr/bin/env bash
# devflow-hook-hardening: v1
set -euo pipefail

# Fail closed: any unexpected exit status becomes exit 2 (blocked). Claude
# Code lets a tool call through on any non-zero status other than 2.
devflow_fail_closed() {
  local status=$?
  if [ "$status" -ne 0 ] && [ "$status" -ne 2 ]; then
    printf '%s\n' "DevFlow hook internal error (protect-main.sh, status $status); denying for safety." >&2
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
    "permissionDecisionReason": "Main-branch protection: a required tool (jq or python3) is not on PATH, so branch protection cannot be evaluated. The operation is blocked (fail-closed). Install the missing tool to proceed."
  }
}'
  exit 0
fi

if ! printf '%s' "$INPUT" | jq -e 'type == "object"' >/dev/null 2>&1; then
  printf '%s\n' "Main-branch protection: hook input is not a JSON object; denying for safety." >&2
  exit 2
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

# Protected branches: main, master and DEVFLOW_PROTECTED_BRANCHES (comma
# list). A detached HEAD is not a protected branch (managed run worktrees and
# tests may be detached).
is_protected_branch() {
  local branch="$1" extra item
  [ -n "$branch" ] || return 1
  case "$branch" in
    main|master) return 0 ;;
  esac
  extra="${DEVFLOW_PROTECTED_BRANCHES:-}"
  local IFS=','
  for item in $extra; do
    item="$(printf '%s' "$item" | tr -d '[:space:]')"
    if [ -n "$item" ] && [ "$item" = "$branch" ]; then
      return 0
    fi
  done
  return 1
}

branch_of() {
  git -C "$1" branch --show-current 2>/dev/null || true
}

TOOL_NAME="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty')"
CWD="$(printf '%s' "$INPUT" | jq -r '.cwd // empty')"

if [ -z "$CWD" ]; then
  CWD="${CLAUDE_PROJECT_DIR:-$PWD}"
fi

ROOT="$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null || true)"

if [ -n "$ROOT" ]; then
  BRANCH="$(branch_of "$ROOT")"
  if is_protected_branch "$BRANCH"; then
    deny "Main branch read-only protection: this Claude session started on $BRANCH and cannot run Bash commands, edit files, create branches, or create worktrees. Ask the user to start an isolated worktree from a normal terminal, for example: claude --worktree feature-name"
    exit 0
  fi
fi

case "$TOOL_NAME" in
  Edit|Write|NotebookEdit)
    # The session may be on a feature branch while the target file lives in
    # another checkout that is on a protected branch: check the file's repo.
    FILE_PATH="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty')"
    if [ -n "$FILE_PATH" ]; then
      case "$FILE_PATH" in
        /*) TARGET="$FILE_PATH" ;;
        *) TARGET="$CWD/$FILE_PATH" ;;
      esac
      TARGET_DIR="$(dirname "$TARGET")"
      while [ ! -d "$TARGET_DIR" ] && [ "$TARGET_DIR" != "/" ] && [ "$TARGET_DIR" != "." ]; do
        TARGET_DIR="$(dirname "$TARGET_DIR")"
      done
      TARGET_ROOT="$(git -C "$TARGET_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
      if [ -n "$TARGET_ROOT" ]; then
        TARGET_BRANCH="$(branch_of "$TARGET_ROOT")"
        if is_protected_branch "$TARGET_BRANCH"; then
          deny "Main branch read-only protection: the target file is in a checkout on protected branch $TARGET_BRANCH. Edit it from an isolated feature worktree instead."
          exit 0
        fi
      fi
    fi
    ;;
  Bash)
    # git -C <repo> / --git-dir / --work-tree, or cd <repo> before git, can
    # mutate a checkout on a protected branch from a session that is not on it.
    COMMAND="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty')"
    PROTECTED_TARGET="$(python3 - "$CWD" "$COMMAND" <<'PYMAIN'
import os, re, shlex, subprocess, sys

cwd, command = sys.argv[1], sys.argv[2]
PUNCT = ";&|\n()`"
MUTATING = {"add", "am", "apply", "branch", "checkout", "cherry-pick", "clean", "commit",
            "merge", "mv", "pull", "push", "rebase", "reset", "restore", "revert", "rm",
            "stash", "switch", "tag", "update-ref", "worktree"}
VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix",
                 "--config-env"}
extra = {b.strip() for b in os.environ.get("DEVFLOW_PROTECTED_BRANCHES", "").split(",") if b.strip()}
PROTECTED = {"main", "master"} | extra


def git_out(*args):
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def resolve(base, path):
    path = os.path.expanduser(path)
    return os.path.normpath(path if os.path.isabs(path) else os.path.join(base, path))


try:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=PUNCT)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    tokens = list(lexer)
except ValueError:
    sys.exit(0)

segments, seg = [], []
for tok in tokens:
    if tok and all(c in PUNCT for c in tok):
        if seg:
            segments.append(seg)
        seg = []
    else:
        seg.append(tok)
if seg:
    segments.append(seg)

here = cwd
for seg in segments:
    while seg and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", seg[0]):
        seg = seg[1:]
    if not seg:
        continue
    name = os.path.basename(seg[0])
    if name in ("cd", "pushd") and len(seg) > 1 and "$" not in seg[1]:
        here = resolve(here, seg[1])
        continue
    if name != "git":
        continue
    repo, git_dir, i = here, None, 1
    while i < len(seg):
        t = seg[i]
        if t == "-C" and i + 1 < len(seg):
            repo = resolve(repo, seg[i + 1]); i += 2; continue
        if t in ("--git-dir", "--work-tree") and i + 1 < len(seg):
            if t == "--git-dir":
                git_dir = resolve(repo, seg[i + 1])
            else:
                repo = resolve(repo, seg[i + 1])
            i += 2; continue
        if t.startswith("--git-dir="):
            git_dir = resolve(repo, t.partition("=")[2]); i += 1; continue
        if t.startswith("--work-tree="):
            repo = resolve(repo, t.partition("=")[2]); i += 1; continue
        if t in VALUE_OPTIONS:
            i += 2; continue
        if t.startswith("-"):
            i += 1; continue
        break
    sub = seg[i] if i < len(seg) else ""
    if sub not in MUTATING:
        continue
    if git_dir:
        branch = git_out("--git-dir", git_dir, "symbolic-ref", "--quiet", "--short", "HEAD")
    elif os.path.isdir(repo):
        branch = git_out("-C", repo, "branch", "--show-current")
    else:
        branch = ""
    if branch in PROTECTED:
        print(branch)
        break
PYMAIN
)"
    if [ -n "$PROTECTED_TARGET" ]; then
      deny "Main branch read-only protection: this command runs a mutating git operation in a checkout on protected branch $PROTECTED_TARGET. Work from an isolated feature worktree instead."
      exit 0
    fi
    ;;
esac

exit 0
