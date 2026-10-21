"""Ponytail integration: the vendored plugin is complete, its rules reach only
the implementer/QA subagents, and both launchers (bin/claude-devflow and
devflow_operations.py launch) load it as a second --plugin-dir."""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_devflow_operations import (  # noqa: E402
    _make_fake_claude,
    _remove_worktrees_and_cleanup,
    make_git_repo,
    run_ops,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PONYTAIL = REPO_ROOT / ".claude" / "vendor" / "ponytail"
OPS_SCRIPT = REPO_ROOT / "scripts" / "devflow_operations.py"
LAUNCHER = REPO_ROOT / "bin" / "claude-devflow"
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"


def load_ops():
    spec = importlib.util.spec_from_file_location("devflow_ops_ponytail", OPS_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fake_node_dir(base: Path) -> Path:
    """A directory holding a stand-in `node`, so tests do not depend on the host."""
    d = base / "fake-node"
    d.mkdir()
    node = d / "node"
    node.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    node.chmod(0o755)
    return d


class VendoredPluginTest(unittest.TestCase):

    def test_manifest_and_provenance(self):
        manifest = json.loads((PONYTAIL / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "ponytail")
        vendored = (PONYTAIL / "VENDORED.md").read_text(encoding="utf-8")
        self.assertRegex(vendored, r"Commit: [0-9a-f]{40}")
        self.assertIn(f"Sürüm: {manifest['version']}", vendored)
        self.assertIn("MIT License", (PONYTAIL / "LICENSE").read_text(encoding="utf-8"))

    def test_skills_present(self):
        for name in ("ponytail", "ponytail-review", "ponytail-audit", "ponytail-debt"):
            with self.subTest(skill=name):
                self.assertTrue((PONYTAIL / "skills" / name / "SKILL.md").is_file())

    def test_registered_hook_scripts_exist(self):
        manifest = json.loads((PONYTAIL / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        for rel in manifest["hooks"]:
            hooks_file = PONYTAIL / rel
            self.assertTrue(hooks_file.is_file(), rel)
            text = hooks_file.read_text(encoding="utf-8")
            for script in re.findall(r"hooks/([\w.-]+\.js)", text):
                with self.subTest(hooks=rel, script=script):
                    self.assertTrue((PONYTAIL / "hooks" / script).is_file())


class RoleScopeTest(unittest.TestCase):

    def setUp(self):
        self.ops = load_ops()
        self.roles = self.ops.PONYTAIL_ROLES.split("|")

    def test_launchers_use_the_same_roles(self):
        m = re.search(r'^PONYTAIL_ROLES="([^"]+)"', LAUNCHER.read_text(encoding="utf-8"), re.M)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), self.ops.PONYTAIL_ROLES)

    def test_roles_are_real_agents(self):
        for role in self.roles:
            with self.subTest(role=role):
                self.assertTrue((AGENTS_DIR / f"{role}.md").is_file())

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_only_implementer_and_qa_subagents_get_the_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp)
            (config / ".ponytail-active").write_text("full", encoding="utf-8")
            env = dict(os.environ, CLAUDE_CONFIG_DIR=str(config),
                       PONYTAIL_SUBAGENT_MATCHER=self.ops.PONYTAIL_ROLES)
            env.pop("CLAUDE_PROJECT_DIR", None)
            env.pop("CLAUDE_PLUGIN_ROOT", None)
            for agent in sorted(AGENTS_DIR.glob("*.md")):
                role = agent.stem
                payload = json.dumps({"agent_type": f"devflow-plugin:{role}"})
                out = subprocess.run(
                    ["node", str(PONYTAIL / "hooks" / "ponytail-subagent.js")],
                    input=payload, capture_output=True, text=True, env=env, timeout=10,
                ).stdout
                with self.subTest(role=role):
                    if role in self.roles:
                        self.assertIn("PONYTAIL MODE ACTIVE — level: full", out)
                    else:
                        self.assertEqual(out.strip(), "")


class LaunchConfigTest(unittest.TestCase):

    def setUp(self):
        self.ops = load_ops()
        self.tmp = tempfile.TemporaryDirectory()
        self.node_path = str(fake_node_dir(Path(self.tmp.name)))

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, **env):
        return self.ops.ponytail_launch_config({"PATH": self.node_path, **env})

    def test_on_by_default_in_full_mode(self):
        plugin, env = self.config()
        self.assertEqual(plugin, PONYTAIL)
        self.assertEqual(env["PONYTAIL_DEFAULT_MODE"], "full")
        self.assertEqual(env["PONYTAIL_SUBAGENT_MATCHER"], self.ops.PONYTAIL_ROLES)

    def test_ultra_is_replaced_by_full_and_lite_is_kept(self):
        self.assertEqual(self.config(PONYTAIL_DEFAULT_MODE="ultra")[1]["PONYTAIL_DEFAULT_MODE"], "full")
        self.assertEqual(self.config(PONYTAIL_DEFAULT_MODE="lite")[1]["PONYTAIL_DEFAULT_MODE"], "lite")

    def test_custom_matcher_is_kept(self):
        self.assertEqual(self.config(PONYTAIL_SUBAGENT_MATCHER="backend")[1]["PONYTAIL_SUBAGENT_MATCHER"], "backend")

    def test_off_switch_and_missing_node(self):
        self.assertEqual(self.config(DEVFLOW_PONYTAIL="0"), (None, {}))
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        self.assertEqual(self.ops.ponytail_launch_config({"PATH": str(empty)}), (None, {}))


class LaunchPassesPonytailTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.target = self.tmpdir / "myproject"
        self.target.mkdir()
        make_git_repo(self.target, branch="main")
        self.report_file = self.tmpdir / "claude_report.json"
        self.fake_claude = _make_fake_claude(self.tmpdir, self.report_file)
        self.node_dir = fake_node_dir(self.tmpdir)

    def tearDown(self):
        _remove_worktrees_and_cleanup(self.target, self.tmpdir)

    def launch(self, *extra, **env):
        run_env = {
            "DEVFLOW_CLAUDE_BINARY": str(self.fake_claude),
            "DEVFLOW_TEST_REPORT": str(self.report_file),
            "PATH": str(self.node_dir) + os.pathsep + os.environ.get("PATH", ""),
            **env,
        }
        return run_ops(["launch", "--target", str(self.target), *extra], env=run_env)

    def report(self):
        if not self.report_file.exists():
            self.skipTest("fake claude did not write a report")
        return json.loads(self.report_file.read_text(encoding="utf-8"))

    def test_launch_adds_ponytail_plugin_and_env(self):
        self.launch()
        data = self.report()
        self.assertEqual(data["args"].count("--plugin-dir"), 2)
        self.assertIn(str(PONYTAIL), data["args"])
        self.assertEqual(data["env"]["PONYTAIL_DEFAULT_MODE"], "full")
        self.assertIn("backend-engineer", data["env"]["PONYTAIL_SUBAGENT_MATCHER"])

    def test_launch_without_ponytail(self):
        self.launch(DEVFLOW_PONYTAIL="0")
        data = self.report()
        self.assertEqual(data["args"].count("--plugin-dir"), 1)
        self.assertNotIn(str(PONYTAIL), data["args"])

    def test_dry_run_shows_ponytail(self):
        result = self.launch("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"--plugin-dir {PONYTAIL}", result.stdout)
        self.assertIn("ponytail roles:", result.stdout)


if __name__ == "__main__":
    unittest.main()
