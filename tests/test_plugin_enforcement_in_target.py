"""
The built plugin enforces role/branch/path boundaries in a target project.

claude-devflow loads the plugin via --plugin-dir in any folder, so the runtime
enforcement hooks now ship in the plugin and must work in a fresh project that
has none of the framework's own files. In particular, enforce-role-boundaries.sh
resolves the ownership validator from the plugin root (DEVFLOW_PLUGIN_ROOT),
not the target's scripts/, which the target does not have.

These tests build the plugin, then run its shipped hooks against a throwaway
target repo — reproducing what happens when a plugin-scoped subagent acts in a
new project.

Covers:
1.  Plugin build ships the enforcement hooks + validator
2.  enforce-role-boundaries denies an implementer writing outside its manifest
    write_paths, using the plugin-shipped validator (target has no validator)
3.  enforce-role-boundaries allows an implementer on its own write_paths
4.  protect-main denies a write while on the main branch
5.  protect-sensitive-paths denies a write to a .env file
6.  A plugin-scoped agent_type is enforced the same as a bare name
"""

# PEP 563: keep annotations unevaluated so this imports on Python 3.9.
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_devflow_plugin.py"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


class PluginEnforcementInTargetTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        # Build the plugin into a throwaway dir.
        out = cls.tmp / "out"
        result = subprocess.run(
            [sys.executable, str(BUILD_SCRIPT), "--output-dir", str(out)],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, result.stderr
        cls.plugin = out / "devflow-plugin"

        # A fresh target project with NONE of the framework's files.
        cls.target = cls.tmp / "target"
        cls.target.mkdir()
        _git(cls.target, "init", "-b", "main")
        _git(cls.target, "config", "user.email", "t@t.t")
        _git(cls.target, "config", "user.name", "T")
        (cls.target / "README.md").write_text("x\n", encoding="utf-8")
        _git(cls.target, "add", "README.md")
        _git(cls.target, "commit", "-m", "init")
        _git(cls.target, "checkout", "-b", "req-042-login")

        # An approved ownership manifest + the references it requires.
        for rel in ("docs/product/requirements", "docs/product/acceptance-criteria",
                    "docs/contracts/openapi", "docs/ownership",
                    "apps/api/src", "apps/web/src"):
            (cls.target / rel).mkdir(parents=True, exist_ok=True)
        (cls.target / "docs/product/requirements/REQ-042.md").write_text("# r\n", encoding="utf-8")
        (cls.target / "docs/product/acceptance-criteria/REQ-042.md").write_text("# a\n", encoding="utf-8")
        (cls.target / "docs/contracts/openapi/req-042-login.yaml").write_text("openapi: 3.0.0\n", encoding="utf-8")
        (cls.target / "docs/ownership/REQ-042.json").write_text(json.dumps({
            "schema_version": 1, "req_id": "REQ-042", "status": "approved",
            "approval": {"approved_by": "human", "approved_at": "2026-01-01T00:00:00Z"},
            "references": {
                "requirement": "docs/product/requirements/REQ-042.md",
                "acceptance_criteria": "docs/product/acceptance-criteria/REQ-042.md",
                "contracts": ["docs/contracts/openapi/req-042-login.yaml"],
                "adrs": [],
            },
            "owners": [
                {"agent": "backend-engineer", "write_paths": ["apps/api/src"]},
                {"agent": "frontend-engineer", "write_paths": ["apps/web/src"]},
            ],
        }), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _run_hook(self, hook_name: str, payload: dict, plugin_root: bool = False):
        env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")}
        if plugin_root:
            env["DEVFLOW_PLUGIN_ROOT"] = str(self.plugin)
        return subprocess.run(
            ["bash", str(self.plugin / "hooks" / hook_name)],
            input=json.dumps(payload), capture_output=True, text=True, env=env,
        )

    def _is_deny(self, result) -> bool:
        if result.returncode != 0 or not result.stdout.strip():
            return False
        try:
            return json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
        except (json.JSONDecodeError, KeyError):
            return False

    # 1. build ships the pieces
    def test_plugin_ships_hooks_and_validator(self):
        for f in ("hooks/enforce-role-boundaries.sh", "hooks/protect-main.sh",
                  "hooks/protect-sensitive-paths.sh", "hooks/session-start.sh",
                  "scripts/validate_ownership_manifest.py"):
            self.assertTrue((self.plugin / f).exists(), f"{f} missing from plugin")
        # The target must NOT have its own validator — proving the plugin's is used.
        self.assertFalse((self.target / "scripts" / "validate_ownership_manifest.py").exists())

    # 2 & 3. role enforcement via the plugin-shipped validator
    def test_implementer_off_its_write_paths_denied(self):
        r = self._run_hook("enforce-role-boundaries.sh", {
            "tool_name": "Write", "agent_type": "backend-engineer",
            "cwd": str(self.target), "tool_input": {"file_path": "apps/web/src/App.tsx"},
        }, plugin_root=True)
        self.assertTrue(self._is_deny(r), f"stdout={r.stdout!r} stderr={r.stderr!r}")

    def test_implementer_on_its_write_paths_allowed(self):
        r = self._run_hook("enforce-role-boundaries.sh", {
            "tool_name": "Write", "agent_type": "backend-engineer",
            "cwd": str(self.target), "tool_input": {"file_path": "apps/api/src/handler.py"},
        }, plugin_root=True)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")

    # 6. plugin-scoped name enforced the same
    def test_plugin_scoped_agent_enforced(self):
        r = self._run_hook("enforce-role-boundaries.sh", {
            "tool_name": "Write", "agent_type": "devflow-plugin:backend-engineer",
            "cwd": str(self.target), "tool_input": {"file_path": "apps/web/src/App.tsx"},
        }, plugin_root=True)
        self.assertTrue(self._is_deny(r))

    # 4. main protection
    def test_protect_main_denies_on_main(self):
        _git(self.target, "checkout", "main")
        try:
            r = self._run_hook("protect-main.sh", {
                "tool_name": "Write", "cwd": str(self.target),
                "tool_input": {"file_path": "x.txt"},
            })
            self.assertTrue(self._is_deny(r), f"stdout={r.stdout!r}")
        finally:
            _git(self.target, "checkout", "req-042-login")

    # 5. sensitive path protection
    def test_protect_sensitive_denies_dotenv(self):
        r = self._run_hook("protect-sensitive-paths.sh", {
            "tool_name": "Write",
            "tool_input": {"file_path": str(self.target / ".env")},
        })
        self.assertTrue(self._is_deny(r))


if __name__ == "__main__":
    unittest.main()
