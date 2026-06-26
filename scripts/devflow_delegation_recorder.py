#!/usr/bin/env python3
"""
DevFlow Delegation Evidence Recorder

Reads sanitized subagent lifecycle event data from stdin (Claude Code hook).
Writes a narrow, sanitized evidence record to .devflow/delegation-events/ in
the current working directory (target project root).

Supported hook events: SubagentStart, SubagentStop.

Non-blocking: any failure exits 0 so the hook never blocks delivery.

Stored fields (exact set, nothing more):
    schema_version, evidence_id, timestamp, run_id,
    hook_event, lifecycle_state, agent_type, evidence_source

Never stored:
    session_id, agent_id, transcript_path, agent_transcript_path,
    prompt, input, output, last_assistant_message, task_description,
    file_content, token, secret, credential, url, api_key, password,
    message, content, text, log, or any free-text field.
"""

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1"
EVIDENCE_SOURCE = "native_hook_event"

ALLOWED_HOOK_EVENTS = frozenset({"SubagentStart", "SubagentStop"})

_FORBIDDEN_EVIDENCE_FIELDS = frozenset({
    "session_id",
    "agent_id",
    "transcript_path",
    "agent_transcript_path",
    "prompt",
    "input",
    "output",
    "last_assistant_message",
    "task_description",
    "file_content",
    "token",
    "secret",
    "credential",
    "url",
    "api_key",
    "password",
    "message",
    "content",
    "text",
    "log",
})

_AGENT_TYPE_FORBIDDEN_SUBSTRINGS = frozenset({
    "token", "key", "secret", "password", "credential", "session",
})


def _get_run_id(cwd: Path) -> str:
    try:
        project_file = cwd / ".devflow" / "project.json"
        if project_file.exists():
            data = json.loads(project_file.read_text(encoding="utf-8"))
            run_id = data.get("current_run_id")
            if isinstance(run_id, str) and run_id:
                return run_id
    except Exception:
        pass
    return "unknown"


def _extract_agent_type(raw: dict) -> str:
    for key in ("agent_type", "subagent_type", "role"):
        value = raw.get(key)
        if value and isinstance(value, str):
            value = value[:64]
            lower = value.lower()
            if not any(s in lower for s in _AGENT_TYPE_FORBIDDEN_SUBSTRINGS):
                return value
    return "unknown"


def _lifecycle_state(hook_event: str) -> str:
    if hook_event == "SubagentStart":
        return "started"
    if hook_event == "SubagentStop":
        return "stopped"
    return "unknown"


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    cwd = Path.cwd()

    try:
        raw_input = sys.stdin.read()
        raw = json.loads(raw_input) if raw_input.strip() else {}
    except Exception:
        raw = {}

    if not isinstance(raw, dict):
        raw = {}

    hook_event = raw.get("hook_event_name") or raw.get("hook_event") or ""
    if not isinstance(hook_event, str):
        hook_event = ""

    if hook_event not in ALLOWED_HOOK_EVENTS:
        sys.exit(0)

    evidence = {
        "schema_version": SCHEMA_VERSION,
        "evidence_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": _get_run_id(cwd),
        "hook_event": hook_event,
        "lifecycle_state": _lifecycle_state(hook_event),
        "agent_type": _extract_agent_type(raw),
        "evidence_source": EVIDENCE_SOURCE,
    }

    for field in _FORBIDDEN_EVIDENCE_FIELDS:
        evidence.pop(field, None)

    try:
        events_dir = cwd / ".devflow" / "delegation-events"
        events_dir.mkdir(parents=True, exist_ok=True)
        event_file = events_dir / f"{evidence['evidence_id']}.json"
        _atomic_write(event_file, json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
