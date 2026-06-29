"""
Tests for Work Product Evidence Gate.

Covers 5 required scenarios:
  1. Implementation/QA completion blocked without evidence
  2. Docs-only, unmodified, unsafe, and configuration paths rejected
  3. Changed source/template path recorded for implementation task
  4. Changed test path recorded for QA task
  5. Final report is not_ready when required work-product evidence is missing or stale
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OPS_SCRIPT = REPO_ROOT / "scripts" / "devflow_operations.py"


def _load_ops_module():
    spec = importlib.util.spec_from_file_location("devflow_ops_wp_ev", OPS_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_git_repo(path: Path, branch: str = "feature-wp-test") -> None:
    subprocess.run(["git", "init", "-b", branch, str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@devflow.test"],
        check=True, capture_output=True, cwd=str(path),
    )
    subprocess.run(
        ["git", "config", "user.name", "DevFlow Test"],
        check=True, capture_output=True, cwd=str(path),
    )
    readme = path / "README.md"
    readme.write_text("work product evidence test project\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], check=True, capture_output=True, cwd=str(path))
    subprocess.run(
        ["git", "commit", "-m", "init"],
        check=True, capture_output=True, cwd=str(path),
    )


def run_ops(args: list) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(OPS_SCRIPT)] + args,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )


def _setup_backend_utility_run(target: Path, objective: str = "Build CSV parser") -> str:
    run_ops(["init-target", "--target", str(target)])
    run_ops(["create-run", "--target", str(target), "--objective", objective])
    run_ops([
        "generate-task-graph",
        "--target", str(target),
        "--delivery-type", "backend_utility",
        "--objective", objective,
    ])
    devflow = target / ".devflow"
    project = json.loads((devflow / "project.json").read_text())
    return project["current_run_id"]


def _get_tasks_of_type(target: Path, run_id: str, task_type: str) -> list:
    devflow = target / ".devflow"
    run_data = json.loads((devflow / "runs" / f"{run_id}.json").read_text())
    return [t for t in run_data.get("tasks", []) if t.get("task_type") == task_type]


def _make_src_file(target: Path, name: str = "feature.py") -> str:
    src_dir = target / "src"
    src_dir.mkdir(exist_ok=True)
    (src_dir / name).write_text(f"# {name}\n", encoding="utf-8")
    return f"src/{name}"


def _make_test_file(target: Path, name: str = "test_feature.py") -> str:
    tests_dir = target / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / name).write_text(f"# {name}\n", encoding="utf-8")
    return f"tests/{name}"


# ---------------------------------------------------------------------------
# Scenario 1: Completion blocked without evidence
# ---------------------------------------------------------------------------

class CompletionBlockedWithoutEvidenceTest(unittest.TestCase):
    """Scenario 1: implementation/QA cannot reach completed/verified without evidence."""

    def test_implementation_completion_blocked_without_evidence_cli(self):
        """update-task-status to completed for implementation task exits 15 without evidence."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target)
            run_id = _setup_backend_utility_run(target)

            impl_tasks = _get_tasks_of_type(target, run_id, "implementation")
            self.assertTrue(impl_tasks, "backend_utility must have implementation task")
            impl_task_id = impl_tasks[0]["id"]

            # Advance to in_progress (not blocked by work-product gate)
            run_ops(["update-task-status", "--target", str(target),
                     "--task-id", impl_task_id, "--status", "ready"])
            run_ops(["update-task-status", "--target", str(target),
                     "--task-id", impl_task_id, "--status", "in_progress"])

            # Now attempt completed — must be blocked
            res = run_ops(["update-task-status", "--target", str(target),
                           "--task-id", impl_task_id, "--status", "completed"])
            self.assertNotEqual(res.returncode, 0,
                                "Completion must be blocked without work-product evidence")
            self.assertEqual(res.returncode, 15,
                             f"Expected exit 15. stderr: {res.stderr}")
            self.assertIn("record-work-product-evidence", res.stderr)

    def test_qa_completion_blocked_without_evidence_cli(self):
        """update-task-status to completed for QA task exits 15 without evidence."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target)
            run_id = _setup_backend_utility_run(target)

            qa_tasks = _get_tasks_of_type(target, run_id, "qa")
            self.assertTrue(qa_tasks, "backend_utility must have a QA task")
            qa_task_id = qa_tasks[0]["id"]

            # Advance to in_progress
            run_ops(["update-task-status", "--target", str(target),
                     "--task-id", qa_task_id, "--status", "ready"])
            run_ops(["update-task-status", "--target", str(target),
                     "--task-id", qa_task_id, "--status", "in_progress"])

            # Now attempt completed — must be blocked
            res = run_ops(["update-task-status", "--target", str(target),
                           "--task-id", qa_task_id, "--status", "completed"])
            self.assertNotEqual(res.returncode, 0)
            self.assertEqual(res.returncode, 15,
                             f"Expected exit 15 for QA gate. stderr: {res.stderr}")

    def test_planning_task_not_blocked(self):
        """Planning tasks are not blocked by work-product gate."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target)
            run_id = _setup_backend_utility_run(target)

            planning_tasks = _get_tasks_of_type(target, run_id, "planning")
            self.assertTrue(planning_tasks)
            pid = planning_tasks[0]["id"]

            res = run_ops(["update-task-status", "--target", str(target),
                           "--task-id", pid, "--status", "ready"])
            self.assertEqual(res.returncode, 0,
                             f"Planning task must not be blocked. stderr: {res.stderr}")

    def test_in_progress_not_blocked(self):
        """in_progress is not blocked by work-product gate (only completed/verified are)."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target)
            run_id = _setup_backend_utility_run(target)

            impl_tasks = _get_tasks_of_type(target, run_id, "implementation")
            impl_task_id = impl_tasks[0]["id"]

            run_ops(["update-task-status", "--target", str(target),
                     "--task-id", impl_task_id, "--status", "ready"])
            res = run_ops(["update-task-status", "--target", str(target),
                           "--task-id", impl_task_id, "--status", "in_progress"])
            self.assertEqual(res.returncode, 0,
                             f"in_progress must not be blocked by WP gate. stderr: {res.stderr}")

    def test_build_run_report_gate_not_satisfied_without_evidence(self):
        """build_run_report: gate_satisfied=False when impl task completed without evidence."""
        mod = _load_ops_module()
        tasks = mod.generate_task_graph_nodes("RUN-001", "backend_utility", "Build CSV parser")
        for t in tasks:
            t["status"] = "verified"
        run_data = {
            "run_id": "RUN-001",
            "objective": "Build CSV parser",
            "execution_mode": "subagents",
            "agent_teams_requested": False,
            "tasks": tasks,
            "approval_gates": {
                "tests_passing": True,
                "qa_sign_off": True,
            },
            "security_review_required": False,
            "security_applicability_reason": "low_risk_local_utility",
            "contract_required": False,
            "contract_status": "not_applicable",
            "contract_gate_satisfied": True,
            # No work_product_evidence
        }
        report = mod.build_run_report(run_data, "RUN-001")
        wp = report["work_product_gate"]
        self.assertFalse(wp["gate_satisfied"],
                         "gate_satisfied must be False when impl/QA tasks completed without evidence")
        self.assertEqual(report["technical_readiness"], "not_ready",
                         "technical_readiness must be not_ready when WP gate is not satisfied")


# ---------------------------------------------------------------------------
# Scenario 2: Forbidden paths rejected
# ---------------------------------------------------------------------------

class ForbiddenPathsRejectedTest(unittest.TestCase):
    """Scenario 2: docs-only, unmodified, unsafe, and configuration paths rejected."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_ops_module()
        cls.tmpdir_obj = tempfile.TemporaryDirectory()
        cls.target = Path(cls.tmpdir_obj.name)
        # Create a dummy src file so existence check can pass for some tests
        src = cls.target / "src"
        src.mkdir(exist_ok=True)
        (src / "app.py").write_text("# app\n", encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir_obj.cleanup()

    def _check(self, task_type, path, expect_ok=False):
        ok, err = self.mod.validate_work_product_evidence_path(self.target, task_type, path)
        if expect_ok:
            self.assertTrue(ok, f"Expected OK for {path!r}. Error: {err}")
        else:
            self.assertFalse(ok, f"Expected REJECT for {path!r}. Got ok=True")
        return ok, err

    # --- docs paths ---
    def test_docs_security_report_rejected(self):
        self._check("implementation", "docs/quality/security-reports/report.md")

    def test_docs_contract_path_rejected(self):
        self._check("implementation", "docs/quality/contracts/api.md")

    def test_docs_handoff_rejected(self):
        self._check("qa", "docs/handoffs/REQ-001.md")

    def test_docs_architecture_rejected(self):
        self._check("implementation", "docs/architecture/adr/ADR-001.md")

    # --- .devflow paths ---
    def test_devflow_run_rejected(self):
        ok, err = self._check("implementation", ".devflow/runs/RUN-001.json")
        self.assertIn(".devflow/", err)

    # --- lockfiles and dependency specs ---
    def test_package_lock_rejected(self):
        self._check("implementation", "src/package-lock.json")

    def test_requirements_txt_rejected(self):
        self._check("implementation", "src/requirements.txt")

    def test_setup_py_rejected(self):
        self._check("implementation", "src/setup.py")

    def test_pyproject_toml_rejected(self):
        self._check("implementation", "src/pyproject.toml")

    def test_dockerfile_rejected(self):
        self._check("implementation", "src/Dockerfile")

    def test_makefile_rejected(self):
        self._check("implementation", "src/Makefile")

    # --- .env / secret files ---
    def test_env_file_rejected(self):
        self._check("implementation", "src/.env")

    def test_env_production_rejected(self):
        self._check("implementation", "src/.env.production")

    def test_secret_file_rejected(self):
        self._check("implementation", "src/secret_key.py")

    def test_credential_file_rejected(self):
        self._check("implementation", "src/credentials.json")

    # --- migration paths ---
    def test_migration_dir_rejected(self):
        self._check("implementation", "src/migrations/001_add_table.py")

    # --- wrong prefix for task type ---
    def test_impl_with_test_prefix_rejected(self):
        ok, err = self._check("implementation", "tests/test_feature.py")
        self.assertIn("src/", err)

    def test_qa_with_src_prefix_rejected(self):
        ok, err = self._check("qa", "src/feature.py")
        self.assertIn("tests/", err)

    # --- path traversal ---
    def test_traversal_rejected(self):
        self._check("implementation", "src/../docs/something.md")

    # --- absolute path ---
    def test_absolute_path_rejected(self):
        self._check("implementation", "/absolute/src/app.py")

    # --- wildcards ---
    def test_wildcard_rejected(self):
        self._check("implementation", "src/*.py")

    # --- unmodified file (git check) ---
    def test_unmodified_file_rejected_by_git_check(self):
        """A committed, clean file is rejected by the git worktree change check."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target)
            src_dir = target / "src"
            src_dir.mkdir()
            clean_file = src_dir / "committed_clean.py"
            clean_file.write_text("# committed\n")
            subprocess.run(["git", "add", "src/committed_clean.py"],
                           cwd=str(target), check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "add committed file"],
                           cwd=str(target), check=True, capture_output=True)

            # File exists but is not a worktree change
            ok, err = self.mod.validate_work_product_evidence_path(
                target, "implementation", "src/committed_clean.py"
            )
            self.assertTrue(ok, f"Path validation should pass; git check is separate. err={err}")
            is_change = self.mod.is_path_git_worktree_change(target, "src/committed_clean.py")
            self.assertFalse(is_change,
                             "Committed clean file must NOT show as git worktree change")


# ---------------------------------------------------------------------------
# Scenario 3: Changed source path recorded for implementation task
# ---------------------------------------------------------------------------

class ImplementationEvidenceRecordedTest(unittest.TestCase):
    """Scenario 3: A changed source path can be recorded for an implementation task."""

    def test_record_implementation_evidence_untracked_file(self):
        """An untracked src/ file is accepted as implementation evidence."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target)
            run_id = _setup_backend_utility_run(target)

            impl_tasks = _get_tasks_of_type(target, run_id, "implementation")
            self.assertTrue(impl_tasks)
            impl_task_id = impl_tasks[0]["id"]

            # Create untracked source file
            src_path = _make_src_file(target, "parser.py")

            res = run_ops([
                "record-work-product-evidence",
                "--target", str(target),
                "--task-id", impl_task_id,
                "--evidence-path", src_path,
            ])
            self.assertEqual(res.returncode, 0,
                             f"Recording untracked src file must succeed. stderr: {res.stderr}")

            devflow = target / ".devflow"
            run_data = json.loads((devflow / "runs" / f"{run_id}.json").read_text())
            wp_ev = run_data.get("work_product_evidence", {})
            self.assertIn(impl_task_id, wp_ev)
            self.assertEqual(wp_ev[impl_task_id]["evidence_path"], src_path)
            self.assertEqual(wp_ev[impl_task_id]["task_type"], "implementation")
            self.assertTrue(wp_ev[impl_task_id]["git_change_verified_at_record_time"])

    def test_record_implementation_evidence_modified_file(self):
        """A modified (staged) src/ file is accepted as implementation evidence."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target)
            run_id = _setup_backend_utility_run(target)

            impl_tasks = _get_tasks_of_type(target, run_id, "implementation")
            impl_task_id = impl_tasks[0]["id"]

            # Commit the file first, then modify it
            src_dir = target / "src"
            src_dir.mkdir(exist_ok=True)
            src_file = src_dir / "util.py"
            src_file.write_text("# original\n")
            subprocess.run(["git", "add", "src/util.py"],
                           cwd=str(target), check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "add util"],
                           cwd=str(target), check=True, capture_output=True)
            src_file.write_text("# modified\n")  # unstaged change

            res = run_ops([
                "record-work-product-evidence",
                "--target", str(target),
                "--task-id", impl_task_id,
                "--evidence-path", "src/util.py",
            ])
            self.assertEqual(res.returncode, 0,
                             f"Modified file must be accepted. stderr: {res.stderr}")

    def test_record_evidence_enables_completion(self):
        """After recording evidence, implementation task can be moved to completed."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target)
            run_id = _setup_backend_utility_run(target)

            impl_tasks = _get_tasks_of_type(target, run_id, "implementation")
            impl_task_id = impl_tasks[0]["id"]

            # Create and record evidence
            src_path = _make_src_file(target, "feature2.py")
            run_ops(["record-work-product-evidence", "--target", str(target),
                     "--task-id", impl_task_id, "--evidence-path", src_path])

            # Advance to in_progress
            run_ops(["update-task-status", "--target", str(target),
                     "--task-id", impl_task_id, "--status", "ready"])
            run_ops(["update-task-status", "--target", str(target),
                     "--task-id", impl_task_id, "--status", "in_progress"])

            # Now completed should be allowed
            res = run_ops(["update-task-status", "--target", str(target),
                           "--task-id", impl_task_id, "--status", "completed"])
            self.assertEqual(res.returncode, 0,
                             f"Completion must succeed after evidence recorded. stderr: {res.stderr}")

    def test_task_not_in_run_rejected(self):
        """Task ID not belonging to active run exits 19."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target)
            _setup_backend_utility_run(target)
            src_path = _make_src_file(target, "x.py")

            res = run_ops([
                "record-work-product-evidence",
                "--target", str(target),
                "--task-id", "RUN-999-TASK-001",
                "--evidence-path", src_path,
            ])
            self.assertNotEqual(res.returncode, 0)
            self.assertEqual(res.returncode, 19,
                             f"Expected exit 19 for unknown task. stderr: {res.stderr}")

    def test_wrong_run_id_rejected(self):
        """--run-id mismatch exits 19."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target)
            run_id = _setup_backend_utility_run(target)

            impl_tasks = _get_tasks_of_type(target, run_id, "implementation")
            src_path = _make_src_file(target, "x2.py")

            res = run_ops([
                "record-work-product-evidence",
                "--target", str(target),
                "--run-id", "RUN-999",
                "--task-id", impl_tasks[0]["id"],
                "--evidence-path", src_path,
            ])
            self.assertEqual(res.returncode, 19,
                             f"Expected exit 19 for run-id mismatch. stderr: {res.stderr}")

    def test_planning_task_rejected(self):
        """Planning task type exits 19 — only implementation/qa accepted."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target)
            run_id = _setup_backend_utility_run(target)

            planning_tasks = _get_tasks_of_type(target, run_id, "planning")
            src_path = _make_src_file(target, "x3.py")

            res = run_ops([
                "record-work-product-evidence",
                "--target", str(target),
                "--task-id", planning_tasks[0]["id"],
                "--evidence-path", src_path,
            ])
            self.assertEqual(res.returncode, 19,
                             f"Expected exit 19 for planning task. stderr: {res.stderr}")


# ---------------------------------------------------------------------------
# Scenario 4: Changed test path recorded for QA task
# ---------------------------------------------------------------------------

class QAEvidenceRecordedTest(unittest.TestCase):
    """Scenario 4: A changed test path can be recorded for a QA task."""

    def test_record_qa_evidence_untracked_test_file(self):
        """An untracked tests/ file is accepted as QA evidence."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target)
            run_id = _setup_backend_utility_run(target)

            qa_tasks = _get_tasks_of_type(target, run_id, "qa")
            self.assertTrue(qa_tasks, "backend_utility must have QA task")
            qa_task_id = qa_tasks[0]["id"]

            test_path = _make_test_file(target, "test_parser.py")

            res = run_ops([
                "record-work-product-evidence",
                "--target", str(target),
                "--task-id", qa_task_id,
                "--evidence-path", test_path,
            ])
            self.assertEqual(res.returncode, 0,
                             f"Untracked tests/ file must be accepted. stderr: {res.stderr}")

            devflow = target / ".devflow"
            run_data = json.loads((devflow / "runs" / f"{run_id}.json").read_text())
            wp_ev = run_data.get("work_product_evidence", {})
            self.assertIn(qa_task_id, wp_ev)
            self.assertEqual(wp_ev[qa_task_id]["task_type"], "qa")
            self.assertEqual(wp_ev[qa_task_id]["evidence_path"], test_path)

    def test_src_file_rejected_for_qa_task(self):
        """src/ production source file is rejected for QA task — must be a test asset."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target)
            run_id = _setup_backend_utility_run(target)

            qa_tasks = _get_tasks_of_type(target, run_id, "qa")
            src_path = _make_src_file(target, "app_logic.py")

            res = run_ops([
                "record-work-product-evidence",
                "--target", str(target),
                "--task-id", qa_tasks[0]["id"],
                "--evidence-path", src_path,
            ])
            self.assertNotEqual(res.returncode, 0)
            self.assertEqual(res.returncode, 19,
                             f"src/ path must be rejected for QA task. stderr: {res.stderr}")

    def test_qa_evidence_enables_completion(self):
        """After recording QA evidence, QA task can be moved to completed."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target)
            run_id = _setup_backend_utility_run(target)

            qa_tasks = _get_tasks_of_type(target, run_id, "qa")
            qa_task_id = qa_tasks[0]["id"]

            test_path = _make_test_file(target, "test_util.py")
            run_ops(["record-work-product-evidence", "--target", str(target),
                     "--task-id", qa_task_id, "--evidence-path", test_path])

            run_ops(["update-task-status", "--target", str(target),
                     "--task-id", qa_task_id, "--status", "ready"])
            run_ops(["update-task-status", "--target", str(target),
                     "--task-id", qa_task_id, "--status", "in_progress"])

            res = run_ops(["update-task-status", "--target", str(target),
                           "--task-id", qa_task_id, "--status", "completed"])
            self.assertEqual(res.returncode, 0,
                             f"QA completion must succeed after evidence recorded. stderr: {res.stderr}")


# ---------------------------------------------------------------------------
# Scenario 5: Final report not_ready when evidence missing or stale
# ---------------------------------------------------------------------------

class ReportNotReadyWithoutEvidenceTest(unittest.TestCase):
    """Scenario 5: Report is not_ready when required work-product evidence is missing or stale."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_ops_module()

    def _fully_satisfied_run_data(self, task_list, evidence: dict) -> dict:
        return {
            "run_id": "RUN-001",
            "objective": "Build CSV parser",
            "execution_mode": "subagents",
            "agent_teams_requested": False,
            "tasks": task_list,
            "approval_gates": {
                "tests_passing": True,
                "qa_sign_off": True,
                "security_review_complete": False,
                "human_approval": False,
            },
            "security_review_required": False,
            "security_applicability_reason": "low_risk_local_utility",
            "contract_required": False,
            "contract_status": "not_applicable",
            "contract_gate_satisfied": True,
            "work_product_evidence": evidence,
        }

    def test_not_ready_when_impl_evidence_missing(self):
        """technical_readiness=not_ready when implementation task verified but no evidence."""
        tasks = self.mod.generate_task_graph_nodes("RUN-001", "backend_utility", "Build CSV parser")
        for t in tasks:
            t["status"] = "verified"
        run_data = self._fully_satisfied_run_data(tasks, {})
        report = self.mod.build_run_report(run_data, "RUN-001")
        self.assertEqual(report["technical_readiness"], "not_ready")
        wp = report["work_product_gate"]
        self.assertFalse(wp["gate_satisfied"])

    def test_not_ready_when_qa_evidence_missing(self):
        """technical_readiness=not_ready when QA task verified but no evidence."""
        tasks = self.mod.generate_task_graph_nodes("RUN-001", "backend_utility", "Build CSV parser")
        # Record evidence for impl but not QA
        impl_task = next(t for t in tasks if t["task_type"] == "implementation")
        qa_task = next(t for t in tasks if t["task_type"] == "qa")
        for t in tasks:
            t["status"] = "verified"
        evidence = {
            impl_task["id"]: {
                "task_type": "implementation",
                "evidence_path": "src/parser.py",
                "recorded_at": "2026-06-29T00:00:00Z",
                "git_change_verified_at_record_time": True,
            }
        }
        run_data = self._fully_satisfied_run_data(tasks, evidence)
        report = self.mod.build_run_report(run_data, "RUN-001")
        self.assertEqual(report["technical_readiness"], "not_ready",
                         "Must be not_ready when QA task has no evidence")
        wp = report["work_product_gate"]
        self.assertFalse(wp["gate_satisfied"])

    def test_ready_when_all_evidence_present(self):
        """technical_readiness=ready when all impl/QA tasks have evidence and other gates pass."""
        tasks = self.mod.generate_task_graph_nodes("RUN-001", "backend_utility", "Build CSV parser")
        impl_task = next(t for t in tasks if t["task_type"] == "implementation")
        qa_task = next(t for t in tasks if t["task_type"] == "qa")
        for t in tasks:
            t["status"] = "verified"
        evidence = {
            impl_task["id"]: {
                "task_type": "implementation",
                "evidence_path": "src/parser.py",
                "recorded_at": "2026-06-29T00:00:00Z",
                "git_change_verified_at_record_time": True,
            },
            qa_task["id"]: {
                "task_type": "qa",
                "evidence_path": "tests/test_parser.py",
                "recorded_at": "2026-06-29T00:00:00Z",
                "git_change_verified_at_record_time": True,
            },
        }
        run_data = self._fully_satisfied_run_data(tasks, evidence)
        report = self.mod.build_run_report(run_data, "RUN-001")
        self.assertEqual(report["technical_readiness"], "ready",
                         "technical_readiness must be ready when all evidence present")
        wp = report["work_product_gate"]
        self.assertTrue(wp["gate_satisfied"])

    def test_not_ready_when_evidence_path_stale(self):
        """technical_readiness=not_ready when recorded evidence path no longer a git change."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target)
            run_id = _setup_backend_utility_run(target)

            tasks_raw = _get_tasks_of_type(target, run_id, "implementation")
            impl_task_id = tasks_raw[0]["id"]

            # Create file, record evidence, then commit (making it clean/stale)
            src_dir = target / "src"
            src_dir.mkdir(exist_ok=True)
            src_file = src_dir / "stale.py"
            src_file.write_text("# stale\n")

            # Evidence recorded while file is untracked
            run_ops(["record-work-product-evidence", "--target", str(target),
                     "--task-id", impl_task_id, "--evidence-path", "src/stale.py"])

            # Now commit the file → no longer a worktree change
            subprocess.run(["git", "add", "src/stale.py"], cwd=str(target), check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "commit stale"], cwd=str(target), check=True, capture_output=True)

            # Verify staleness via direct function call
            is_change = self.mod.is_path_git_worktree_change(target, "src/stale.py")
            self.assertFalse(is_change, "File after commit must not be a worktree change")

            # build_run_report with target should detect stale evidence
            devflow = target / ".devflow"
            run_data = json.loads((devflow / "runs" / f"{run_id}.json").read_text())
            for t in run_data["tasks"]:
                t["status"] = "verified"
            run_data["approval_gates"].update({
                "tests_passing": True,
                "qa_sign_off": True,
            })
            run_data["security_review_required"] = False
            run_data["contract_required"] = False
            run_data["contract_gate_satisfied"] = True

            report = self.mod.build_run_report(run_data, "RUN-001", target=target)
            wp = report["work_product_gate"]
            # Find the stale task entry
            stale_entries = [s for s in wp["tasks"] if s.get("evidence_path") == "src/stale.py"]
            if stale_entries:
                self.assertFalse(stale_entries[0].get("git_change_active"),
                                 "Stale evidence must show git_change_active=False")
            self.assertFalse(wp["gate_satisfied"],
                             "Gate must not be satisfied when evidence path is stale")
            self.assertEqual(report["technical_readiness"], "not_ready",
                             "technical_readiness must be not_ready when evidence is stale")

    def test_work_product_gate_in_report_structure(self):
        """build_run_report output contains work_product_gate with required fields."""
        tasks = self.mod.generate_task_graph_nodes("RUN-001", "backend_utility", "Build CSV parser")
        run_data = {
            "run_id": "RUN-001",
            "objective": "Build CSV parser",
            "execution_mode": "subagents",
            "agent_teams_requested": False,
            "tasks": tasks,
            "approval_gates": {},
            "security_review_required": False,
            "contract_required": False,
            "contract_gate_satisfied": True,
        }
        report = self.mod.build_run_report(run_data, "RUN-001")
        self.assertIn("work_product_gate", report)
        wp = report["work_product_gate"]
        self.assertIn("required", wp)
        self.assertIn("status", wp)
        self.assertIn("gate_satisfied", wp)
        self.assertIn("tasks", wp)
        self.assertIn("limitation_note", wp)
        # Limitation note must warn about local-only verification (Turkish or English)
        note = wp["limitation_note"]
        self.assertTrue(
            "causal attribution" in note or "causal" in note.lower() or "attribution" in note.lower()
            or "agent session" in note,
            f"Limitation note must mention agent session / causal attribution: {note!r}",
        )

    def test_generate_run_report_includes_wp_gate_in_scorecard(self):
        """generate-run-report scorecard includes ## Work Product Gate section."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target)
            run_id = _setup_backend_utility_run(target)

            run_ops(["generate-run-report", "--target", str(target)])

            devflow = target / ".devflow"
            scorecard = (devflow / "reports" / f"{run_id}-scorecard.md").read_text()
            self.assertIn("## Work Product Gate", scorecard,
                          "Scorecard must include ## Work Product Gate section")

    def test_not_applicable_when_no_impl_qa_tasks(self):
        """If delivery type has no impl/QA tasks, work_product_gate status=not_applicable."""
        mod = self.mod
        # new_product_discovery has only planning/design/approval tasks
        tasks = mod.generate_task_graph_nodes("RUN-001", "new_product_discovery", "Discover product")
        impl_qa = [t for t in tasks if t["task_type"] in ("implementation", "qa")]
        if impl_qa:
            self.skipTest("new_product_discovery unexpectedly has impl/qa tasks")
        for t in tasks:
            t["status"] = "verified"
        run_data = {
            "run_id": "RUN-001",
            "objective": "Discover product",
            "execution_mode": "subagents",
            "agent_teams_requested": False,
            "tasks": tasks,
            "approval_gates": {"tests_passing": True, "qa_sign_off": True},
            "security_review_required": False,
            "contract_required": False,
            "contract_gate_satisfied": True,
        }
        report = mod.build_run_report(run_data, "RUN-001")
        wp = report["work_product_gate"]
        self.assertEqual(wp["status"], "not_applicable",
                         "Work product gate must be not_applicable when no impl/QA tasks")
        self.assertTrue(wp["gate_satisfied"])


# ---------------------------------------------------------------------------
# Validate work product evidence path — unit tests
# ---------------------------------------------------------------------------

class ValidateWorkProductPathUnitTest(unittest.TestCase):
    """Unit tests for validate_work_product_evidence_path."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_ops_module()
        cls.tmpdir_obj = tempfile.TemporaryDirectory()
        cls.target = Path(cls.tmpdir_obj.name)
        # Create valid files for existence checks
        src = cls.target / "src"
        src.mkdir(exist_ok=True)
        (src / "code.py").write_text("# code\n")
        tests_dir = cls.target / "tests"
        tests_dir.mkdir(exist_ok=True)
        (tests_dir / "test_code.py").write_text("# test\n")

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir_obj.cleanup()

    def test_valid_src_path_for_implementation(self):
        ok, err = self.mod.validate_work_product_evidence_path(
            self.target, "implementation", "src/code.py"
        )
        self.assertTrue(ok, f"Valid src path must be accepted. err={err}")

    def test_valid_test_path_for_qa(self):
        ok, err = self.mod.validate_work_product_evidence_path(
            self.target, "qa", "tests/test_code.py"
        )
        self.assertTrue(ok, f"Valid tests path must be accepted. err={err}")

    def test_empty_path_rejected(self):
        ok, err = self.mod.validate_work_product_evidence_path(self.target, "implementation", "")
        self.assertFalse(ok)

    def test_absolute_path_rejected(self):
        ok, err = self.mod.validate_work_product_evidence_path(
            self.target, "implementation", "/abs/src/code.py"
        )
        self.assertFalse(ok)
        self.assertIn("mutlak", err.lower())

    def test_traversal_rejected(self):
        ok, err = self.mod.validate_work_product_evidence_path(
            self.target, "implementation", "src/../.env"
        )
        self.assertFalse(ok)
        self.assertIn("..", err)

    def test_wildcard_rejected(self):
        ok, err = self.mod.validate_work_product_evidence_path(
            self.target, "implementation", "src/*.py"
        )
        self.assertFalse(ok)
        self.assertIn("wildcard", err.lower())

    def test_constants_exposed(self):
        """Key constants are accessible."""
        self.assertIn("src/", self.mod.IMPLEMENTATION_EVIDENCE_PREFIXES)
        self.assertIn("tests/", self.mod.QA_EVIDENCE_PREFIXES)
        self.assertEqual(self.mod.WORK_PRODUCT_GATE_EXIT_CODE, 19)
        self.assertIn("implementation", self.mod.WORK_PRODUCT_REQUIRED_TASK_TYPES)
        self.assertIn("qa", self.mod.WORK_PRODUCT_REQUIRED_TASK_TYPES)
        self.assertIn("completed", self.mod.WORK_PRODUCT_GATE_BLOCKED_STATUSES)
        self.assertIn("verified", self.mod.WORK_PRODUCT_GATE_BLOCKED_STATUSES)

    def test_task_packet_has_work_product_requirements_for_impl(self):
        """Task packet for implementation task includes work_product_requirements."""
        mod = self.mod
        tasks = mod.generate_task_graph_nodes("RUN-001", "backend_utility", "Build CSV parser")
        impl_task = next(t for t in tasks if t["task_type"] == "implementation")
        packet = mod.generate_task_packet_dict(impl_task, "RUN-001", "Build CSV parser")
        self.assertIn("work_product_requirements", packet,
                      "Implementation task packet must include work_product_requirements")
        wp_req = packet["work_product_requirements"]
        self.assertTrue(wp_req.get("required"))
        instructions = wp_req.get("instructions", [])
        self.assertTrue(any("record-work-product-evidence" in s for s in instructions),
                        "Instructions must mention record-work-product-evidence CLI")
        self.assertTrue(any("Self-reported" in s for s in instructions),
                        "Instructions must warn that self-reported completion is not sufficient")

    def test_task_packet_has_work_product_requirements_for_qa(self):
        """Task packet for QA task includes work_product_requirements."""
        mod = self.mod
        tasks = mod.generate_task_graph_nodes("RUN-001", "backend_utility", "Build CSV parser")
        qa_task = next(t for t in tasks if t["task_type"] == "qa")
        packet = mod.generate_task_packet_dict(qa_task, "RUN-001", "Build CSV parser")
        self.assertIn("work_product_requirements", packet)

    def test_task_packet_planning_has_no_work_product_requirements(self):
        """Planning task packet does NOT include work_product_requirements."""
        mod = self.mod
        tasks = mod.generate_task_graph_nodes("RUN-001", "backend_utility", "Build CSV parser")
        planning_task = next(t for t in tasks if t["task_type"] == "planning")
        packet = mod.generate_task_packet_dict(planning_task, "RUN-001", "Build CSV parser")
        self.assertNotIn("work_product_requirements", packet,
                         "Planning task packet must NOT include work_product_requirements")


# ---------------------------------------------------------------------------
# Django-layout paths (nested application packages)
# ---------------------------------------------------------------------------

class DjangoLayoutPathsTest(unittest.TestCase):
    """Framework-layout-aware validation for conventional Django app structures."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_ops_module()
        cls.tmpdir_obj = tempfile.TemporaryDirectory()
        cls.target = Path(cls.tmpdir_obj.name)

        # jobs/views.py
        jobs_dir = cls.target / "jobs"
        jobs_dir.mkdir(parents=True, exist_ok=True)
        (jobs_dir / "views.py").write_text("# views\n", encoding="utf-8")

        # jobs/templates/jobs/dashboard.html
        tmpl_dir = cls.target / "jobs" / "templates" / "jobs"
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        (tmpl_dir / "dashboard.html").write_text("<!-- dashboard -->\n", encoding="utf-8")

        # jobs/tests.py
        (jobs_dir / "tests.py").write_text("# tests\n", encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir_obj.cleanup()

    def _validate(self, task_type, path):
        return self.mod.validate_work_product_evidence_path(self.target, task_type, path)

    # --- Implementation evidence ---

    def test_jobs_views_accepted_for_implementation(self):
        ok, err = self._validate("implementation", "jobs/views.py")
        self.assertTrue(ok, f"jobs/views.py must be accepted as implementation evidence. err={err}")

    def test_jobs_template_html_accepted_for_implementation(self):
        ok, err = self._validate("implementation", "jobs/templates/jobs/dashboard.html")
        self.assertTrue(ok,
            f"jobs/templates/jobs/dashboard.html must be accepted as implementation evidence. err={err}")

    # --- QA evidence ---

    def test_jobs_tests_accepted_for_qa(self):
        ok, err = self._validate("qa", "jobs/tests.py")
        self.assertTrue(ok, f"jobs/tests.py must be accepted as QA evidence. err={err}")

    def test_jobs_views_rejected_for_qa(self):
        ok, err = self._validate("qa", "jobs/views.py")
        self.assertFalse(ok, "jobs/views.py must be rejected as QA evidence")

    # --- Safety restrictions remain in force ---

    def test_docs_path_still_rejected(self):
        ok, _ = self._validate("implementation", "docs/config/setup.md")
        self.assertFalse(ok, "docs/ path must still be rejected")

    def test_migration_component_still_rejected(self):
        # Create the file so only the path component check fires, not existence
        mig_dir = self.target / "jobs" / "migrations"
        mig_dir.mkdir(parents=True, exist_ok=True)
        (mig_dir / "0001_initial.py").write_text("# migration\n", encoding="utf-8")
        ok, err = self._validate("implementation", "jobs/migrations/0001_initial.py")
        self.assertFalse(ok, f"migration path component must still be rejected. err={err}")

    def test_secret_filename_still_rejected(self):
        secret_dir = self.target / "jobs"
        (secret_dir / "secret_key.py").write_text("# secret\n", encoding="utf-8")
        ok, _ = self._validate("implementation", "jobs/secret_key.py")
        self.assertFalse(ok, "secret filename must still be rejected")

    def test_env_file_still_rejected(self):
        jobs_dir = self.target / "jobs"
        (jobs_dir / ".env").write_text("SECRET=x\n", encoding="utf-8")
        ok, _ = self._validate("implementation", "jobs/.env")
        self.assertFalse(ok, ".env file must still be rejected")


if __name__ == "__main__":
    unittest.main()
