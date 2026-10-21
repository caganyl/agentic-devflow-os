"""scripts/devflow_code_map.py (Graphify wrapper) and the role hook's
read-only code map allowance.

A stand-in `graphify` records how it was called, so the tests run without
Graphify installed. One integration test uses a real graphify 0.9.93 when
DEVFLOW_GRAPHIFY_BIN points at it (skipped otherwise)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_hook_hardening_hooks import _HookCase  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "devflow_code_map.py"
MAP_REL = Path(".devflow") / "cache" / "code-map"

FAKE_GRAPHIFY = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
log = Path(os.environ["FAKE_GRAPHIFY_LOG"])
calls = json.loads(log.read_text()) if log.exists() else []
calls.append({"argv": sys.argv[1:], "env": {k: os.environ.get(k) for k in
              ("GRAPHIFY_BACKEND", "GRAPHIFY_NO_AUTO_REFRESH", "GRAPHIFY_OUT",
               "OPENAI_API_KEY", "GEMINI_API_KEY", "PATH")}})
log.write_text(json.dumps(calls))
if sys.argv[1:] == ["--version"]:
    print("graphify " + os.environ.get("FAKE_GRAPHIFY_VERSION", "0.9.93"))
elif sys.argv[1] == "update":
    out = Path(os.environ["GRAPHIFY_OUT"])
    out.mkdir(parents=True, exist_ok=True)
    (out / "graph.json").write_text("{}")
    print("[graphify watch] Rebuilt: 3 nodes, 2 edges, 1 communities")
else:
    print("ANSWER " + " ".join(sys.argv[1:]))
'''


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


class CodeMapWrapperTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.root = base / "proj"
        self.root.mkdir()
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@example.com")
        git(self.root, "config", "user.name", "T")
        (self.root / "Order.cs").write_text("public sealed class Order {}\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "init")
        self.fake = base / "graphify"
        self.fake.write_text(FAKE_GRAPHIFY, encoding="utf-8")
        self.fake.chmod(0o755)
        self.log = base / "calls.json"

    def tearDown(self):
        self.tmp.cleanup()

    def run_map(self, *args, cwd=None, **env):
        run_env = dict(os.environ, DEVFLOW_GRAPHIFY_BIN=str(self.fake),
                       FAKE_GRAPHIFY_LOG=str(self.log))
        run_env.update(env)
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=str(cwd or self.root),
                              capture_output=True, text=True, env=run_env)

    def calls(self):
        return json.loads(self.log.read_text()) if self.log.exists() else []

    def build(self, **env):
        result = self.run_map("build", **env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_status_and_queries_without_map(self):
        self.assertEqual(self.run_map("status").returncode, 2)
        result = self.run_map("affected", "Order")
        self.assertEqual(result.returncode, 2)
        self.assertIn("claude-devflow map", result.stderr)
        self.assertEqual(self.calls(), [], "no graphify call without a map")

    def test_missing_graphify(self):
        result = self.run_map("build", DEVFLOW_GRAPHIFY_BIN=str(self.root / "nope"))
        self.assertEqual(result.returncode, 3)
        self.assertIn("graphifyy==0.9.93", result.stderr)

    def test_build_runs_ast_only_inside_devflow_cache(self):
        result = self.build(OPENAI_API_KEY="sk-x", GEMINI_API_KEY="g-x")
        self.assertIn("3 nodes", result.stdout)
        update = [c for c in self.calls() if c["argv"][0] == "update"][0]
        self.assertEqual(update["argv"], ["update", str(self.root)])
        env = update["env"]
        self.assertEqual(env["GRAPHIFY_BACKEND"], "none")
        self.assertEqual(env["GRAPHIFY_NO_AUTO_REFRESH"], "1")
        self.assertEqual(env["GRAPHIFY_OUT"], str(self.root / MAP_REL))
        self.assertIsNone(env["OPENAI_API_KEY"])
        self.assertIsNone(env["GEMINI_API_KEY"])
        self.assertIn("cache/", (self.root / ".devflow" / ".gitignore").read_text().split())
        self.assertTrue((self.root / MAP_REL / "graph.json").is_file())

    def test_version_mismatch_warns_but_builds(self):
        result = self.build(FAKE_GRAPHIFY_VERSION="1.0.0")
        self.assertIn("0.9.93 ile test edildi", result.stderr)

    def test_read_commands_pass_graph_and_limits(self):
        self.build()
        graph = str(self.root / MAP_REL / "graph.json")
        cases = [
            (("affected", "Order", "--depth", "3"), ["affected", "Order", "--graph", graph, "--depth", "3"]),
            (("explain", "Order"), ["explain", "Order", "--graph", graph]),
            (("path", "A", "B"), ["path", "A", "B", "--graph", graph]),
            (("query", "who saves orders"), ["query", "who saves orders", "--graph", graph, "--budget", "1500"]),
            (("query", "x", "--budget", "500"), ["query", "x", "--graph", graph, "--budget", "500"]),
        ]
        for args, expected in cases:
            with self.subTest(args=args):
                result = self.run_map(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.calls()[-1]["argv"], expected)

    def test_finds_repo_root_from_subfolder(self):
        self.build()
        sub = self.root / "src"
        sub.mkdir()
        result = self.run_map("explain", "Order", cwd=sub)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(self.root / MAP_REL / "graph.json"), self.calls()[-1]["argv"])

    def test_status_reports_stale_after_edit_and_commit(self):
        self.build()
        self.assertIn("güncel", self.run_map("status").stdout)
        os.utime(self.root / MAP_REL / "graph.json", (1, 1))
        (self.root / "Order.cs").write_text("public sealed class Order { int Id; }\n")
        self.assertIn("eski", self.run_map("status").stdout)
        self.assertIn("eski", self.run_map("explain", "Order").stderr)


@unittest.skipUnless(os.environ.get("DEVFLOW_GRAPHIFY_BIN"), "needs a real graphify (DEVFLOW_GRAPHIFY_BIN)")
class RealGraphifyTest(unittest.TestCase):
    """C# DI dispatch and TS alias edges, end to end with the pinned Graphify."""

    def test_affected_crosses_di_and_ts_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git(root, "init", "-q")
            (root / "Svc.cs").write_text(
                "public interface IRepo { int Get(); }\n"
                "public sealed class Svc { private readonly IRepo _r;\n"
                "  public Svc(IRepo r) { _r = r; }\n  public int Total() { return _r.Get(); } }\n")
            (root / "web").mkdir()
            (root / "web" / "tsconfig.json").write_text('{"compilerOptions":{"baseUrl":".","paths":{"@/*":["src/*"]}}}')
            (root / "web" / "src").mkdir()
            (root / "web" / "src" / "api.ts").write_text("export function load() { return 1; }\n")
            (root / "web" / "src" / "View.tsx").write_text(
                'import { load } from "@/api";\nexport function View() { load(); return null; }\n')
            run = lambda *a: subprocess.run([sys.executable, str(SCRIPT), *a], cwd=tmp,  # noqa: E731
                                            capture_output=True, text=True)
            self.assertEqual(run("build").returncode, 0)
            self.assertIn("Svc", run("affected", "IRepo").stdout)
            self.assertIn("View", run("affected", "load").stdout)


class CodeMapHookTest(_HookCase):
    """security-red-team and architecture-analyst may run read-only map queries only."""

    PLUGIN = "/opt/devflow-plugin"
    REAL = PLUGIN + "/scripts/devflow_code_map.py"

    def bash_env(self, agent, command):
        return self.bash(agent, command, env_extra={"DEVFLOW_PLUGIN_ROOT": self.PLUGIN})

    def test_read_queries_allowed(self):
        for agent in ("security-red-team", "architecture-analyst"):
            for command in ('python3 "$DEVFLOW_CODE_MAP_SCRIPT" affected "AuthService"',
                            'python3 "${DEVFLOW_CODE_MAP_SCRIPT}" explain Order',
                            f'python3 {self.REAL} path "Login" "TokenStore"',
                            'python3 "$DEVFLOW_CODE_MAP_SCRIPT" query "who validates tokens" --budget 800',
                            'python3 "$DEVFLOW_CODE_MAP_SCRIPT" status'):
                with self.subTest(agent=agent, command=command):
                    decision, reason = self.bash_env(agent, command)
                    self.assertEqual(decision, "allow", reason)

    def test_build_planted_script_and_chaining_denied(self):
        for agent in ("security-red-team", "architecture-analyst"):
            for command in ('python3 "$DEVFLOW_CODE_MAP_SCRIPT" build',
                            "python3 scripts/devflow_code_map.py affected Order",
                            "python3 ./evil/devflow_code_map.py affected Order",
                            'python3 "$DEVFLOW_CODE_MAP_SCRIPT" affected Order; rm -rf docs',
                            'python3 "$DEVFLOW_CODE_MAP_SCRIPT" affected Order && touch x',
                            'python3 "$DEVFLOW_CODE_MAP_SCRIPT" affected $(id)',
                            'python3 -c "import os" "$DEVFLOW_CODE_MAP_SCRIPT" affected Order'):
                with self.subTest(agent=agent, command=command):
                    self.assertEqual(self.bash_env(agent, command)[0], "deny")

    def test_planning_roles_still_have_no_bash(self):
        for agent in ("design-reviewer", "adr-reviewer", "delivery-lead"):
            with self.subTest(agent=agent):
                command = 'python3 "$DEVFLOW_CODE_MAP_SCRIPT" affected Order'
                self.assertEqual(self.bash_env(agent, command)[0], "deny")


if __name__ == "__main__":
    unittest.main()
