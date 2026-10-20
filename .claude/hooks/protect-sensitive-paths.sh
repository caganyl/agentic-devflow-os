#!/usr/bin/env bash
# devflow-hook-hardening: v1
set -euo pipefail

# Fail closed: any unexpected exit status becomes exit 2 (blocked). Claude
# Code lets a tool call through on any non-zero status other than 2.
devflow_fail_closed() {
  local status=$?
  if [ "$status" -ne 0 ] && [ "$status" -ne 2 ]; then
    printf '%s\n' "DevFlow hook internal error (protect-sensitive-paths.sh, status $status); denying for safety." >&2
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
    "permissionDecisionReason": "Sensitive-path protection: a required tool (jq or python3) is not on PATH, so the policy cannot be evaluated. The operation is blocked (fail-closed). Install the missing tool to proceed."
  }
}'
  exit 0
fi

if ! printf '%s' "$INPUT" | jq -e 'type == "object"' >/dev/null 2>&1; then
  printf '%s\n' "Sensitive-path protection: hook input is not a JSON object; denying for safety." >&2
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
  devflow_office_note "protect-sensitive-paths" "$reason"
}

# Sensitive targets (case-insensitive, at any depth): .env, .env.* (except
# .env.example), .envrc, secrets/ directories, credentials.json, *.pem, *.key,
# *.p12, *.pfx, id_rsa*/id_ed25519*/..., .claude/settings*.json and
# .claude/hooks/. File paths are normalised first (./, //, .., symlinks, and
# relative to the repository root when inside it). Bash commands are checked
# per path token after quotes are removed, and dot-globs that can expand to an
# env file (.e*v, .en?) count as the env file. `.env` must be a whole path
# segment, so `process.env` or `jq .keywords` do not match.
# The heredoc lives in a function, not directly inside $( ): bash 3.2
# (macOS /bin/bash) mis-parses quoted heredocs within command substitution
# when the body contains backticks.
sensitive_reason() {
  HOOK_INPUT="$INPUT" python3 - <<'PYSENS'
import fnmatch, json, os, posixpath, re, subprocess, sys

data = json.loads(os.environ["HOOK_INPUT"])
tool = data.get("tool_name") or ""
ti = data.get("tool_input") or {}
if not isinstance(ti, dict):
    ti = {}
cwd = data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

ENV_ALLOWED = {".env.example"}
KEY_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
DOT_SAMPLES = (".env", ".env.local", ".env.production", ".envrc")
NAME_SAMPLES = ("secrets", "id_rsa", "id_ed25519", "credentials.json",
                "x.pem", "x.key", "x.p12", "x.pfx")
GLOB = re.compile(r"[*?\[]")


def repo_root(start):
    if not os.path.isdir(start):
        return None
    try:
        r = subprocess.run(["git", "-C", start, "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


ROOT = repo_root(cwd)


DIR_NAMES = ("secrets", ".env")


def name_sensitive(name):
    if name in (".env", ".envrc", "credentials.json"):
        return True
    if name.startswith(".env.") and name not in ENV_ALLOWED:
        return True
    if any(name.endswith(s) and len(name) > len(s) for s in KEY_SUFFIXES):
        return True
    return bool(re.match(r"id_(rsa|dsa|ecdsa|ed25519)", name))


def glob_matches(segment, samples):
    """Whether a glob segment could expand to one of the sample names."""
    if not GLOB.search(segment):
        return False
    if not segment.startswith(".") and not re.search(r"[a-z0-9]", segment):
        return False  # pure wildcards such as * or *.* are not specific enough
    # Shell globs match a leading dot only when the pattern starts with one.
    return any(fnmatch.fnmatchcase(s, segment) for s in samples
               if s.startswith(".") == segment.startswith("."))


def parts_sensitive(path, is_dir=False):
    parts = [p for p in path.lower().split("/") if p not in ("", ".")]
    if not parts:
        return False
    dirs, name = (parts, "") if is_dir else (parts[:-1], parts[-1])
    # A directory such as secrets/ or .env/ anywhere on the path.
    if any(d in DIR_NAMES or glob_matches(d, DIR_NAMES) for d in dirs):
        return True
    if name and (name_sensitive(name) or glob_matches(name, DOT_SAMPLES + NAME_SAMPLES)):
        return True
    joined = "/".join(parts)
    if re.search(r"(^|/)\.claude/settings[^/]*\.json$", joined):
        return True
    return bool(re.search(r"(^|/)\.claude/hooks(/|$)", joined))


def file_candidates(raw):
    path = os.path.expanduser(raw)
    if not os.path.isabs(path):
        path = os.path.join(cwd, path)
    forms = [posixpath.normpath(path)]
    try:
        forms.append(os.path.realpath(path))
    except (OSError, ValueError):
        pass
    out = []
    for form in forms:
        if ROOT and (form == ROOT or form.startswith(ROOT.rstrip("/") + "/")):
            out.append(form[len(ROOT):].lstrip("/"))
        else:
            out.append(form)
    return out


def command_sensitive(command):
    text = command.replace("'", "").replace('"', "").replace("\\", "")
    for token in re.split(r"[\s;&|<>()`=,:{}@]+", text):
        if token and parts_sensitive(posixpath.normpath(token), is_dir=token.endswith("/")):
            return True
    return False


if tool in ("Edit", "Write", "NotebookEdit"):
    raw = ti.get("file_path") or ti.get("notebook_path") or ""
    if isinstance(raw, str) and raw and any(parts_sensitive(c) for c in file_candidates(raw)):
        print("Sensitive-path protection: Claude cannot modify or create secrets, "
              "environment files, credentials, Claude settings or hook scripts.")
elif tool == "Bash":
    command = ti.get("command") or ""
    if isinstance(command, str) and command_sensitive(command):
        print("Sensitive-path protection: command references a protected credential, "
              "environment or Claude guardrail path.")
PYSENS
}
REASON="$(sensitive_reason)"

if [ -n "$REASON" ]; then
  deny "$REASON"
fi

exit 0
