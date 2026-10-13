"""Hardening tests: ownership manifests must never grant repo-root or
control-plane authority (Package B1).

Covers the manifest validator (write_paths validation + authorize target
re-check) and the CI diff gate (bootstrap and base-manifest req branches).
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import validate_ownership_manifest as vom  # noqa: E402

DIFF_VALIDATOR = REPO_ROOT / "scripts" / "validate_ownership_diff.py"


def _manifest(req_id, write_paths, contracts=None):
    return {
        "schema_version": 1,
        "req_id": req_id,
        "title": "Hardening fixture",
        "status": "approved",
        "approval": {"approved_by": "human-maintainer", "approved_at": "2026-10-13"},
        "references": {
            "requirement": f"docs/product/requirements/{req_id}.md",
            "acceptance_criteria": f"docs/product/acceptance-criteria/{req_id}.md",
            "contracts": contracts or [],
            "contract_exception": {
                "reason": "no external contract needed",
                "approved_by": "human-maintainer",
                "approved_at": "2026-10-13",
            },
            "adrs": [],
        },
        "owners": [{"agent": "backend-engineer", "write_paths": write_paths}],
    }


class RootPathRejectionTests(unittest.TestCase):
    def test_root_like_paths_are_not_safe(self):
        for raw in ("", " ", ".", "./", ".//", "./."):
            with self.subTest(raw=raw):
                self.assertFalse(vom.is_relative_safe_path(raw))

    def test_normal_relative_paths_still_safe(self):
        for raw in ("apps/api/src", "./apps/api", "src"):
            with self.subTest(raw=raw):
                self.assertTrue(vom.is_relative_safe_path(raw))


class ManifestValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for rel in ("docs/product/requirements/REQ-999.md",
                    "docs/product/acceptance-criteria/REQ-999.md"):
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x\n")
        self.manifest_path = self.root / "docs" / "ownership" / "REQ-999.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _validate(self, write_paths):
        vom.validate_manifest(_manifest("REQ-999", write_paths), str(self.manifest_path), self.root)

    def test_root_and_control_plane_write_paths_rejected(self):
        for wp in (".", "./", "scripts", "scripts/tool.py", ".github", ".github/workflows",
                   ".codex", "hooks", ".devflow/state", ".git", ".claude"):
            with self.subTest(write_path=wp):
                with self.assertRaises(vom.ManifestError):
                    self._validate([wp])

    def test_feature_write_path_accepted(self):
        self._validate(["apps/api/src/features/req-999"])


class AuthorizeTargetRecheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _authorize(self, write_paths, target):
        manifest = _manifest("REQ-999", write_paths)
        vom.authorize(manifest, self.root, "req-999-x", "backend-engineer", target)

    def test_root_write_path_cannot_reach_governance_files(self):
        # Even if a (hand-crafted, unvalidated) manifest carries ".", the
        # target re-check refuses control-plane files.
        for target in (".claude/hooks/protect-main.sh",
                       "scripts/validate_ownership_manifest.py",
                       ".github/workflows/ci.yml",
                       "hooks/hooks.json",
                       ".devflow/state/run.json",
                       "docs/ownership/REQ-999.json",
                       "CLAUDE.md"):
            with self.subTest(target=target):
                with self.assertRaises(vom.ManifestError):
                    self._authorize(["."], target)

    def test_ancestor_write_path_cannot_reach_protected_subtree(self):
        with self.assertRaises(vom.ManifestError) as ctx:
            self._authorize(["docs"], "docs/ownership/REQ-001.json")
        self.assertIn("protected", str(ctx.exception))
        with self.assertRaises(vom.ManifestError):
            self._authorize(["docs"], "docs/product/requirements/REQ-999.md")

    def test_owned_target_still_authorized(self):
        self._authorize(["apps/api/src"], "apps/api/src/service.py")
        self._authorize(["docs"], "docs/handoffs/REQ-999.md")


class DiffGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._git("init", "-q", "-b", "main")
        self._git("config", "user.email", "test@example.com")
        self._git("config", "user.name", "Test")

    def tearDown(self):
        self.tmp.cleanup()

    def _git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args],
                              check=True, capture_output=True, text=True)

    def _write(self, rel, content="x\n"):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    def _commit(self, msg):
        self._git("add", "-A")
        self._git("commit", "-q", "-m", msg)
        return self._git("rev-parse", "HEAD").stdout.strip()

    def _run(self, base, head, branch):
        return subprocess.run(
            [sys.executable, str(DIFF_VALIDATOR), "--root", str(self.root),
             "--base-sha", base, "--head-sha", head, "--branch", branch],
            capture_output=True, text=True,
        )

    def test_bootstrap_root_manifest_cannot_edit_ci_or_scripts(self):
        """The reported CI exploit: a req-999 bootstrap PR with a self-written
        approved manifest using "." edits the CI workflow and a script."""
        self._write("README.md", "readme\n")
        base = self._commit("base")
        self._git("checkout", "-q", "-b", "req-999-exploit")
        self._write("docs/ownership/REQ-999.json", json.dumps(_manifest("REQ-999", ["."])))
        self._write("docs/product/requirements/REQ-999.md")
        self._write("docs/product/acceptance-criteria/REQ-999.md")
        self._write(".github/workflows/ci.yml", "name: pwned\n")
        self._write("scripts/x.py", "print('pwned')\n")
        head = self._commit("bootstrap exploit")

        result = self._run(base, head, "req-999-exploit")

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("error:", result.stderr)

    def test_base_manifest_ancestor_write_path_cannot_edit_protected_docs(self):
        self._write("docs/product/requirements/REQ-042.md")
        self._write("docs/product/acceptance-criteria/REQ-042.md")
        self._write("docs/ownership/REQ-042.json", json.dumps(_manifest("REQ-042", ["docs"])))
        base = self._commit("base with broad docs owner")
        self._git("checkout", "-q", "-b", "req-042-broad")
        self._write("docs/product/requirements/REQ-042.md", "rewritten\n")
        head = self._commit("rewrite requirement")

        result = self._run(base, head, "req-042-broad")

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("protected area", result.stderr)

    def test_governance_branch_may_change_tooling_config(self):
        self._write("README.md", "readme\n")
        base = self._commit("base")
        self._git("checkout", "-q", "-b", "devflow/tooling")
        self._write("pyproject.toml", "[tool.ruff]\ntarget-version = \"py39\"\n")
        self._write(".github/CODEOWNERS", "* @owner\n")
        head = self._commit("tooling")

        result = self._run(base, head, "devflow/tooling")

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_base_manifest_owned_path_still_allowed(self):
        self._write("docs/product/requirements/REQ-042.md")
        self._write("docs/product/acceptance-criteria/REQ-042.md")
        self._write("docs/ownership/REQ-042.json", json.dumps(_manifest("REQ-042", ["docs"])))
        base = self._commit("base")
        self._git("checkout", "-q", "-b", "req-042-ok")
        self._write("docs/handoffs/REQ-042.md", "handoff\n")
        head = self._commit("handoff")

        result = self._run(base, head, "req-042-ok")

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
