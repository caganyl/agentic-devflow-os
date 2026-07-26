"""
Opt-in ownership binding for work-product evidence.

The delivery-run task graph gives both the backend and the frontend
implementation task the same coarse output area (src/), so the work-product
gate alone could not tell "frontend recorded a backend file" from legitimate
evidence. When a run declares a REQ-ID and an approved ownership manifest
governs the task's role, the evidence must fall under that role's write_paths.

The binding is opt-in and backward compatible: no --req-id, no manifest, an
unapproved manifest, or a role the manifest does not list all leave the
existing coarse checks untouched.

Covers:
1.  Evidence under the role's write_paths is accepted
2.  Evidence under ANOTHER role's write_paths is denied (the headline case)
3.  No --req-id → binding is inert (backward compatible)
4.  --req-id but no manifest → inert
5.  Draft (unapproved) manifest → inert
6.  Role not listed in the manifest → inert (no invented restriction)
7.  A non-implementer role (security-red-team) → inert
8.  Malformed --req-id is rejected at create-run
9.  req_id is stored in run state
10. End-to-end: cross-role evidence recording fails via the CLI
"""

# PEP 563: keep `X | None` annotations unevaluated so this imports on Python 3.9.
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OPS_SCRIPT = REPO_ROOT / "scripts" / "devflow_operations.py"

WORK_PRODUCT_EXIT = 19


def _load_ops():
    spec = importlib.util.spec_from_file_location("devflow_ops_ownership", OPS_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_ops(args: list) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(OPS_SCRIPT)] + args,
        capture_output=True, text=True, env=os.environ.copy(),
    )


def make_git_repo(path: Path, branch: str = "feature-work") -> None:
    subprocess.run(["git", "init", "-b", branch, str(path)], check=True, capture_output=True)
    for k, v in (("user.email", "t@t.t"), ("user.name", "T")):
        subprocess.run(["git", "config", k, v], check=True, capture_output=True, cwd=str(path))
    (path / "README.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], check=True, capture_output=True, cwd=str(path))
    subprocess.run(["git", "commit", "-m", "init"], check=True, capture_output=True, cwd=str(path))


APPROVED_MANIFEST = {
    "schema_version": 1,
    "req_id": "REQ-007",
    "status": "approved",
    "owners": [
        {"agent": "backend-engineer", "write_paths": ["apps/api/src"]},
        {"agent": "frontend-engineer", "write_paths": ["apps/web/src"]},
    ],
}


class OwnershipHelperTest(unittest.TestCase):
    """Direct unit tests of the authorize helper (no CLI)."""

    def setUp(self):
        self.mod = _load_ops()
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "docs" / "ownership").mkdir(parents=True)
        self._write_manifest(APPROVED_MANIFEST)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_manifest(self, data: dict, name: str = "REQ-007.json"):
        (self.tmp / "docs" / "ownership" / name).write_text(json.dumps(data), encoding="utf-8")

    def _auth(self, req, role, path):
        return self.mod.authorize_work_product_ownership(self.tmp, req, role, path)

    def test_own_path_accepted(self):
        ok, _ = self._auth("REQ-007", "backend-engineer", "apps/api/src/handler.py")
        self.assertTrue(ok)

    def test_cross_role_path_denied(self):
        ok, reason = self._auth("REQ-007", "backend-engineer", "apps/web/src/App.tsx")
        self.assertFalse(ok)
        self.assertIn("backend-engineer", reason)

    def test_frontend_into_backend_denied(self):
        ok, _ = self._auth("REQ-007", "frontend-engineer", "apps/api/src/handler.py")
        self.assertFalse(ok)

    def test_no_req_id_is_inert(self):
        ok, _ = self._auth("", "backend-engineer", "apps/web/src/App.tsx")
        self.assertTrue(ok)

    def test_missing_manifest_is_inert(self):
        ok, _ = self._auth("REQ-999", "backend-engineer", "apps/web/src/App.tsx")
        self.assertTrue(ok)

    def test_draft_manifest_is_inert(self):
        draft = dict(APPROVED_MANIFEST, status="draft")
        self._write_manifest(draft, "REQ-008.json")
        draft = dict(draft, req_id="REQ-008")
        self._write_manifest(draft, "REQ-008.json")
        ok, _ = self._auth("REQ-008", "backend-engineer", "apps/web/src/App.tsx")
        self.assertTrue(ok)

    def test_role_not_in_manifest_is_inert(self):
        # database-engineer is a bindable role but not an owner here.
        ok, _ = self._auth("REQ-007", "database-engineer", "anywhere/x.sql")
        self.assertTrue(ok)

    def test_non_bindable_role_is_inert(self):
        ok, _ = self._auth("REQ-007", "security-red-team", "apps/api/src/x.py")
        self.assertTrue(ok)

    def test_nested_path_under_write_path_accepted(self):
        ok, _ = self._auth("REQ-007", "backend-engineer", "apps/api/src/deep/nested/x.py")
        self.assertTrue(ok)


class CreateRunReqIdTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.target = self.tmp / "proj"
        self.target.mkdir()
        make_git_repo(self.target)
        run_ops(["init-target", "--target", str(self.target)])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_state(self) -> dict:
        return _load_ops().read_run_state(
            self.target, sorted((self.target / ".devflow" / "runs").glob("*.json"))[0]
        )

    def test_req_id_stored_in_run_state(self):
        res = run_ops(["create-run", "--target", str(self.target),
                       "--objective", "x", "--req-id", "REQ-007"])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self._run_state()["req_id"], "REQ-007")

    def test_malformed_req_id_rejected(self):
        res = run_ops(["create-run", "--target", str(self.target),
                       "--objective", "x", "--req-id", "REQ-7"])
        self.assertNotEqual(res.returncode, 0)

    def test_no_req_id_leaves_empty(self):
        run_ops(["create-run", "--target", str(self.target), "--objective", "x"])
        self.assertEqual(self._run_state()["req_id"], "")


class OwnershipBindingEndToEndTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.target = self.tmp / "proj"
        self.target.mkdir()
        make_git_repo(self.target)
        (self.target / "docs" / "ownership").mkdir(parents=True)
        (self.target / "docs" / "ownership" / "REQ-007.json").write_text(
            json.dumps(APPROVED_MANIFEST), encoding="utf-8"
        )
        (self.target / "apps" / "api" / "src").mkdir(parents=True)
        (self.target / "apps" / "web" / "src").mkdir(parents=True)
        (self.target / "apps" / "api" / "src" / "handler.py").write_text("x\n", encoding="utf-8")
        (self.target / "apps" / "web" / "src" / "App.tsx").write_text("x\n", encoding="utf-8")

        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target),
                 "--objective", "ownership run", "--req-id", "REQ-007"])
        run_ops(["generate-task-graph", "--target", str(self.target),
                 "--delivery-type", "new_feature"])
        self.mod = _load_ops()
        self.run_file = sorted((self.target / ".devflow" / "runs").glob("*.json"))[0]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _impl_task_for(self, role: str) -> str:
        state = self.mod.read_run_state(self.target, self.run_file)
        for t in state["tasks"]:
            if t["task_type"] == "implementation" and t["assigned_role"] == role:
                return t["id"]
        self.fail(f"no implementation task for {role}")

    def _ready(self, task_id: str):
        for s in ("ready", "in_progress"):
            run_ops(["update-task-status", "--target", str(self.target),
                     "--task-id", task_id, "--status", s])

    def test_backend_recording_frontend_file_is_denied(self):
        backend = self._impl_task_for("backend-engineer")
        self._ready(backend)
        res = run_ops(["record-work-product-evidence", "--target", str(self.target),
                       "--task-id", backend, "--evidence-path", "apps/web/src/App.tsx"])
        self.assertEqual(res.returncode, WORK_PRODUCT_EXIT,
                         f"backend must not claim a frontend file. stdout: {res.stdout}")
        self.assertIn("write_paths", res.stderr)

    def test_backend_recording_own_file_is_accepted(self):
        backend = self._impl_task_for("backend-engineer")
        self._ready(backend)
        res = run_ops(["record-work-product-evidence", "--target", str(self.target),
                       "--task-id", backend, "--evidence-path", "apps/api/src/handler.py"])
        self.assertEqual(res.returncode, 0, res.stderr)


if __name__ == "__main__":
    unittest.main()
