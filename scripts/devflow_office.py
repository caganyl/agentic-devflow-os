#!/usr/bin/env python3
"""
DevFlow Ofis — canlı ofis görünümü.

Bir target projenin .devflow/ çalışma alanını okur ve ajan ekibini bir ofis
olarak gösteren yerel bir sayfa sunar: kim çalışıyor, hangi skill'i aldı,
handoff'lar, onay kapıları ve hook engelleri.

    python3 scripts/devflow_office.py [--target PATH] [--port 4646] [--no-open]
    python3 scripts/devflow_office.py --demo        # örnek run'ı canlı oynatır
    claude-devflow office [--demo] [--port N]       # aynı şey, bulunulan proje için

Veri kaynakları (yalnızca okunur, hiçbir şey yazılmaz):
    .devflow/project.json              current_run_id
    .devflow/runs/<RUN>.json           task'lar, approval_gates (imza doğrulanmaz;
                                       görünüm yalnızca gösterir, karar vermez)
    .devflow/office/events.jsonl       devflow_office_recorder.py telemetrisi
    .devflow/delegation-events/*.json  office telemetrisi yoksa start/stop yedeği

Sunucu yalnızca 127.0.0.1'e bağlanır ve yalnızca standart kütüphane kullanır.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import threading
import time
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
UI_FILE = Path(__file__).resolve().parent / "devflow_office_ui.html"
MAX_EVENTS = 300
STALE_AGENT_SECONDS = 20 * 60
POLL_SECONDS = 0.5
MAIN = "@main"

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---", re.S)


# ---------------------------------------------------------------------------
# readers
# ---------------------------------------------------------------------------

def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_ts(value) -> float:
    if not isinstance(value, str):
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def read_roster(*agent_dirs: Path) -> list[dict]:
    """Agent name/model/color from frontmatter; later dirs override earlier ones."""
    roster: dict[str, dict] = {}
    for agent_dir in agent_dirs:
        if not agent_dir.is_dir():
            continue
        for md in sorted(agent_dir.glob("*.md")):
            match = _FRONTMATTER.match(md.read_text(encoding="utf-8", errors="replace"))
            if not match:
                continue
            fields = {}
            for line in match.group(1).splitlines():
                if ":" in line and not line.startswith((" ", "-")):
                    k, v = line.split(":", 1)
                    fields[k.strip()] = v.strip().strip("\"'")
            name = fields.get("name") or md.stem
            roster[name] = {
                "id": name,
                "model": (fields.get("model") or "inherit").lower(),
                "color": (fields.get("color") or "").lower(),
            }
    return list(roster.values())


def read_skills(*skill_dirs: Path) -> list[str]:
    names = set()
    for skill_dir in skill_dirs:
        if skill_dir.is_dir():
            names.update(p.parent.name for p in skill_dir.glob("*/SKILL.md"))
    return sorted(names)


def read_office_events(devflow: Path) -> list[dict]:
    log = devflow / "office" / "events.jsonl"
    if not log.is_file():
        return []
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()[-MAX_EVENTS:]
    except OSError:
        return []
    events = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and isinstance(event.get("kind"), str):
            event["id"] = hashlib.sha1(line.encode("utf-8")).hexdigest()[:12]
            events.append(event)
    return events


def read_delegation_events(devflow: Path) -> list[dict]:
    events = []
    folder = devflow / "delegation-events"
    if not folder.is_dir():
        return events
    for path in sorted(folder.glob("*.json")):
        data = _read_json(path)
        if not isinstance(data, dict):
            continue
        state = data.get("lifecycle_state")
        kind = {"started": "agent_start", "stopped": "agent_stop"}.get(state)
        if not kind:
            continue
        events.append({
            "id": str(data.get("evidence_id", path.stem))[:12],
            "ts": data.get("timestamp", ""),
            "kind": kind,
            "agent": data.get("agent_type", "unknown"),
            "source": "delegation",
        })
    events.sort(key=lambda e: _parse_ts(e["ts"]))
    return events[-MAX_EVENTS:]


def read_run(devflow: Path) -> dict | None:
    project = _read_json(devflow / "project.json") or {}
    run_id = project.get("current_run_id")
    run_file = devflow / "runs" / f"{run_id}.json" if isinstance(run_id, str) and run_id else None
    if run_file is None or not run_file.is_file():
        runs = sorted((devflow / "runs").glob("RUN-*.json"), key=lambda p: p.stat().st_mtime) if (devflow / "runs").is_dir() else []
        run_file = runs[-1] if runs else None
    data = _read_json(run_file) if run_file else None
    if not isinstance(data, dict):
        return None
    tasks = []
    for task in data.get("tasks", []) or []:
        if isinstance(task, dict):
            tasks.append({k: task.get(k) for k in ("id", "title", "assigned_role", "status", "task_type")})
    gates = data.get("approval_gates") if isinstance(data.get("approval_gates"), dict) else {}
    return {
        "run_id": data.get("run_id"),
        "req_id": data.get("req_id") or "",
        "objective": (data.get("objective") or "")[:160],
        "status": data.get("status") or "",
        "created_at": data.get("created_at") or "",
        "tasks": tasks,
        "approval_gates": {k: bool(v) for k, v in gates.items()},
    }


# ---------------------------------------------------------------------------
# derived state
# ---------------------------------------------------------------------------

def derive_agents(events: list[dict], now: float) -> dict:
    """Per-agent live state from the ordered event stream."""
    active: dict[str, dict] = {}
    info: dict[str, dict] = {}

    def slot(name):
        return info.setdefault(name, {"working": False, "since": None, "last": None,
                                      "last_skill": None, "runs": 0, "last_ts": 0.0})

    for event in events:
        ts = _parse_ts(event.get("ts"))
        kind = event.get("kind")
        agent = event.get("agent") or MAIN
        key = event.get("agent_key") or agent
        if kind == "agent_start":
            active[key] = {"agent": agent, "since": event.get("ts"), "ts": ts}
        elif kind == "agent_stop":
            if key not in active:
                key = next((k for k, v in active.items() if v["agent"] == agent), key)
            active.pop(key, None)
            slot(agent)["runs"] += 1
        elif kind == "skill":
            slot(agent)["last_skill"] = event.get("skill")
        if kind in ("tool", "skill", "deny"):
            slot(agent)["last"] = {"kind": kind, "tool": event.get("tool"), "path": event.get("path"),
                                   "skill": event.get("skill"), "ts": event.get("ts")}
        if agent in active or kind in ("agent_start", "tool", "skill"):
            slot(agent)["last_ts"] = max(slot(agent)["last_ts"], ts)
        for entry in active.values():
            if entry["agent"] == agent:
                entry["ts"] = max(entry["ts"], ts)

    for entry in active.values():
        if now - entry["ts"] > STALE_AGENT_SECONDS:
            continue
        s = slot(entry["agent"])
        s["working"] = True
        s["since"] = s["since"] or entry["since"]
    for s in info.values():
        s.pop("last_ts", None)
    return info


class OfficeState:
    """Polls the target's .devflow/ and keeps a versioned snapshot."""

    def __init__(self, target: Path):
        self.target = target
        self.devflow = target / ".devflow"
        self.roster = read_roster(FRAMEWORK_ROOT / ".claude" / "agents", FRAMEWORK_ROOT / "agents",
                                  target / ".claude" / "agents")
        self.skills = read_skills(FRAMEWORK_ROOT / ".claude" / "skills", FRAMEWORK_ROOT / "skills",
                                  target / ".claude" / "skills")
        self.cond = threading.Condition()
        self.version = 0
        self.snapshot: dict = {}
        self._digest = ""
        self._prev_run: dict | None = None
        self._synthetic: list[dict] = []
        self.refresh()

    def _diff_run(self, run: dict | None) -> None:
        prev, now_iso = self._prev_run, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-4] + "Z"
        if run and prev and prev.get("run_id") == run.get("run_id"):
            before = {t["id"]: t.get("status") for t in prev.get("tasks", [])}
            for task in run["tasks"]:
                if task["id"] in before and before[task["id"]] != task.get("status"):
                    self._synthetic.append({"ts": now_iso, "kind": "task", "task": task["id"],
                                            "title": task.get("title"), "role": task.get("assigned_role"),
                                            "status": task.get("status"), "from": before[task["id"]]})
            for gate, value in run["approval_gates"].items():
                if value and not prev["approval_gates"].get(gate):
                    self._synthetic.append({"ts": now_iso, "kind": "gate", "gate": gate})
        elif run and (prev is None or prev.get("run_id") != run.get("run_id")) and self.version > 0:
            self._synthetic.append({"ts": now_iso, "kind": "run", "run": run.get("run_id")})
        for i, event in enumerate(self._synthetic[-60:]):
            event.setdefault("id", hashlib.sha1(json.dumps(event, sort_keys=True).encode()).hexdigest()[:12])
        self._synthetic = self._synthetic[-60:]
        self._prev_run = run

    def refresh(self) -> bool:
        run = read_run(self.devflow)
        self._diff_run(run)
        office = read_office_events(self.devflow)
        has_lifecycle = any(e.get("kind") in ("agent_start", "agent_stop") for e in office)
        events = office + ([] if has_lifecycle else read_delegation_events(self.devflow)) + list(self._synthetic)
        events.sort(key=lambda e: _parse_ts(e.get("ts")))
        events = events[-MAX_EVENTS:]
        body = {
            "target": self.target.name,
            "initialized": self.devflow.is_dir(),
            "telemetry": (self.devflow / "office" / "events.jsonl").is_file(),
            "run": run,
            "roster": self.roster,
            "skills": self.skills,
            "agents": derive_agents(events, time.time()),
            "events": events[-120:],
        }
        digest = hashlib.sha1(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
        if digest == self._digest:
            return False
        with self.cond:
            self._digest = digest
            self.version += 1
            self.snapshot = dict(body, version=self.version)
            self.cond.notify_all()
        return True

    def watch(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                self.refresh()
            except Exception as exc:  # keep serving the last good snapshot
                print(f"devflow-office: okuma hatası: {exc}", file=sys.stderr)
            stop.wait(POLL_SECONDS)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def make_handler(state: OfficeState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "DevFlowOffice/1"

        def log_message(self, *args):  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                self._send(200, UI_FILE.read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/snapshot":
                with state.cond:
                    body = json.dumps(state.snapshot, ensure_ascii=False).encode("utf-8")
                self._send(200, body, "application/json; charset=utf-8")
            elif path == "/api/stream":
                self._stream()
            else:
                self._send(404, b"not found", "text/plain")

        def _stream(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            seen = -1
            try:
                while True:
                    with state.cond:
                        if state.version == seen:
                            state.cond.wait(timeout=10)
                        version, snap = state.version, state.snapshot
                    if version != seen:
                        seen = version
                        payload = json.dumps(snap, ensure_ascii=False)
                        self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    else:
                        self.wfile.write(b"event: ping\ndata: {}\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

    return Handler


# ---------------------------------------------------------------------------
# demo
# ---------------------------------------------------------------------------

DEMO_TASKS = [
    ("001", "Delivery Planning", "planning", "delivery-lead"),
    ("002", "Acceptance Criteria Review", "planning", "product-analyst"),
    ("004", "Contract Definition", "contract_definition", "contract-broker"),
    ("005", "Backend Implementation", "implementation", "backend-engineer"),
    ("006", "Frontend Implementation", "implementation", "frontend-engineer"),
    ("007", "QA Test Suite", "qa", "qa-automation"),
    ("008", "Security Review", "security_review", "security-red-team"),
    ("010", "Documentation", "documentation", "docs-writer"),
    ("009", "Integration and Release Scorecard", "release", "integration-release"),
]

# (seconds, action, args...) — the same flow the sample video showed.
DEMO_SCRIPT = [
    (1.0, "task", "001", "in_progress"), (1.2, "delegate", "delivery-lead"), (1.6, "start", "delivery-lead"),
    (2.6, "skill", "delivery-lead", "task-routing"), (4.0, "tool", "delivery-lead", "Read", "docs/product/requirements/REQ-042.md"),
    (6.0, "stop", "delivery-lead"), (6.3, "task", "001", "completed"),
    (7.0, "task", "002", "in_progress"), (7.2, "delegate", "product-analyst"), (7.6, "start", "product-analyst"),
    (8.4, "skill", "product-analyst", "requirement-grilling"), (10.0, "tool", "product-analyst", "Write", "docs/product/acceptance-criteria/AC-042.md"),
    (12.0, "stop", "product-analyst"), (12.3, "task", "002", "completed"),
    (13.0, "task", "004", "in_progress"), (13.2, "delegate", "contract-broker"), (13.6, "start", "contract-broker"),
    (14.4, "skill", "contract-broker", "api-contract-design"), (16.0, "tool", "contract-broker", "Write", "docs/contracts/openapi/profile.yaml"),
    (17.6, "stop", "contract-broker"), (17.8, "task", "004", "completed"), (18.0, "gate", "contract_approved"),
    (18.6, "task", "005", "in_progress"), (18.6, "task", "006", "in_progress"),
    (18.8, "delegate", "backend-engineer"), (19.0, "start", "backend-engineer"),
    (19.2, "delegate", "frontend-engineer"), (19.4, "start", "frontend-engineer"),
    (20.0, "skill", "backend-engineer", "tdd-vertical-slice"), (20.4, "skill", "frontend-engineer", "tdd-vertical-slice"),
    (22.0, "tool", "backend-engineer", "Write", "src/Api/Profile/ProfileController.cs"),
    (22.6, "tool", "frontend-engineer", "Write", "web/app/profile/page.tsx"),
    (24.0, "deny", "frontend-engineer", "enforce-role-boundaries", "src/Api/Profile/ProfileDto.cs",
     "Ownership-manifest protection: path is outside frontend-engineer's write paths"),
    (25.4, "tool", "backend-engineer", "Bash", ""), (26.4, "tool", "frontend-engineer", "Edit", "web/app/profile/ProfileForm.tsx"),
    (28.0, "stop", "backend-engineer"), (28.2, "task", "005", "completed"),
    (29.0, "stop", "frontend-engineer"), (29.2, "task", "006", "completed"), (29.4, "gate", "tests_passing"),
    (30.0, "task", "007", "in_progress"), (30.2, "delegate", "qa-automation"), (30.6, "start", "qa-automation"),
    (31.4, "skill", "qa-automation", "qa-acceptance-verification"), (32.6, "tool", "qa-automation", "Bash", ""),
    (34.6, "stop", "qa-automation"), (34.8, "task", "007", "completed"), (35.0, "gate", "qa_sign_off"),
    (35.6, "task", "008", "in_progress"), (35.8, "delegate", "security-red-team"), (36.2, "start", "security-red-team"),
    (37.0, "skill", "security-red-team", "adversarial-security-review"), (38.4, "tool", "security-red-team", "Grep", ""),
    (40.0, "stop", "security-red-team"), (40.2, "task", "008", "completed"), (40.4, "gate", "security_review_complete"),
    (41.0, "task", "010", "in_progress"), (41.2, "delegate", "docs-writer"), (41.6, "start", "docs-writer"),
    (42.4, "skill", "docs-writer", "documentation-sync"), (43.6, "tool", "docs-writer", "Edit", "README.md"),
    (45.0, "stop", "docs-writer"), (45.2, "task", "010", "completed"),
    (46.0, "task", "009", "in_progress"), (46.2, "delegate", "integration-release"), (46.6, "start", "integration-release"),
    (47.4, "skill", "integration-release", "release-scorecard"), (48.6, "tool", "integration-release", "Write", ".devflow/reports/RUN-042-scorecard.md"),
    (50.6, "stop", "integration-release"), (50.8, "task", "009", "awaiting_human_approval"),
    (55.0, "gate", "human_approval"), (55.2, "task", "009", "verified"),
]
DEMO_LOOP_SECONDS = 64.0


class Demo:
    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="devflow-office-demo-"))
        self.target = self.root / "ornek-proje"
        self.devflow = self.target / ".devflow"
        self._keys: dict[str, str] = {}

    def _now(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-4] + "Z"

    def reset(self) -> None:
        shutil.rmtree(self.devflow, ignore_errors=True)
        (self.devflow / "runs").mkdir(parents=True)
        (self.devflow / "office").mkdir()
        (self.devflow / "project.json").write_text(json.dumps({"current_run_id": "RUN-042"}), encoding="utf-8")
        self.run = {
            "run_id": "RUN-042", "req_id": "REQ-042", "objective": "REQ-042: Kullanıcı profil sayfası",
            "status": "in_progress", "created_at": self._now(),
            "tasks": [{"id": f"RUN-042-TASK-{s}", "title": t, "task_type": tt, "assigned_role": r, "status": "planned"}
                      for s, t, tt, r in DEMO_TASKS],
            "approval_gates": {g: False for g in ("contract_approved", "tests_passing", "security_review_complete",
                                                  "qa_sign_off", "human_approval")},
        }
        self._write_run()

    def _write_run(self) -> None:
        path = self.devflow / "runs" / "RUN-042.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.run, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def _event(self, **fields) -> None:
        with (self.devflow / "office" / "events.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(dict(ts=self._now(), **fields), ensure_ascii=False) + "\n")

    def _key(self, agent: str, new: bool = False) -> str:
        if new or agent not in self._keys:
            self._keys[agent] = hashlib.sha256(f"{agent}{time.time()}".encode()).hexdigest()[:10]
        return self._keys[agent]

    def apply(self, step: tuple) -> None:
        action, args = step[1], step[2:]
        if action == "task":
            for task in self.run["tasks"]:
                if task["id"].endswith(args[0]):
                    task["status"] = args[1]
            self._write_run()
        elif action == "gate":
            self.run["approval_gates"][args[0]] = True
            if args[0] == "human_approval":
                self.run["status"] = "completed"
            self._write_run()
        elif action == "delegate":
            self._event(kind="delegate", subagent=args[0])
        elif action == "start":
            self._event(kind="agent_start", agent=args[0], agent_key=self._key(args[0], new=True))
        elif action == "stop":
            self._event(kind="agent_stop", agent=args[0], agent_key=self._key(args[0]))
        elif action == "skill":
            self._event(kind="skill", agent=args[0], agent_key=self._key(args[0]), skill=args[1])
        elif action == "tool":
            fields = dict(kind="tool", agent=args[0], agent_key=self._key(args[0]), tool=args[1])
            if args[2]:
                fields["path"] = args[2]
            self._event(**fields)
        elif action == "deny":
            self._event(kind="deny", agent=args[0], agent_key=self._key(args[0]), hook=args[1],
                        tool="Write", path=args[2], reason=args[3])

    def run_forever(self, stop: threading.Event) -> None:
        while not stop.is_set():
            self.reset()
            start = time.time()
            for step in DEMO_SCRIPT:
                if stop.wait(max(0.0, start + step[0] - time.time())):
                    return
                self.apply(step)
            stop.wait(max(0.0, start + DEMO_LOOP_SECONDS - time.time()))

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="DevFlow Ofis — canlı ofis görünümü")
    parser.add_argument("--target", default=".", help="Target proje kökü (varsayılan: bulunulan klasör)")
    parser.add_argument("--port", type=int, default=4646)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--demo", action="store_true", help="Örnek bir run'ı canlı oynat")
    parser.add_argument("--no-open", action="store_true", help="Tarayıcıyı otomatik açma")
    args = parser.parse_args(argv)

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("devflow-office: yalnızca yerel adrese bağlanır (127.0.0.1).", file=sys.stderr)
        return 2

    stop = threading.Event()
    demo = None
    if args.demo:
        demo = Demo()
        demo.reset()
        target = demo.target
        threading.Thread(target=demo.run_forever, args=(stop,), daemon=True).start()
    else:
        target = Path(args.target).resolve()
        if not (target / ".devflow").is_dir():
            print(f"Uyarı: {target} içinde .devflow/ yok. DevFlow bu projede başlatıldığında ofis canlanır.",
                  file=sys.stderr)

    state = OfficeState(target)
    threading.Thread(target=state.watch, args=(stop,), daemon=True).start()
    try:
        server = ThreadingHTTPServer((args.host, args.port), make_handler(state))
    except OSError as exc:
        print(f"devflow-office: {args.host}:{args.port} açılamadı ({exc}). --port ile başka port deneyin.",
              file=sys.stderr)
        return 1
    server.daemon_threads = True
    url = f"http://{args.host}:{args.port}/"
    print(f"DevFlow Ofis: {url}  ({'demo' if demo else target})  — durdurmak için Ctrl+C")
    if not args.no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
        if demo:
            demo.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
