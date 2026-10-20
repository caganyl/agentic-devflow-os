#!/usr/bin/env python3
"""
DevFlow Office telemetry recorder.

Feeds the live "DevFlow Ofis" view (scripts/devflow_office.py). Registered as
an async Claude Code hook; it appends one sanitized JSON line per event to
.devflow/office/events.jsonl in the target project.

Hook events handled (read from stdin):
    SubagentStart / SubagentStop   -> agent_start / agent_stop
    PreToolUse  tool_name=Skill    -> skill
    PreToolUse  tool_name=Agent|Task -> delegate (subagent_type only)
    PreToolUse  Edit|Write|NotebookEdit|Bash|Read|Grep|Glob -> tool
    PreToolUse  AskUserQuestion|ExitPlanMode -> attention (question / plan)
    PostToolUse Agent|Task          -> delegate_done (subagent returned)
    PostToolUse AskUserQuestion|ExitPlanMode -> resume
    Notification                    -> attention (permission / idle / question)
    Stop                            -> attention (turn_end: waiting for the user)
    UserPromptSubmit                -> resume

Deny notes are written by the enforcement hooks themselves:
    devflow_office_recorder.py --deny <hook-name> <reason>   (hook input on stdin)

Stored fields (exact set): ts, kind, agent, agent_key, tool, skill, path,
subagent, hook, reason. Never stored: prompts, tool input bodies, Bash
commands, file contents, transcripts, session ids, raw agent ids (agent_key
is a short one-way hash used only to pair start/stop of the same subagent).

Telemetry only: it never gates anything and every failure exits 0. Nothing is
written unless the working directory already has a .devflow/ workspace.
"""

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

MAX_LOG_BYTES = 2 * 1024 * 1024
ACTIVITY_TOOLS = frozenset({"Edit", "Write", "NotebookEdit", "Bash", "Read", "Grep", "Glob"})
PATH_TOOLS = frozenset({"Edit", "Write", "NotebookEdit", "Read"})
DELEGATION_TOOLS = frozenset({"Agent", "Task"})
ATTENTION_TOOLS = {"AskUserQuestion": "question", "ExitPlanMode": "plan"}
_PERMISSION_TOOL = re.compile(r"\buse ([A-Za-z_][\w:.-]{0,63})")
_FORBIDDEN_NAME_PARTS = ("token", "secret", "password", "credential", "api_key", "apikey")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"


def _clean_name(value, limit: int = 64) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()[:limit]
    if not value or any(p in value.lower() for p in _FORBIDDEN_NAME_PARTS):
        return ""
    return "".join(ch for ch in value if ch.isalnum() or ch in "-_:.")


def _agent_key(raw: dict) -> str:
    agent_id = raw.get("agent_id")
    if isinstance(agent_id, str) and agent_id:
        return hashlib.sha256(agent_id.encode("utf-8")).hexdigest()[:10]
    return ""


def _rel_path(raw_path, cwd: Path) -> str:
    if not isinstance(raw_path, str) or not raw_path:
        return ""
    try:
        p = Path(raw_path)
        if p.is_absolute():
            p = p.resolve().relative_to(cwd.resolve())
        text = p.as_posix()
    except Exception:
        return ""
    if text.startswith("..") or any(part in text.lower() for part in (".env", "secret", ".pem", ".key")):
        return ""
    return text[-120:]


def _skill_name(tool_input: dict) -> str:
    for key in ("skill", "skill_name", "name", "command"):
        name = _clean_name(tool_input.get(key))
        if name:
            return name.lstrip("/")
    return ""


def _notification_reason(raw: dict) -> tuple[str, str]:
    """Classify a Notification payload; only the category and a tool name are kept."""
    kind = raw.get("notification_type") if isinstance(raw.get("notification_type"), str) else ""
    message = raw.get("message") if isinstance(raw.get("message"), str) else ""
    tool_match = _PERMISSION_TOOL.search(message)
    tool = _clean_name(tool_match.group(1)) if tool_match else ""
    if kind == "permission_prompt" or "permission" in message.lower():
        return "permission", tool
    if kind == "idle_prompt" or "waiting for your input" in message.lower():
        return "idle", ""
    if kind.startswith("elicitation") or "question" in message.lower():
        return "question", ""
    return "other", ""


def build_event(raw: dict, cwd: Path, deny_hook: str = "", deny_reason: str = ""):
    """Return the sanitized event dict for one hook payload, or None to skip."""
    if not isinstance(raw, dict):
        raw = {}
    base = {"ts": _now()}
    agent = _clean_name(raw.get("agent_type")) or _clean_name(raw.get("subagent_type"))
    key = _agent_key(raw)
    if agent:
        base["agent"] = agent
    if key:
        base["agent_key"] = key

    tool = raw.get("tool_name") if isinstance(raw.get("tool_name"), str) else ""
    tool_input = raw.get("tool_input") if isinstance(raw.get("tool_input"), dict) else {}

    if deny_hook:
        event = dict(base, kind="deny", hook=_clean_name(deny_hook))
        if tool:
            event["tool"] = _clean_name(tool)
        path = _rel_path(tool_input.get("file_path") or tool_input.get("notebook_path"), cwd)
        if path:
            event["path"] = path
        reason = " ".join(str(deny_reason).split())
        if reason:
            event["reason"] = reason[:160]
        return event

    hook_event = raw.get("hook_event_name") or raw.get("hook_event") or ""
    if hook_event == "SubagentStart":
        return dict(base, kind="agent_start")
    if hook_event == "SubagentStop":
        return dict(base, kind="agent_stop")
    if hook_event == "Notification":
        reason, ntool = _notification_reason(raw)
        event = dict(base, kind="attention", reason=reason)
        if ntool:
            event["tool"] = ntool
        return event
    if hook_event == "Stop":
        return dict(base, kind="attention", reason="turn_end")
    if hook_event == "UserPromptSubmit":
        return dict(base, kind="resume")
    if hook_event == "PostToolUse":
        if tool in DELEGATION_TOOLS:
            sub = _clean_name(tool_input.get("subagent_type"))
            return dict(base, kind="delegate_done", subagent=sub) if sub else None
        if tool in ATTENTION_TOOLS:
            return dict(base, kind="resume", tool=tool)
        return None
    if hook_event != "PreToolUse":
        return None
    if tool in ATTENTION_TOOLS:
        return dict(base, kind="attention", reason=ATTENTION_TOOLS[tool], tool=tool)
    if tool == "Skill":
        skill = _skill_name(tool_input)
        return dict(base, kind="skill", skill=skill) if skill else None
    if tool in DELEGATION_TOOLS:
        sub = _clean_name(tool_input.get("subagent_type"))
        return dict(base, kind="delegate", subagent=sub) if sub else None
    if tool in ACTIVITY_TOOLS:
        event = dict(base, kind="tool", tool=tool)
        if tool in PATH_TOOLS:
            path = _rel_path(tool_input.get("file_path") or tool_input.get("notebook_path"), cwd)
            if path:
                event["path"] = path
        return event
    return None


def find_workspace_root(cwd: Path, project_dir=None) -> Path:
    """The project dir, or the nearest ancestor of cwd, that has .devflow/.

    The session's cwd follows `cd` in Bash (e.g. into src/), so the target
    root is searched upwards; cwd itself is returned when none is found.
    """
    candidates = [Path(project_dir)] if project_dir else []
    candidates += [cwd, *list(cwd.parents)[:8]]
    for candidate in candidates:
        try:
            if (candidate / ".devflow").is_dir():
                return candidate
        except OSError:
            continue
    return cwd


def append_event(cwd: Path, event: dict) -> None:
    devflow = cwd / ".devflow"
    if not devflow.is_dir():
        return
    office = devflow / "office"
    office.mkdir(exist_ok=True)
    log = office / "events.jsonl"
    try:
        if log.exists() and log.stat().st_size > MAX_LOG_BYTES:
            log.replace(office / "events.1.jsonl")
    except OSError:
        pass
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
    fd = os.open(str(log), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        deny_hook = deny_reason = ""
        if argv[:1] == ["--deny"]:
            deny_hook = argv[1] if len(argv) > 1 else "hook"
            deny_reason = argv[2] if len(argv) > 2 else ""
        # Read bytes: on Windows the locale codec (cp1254) cannot decode every
        # UTF-8 payload (e.g. "Ş" = C5 9E) and the event would be lost.
        text = "" if sys.stdin.isatty() else sys.stdin.buffer.read().decode("utf-8", errors="replace")
        raw = json.loads(text) if text.strip() else {}
        cwd = Path(raw.get("cwd") or os.getcwd()) if isinstance(raw, dict) else Path.cwd()
        cwd = find_workspace_root(cwd, os.environ.get("CLAUDE_PROJECT_DIR"))
        event = build_event(raw, cwd, deny_hook, deny_reason)
        if event:
            append_event(cwd, event)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
