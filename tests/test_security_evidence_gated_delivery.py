"""
Tests for Risk-Gated Security Evidence & Release Gate.

Covers 12 scenarios:
 1. Risk signal containing objective → security task injected into task graph
 2. Low-risk backend_utility → no security task (template unchanged)
 3. Risky run + no evidence → technical_readiness=not_ready, status=not_ready
 4. record-security-evidence on low-risk run → rejected (exit 17)
 5. Valid docs/quality/security-reports/... path → accepted (exit 0)
 6. Absolute/traversal/wildcard/wrong-prefix/non-existent paths → rejected (exit 17)
 7. pass + none/low severity → security_gate_satisfied=True
 8. blocked + medium/high/critical → security_gate_satisfied=False
 9. Invalid verdict+severity combos → rejected (exit 17)
10. Full scenario: risky + QA + pass evidence + human=False → awaiting_human_approval
11. State JSON, report JSON, and scorecard all project consistent security values
12. (Regression guard) Low-risk run still produces not_applicable in build_run_report
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
    spec = importlib.util.spec_from_file_location("devflow_ops_sec_ev", OPS_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_git_repo(path: Path, branch: str = "feature-sec-test") -> None:
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
    readme.write_text("security evidence test project\n", encoding="utf-8")
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


def _setup_risky_run(target: Path, objective: str = "Add REST API endpoint with JWT auth") -> str:
    """Init, create-run, generate-task-graph for a risky objective. Returns run_id."""
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


def _setup_lowrisk_run(target: Path, objective: str = "Parse CSV files") -> str:
    """Init, create-run, generate-task-graph for a low-risk objective. Returns run_id."""
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


def _create_security_report(target: Path, filename: str = "sec-report.md") -> str:
    """Create a dummy security report file and return its relative path."""
    report_dir = target / "docs" / "quality" / "security-reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_file = report_dir / filename
    report_file.write_text(
        "# Security Review\n\nNo critical findings.\n", encoding="utf-8"
    )
    return f"docs/quality/security-reports/{filename}"


# ---------------------------------------------------------------------------
# Test 1 & 2: Task graph injection
# ---------------------------------------------------------------------------

class TaskGraphSecurityInjectionTest(unittest.TestCase):
    """Tests 1 and 2: Security task injection based on risk signals."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_ops_module()

    def test_risk_signal_injects_security_review_task(self):
        """Test 1: Objective with auth/API risk signal → security task in graph."""
        run_id = "RUN-001"
        objective = "Add REST API endpoint with JWT authentication"
        tasks = self.mod.generate_task_graph_nodes(run_id, "backend_utility", objective)
        task_types = [t["task_type"] for t in tasks]
        self.assertIn("security_review", task_types, (
            f"Expected security_review task for risky objective. Got task types: {task_types}"
        ))

    def test_risk_signal_security_task_assigned_to_security_red_team(self):
        """Risk-signal task gets the correct role."""
        run_id = "RUN-001"
        objective = "Add REST API endpoint with JWT authentication"
        tasks = self.mod.generate_task_graph_nodes(run_id, "backend_utility", objective)
        sec_tasks = [t for t in tasks if t["task_type"] == "security_review"]
        self.assertEqual(len(sec_tasks), 1)
        self.assertEqual(sec_tasks[0]["assigned_role"], "security-red-team")

    def test_risk_signal_security_task_depends_on_implementation_and_qa(self):
        """Security Review task must depend on implementation and QA tasks."""
        run_id = "RUN-001"
        objective = "Add REST API endpoint with JWT authentication"
        tasks = self.mod.generate_task_graph_nodes(run_id, "backend_utility", objective)
        sec_task = next(t for t in tasks if t["task_type"] == "security_review")
        dep_ids = sec_task["dependency_ids"]
        impl_ids = {t["id"] for t in tasks if t["task_type"] == "implementation"}
        qa_ids = {t["id"] for t in tasks if t["task_type"] == "qa"}
        self.assertTrue(
            impl_ids & set(dep_ids) or qa_ids & set(dep_ids),
            f"Security task should depend on implementation/QA. deps={dep_ids}"
        )

    def test_risk_signal_release_task_depends_on_security_review(self):
        """Release/integration task must depend on Security Review."""
        run_id = "RUN-001"
        objective = "Add REST API endpoint with JWT authentication"
        tasks = self.mod.generate_task_graph_nodes(run_id, "backend_utility", objective)
        sec_task = next(t for t in tasks if t["task_type"] == "security_review")
        release_tasks = [t for t in tasks if t["task_type"] in ("release", "integration")]
        self.assertTrue(release_tasks, "Expected a release/integration task")
        release = release_tasks[-1]
        self.assertIn(
            sec_task["id"],
            release["dependency_ids"],
            f"Release task must depend on security review. release_deps={release['dependency_ids']}"
        )

    def test_low_risk_backend_utility_has_no_security_task(self):
        """Test 2: Low-risk objective → no security task injected."""
        run_id = "RUN-001"
        objective = "Parse CSV files and compute summary statistics"
        tasks = self.mod.generate_task_graph_nodes(run_id, "backend_utility", objective)
        task_types = [t["task_type"] for t in tasks]
        self.assertNotIn("security_review", task_types, (
            f"Low-risk run must not have a security_review task. types={task_types}"
        ))

    def test_low_risk_backend_utility_has_four_tasks(self):
        """Low-risk backend_utility preserves the original 4-task template."""
        run_id = "RUN-001"
        objective = "Parse CSV files and compute summary statistics"
        tasks = self.mod.generate_task_graph_nodes(run_id, "backend_utility", objective)
        self.assertEqual(len(tasks), 4, (
            f"Low-risk backend_utility should have 4 tasks. Got {len(tasks)}: "
            f"{[t['task_type'] for t in tasks]}"
        ))

    def test_risky_backend_utility_has_five_tasks(self):
        """Risky backend_utility should have 5 tasks (4 original + injected security)."""
        run_id = "RUN-001"
        objective = "Add REST API endpoint with JWT authentication"
        tasks = self.mod.generate_task_graph_nodes(run_id, "backend_utility", objective)
        self.assertEqual(len(tasks), 5, (
            f"Risky backend_utility should have 5 tasks. Got {len(tasks)}: "
            f"{[t['task_type'] for t in tasks]}"
        ))

    def test_external_service_signal_injects_security_task(self):
        """External service signal also triggers security task injection."""
        run_id = "RUN-001"
        objective = "Integrate payment gateway via Stripe external API"
        tasks = self.mod.generate_task_graph_nodes(run_id, "backend_utility", objective)
        task_types = [t["task_type"] for t in tasks]
        self.assertIn("security_review", task_types)

    def test_new_feature_already_has_security_no_double_inject(self):
        """new_feature already includes security_review; injection must not duplicate it."""
        run_id = "RUN-001"
        objective = "Add REST API endpoint with JWT authentication"
        tasks = self.mod.generate_task_graph_nodes(run_id, "new_feature", objective)
        sec_count = sum(1 for t in tasks if t["task_type"] == "security_review")
        self.assertEqual(sec_count, 1, (
            f"new_feature should have exactly 1 security_review task. Got {sec_count}"
        ))


# ---------------------------------------------------------------------------
# Test 3 & 12: build_run_report state machine (unit-level)
# ---------------------------------------------------------------------------

class SecurityGateStateMachineTest(unittest.TestCase):
    """Tests 3 and 12: Security gate 3-state machine in build_run_report."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_ops_module()

    def _verified_tasks(self, delivery_type: str, objective: str) -> list:
        tasks = self.mod.generate_task_graph_nodes("RUN-001", delivery_type, objective)
        for t in tasks:
            t["status"] = "verified"
        return tasks

    def test_risky_run_no_evidence_is_not_ready(self):
        """Test 3: Risky run + no evidence → not_ready status."""
        objective = "Add REST API endpoint with JWT authentication"
        run_data = {
            "run_id": "RUN-001",
            "objective": objective,
            "execution_mode": "subagents",
            "agent_teams_requested": False,
            "tasks": self._verified_tasks("backend_utility", objective),
            "approval_gates": {
                "tests_passing": True,
                "qa_sign_off": True,
                "security_review_complete": False,
                "human_approval": False,
            },
            "security_review_required": True,
            "security_applicability_reason": "api_or_http_surface",
        }
        report = self.mod.build_run_report(run_data, "RUN-001")
        sec = report["security_applicability"]
        self.assertEqual(sec["security_review_status"], "pending")
        self.assertFalse(sec["security_gate_satisfied"])
        self.assertEqual(report["technical_readiness"], "not_ready")
        self.assertEqual(report["status"], "not_ready")
        self.assertEqual(report["merge_recommendation"], "not_ready")

    def test_risky_run_with_pass_evidence_is_gate_satisfied(self):
        """Test 7a: pass + none → security_gate_satisfied=True."""
        objective = "Add REST API endpoint with JWT authentication"
        run_data = {
            "run_id": "RUN-001",
            "objective": objective,
            "execution_mode": "subagents",
            "agent_teams_requested": False,
            "tasks": self._verified_tasks("backend_utility", objective),
            "approval_gates": {
                "tests_passing": True,
                "qa_sign_off": True,
                "security_review_complete": False,
                "human_approval": False,
            },
            "security_review_required": True,
            "security_applicability_reason": "api_or_http_surface",
            "security_review_status": "completed",
            "security_gate_satisfied": True,
            "security_evidence": {
                "verdict": "pass",
                "max_severity": "none",
                "evidence_path": "docs/quality/security-reports/sec-report.md",
                "recorded_at": "2026-06-28T12:00:00Z",
                "provenance": "generated_in_run",
            },
        }
        report = self.mod.build_run_report(run_data, "RUN-001")
        sec = report["security_applicability"]
        self.assertEqual(sec["security_review_status"], "completed")
        self.assertTrue(sec["security_gate_satisfied"])

    def test_risky_run_with_pass_low_evidence_is_gate_satisfied(self):
        """Test 7b: pass + low → security_gate_satisfied=True."""
        objective = "Add REST API endpoint with JWT authentication"
        run_data = {
            "run_id": "RUN-001",
            "objective": objective,
            "execution_mode": "subagents",
            "agent_teams_requested": False,
            "tasks": self._verified_tasks("backend_utility", objective),
            "approval_gates": {
                "tests_passing": True,
                "qa_sign_off": True,
                "security_review_complete": False,
                "human_approval": False,
            },
            "security_review_required": True,
            "security_applicability_reason": "api_or_http_surface",
            "security_review_status": "completed",
            "security_gate_satisfied": True,
            "security_evidence": {
                "verdict": "pass",
                "max_severity": "low",
                "evidence_path": "docs/quality/security-reports/sec-report.md",
                "recorded_at": "2026-06-28T12:00:00Z",
                "provenance": "generated_in_run",
            },
        }
        report = self.mod.build_run_report(run_data, "RUN-001")
        self.assertTrue(report["security_applicability"]["security_gate_satisfied"])

    def test_risky_run_with_blocked_evidence_is_gate_not_satisfied(self):
        """Test 8: blocked + medium → security_gate_satisfied=False, not_ready."""
        objective = "Add REST API endpoint with JWT authentication"
        run_data = {
            "run_id": "RUN-001",
            "objective": objective,
            "execution_mode": "subagents",
            "agent_teams_requested": False,
            "tasks": self._verified_tasks("backend_utility", objective),
            "approval_gates": {
                "tests_passing": True,
                "qa_sign_off": True,
                "security_review_complete": False,
                "human_approval": False,
            },
            "security_review_required": True,
            "security_applicability_reason": "api_or_http_surface",
            "security_review_status": "completed",
            "security_gate_satisfied": False,
            "security_evidence": {
                "verdict": "blocked",
                "max_severity": "medium",
                "evidence_path": "docs/quality/security-reports/sec-report.md",
                "recorded_at": "2026-06-28T12:00:00Z",
                "provenance": "generated_in_run",
            },
        }
        report = self.mod.build_run_report(run_data, "RUN-001")
        sec = report["security_applicability"]
        self.assertEqual(sec["security_review_status"], "completed")
        self.assertFalse(sec["security_gate_satisfied"])
        self.assertEqual(report["technical_readiness"], "not_ready")
        self.assertEqual(report["status"], "not_ready")
        self.assertEqual(report["merge_recommendation"], "not_ready")

    def test_full_scenario_pass_evidence_human_false_awaiting_approval(self):
        """Test 10: risky + QA + pass evidence + human=False → awaiting_human_approval."""
        objective = "Add REST API endpoint with JWT authentication"
        tasks = self._verified_tasks("backend_utility", objective)
        run_data = {
            "run_id": "RUN-001",
            "objective": objective,
            "execution_mode": "subagents",
            "agent_teams_requested": False,
            "tasks": tasks,
            "approval_gates": {
                "tests_passing": True,
                "qa_sign_off": True,
                "security_review_complete": True,
                "human_approval": False,
            },
            "security_review_required": True,
            "security_applicability_reason": "api_or_http_surface",
            "security_review_status": "completed",
            "security_gate_satisfied": True,
            "security_evidence": {
                "verdict": "pass",
                "max_severity": "none",
                "evidence_path": "docs/quality/security-reports/sec-report.md",
                "recorded_at": "2026-06-28T12:00:00Z",
                "provenance": "generated_in_run",
            },
        }
        report = self.mod.build_run_report(run_data, "RUN-001")
        self.assertEqual(report["technical_readiness"], "ready")
        self.assertEqual(report["status"], "awaiting_human_approval")
        self.assertEqual(report["merge_recommendation"], "awaiting_human_approval")

    def test_security_evidence_metadata_present_in_report(self):
        """security_applicability.security_evidence is populated from run state."""
        objective = "Add REST API endpoint with JWT authentication"
        evidence_meta = {
            "verdict": "pass",
            "max_severity": "none",
            "evidence_path": "docs/quality/security-reports/sec-report.md",
            "recorded_at": "2026-06-28T12:00:00Z",
            "provenance": "generated_in_run",
        }
        run_data = {
            "run_id": "RUN-001",
            "objective": objective,
            "execution_mode": "subagents",
            "agent_teams_requested": False,
            "tasks": self._verified_tasks("backend_utility", objective),
            "approval_gates": {
                "tests_passing": True,
                "qa_sign_off": True,
                "security_review_complete": True,
                "human_approval": False,
            },
            "security_review_required": True,
            "security_applicability_reason": "api_or_http_surface",
            "security_review_status": "completed",
            "security_gate_satisfied": True,
            "security_evidence": evidence_meta,
        }
        report = self.mod.build_run_report(run_data, "RUN-001")
        sec = report["security_applicability"]
        self.assertIsNotNone(sec.get("security_evidence"))
        self.assertEqual(sec["security_evidence"]["verdict"], "pass")
        self.assertEqual(sec["security_evidence"]["provenance"], "generated_in_run")

    def test_low_risk_run_security_not_applicable_regression(self):
        """Test 12 regression: Low-risk run still produces not_applicable."""
        objective = "Parse CSV files and compute summary statistics"
        tasks = self.mod.generate_task_graph_nodes("RUN-001", "backend_utility", objective)
        for t in tasks:
            t["status"] = "verified"
        run_data = {
            "run_id": "RUN-001",
            "objective": objective,
            "execution_mode": "subagents",
            "agent_teams_requested": False,
            "tasks": tasks,
            "approval_gates": {
                "tests_passing": True,
                "qa_sign_off": True,
                "security_review_complete": False,
                "human_approval": False,
            },
            "security_review_required": False,
            "security_applicability_reason": "low_risk_local_utility",
        }
        report = self.mod.build_run_report(run_data, "RUN-001")
        sec = report["security_applicability"]
        self.assertEqual(sec["security_review_status"], "not_applicable")
        self.assertTrue(sec["security_gate_satisfied"])
        self.assertEqual(report["technical_readiness"], "ready")

    def test_backward_compat_security_review_complete_gate(self):
        """Backward compat: security_review_complete=True satisfies gate without evidence field."""
        objective = "Add REST API endpoint with JWT authentication"
        tasks = self.mod.generate_task_graph_nodes("RUN-001", "backend_utility", objective)
        for t in tasks:
            t["status"] = "verified"
        run_data = {
            "run_id": "RUN-001",
            "objective": objective,
            "execution_mode": "subagents",
            "agent_teams_requested": False,
            "tasks": tasks,
            "approval_gates": {
                "tests_passing": True,
                "qa_sign_off": True,
                "security_review_complete": True,
                "human_approval": False,
            },
            "security_review_required": True,
            "security_applicability_reason": "api_or_http_surface",
        }
        report = self.mod.build_run_report(run_data, "RUN-001")
        sec = report["security_applicability"]
        self.assertEqual(sec["security_review_status"], "completed")
        self.assertTrue(sec["security_gate_satisfied"])


# ---------------------------------------------------------------------------
# Test path validation (unit-level)
# ---------------------------------------------------------------------------

class SecurityEvidencePathValidationTest(unittest.TestCase):
    """Validate_security_evidence_path unit tests."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_ops_module()
        cls.tmpdir_obj = tempfile.TemporaryDirectory()
        cls.target = Path(cls.tmpdir_obj.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir_obj.cleanup()

    def _create_report(self, filename: str = "report.md") -> str:
        report_dir = self.target / "docs" / "quality" / "security-reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / filename).write_text("# Report\n", encoding="utf-8")
        return f"docs/quality/security-reports/{filename}"

    def test_valid_path_accepted(self):
        """Test 5: Valid docs/quality/security-reports/... path is accepted."""
        rel_path = self._create_report("valid-report.md")
        ok, err = self.mod.validate_security_evidence_path(self.target, rel_path)
        self.assertTrue(ok, f"Expected valid path to be accepted. Error: {err}")
        self.assertEqual(err, "")

    def test_absolute_path_rejected(self):
        """Test 6a: Absolute path is rejected."""
        abs_path = str(self.target / "docs" / "quality" / "security-reports" / "report.md")
        ok, err = self.mod.validate_security_evidence_path(self.target, abs_path)
        self.assertFalse(ok)
        self.assertIn("mutlak", err.lower())

    def test_traversal_rejected(self):
        """Test 6b: Path traversal (..) is rejected."""
        ok, err = self.mod.validate_security_evidence_path(
            self.target, "docs/quality/security-reports/../../../etc/passwd"
        )
        self.assertFalse(ok)
        self.assertIn("..", err)

    def test_wildcard_rejected(self):
        """Test 6c: Wildcard in path is rejected."""
        ok, err = self.mod.validate_security_evidence_path(
            self.target, "docs/quality/security-reports/*.md"
        )
        self.assertFalse(ok)
        self.assertIn("wildcard", err.lower())

    def test_wrong_prefix_rejected(self):
        """Test 6d: Path not under docs/quality/security-reports/ is rejected."""
        ok, err = self.mod.validate_security_evidence_path(
            self.target, "docs/quality/qa-evidence/report.md"
        )
        self.assertFalse(ok)
        self.assertIn("docs/quality/security-reports/", err)

    def test_devflow_path_rejected(self):
        """Test 6e: .devflow/ path is rejected (wrong prefix)."""
        ok, err = self.mod.validate_security_evidence_path(
            self.target, ".devflow/runs/security-report.md"
        )
        self.assertFalse(ok)
        self.assertIn("docs/quality/security-reports/", err)

    def test_claude_path_rejected(self):
        """Test 6f: .claude/ path is rejected (wrong prefix)."""
        ok, err = self.mod.validate_security_evidence_path(
            self.target, ".claude/agents/security-red-team.md"
        )
        self.assertFalse(ok)
        self.assertIn("docs/quality/security-reports/", err)

    def test_nonexistent_file_rejected(self):
        """Test 6g: File with correct prefix but that doesn't exist is rejected."""
        ok, err = self.mod.validate_security_evidence_path(
            self.target, "docs/quality/security-reports/nonexistent-xyz-report.md"
        )
        self.assertFalse(ok)
        self.assertIn("bulunamadı", err)


# ---------------------------------------------------------------------------
# Test 4, 7, 8, 9: CLI record-security-evidence integration tests
# ---------------------------------------------------------------------------

class RecordSecurityEvidenceCLITest(unittest.TestCase):
    """CLI tests for record-security-evidence subcommand."""

    def setUp(self):
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.target = Path(self.tmpdir_obj.name)
        make_git_repo(self.target)

    def tearDown(self):
        self.tmpdir_obj.cleanup()

    def _risky_run_with_report(self, objective: str = "Add REST API endpoint with JWT auth") -> tuple:
        """Create a risky run and an evidence file. Returns (run_id, evidence_path)."""
        run_id = _setup_risky_run(self.target, objective)
        evidence_path = _create_security_report(self.target)
        return run_id, evidence_path

    def test_rejected_on_low_risk_run(self):
        """Test 4: record-security-evidence rejected on low-risk run (exit 17)."""
        _setup_lowrisk_run(self.target)
        evidence_path = _create_security_report(self.target)
        result = run_ops([
            "record-security-evidence",
            "--target", str(self.target),
            "--verdict", "pass",
            "--max-severity", "none",
            "--evidence-path", evidence_path,
        ])
        self.assertEqual(result.returncode, 17, (
            f"Expected exit 17 for low-risk run. stderr={result.stderr!r}"
        ))
        self.assertIn("security_review_required", result.stderr.lower().replace("_", "_"))

    def test_valid_pass_none_accepted(self):
        """Test 5 / Test 7a: Valid pass+none on risky run → accepted (exit 0)."""
        _, evidence_path = self._risky_run_with_report()
        result = run_ops([
            "record-security-evidence",
            "--target", str(self.target),
            "--verdict", "pass",
            "--max-severity", "none",
            "--evidence-path", evidence_path,
        ])
        self.assertEqual(result.returncode, 0, (
            f"Expected exit 0 for valid evidence. stderr={result.stderr!r}"
        ))

    def test_pass_none_writes_gate_satisfied_true(self):
        """Test 7a (write): pass+none writes security_gate_satisfied=True to run state."""
        run_id, evidence_path = self._risky_run_with_report()
        run_ops([
            "record-security-evidence",
            "--target", str(self.target),
            "--verdict", "pass",
            "--max-severity", "none",
            "--evidence-path", evidence_path,
        ])
        run_state = json.loads(
            (self.target / ".devflow" / "runs" / f"{run_id}.json").read_text()
        )
        self.assertTrue(run_state["security_gate_satisfied"])
        self.assertEqual(run_state["security_review_status"], "completed")
        self.assertEqual(run_state["security_evidence"]["verdict"], "pass")
        self.assertEqual(run_state["security_evidence"]["provenance"], "generated_in_run")

    def test_pass_low_writes_gate_satisfied_true(self):
        """Test 7b: pass+low → gate satisfied."""
        run_id, evidence_path = self._risky_run_with_report()
        run_ops([
            "record-security-evidence",
            "--target", str(self.target),
            "--verdict", "pass",
            "--max-severity", "low",
            "--evidence-path", evidence_path,
        ])
        run_state = json.loads(
            (self.target / ".devflow" / "runs" / f"{run_id}.json").read_text()
        )
        self.assertTrue(run_state["security_gate_satisfied"])

    def test_blocked_medium_writes_gate_satisfied_false(self):
        """Test 8a: blocked+medium → gate NOT satisfied."""
        run_id, evidence_path = self._risky_run_with_report()
        run_ops([
            "record-security-evidence",
            "--target", str(self.target),
            "--verdict", "blocked",
            "--max-severity", "medium",
            "--evidence-path", evidence_path,
        ])
        run_state = json.loads(
            (self.target / ".devflow" / "runs" / f"{run_id}.json").read_text()
        )
        self.assertFalse(run_state["security_gate_satisfied"])
        self.assertEqual(run_state["security_evidence"]["verdict"], "blocked")

    def test_blocked_high_writes_gate_satisfied_false(self):
        """Test 8b: blocked+high → gate NOT satisfied."""
        run_id, evidence_path = self._risky_run_with_report()
        run_ops([
            "record-security-evidence",
            "--target", str(self.target),
            "--verdict", "blocked",
            "--max-severity", "high",
            "--evidence-path", evidence_path,
        ])
        run_state = json.loads(
            (self.target / ".devflow" / "runs" / f"{run_id}.json").read_text()
        )
        self.assertFalse(run_state["security_gate_satisfied"])

    def test_blocked_critical_writes_gate_satisfied_false(self):
        """Test 8c: blocked+critical → gate NOT satisfied."""
        run_id, evidence_path = self._risky_run_with_report()
        run_ops([
            "record-security-evidence",
            "--target", str(self.target),
            "--verdict", "blocked",
            "--max-severity", "critical",
            "--evidence-path", evidence_path,
        ])
        run_state = json.loads(
            (self.target / ".devflow" / "runs" / f"{run_id}.json").read_text()
        )
        self.assertFalse(run_state["security_gate_satisfied"])

    def test_pass_medium_combo_rejected(self):
        """Test 9a: pass+medium is an invalid combo → exit 17."""
        _, evidence_path = self._risky_run_with_report()
        result = run_ops([
            "record-security-evidence",
            "--target", str(self.target),
            "--verdict", "pass",
            "--max-severity", "medium",
            "--evidence-path", evidence_path,
        ])
        self.assertEqual(result.returncode, 17, (
            f"pass+medium should be rejected. stderr={result.stderr!r}"
        ))

    def test_pass_critical_combo_rejected(self):
        """Test 9b: pass+critical is an invalid combo → exit 17."""
        _, evidence_path = self._risky_run_with_report()
        result = run_ops([
            "record-security-evidence",
            "--target", str(self.target),
            "--verdict", "pass",
            "--max-severity", "critical",
            "--evidence-path", evidence_path,
        ])
        self.assertEqual(result.returncode, 17)

    def test_blocked_none_combo_rejected(self):
        """Test 9c: blocked+none is an invalid combo → exit 17."""
        _, evidence_path = self._risky_run_with_report()
        result = run_ops([
            "record-security-evidence",
            "--target", str(self.target),
            "--verdict", "blocked",
            "--max-severity", "none",
            "--evidence-path", evidence_path,
        ])
        self.assertEqual(result.returncode, 17, (
            f"blocked+none should be rejected. stderr={result.stderr!r}"
        ))

    def test_blocked_low_combo_rejected(self):
        """Test 9d: blocked+low is an invalid combo → exit 17."""
        _, evidence_path = self._risky_run_with_report()
        result = run_ops([
            "record-security-evidence",
            "--target", str(self.target),
            "--verdict", "blocked",
            "--max-severity", "low",
            "--evidence-path", evidence_path,
        ])
        self.assertEqual(result.returncode, 17)

    def test_absolute_path_rejected_exit_17(self):
        """Absolute evidence path → exit 17."""
        _, _ = self._risky_run_with_report()
        result = run_ops([
            "record-security-evidence",
            "--target", str(self.target),
            "--verdict", "pass",
            "--max-severity", "none",
            "--evidence-path", "/absolute/path/to/report.md",
        ])
        self.assertEqual(result.returncode, 17)

    def test_traversal_path_rejected_exit_17(self):
        """Path traversal evidence path → exit 17."""
        _, _ = self._risky_run_with_report()
        result = run_ops([
            "record-security-evidence",
            "--target", str(self.target),
            "--verdict", "pass",
            "--max-severity", "none",
            "--evidence-path", "docs/quality/security-reports/../../../etc/passwd",
        ])
        self.assertEqual(result.returncode, 17)

    def test_wrong_prefix_path_rejected_exit_17(self):
        """Path with wrong prefix → exit 17."""
        _, _ = self._risky_run_with_report()
        result = run_ops([
            "record-security-evidence",
            "--target", str(self.target),
            "--verdict", "pass",
            "--max-severity", "none",
            "--evidence-path", "docs/quality/qa-evidence/report.md",
        ])
        self.assertEqual(result.returncode, 17)

    def test_nonexistent_file_rejected_exit_17(self):
        """Valid prefix path but file doesn't exist → exit 17."""
        _, _ = self._risky_run_with_report()
        result = run_ops([
            "record-security-evidence",
            "--target", str(self.target),
            "--verdict", "pass",
            "--max-severity", "none",
            "--evidence-path", "docs/quality/security-reports/does-not-exist.md",
        ])
        self.assertEqual(result.returncode, 17)


# ---------------------------------------------------------------------------
# Test 10 & 11: Full end-to-end scenario + consistency check
# ---------------------------------------------------------------------------

class SecurityEvidenceFullScenarioTest(unittest.TestCase):
    """Tests 10 and 11: Full CLI scenario and state/report/scorecard consistency."""

    def setUp(self):
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.target = Path(self.tmpdir_obj.name)
        make_git_repo(self.target)

    def tearDown(self):
        self.tmpdir_obj.cleanup()

    def _mark_all_tasks_verified(self, run_id: str) -> None:
        """Directly update all tasks to 'verified' in run state."""
        run_file = self.target / ".devflow" / "runs" / f"{run_id}.json"
        run_data = json.loads(run_file.read_text())
        for t in run_data["tasks"]:
            t["status"] = "verified"
        run_file.write_text(json.dumps(run_data, indent=2) + "\n", encoding="utf-8")

    def _set_qa_gates(self, run_id: str) -> None:
        """Set tests_passing and qa_sign_off gates in run state."""
        run_file = self.target / ".devflow" / "runs" / f"{run_id}.json"
        run_data = json.loads(run_file.read_text())
        run_data.setdefault("approval_gates", {})
        run_data["approval_gates"]["tests_passing"] = True
        run_data["approval_gates"]["qa_sign_off"] = True
        run_file.write_text(json.dumps(run_data, indent=2) + "\n", encoding="utf-8")

    def test_full_pass_evidence_scenario_awaiting_human_approval(self):
        """Test 10: Full risky + QA + pass evidence + human=False → awaiting_human_approval."""
        objective = "Add REST API endpoint with JWT authentication"
        run_id = _setup_risky_run(self.target, objective)
        self._mark_all_tasks_verified(run_id)
        self._set_qa_gates(run_id)

        evidence_path = _create_security_report(self.target)
        result = run_ops([
            "record-security-evidence",
            "--target", str(self.target),
            "--verdict", "pass",
            "--max-severity", "none",
            "--evidence-path", evidence_path,
        ])
        self.assertEqual(result.returncode, 0, f"Evidence recording failed: {result.stderr!r}")

        report_result = run_ops(["generate-run-report", "--target", str(self.target)])
        self.assertEqual(report_result.returncode, 0, f"Report generation failed: {report_result.stderr!r}")

        report_file = self.target / ".devflow" / "reports" / f"{run_id}-report.json"
        report = json.loads(report_file.read_text())

        self.assertEqual(report["technical_readiness"], "ready")
        self.assertEqual(report["status"], "awaiting_human_approval")
        self.assertEqual(report["merge_recommendation"], "awaiting_human_approval")
        sec = report["security_applicability"]
        self.assertEqual(sec["security_review_status"], "completed")
        self.assertTrue(sec["security_gate_satisfied"])

    def test_state_report_scorecard_consistent_security_values(self):
        """Test 11: Run state JSON, report JSON, and scorecard all agree on security fields."""
        objective = "Add REST API endpoint with JWT authentication"
        run_id = _setup_risky_run(self.target, objective)
        self._mark_all_tasks_verified(run_id)
        self._set_qa_gates(run_id)

        evidence_path = _create_security_report(self.target, "consistency-report.md")
        run_ops([
            "record-security-evidence",
            "--target", str(self.target),
            "--verdict", "pass",
            "--max-severity", "low",
            "--evidence-path", evidence_path,
        ])

        run_ops(["generate-run-report", "--target", str(self.target)])

        # Read the three sources
        run_file = self.target / ".devflow" / "runs" / f"{run_id}.json"
        run_state = json.loads(run_file.read_text())

        report_file = self.target / ".devflow" / "reports" / f"{run_id}-report.json"
        report = json.loads(report_file.read_text())

        scorecard_file = self.target / ".devflow" / "reports" / f"{run_id}-scorecard.md"
        scorecard_text = scorecard_file.read_text()

        # All three must agree that security_gate_satisfied=True
        self.assertTrue(run_state["security_gate_satisfied"],
                        "run state: security_gate_satisfied should be True")
        self.assertTrue(report["security_applicability"]["security_gate_satisfied"],
                        "report: security_gate_satisfied should be True")
        self.assertIn("security_gate_satisfied: True", scorecard_text,
                      "scorecard: should show security_gate_satisfied: True")

        # All three must agree security_review_status=completed
        self.assertEqual(run_state["security_review_status"], "completed",
                         "run state: security_review_status should be completed")
        self.assertEqual(report["security_applicability"]["security_review_status"], "completed",
                         "report: security_review_status should be completed")
        self.assertIn("security_review_status: completed", scorecard_text,
                      "scorecard: should show security_review_status: completed")

        # Scorecard must show evidence metadata
        self.assertIn("evidence_verdict: pass", scorecard_text)
        self.assertIn("evidence_max_severity: low", scorecard_text)
        self.assertIn(evidence_path, scorecard_text)
        self.assertIn("evidence_provenance: generated_in_run", scorecard_text)

        # Scorecard must include the causal binding disclaimer
        self.assertIn("causal binding", scorecard_text.lower())

    def test_blocked_evidence_full_scenario_not_ready(self):
        """blocked evidence → full scenario stays not_ready even with all tasks verified."""
        objective = "Add REST API endpoint with JWT authentication"
        run_id = _setup_risky_run(self.target, objective)
        self._mark_all_tasks_verified(run_id)
        self._set_qa_gates(run_id)

        evidence_path = _create_security_report(self.target, "blocker-report.md")
        run_ops([
            "record-security-evidence",
            "--target", str(self.target),
            "--verdict", "blocked",
            "--max-severity", "critical",
            "--evidence-path", evidence_path,
        ])
        run_ops(["generate-run-report", "--target", str(self.target)])

        report_file = self.target / ".devflow" / "reports" / f"{run_id}-report.json"
        report = json.loads(report_file.read_text())

        self.assertEqual(report["technical_readiness"], "not_ready")
        self.assertEqual(report["status"], "not_ready")
        self.assertEqual(report["merge_recommendation"], "not_ready")
        sec = report["security_applicability"]
        self.assertFalse(sec["security_gate_satisfied"])


# ---------------------------------------------------------------------------
# Test: record-security-evidence does not exist before generate-task-graph
# ---------------------------------------------------------------------------

class RecordBeforeGenerateTaskGraphTest(unittest.TestCase):
    """record-security-evidence before generate-task-graph → rejected (no security_review_required)."""

    def setUp(self):
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.target = Path(self.tmpdir_obj.name)
        make_git_repo(self.target)

    def tearDown(self):
        self.tmpdir_obj.cleanup()

    def test_rejected_without_generate_task_graph(self):
        """Without generate-task-graph, security_review_required is not set → exit 17."""
        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target), "--objective", "Add REST API"])

        # Create evidence file but do NOT run generate-task-graph
        _create_security_report(self.target)
        evidence_path = "docs/quality/security-reports/sec-report.md"

        result = run_ops([
            "record-security-evidence",
            "--target", str(self.target),
            "--verdict", "pass",
            "--max-severity", "none",
            "--evidence-path", evidence_path,
        ])
        self.assertEqual(result.returncode, 17, (
            f"Expected exit 17 without generate-task-graph. stderr={result.stderr!r}"
        ))


if __name__ == "__main__":
    unittest.main()
