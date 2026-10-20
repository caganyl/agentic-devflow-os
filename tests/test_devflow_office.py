"""
Tests for the live office view: telemetry recorder, deny notes from the
enforcement hooks, the snapshot server and plugin wiring.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
RECORDER = SCRIPTS / "devflow_office_recorder.py"
OFFICE = SCRIPTS / "devflow_office.py"
HOOKS_DIR = REPO_ROOT / ".claude" / "hooks"
PLUGIN_HOOKS = REPO_ROOT / "hooks" / "hooks.json"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


office = _load(OFFICE, "devflow_office_under_test")
recorder = _load(RECORDER, "devflow_office_recorder_under_test")

_HOME = tempfile.TemporaryDirectory()


def setUpModule():
    # Never touch the real ~/.devflow-office registry from tests (subprocesses inherit it).
    os.environ["DEVFLOW_OFFICE_HOME"] = _HOME.name


def tearDownModule():
    os.environ.pop("DEVFLOW_OFFICE_HOME", None)
    _HOME.cleanup()


def _serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _events(target: Path) -> list[dict]:
    log = target / ".devflow" / "office" / "events.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


class _TargetCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.target = Path(self.tmp.name).resolve() / "proj"
        (self.target / ".devflow").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def record(self, payload, *args, cwd=None):
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        return subprocess.run([sys.executable, str(RECORDER), *args], input=json.dumps(payload),
                              capture_output=True, text=True, cwd=str(cwd or self.target), env=env)


class RecorderTest(_TargetCase):
    def test_subagent_lifecycle_hashes_agent_id(self):
        base = {"cwd": str(self.target), "agent_type": "backend-engineer", "agent_id": "agent-raw-123",
                "session_id": "sess-1", "transcript_path": "/x/t.jsonl", "prompt": "do the thing"}
        self.record(dict(base, hook_event_name="SubagentStart"))
        self.record(dict(base, hook_event_name="SubagentStop", last_assistant_message="done"))
        start, stop = _events(self.target)
        self.assertEqual((start["kind"], stop["kind"]), ("agent_start", "agent_stop"))
        self.assertEqual(start["agent"], "backend-engineer")
        self.assertEqual(start["agent_key"], stop["agent_key"])
        dump = json.dumps(_events(self.target))
        for secret in ("agent-raw-123", "sess-1", "t.jsonl", "do the thing", "done"):
            self.assertNotIn(secret, dump)

    def test_skill_and_delegation(self):
        self.record({"cwd": str(self.target), "hook_event_name": "PreToolUse", "agent_type": "qa-automation",
                     "tool_name": "Skill", "tool_input": {"skill": "qa-acceptance-verification"}})
        self.record({"cwd": str(self.target), "hook_event_name": "PreToolUse", "tool_name": "Agent",
                     "tool_input": {"subagent_type": "docs-writer", "prompt": "secret plan"}})
        skill, delegate = _events(self.target)
        self.assertEqual((skill["kind"], skill["skill"], skill["agent"]), ("skill", "qa-acceptance-verification", "qa-automation"))
        self.assertEqual((delegate["kind"], delegate["subagent"]), ("delegate", "docs-writer"))
        self.assertNotIn("agent", delegate)
        self.assertNotIn("secret plan", json.dumps(delegate))

    def test_tool_events_keep_only_tool_and_relative_path(self):
        self.record({"cwd": str(self.target), "hook_event_name": "PreToolUse", "tool_name": "Bash",
                     "tool_input": {"command": "export API_TOKEN=abc && make test"}})
        self.record({"cwd": str(self.target), "hook_event_name": "PreToolUse", "tool_name": "Write",
                     "tool_input": {"file_path": str(self.target / "src" / "app.ts"), "content": "body"}})
        self.record({"cwd": str(self.target), "hook_event_name": "PreToolUse", "tool_name": "Edit",
                     "tool_input": {"file_path": str(self.target / ".env"), "old_string": "a", "new_string": "b"}})
        bash, write, env_edit = _events(self.target)
        self.assertEqual(bash, {"ts": bash["ts"], "kind": "tool", "tool": "Bash"})
        self.assertEqual(write["path"], "src/app.ts")
        self.assertNotIn("path", env_edit)
        self.assertNotIn("body", json.dumps(_events(self.target)))

    def test_ignores_unrelated_events_and_bad_input(self):
        self.record({"cwd": str(self.target), "hook_event_name": "PreCompact", "trigger": "auto"})
        result = subprocess.run([sys.executable, str(RECORDER)], input="not json", capture_output=True,
                                text=True, cwd=str(self.target))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(_events(self.target), [])

    def test_no_devflow_workspace_writes_nothing(self):
        bare = self.target.parent / "bare"
        bare.mkdir()
        result = self.record({"cwd": str(bare), "hook_event_name": "SubagentStart", "agent_type": "x"}, cwd=bare)
        self.assertEqual(result.returncode, 0)
        self.assertFalse((bare / ".devflow").exists())

    def test_subfolder_cwd_writes_to_workspace_root(self):
        sub = self.target / "src" / "Api"
        sub.mkdir(parents=True)
        self.record({"cwd": str(sub), "hook_event_name": "PreToolUse", "tool_name": "Bash",
                     "tool_input": {"command": "dotnet build"}}, cwd=sub)
        self.assertEqual([e["kind"] for e in _events(self.target)], ["tool"])
        self.assertFalse((sub / ".devflow").exists())

    def test_attention_events(self):
        base = {"cwd": str(self.target)}
        self.record(dict(base, hook_event_name="Notification", notification_type="permission_prompt",
                         message="Claude needs your permission to use Bash"))
        self.record(dict(base, hook_event_name="Notification", message="Claude is waiting for your input"))
        self.record(dict(base, hook_event_name="PreToolUse", tool_name="AskUserQuestion",
                         tool_input={"questions": [{"question": "gizli soru?"}]}))
        self.record(dict(base, hook_event_name="PostToolUse", tool_name="AskUserQuestion", tool_input={}))
        self.record(dict(base, hook_event_name="Stop", last_assistant_message="bitti"))
        self.record(dict(base, hook_event_name="UserPromptSubmit", prompt="şimdi şunu yap"))
        self.record(dict(base, hook_event_name="PostToolUse", tool_name="Agent",
                         tool_input={"subagent_type": "devflow-plugin:docs-writer", "prompt": "x"}))
        events = _events(self.target)
        self.assertEqual([(e["kind"], e.get("reason"), e.get("tool")) for e in events], [
            ("attention", "permission", "Bash"), ("attention", "idle", None),
            ("attention", "question", "AskUserQuestion"), ("resume", None, "AskUserQuestion"),
            ("attention", "turn_end", None), ("resume", None, None), ("delegate_done", None, None)])
        self.assertEqual(events[-1]["subagent"], "devflow-plugin:docs-writer")
        dump = json.dumps(events, ensure_ascii=False)
        for secret in ("gizli", "bitti", "şimdi", "needs your permission"):
            self.assertNotIn(secret, dump)

    def test_utf8_payload_with_turkish_letters(self):
        payload = {"cwd": str(self.target), "hook_event_name": "SubagentStart", "agent_type": "qa-automation",
                   "prompt": "Şirket İçi Ğ testleri"}
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        env["PYTHONIOENCODING"] = "cp1254"
        env["PYTHONUTF8"] = "0"
        subprocess.run([sys.executable, str(RECORDER)], input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       capture_output=True, cwd=str(self.target), env=env)
        self.assertEqual([e["kind"] for e in _events(self.target)], ["agent_start"])

    def test_events_note_the_project_in_the_registry(self):
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        env["TERM_PROGRAM"] = "vscode"
        env.pop("VisualStudioVersion", None)
        subprocess.run([sys.executable, str(RECORDER)], input=json.dumps(
            {"cwd": str(self.target), "hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {}}),
            capture_output=True, text=True, cwd=str(self.target), env=env)
        registry = json.loads((Path(os.environ["DEVFLOW_OFFICE_HOME"]) / "projects.json").read_text(encoding="utf-8"))
        entry = registry["projects"][str(self.target.resolve())]
        self.assertEqual((entry["name"], entry["ide"]), ("proj", "VS Code"))

    def test_ide_label(self):
        self.assertEqual(recorder.ide_label({"VisualStudioVersion": "18.0"}), "VS")
        self.assertEqual(recorder.ide_label({"TERM_PROGRAM": "vscode"}), "VS Code")
        self.assertEqual(recorder.ide_label({"TERMINAL_EMULATOR": "JetBrains-JediTerm"}), "JetBrains")
        self.assertEqual(recorder.ide_label({}), "")

    def test_deny_note(self):
        self.record({"cwd": str(self.target), "agent_type": "frontend-engineer", "tool_name": "Write",
                     "tool_input": {"file_path": "src/Api/Dto.cs", "content": "x"}},
                    "--deny", "enforce-role-boundaries", "Ownership-manifest protection: outside write paths")
        (event,) = _events(self.target)
        self.assertEqual(event["kind"], "deny")
        self.assertEqual(event["hook"], "enforce-role-boundaries")
        self.assertEqual(event["path"], "src/Api/Dto.cs")
        self.assertIn("Ownership-manifest", event["reason"])


class HookDenyNoteTest(unittest.TestCase):
    """protect-main still emits exactly one deny JSON and also leaves an office note."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name).resolve() / "repo"
        self.repo.mkdir()
        for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.com"],
                     ["config", "user.name", "T"]):
            subprocess.run(["git", "-C", str(self.repo), *args], check=True)
        (self.repo / "README.md").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-m", "init"], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def run_main_hook(self):
        payload = {"cwd": str(self.repo), "tool_name": "Write",
                   "tool_input": {"file_path": str(self.repo / "README.md"), "content": "y"}}
        env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")}
        return subprocess.run(["bash", str(HOOKS_DIR / "protect-main.sh")], input=json.dumps(payload),
                              capture_output=True, text=True, env=env)

    def test_deny_output_unchanged_and_note_written(self):
        (self.repo / ".devflow").mkdir()
        result = self.run_main_hook()
        self.assertEqual(result.returncode, 0, result.stderr)
        decision = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "deny")
        (event,) = _events(self.repo)
        self.assertEqual((event["kind"], event["hook"], event["path"]), ("deny", "protect-main", "README.md"))

    def test_deny_without_devflow_workspace_still_denies(self):
        result = self.run_main_hook()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertFalse((self.repo / ".devflow").exists())

    def test_every_guard_deny_helper_notes_the_office(self):
        for name in ("protect-main", "protect-sensitive-paths", "enforce-role-boundaries"):
            text = (HOOKS_DIR / f"{name}.sh").read_text(encoding="utf-8")
            self.assertIn(f'devflow_office_note "{name}" "$reason"', text, name)
            self.assertIn(">/dev/null 2>&1 || true", text, name)


class SnapshotTest(_TargetCase):
    def write_run(self, gates=None, statuses=None):
        devflow = self.target / ".devflow"
        (devflow / "runs").mkdir(exist_ok=True)
        (devflow / "project.json").write_text(json.dumps({"current_run_id": "RUN-007"}), encoding="utf-8")
        tasks = [{"id": "RUN-007-TASK-001", "title": "Delivery Planning", "assigned_role": "delivery-lead",
                  "task_type": "planning", "status": (statuses or {}).get("001", "planned"), "prompt": "x"}]
        run = {"run_id": "RUN-007", "req_id": "REQ-007", "objective": "REQ-007: test", "status": "in_progress",
               "tasks": tasks, "approval_gates": dict({"contract_approved": False}, **(gates or {})),
               "_signature": "abc"}
        (devflow / "runs" / "RUN-007.json").write_text(json.dumps(run), encoding="utf-8")

    def append(self, **event):
        log = self.target / ".devflow" / "office" / "events.jsonl"
        log.parent.mkdir(exist_ok=True)
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(dict({"ts": "2026-10-20T10:00:00.00Z"}, **event)) + "\n")

    def test_snapshot_reads_run_and_roster(self):
        self.write_run()
        snap = office.OfficeState(self.target).snapshot
        self.assertEqual(snap["run"]["run_id"], "RUN-007")
        self.assertEqual(snap["run"]["tasks"][0], {"id": "RUN-007-TASK-001", "title": "Delivery Planning",
                                                   "assigned_role": "delivery-lead", "status": "planned",
                                                   "task_type": "planning"})
        self.assertNotIn("_signature", json.dumps(snap))
        roster = {r["id"]: r for r in snap["roster"]}
        self.assertEqual(roster["security-red-team"]["model"], "opus")
        self.assertIn("task-routing", snap["skills"])

    def test_working_state_from_events(self):
        now = office.datetime.now(office.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.00Z")
        self.append(ts=now, kind="agent_start", agent="backend-engineer", agent_key="k1")
        self.append(ts=now, kind="skill", agent="backend-engineer", agent_key="k1", skill="tdd-vertical-slice")
        self.append(ts=now, kind="agent_start", agent="qa-automation", agent_key="k2")
        self.append(ts=now, kind="agent_stop", agent="qa-automation", agent_key="k2")
        agents = office.OfficeState(self.target).snapshot["agents"]
        self.assertTrue(agents["backend-engineer"]["working"])
        self.assertEqual(agents["backend-engineer"]["last_skill"], "tdd-vertical-slice")
        self.assertFalse(agents["qa-automation"]["working"])
        self.assertEqual(agents["qa-automation"]["runs"], 1)

    def test_stale_agent_is_not_working(self):
        self.append(ts="2020-01-01T00:00:00.00Z", kind="agent_start", agent="docs-writer", agent_key="k")
        self.assertFalse(office.OfficeState(self.target).snapshot["agents"]["docs-writer"]["working"])

    def test_delegation_events_fallback(self):
        folder = self.target / ".devflow" / "delegation-events"
        folder.mkdir()
        now = office.datetime.now(office.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        (folder / "a.json").write_text(json.dumps({"evidence_id": "a", "timestamp": now, "hook_event": "SubagentStart",
                                                   "lifecycle_state": "started", "agent_type": "contract-broker"}))
        snap = office.OfficeState(self.target).snapshot
        self.assertTrue(snap["agents"]["contract-broker"]["working"])
        self.assertFalse(snap["telemetry"])

    def test_real_windows_delegation_events(self):
        """Shape seen on a real session: namespaced agent_type, stops without agent_type."""
        folder = self.target / ".devflow" / "delegation-events"
        folder.mkdir()
        now = office.datetime.now(office.timezone.utc)
        rows = [("started", "devflow-plugin:product-analyst", 0), ("started", "devflow-plugin:solution-architect", 1),
                ("stopped", "unknown", 2), ("stopped", "unknown", 3)]
        for i, (state, agent, offset) in enumerate(rows):
            ts = (now + timedelta(seconds=offset)).strftime("%Y-%m-%dT%H:%M:%SZ")
            (folder / f"{i}.json").write_text(json.dumps({"evidence_id": str(i), "timestamp": ts,
                                                          "lifecycle_state": state, "agent_type": agent}))
        snap = office.OfficeState(self.target).snapshot
        # Anonymous stops outnumber starts on real sessions; they must not close
        # running agents or invent an "alt-ajan" desk.
        self.assertEqual([(e["kind"], e["agent"]) for e in snap["events"]],
                         [("agent_start", "product-analyst"), ("agent_start", "solution-architect")])
        self.assertTrue(snap["agents"]["product-analyst"]["working"])
        self.assertTrue(snap["agents"]["solution-architect"]["working"])
        self.assertNotIn("unknown", json.dumps(snap["agents"]))
        self.assertNotIn("alt-ajan", json.dumps(snap))

    def test_stop_without_agent_type_pairs_by_agent_key(self):
        now = office.datetime.now(office.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.00Z")
        self.append(ts=now, kind="agent_start", agent="devflow-plugin:qa-automation", agent_key="a")
        self.append(ts=now, kind="agent_start", agent="devflow-plugin:docs-writer", agent_key="b")
        self.append(ts=now, kind="skill", agent="devflow-plugin:docs-writer", skill="devflow-plugin:documentation-sync")
        self.append(ts=now, kind="agent_stop", agent_key="b")
        snap = office.OfficeState(self.target).snapshot
        self.assertEqual(snap["events"][-1]["agent"], "docs-writer")
        self.assertEqual(snap["events"][-2]["skill"], "documentation-sync")
        self.assertTrue(snap["agents"]["qa-automation"]["working"])
        self.assertFalse(snap["agents"]["docs-writer"]["working"])

    def test_duplicate_stop_closes_only_once_and_extra_is_dropped(self):
        now = office.datetime.now(office.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.00Z")
        self.append(ts=now, kind="agent_start", agent="contract-broker", agent_key="k1")
        self.append(ts=now, kind="agent_start", agent="solution-architect", agent_key="k2")
        self.append(ts=now, kind="agent_stop", agent_key="k1")
        self.append(ts=now, kind="agent_stop", agent_key="k1")
        self.append(ts=now, kind="agent_stop")
        snap = office.OfficeState(self.target).snapshot
        self.assertEqual([e["kind"] for e in snap["events"]], ["agent_start", "agent_start", "agent_stop"])
        self.assertTrue(snap["agents"]["solution-architect"]["working"])
        self.assertFalse(snap["agents"]["contract-broker"]["working"])

    def test_delegate_done_closes_agent_without_stop_event(self):
        now = office.datetime.now(office.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.00Z")
        self.append(ts=now, kind="agent_start", agent="devflow-plugin:docs-writer")
        self.append(ts=now, kind="delegate_done", subagent="devflow-plugin:docs-writer")
        snap = office.OfficeState(self.target).snapshot
        self.assertEqual(snap["events"][-1]["kind"], "agent_stop")
        self.assertEqual(snap["events"][-1]["agent"], "docs-writer")
        self.assertFalse(snap["agents"]["docs-writer"]["working"])

    def test_attention_opens_and_clears(self):
        now = office.datetime.now(office.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.00Z")
        self.append(ts=now, kind="tool", tool="Bash")
        self.append(ts=now, kind="attention", reason="permission", tool="Bash")
        snap = office.OfficeState(self.target).snapshot
        self.assertEqual((snap["attention"]["reason"], snap["attention"]["tool"]), ("permission", "Bash"))
        self.append(ts=now, kind="resume")
        self.assertIsNone(office.OfficeState(self.target).snapshot["attention"])
        self.append(ts=now, kind="attention", reason="turn_end")
        self.assertEqual(office.OfficeState(self.target).snapshot["attention"]["reason"], "turn_end")
        self.append(ts=now, kind="tool", tool="Read")
        self.assertIsNone(office.OfficeState(self.target).snapshot["attention"])

    def test_old_attention_is_ignored(self):
        self.append(ts="2020-01-01T00:00:00.00Z", kind="attention", reason="turn_end")
        self.assertIsNone(office.OfficeState(self.target).snapshot["attention"])

    def test_roster_lists_preloaded_skills(self):
        roster = {r["id"]: r for r in office.OfficeState(self.target).snapshot["roster"]}
        self.assertIn("tdd-vertical-slice", roster["backend-engineer"]["skills"])
        self.assertEqual(roster["contract-broker"]["skills"], ["api-contract-design"])
        self.assertEqual(roster["governance-operations-author"]["skills"], [])

    def test_gate_and_task_changes_become_events(self):
        self.write_run()
        state = office.OfficeState(self.target)
        self.write_run(gates={"contract_approved": True}, statuses={"001": "in_progress"})
        self.assertTrue(state.refresh())
        kinds = {e["kind"]: e for e in state.snapshot["events"]}
        self.assertEqual(kinds["gate"]["gate"], "contract_approved")
        self.assertEqual((kinds["task"]["from"], kinds["task"]["status"]), ("planned", "in_progress"))
        self.assertFalse(state.refresh())


class ServerTest(_TargetCase):
    def test_serves_page_and_snapshot(self):
        multi = office.MultiOffice([self.target], use_registry=False, use_remotes=False)
        server, base = _serve(office.make_handler(multi))
        try:
            page = urllib.request.urlopen(base + "/").read().decode("utf-8")
            self.assertIn("DevFlow Ofis", page)
            self.assertIn("api/stream", page)
            snap = json.loads(urllib.request.urlopen(base + "/api/snapshot").read())
            (project,) = snap["projects"]
            self.assertEqual((project["name"], project["remote"], project["reachable"]), ("proj", False, True))
            self.assertEqual(snap["offices"][project["id"]]["target"], "proj")
            self.assertIsNone(snap["offices"][project["id"]]["run"])
        finally:
            server.shutdown()
            server.server_close()

    def test_stream_sends_snapshot_then_named_ping(self):
        multi = office.MultiOffice([self.target], use_registry=False, use_remotes=False)
        server, base = _serve(office.make_handler(multi))
        try:
            resp = urllib.request.urlopen(base + "/api/stream", timeout=15)
            self.assertTrue(resp.readline().startswith(b"data: {"))
            lines = [resp.readline() for _ in range(3)]
            self.assertIn(b"event: ping\n", lines)
            resp.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_refuses_non_local_host(self):
        self.assertEqual(office.main(["--host", "0.0.0.0", "--no-open"]), 2)

    def test_share_endpoint_requires_token_and_shares_local_offices_only(self):
        multi = office.MultiOffice([self.target], use_registry=False, use_remotes=False)
        server, base = _serve(office.make_handler(multi, token="s3cret-token-value-123"))
        try:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(base + office.SHARE_PATH)
            self.assertEqual(ctx.exception.code, 401)
            bad = urllib.request.Request(base + office.SHARE_PATH, headers={"X-DevFlow-Token": "wrong"})
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(bad)
            self.assertEqual(ctx.exception.code, 401)
            good = urllib.request.Request(base + office.SHARE_PATH, headers={"X-DevFlow-Token": "s3cret-token-value-123"})
            data = json.loads(urllib.request.urlopen(good).read())
            self.assertEqual([o["name"] for o in data["offices"]], ["proj"])
            self.assertIn("events", data["offices"][0]["snapshot"])
        finally:
            server.shutdown()
            server.server_close()

    def test_share_endpoint_closed_without_share_mode(self):
        multi = office.MultiOffice([self.target], use_registry=False, use_remotes=False)
        server, base = _serve(office.make_handler(multi))
        try:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(base + office.SHARE_PATH)
            self.assertEqual(ctx.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()

    def test_lan_and_loopback_checks(self):
        for address in ("127.0.0.1", "::1", "192.168.1.20", "10.0.0.5", "172.16.4.1", "::ffff:192.168.1.9",
                        "fe80::1%en0", "169.254.10.1"):
            self.assertTrue(office.is_lan_client(address), address)
        for address in ("8.8.8.8", "1.1.1.1", "2606:4700::1111", "not-an-ip"):
            self.assertFalse(office.is_lan_client(address), address)
        self.assertTrue(office.is_loopback_client("::ffff:127.0.0.1"))
        self.assertFalse(office.is_loopback_client("192.168.1.20"))

    def test_remote_url(self):
        self.assertEqual(office.remote_url("mac.local"), "http://mac.local:4646/api/share")
        self.assertEqual(office.remote_url("192.168.1.5:4700"), "http://192.168.1.5:4700/api/share")
        self.assertEqual(office.remote_url("http://mac.local/"), "http://mac.local:4646/api/share")

    def test_remote_office_becomes_tabs_and_marks_unreachable(self):
        sharer = office.MultiOffice([self.target], use_registry=False, use_remotes=False)
        server, base = _serve(office.make_handler(sharer, token="tok-tok-tok-tok-tok-1"))
        port = server.server_address[1]
        office.save_remote(f"127.0.0.1:{port}", "tok-tok-tok-tok-tok-1")
        try:
            watcher = office.MultiOffice([], use_registry=False)
            for feed in watcher.feeds.values():
                feed.poll()
            watcher.refresh()
            remote = [p for p in watcher.snapshot["projects"] if p["remote"]]
            self.assertEqual([(p["name"], p["reachable"]) for p in remote], [("proj", True)])
            self.assertIn(remote[0]["id"], watcher.snapshot["offices"])
        finally:
            server.shutdown()
            server.server_close()
        for feed in watcher.feeds.values():
            feed.poll()
        watcher.refresh()
        remote = [p for p in watcher.snapshot["projects"] if p["remote"]]
        self.assertEqual([(p["reachable"], p["error"]) for p in remote], [(False, "ulaşılamıyor")])
        self.assertTrue(office.forget_remote(f"127.0.0.1:{port}"))
        self.assertEqual(office.read_remotes(), [])

    def test_wrong_token_is_reported(self):
        sharer = office.MultiOffice([self.target], use_registry=False, use_remotes=False)
        server, base = _serve(office.make_handler(sharer, token="right-token-right-token"))
        try:
            feed = office.RemoteFeed(f"127.0.0.1:{server.server_address[1]}", "wrong-token")
            feed.poll()
            self.assertEqual((feed.ok, feed.error), (False, "token geçersiz"))
        finally:
            server.shutdown()
            server.server_close()

    def test_registry_projects_become_tabs(self):
        other = self.target.parent / "Z-PmApp"
        (other / ".devflow").mkdir(parents=True)
        stale = self.target.parent / "eski"
        (stale / ".devflow").mkdir(parents=True)
        recorder.note_project(other)
        recorder.note_project(stale, now=time.time() - 13 * 3600)
        multi = office.MultiOffice([self.target], use_remotes=False)
        names = [p["name"] for p in multi.snapshot["projects"]]
        self.assertEqual(names[0], "proj")
        self.assertIn("Z-PmApp", names)
        self.assertNotIn("eski", names)

    def test_share_token_is_kept_until_renewed(self):
        first = office.share_token()
        self.assertEqual(office.share_token(), first)
        self.assertNotEqual(office.share_token(new=True), first)

    def test_demo_script_runs_to_completion(self):
        demo = office.Demo()
        try:
            demo.reset()
            for step in office.DEMO_SCRIPT:
                demo.apply(step)
            snap = office.OfficeState(demo.target).snapshot
            self.assertTrue(all(snap["run"]["approval_gates"].values()))
            self.assertFalse(any(v["working"] for v in snap["agents"].values()))
            self.assertTrue(any(e["kind"] == "deny" for e in snap["events"]))
        finally:
            demo.cleanup()


class PluginWiringTest(unittest.TestCase):
    def test_recorder_registered_async(self):
        hooks = json.loads(PLUGIN_HOOKS.read_text(encoding="utf-8"))["hooks"]

        def recorder_entries(event):
            return [h for group in hooks[event] for h in group["hooks"] if "devflow_office_recorder.py" in h["command"]]

        for event in ("SubagentStart", "SubagentStop", "PreToolUse"):
            entries = recorder_entries(event)
            self.assertEqual(len(entries), 1, event)
            self.assertTrue(entries[0].get("async"), event)
        matcher = next(g["matcher"] for g in hooks["PreToolUse"]
                       if any("devflow_office_recorder.py" in h["command"] for h in g["hooks"]))
        for tool in ("Skill", "Agent", "Task", "Edit", "Write", "Bash", "AskUserQuestion", "ExitPlanMode"):
            self.assertIn(tool, matcher.split("|"))
        for event in ("PostToolUse", "Notification", "Stop", "UserPromptSubmit"):
            entries = recorder_entries(event)
            self.assertEqual(len(entries), 1, event)
            self.assertTrue(entries[0].get("async"), event)

    def test_plugin_build_ships_recorder(self):
        tmp = tempfile.mkdtemp()
        try:
            subprocess.run([sys.executable, str(SCRIPTS / "build_devflow_plugin.py"), "--output-dir", tmp],
                           check=True, capture_output=True, cwd=str(REPO_ROOT))
            self.assertTrue((Path(tmp) / "devflow-plugin" / "scripts" / "devflow_office_recorder.py").is_file())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_cli_has_office_command(self):
        text = (REPO_ROOT / "bin" / "claude-devflow").read_text(encoding="utf-8")
        self.assertIn("devflow_office.py", text)
        result = subprocess.run(["sh", str(REPO_ROOT / "bin" / "claude-devflow"), "--help"],
                                capture_output=True, text=True, env=dict(os.environ, DEVFLOW_HOME=str(REPO_ROOT)))
        self.assertIn("claude-devflow office", result.stdout)


if __name__ == "__main__":
    unittest.main()
