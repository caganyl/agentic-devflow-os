"""
Tests for Canonical Launch Risk Floor / Security Downgrade Prevention.

Policy: launch risk floor is computed from the launch objective at create-run time
and stored in run state. generate-task-graph applies the floor: effective
security_review_required = floor OR graph-level requirement. The floor can only
raise the security requirement, never lower it.

Scenarios:
 1. Risky launch objective + backend_utility + neutral graph objective
    → security required true, Security Review task injected
 2. Risky launch objective + neutral --objective override
    → security floor not lowered
 3. Low-risk launch objective + backend_utility → not_applicable preserved
 4. Low-risk launch objective + new_feature → mandatory security true
 5. Legacy run state without floor metadata → existing behavior preserved
 6. Risk-floor run + pass/none evidence + all gates → awaiting_human_approval
 7. Risk-floor run + blocked/medium evidence → not_ready even with QA pass
 8. State, JSON report, and scorecard consistent effective security decision
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
    spec = importlib.util.spec_from_file_location("devflow_ops_floor", OPS_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_git_repo(path: Path, branch: str = "feature-floor-test") -> None:
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
    readme.write_text("launch risk floor test project\n", encoding="utf-8")
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


def _read_run_state(target: Path) -> dict:
    devflow = target / ".devflow"
    project = json.loads((devflow / "project.json").read_text())
    run_id = project["current_run_id"]
    run_file = devflow / "runs" / f"{run_id}.json"
    return json.loads(run_file.read_text()), run_id


def _create_security_report(target: Path, filename: str = "floor-report.md") -> str:
    report_dir = target / "docs" / "quality" / "security-reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / filename).write_text("# Security Review\n\nNo critical findings.\n", encoding="utf-8")
    return f"docs/quality/security-reports/{filename}"


def _make_wp_evidence(tasks: list) -> dict:
    """Return mock work_product_evidence for all implementation/QA tasks."""
    ev = {}
    for t in tasks:
        tt = t.get("task_type", "")
        if tt == "implementation":
            ev[t["id"]] = {
                "task_type": "implementation",
                "evidence_path": "src/feature.py",
                "recorded_at": "2026-06-29T00:00:00Z",
                "git_change_verified_at_record_time": True,
            }
        elif tt == "qa":
            ev[t["id"]] = {
                "task_type": "qa",
                "evidence_path": "tests/test_feature.py",
                "recorded_at": "2026-06-29T00:00:00Z",
                "git_change_verified_at_record_time": True,
            }
    return ev


def _create_wp_stub_files(target: Path) -> None:
    """Create untracked stub files so git-status check in build_run_report passes."""
    (target / "src").mkdir(exist_ok=True)
    (target / "src" / "feature.py").write_text("# stub\n", encoding="utf-8")
    (target / "tests").mkdir(exist_ok=True)
    (target / "tests" / "test_feature.py").write_text("# stub\n", encoding="utf-8")


def _mark_all_tasks_verified(target: Path, run_id: str) -> None:
    run_file = target / ".devflow" / "runs" / f"{run_id}.json"
    run_data = json.loads(run_file.read_text())
    for t in run_data["tasks"]:
        t["status"] = "verified"
    _create_wp_stub_files(target)
    run_data["work_product_evidence"] = _make_wp_evidence(run_data["tasks"])
    # Signed, not raw: the gates reject run state this CLI did not write.
    _load_ops_module().write_run_state(target, run_file, run_data)


def _set_qa_gates(target: Path, run_id: str) -> None:
    """Set the QA gates the way a real run does: by measuring, not asserting.

    Recording counts by hand marks the evidence "self_reported" and holds the
    report at "unverified_evidence", so these fixtures run a real (trivially
    passing) command through the CLI instead.
    """
    _record_observed_delegation(target, run_id)
    subprocess.run(
        [sys.executable, str(OPS_SCRIPT), "record-qa-evidence",
         "--target", str(target), "--test-command", "python3 -c pass"],
        capture_output=True, text=True, check=True,
    )


def _record_observed_delegation(target: Path, run_id: str) -> None:
    """Write a SubagentStart event so the run counts as actually delegated.

    Without it the report holds at "unverified_evidence": passing auto gates
    never showed that any agent ran.
    """
    events_dir = target / ".devflow" / "delegation-events"
    events_dir.mkdir(parents=True, exist_ok=True)
    (events_dir / "subagent-start-001.json").write_text(
        json.dumps({
            "hook_event": "SubagentStart",
            "lifecycle_state": "started",
            "run_id": run_id,
            "agent_type": "backend-engineer",
        }),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Scenario 1: Risky launch + backend_utility + neutral graph objective
# ---------------------------------------------------------------------------

class LaunchFloorRiskyObjectiveTest(unittest.TestCase):
    """Risky launch objective must survive neutral graph override."""

    def setUp(self):
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.target = Path(self.tmpdir_obj.name)
        make_git_repo(self.target)

    def tearDown(self):
        self.tmpdir_obj.cleanup()

    def test_risky_launch_neutral_graph_objective_security_required_true(self):
        """Scenario 1: Risky launch objective + backend_utility + neutral --objective → required=True."""
        risky_objective = "Add REST API endpoint with JWT authorization"
        neutral_graph_objective = "Refactor utility module"

        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target), "--objective", risky_objective])
        run_ops([
            "generate-task-graph",
            "--target", str(self.target),
            "--delivery-type", "backend_utility",
            "--objective", neutral_graph_objective,
        ])

        run_state, _ = _read_run_state(self.target)
        self.assertTrue(
            run_state["security_review_required"],
            f"Floor must keep security_review_required=True. state={run_state.get('security_review_required')}"
        )

    def test_risky_launch_neutral_graph_objective_task_injected(self):
        """Scenario 1: Security Review task must be injected despite neutral graph objective."""
        risky_objective = "Add REST API endpoint with JWT authorization"
        neutral_graph_objective = "Refactor utility module"

        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target), "--objective", risky_objective])
        run_ops([
            "generate-task-graph",
            "--target", str(self.target),
            "--delivery-type", "backend_utility",
            "--objective", neutral_graph_objective,
        ])

        run_state, _ = _read_run_state(self.target)
        task_types = [t["task_type"] for t in run_state.get("tasks", [])]
        self.assertIn(
            "security_review", task_types,
            f"Security Review task must be injected. task_types={task_types}"
        )

    def test_risky_launch_neutral_graph_objective_release_depends_on_security(self):
        """Scenario 1: Release task must depend on Security Review when floor triggered."""
        risky_objective = "Add REST API endpoint with JWT authorization"
        neutral_graph_objective = "Refactor utility module"

        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target), "--objective", risky_objective])
        run_ops([
            "generate-task-graph",
            "--target", str(self.target),
            "--delivery-type", "backend_utility",
            "--objective", neutral_graph_objective,
        ])

        run_state, _ = _read_run_state(self.target)
        tasks = run_state.get("tasks", [])
        sec_task = next((t for t in tasks if t["task_type"] == "security_review"), None)
        self.assertIsNotNone(sec_task, "Security task must exist")
        release_tasks = [t for t in tasks if t["task_type"] in ("release", "integration")]
        self.assertTrue(release_tasks, "Release task must exist")
        release = release_tasks[-1]
        self.assertIn(
            sec_task["id"], release["dependency_ids"],
            f"Release task must depend on security review. deps={release['dependency_ids']}"
        )

    def test_risky_launch_floor_metadata_stored_in_run_state(self):
        """Launch risk floor metadata must be stored in run state at create-run time."""
        risky_objective = "Add REST API endpoint with JWT authorization"

        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target), "--objective", risky_objective])

        run_state, _ = _read_run_state(self.target)
        self.assertIn("launch_risk_floor_required", run_state)
        self.assertTrue(run_state["launch_risk_floor_required"])
        self.assertIn("launch_risk_floor_reason", run_state)
        self.assertNotEqual(run_state["launch_risk_floor_reason"], "low_risk_local_utility")


# ---------------------------------------------------------------------------
# Scenario 2: Neutral --objective override cannot lower the floor
# ---------------------------------------------------------------------------

class FloorNotLoweredByObjectiveOverrideTest(unittest.TestCase):
    """Neutral graph --objective must not lower the launch risk floor."""

    def setUp(self):
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.target = Path(self.tmpdir_obj.name)
        make_git_repo(self.target)

    def tearDown(self):
        self.tmpdir_obj.cleanup()

    def test_neutral_override_cannot_lower_floor(self):
        """Scenario 2: Risky launch + neutral --objective override → floor not lowered."""
        risky_objective = "Integrate external payment gateway API with secret token"
        neutral_override = "Add logging"

        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target), "--objective", risky_objective])
        run_ops([
            "generate-task-graph",
            "--target", str(self.target),
            "--delivery-type", "backend_utility",
            "--objective", neutral_override,
        ])

        run_state, _ = _read_run_state(self.target)
        self.assertTrue(run_state["security_review_required"])
        task_types = [t["task_type"] for t in run_state.get("tasks", [])]
        self.assertIn("security_review", task_types)

    def test_reason_preserved_when_floor_is_source(self):
        """When floor triggers and graph does not, floor reason is written to run state."""
        risky_objective = "Integrate external payment gateway API with secret token"
        neutral_override = "Add logging"

        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target), "--objective", risky_objective])
        run_ops([
            "generate-task-graph",
            "--target", str(self.target),
            "--delivery-type", "backend_utility",
            "--objective", neutral_override,
        ])

        run_state, _ = _read_run_state(self.target)
        # Reason must be a closed-enum value, not "low_risk_local_utility"
        self.assertNotEqual(
            run_state.get("security_applicability_reason"), "low_risk_local_utility",
            "Floor reason must not be downgraded to low_risk_local_utility"
        )


# ---------------------------------------------------------------------------
# Scenario 3: Low-risk launch + backend_utility → not_applicable preserved
# ---------------------------------------------------------------------------

class LowRiskFloorPreservesNotApplicableTest(unittest.TestCase):
    """Low-risk launch objective must preserve not_applicable behavior."""

    def setUp(self):
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.target = Path(self.tmpdir_obj.name)
        make_git_repo(self.target)

    def tearDown(self):
        self.tmpdir_obj.cleanup()

    def test_low_risk_launch_backend_utility_not_applicable(self):
        """Scenario 3: Low-risk launch + backend_utility → security_review_required=False."""
        low_risk_objective = "Parse CSV files and compute summary statistics, pure python, no external api"

        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target), "--objective", low_risk_objective])
        run_ops([
            "generate-task-graph",
            "--target", str(self.target),
            "--delivery-type", "backend_utility",
            "--objective", low_risk_objective,
        ])

        run_state, run_id = _read_run_state(self.target)
        self.assertFalse(
            run_state["security_review_required"],
            f"Low-risk must remain not_applicable. state={run_state.get('security_review_required')}"
        )
        self.assertEqual(
            run_state.get("security_applicability_reason"), "low_risk_local_utility"
        )
        task_types = [t["task_type"] for t in run_state.get("tasks", [])]
        self.assertNotIn("security_review", task_types)

    def test_low_risk_floor_metadata_stored_correctly(self):
        """Low-risk launch: floor metadata must reflect not-required at create-run time."""
        low_risk_objective = "Parse CSV files and compute summary statistics, pure python, no external api"

        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target), "--objective", low_risk_objective])

        run_state, _ = _read_run_state(self.target)
        self.assertIn("launch_risk_floor_required", run_state)
        self.assertFalse(run_state["launch_risk_floor_required"])
        self.assertEqual(run_state.get("launch_risk_floor_reason"), "low_risk_local_utility")


# ---------------------------------------------------------------------------
# Scenario 4: Low-risk launch + new_feature → mandatory security true
# ---------------------------------------------------------------------------

class MandatoryDeliveryTypeAlwaysSecureTest(unittest.TestCase):
    """Mandatory delivery types must always require security regardless of launch floor."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_ops_module()

    def test_low_risk_launch_new_feature_mandatory_security(self):
        """Scenario 4 (unit): Low-risk launch + new_feature delivery type → security required."""
        # new_feature is in DELIVERY_TYPES_WITH_MANDATORY_SECURITY_REVIEW
        tasks = self.mod.generate_task_graph_nodes(
            "RUN-001", "new_feature", "Parse CSV files"
        )
        task_types = [t["task_type"] for t in tasks]
        self.assertIn("security_review", task_types)

    def test_low_risk_launch_new_feature_security_in_run_state(self):
        """Scenario 4 (integration): Low-risk launch + new_feature delivery type → required=True in state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir)
            make_git_repo(target)
            low_risk_objective = "Parse CSV files, no external api"

            run_ops(["init-target", "--target", str(target)])
            run_ops(["create-run", "--target", str(target), "--objective", low_risk_objective])
            run_ops([
                "generate-task-graph",
                "--target", str(target),
                "--delivery-type", "new_feature",
                "--objective", low_risk_objective,
            ])

            devflow = target / ".devflow"
            project = json.loads((devflow / "project.json").read_text())
            run_id = project["current_run_id"]
            run_state = json.loads((devflow / "runs" / f"{run_id}.json").read_text())
            self.assertTrue(
                run_state["security_review_required"],
                "new_feature always requires security, even with low-risk launch objective"
            )


# ---------------------------------------------------------------------------
# Scenario 5: Legacy run state without floor metadata → backward compat
# ---------------------------------------------------------------------------

class LegacyRunStateBackwardCompatTest(unittest.TestCase):
    """Legacy run states without launch_risk_floor_* fields must behave as before."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_ops_module()

    def _verified_tasks(self, delivery_type: str, objective: str) -> list:
        tasks = self.mod.generate_task_graph_nodes("RUN-001", delivery_type, objective)
        for t in tasks:
            t["status"] = "verified"
        return tasks

    def test_legacy_required_true_no_floor_field(self):
        """Scenario 5: Legacy state with security_review_required=True, no floor fields → required honored."""
        objective = "Add REST API endpoint with JWT auth"
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
            # No launch_risk_floor_required or launch_risk_floor_reason
        }
        report = self.mod.build_run_report(run_data, "RUN-001")
        sec = report["security_applicability"]
        self.assertEqual(sec["security_review_status"], "pending")
        self.assertFalse(sec["security_gate_satisfied"])
        self.assertEqual(report["technical_readiness"], "not_ready")
        # Floor fields should be None (absent from legacy state)
        self.assertIsNone(sec.get("launch_risk_floor_required"))

    def test_legacy_required_false_no_floor_field(self):
        """Scenario 5: Legacy state with security_review_required=False, no floor fields → not_applicable."""
        objective = "Parse CSV files"
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
            "work_product_evidence": _make_wp_evidence(tasks),
            # No launch_risk_floor_required or launch_risk_floor_reason
        }
        report = self.mod.build_run_report(run_data, "RUN-001")
        sec = report["security_applicability"]
        self.assertEqual(sec["security_review_status"], "not_applicable")
        self.assertTrue(sec["security_gate_satisfied"])
        self.assertEqual(report["technical_readiness"], "ready")


# ---------------------------------------------------------------------------
# Scenario 6: Risk-floor run + pass/none → awaiting_human_approval
# ---------------------------------------------------------------------------

class FloorRunPassEvidenceTest(unittest.TestCase):
    """Risk-floor run with pass evidence and all auto gates → awaiting_human_approval."""

    def setUp(self):
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.target = Path(self.tmpdir_obj.name)
        make_git_repo(self.target)

    def tearDown(self):
        self.tmpdir_obj.cleanup()

    def test_risk_floor_pass_none_awaiting_human_approval(self):
        """Scenario 6: Risk-floor run + pass/none + all auto gates → awaiting_human_approval."""
        risky_objective = "Add REST API endpoint with JWT authorization"
        neutral_override = "Refactor utility"

        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target), "--objective", risky_objective])
        run_ops([
            "generate-task-graph",
            "--target", str(self.target),
            "--delivery-type", "backend_utility",
            "--objective", neutral_override,
        ])

        _, run_id = _read_run_state(self.target)
        _mark_all_tasks_verified(self.target, run_id)
        _set_qa_gates(self.target, run_id)

        evidence_path = _create_security_report(self.target, "floor-pass-report.md")
        result = run_ops([
            "record-security-evidence",
            "--target", str(self.target),
            "--verdict", "pass",
            "--max-severity", "none",
            "--evidence-path", evidence_path,
        ])
        self.assertEqual(result.returncode, 0, f"Evidence recording failed: {result.stderr!r}")

        report_result = run_ops(["generate-run-report", "--target", str(self.target)])
        self.assertEqual(report_result.returncode, 0)

        report_file = self.target / ".devflow" / "reports" / f"{run_id}-report.json"
        report = json.loads(report_file.read_text())

        self.assertEqual(report["technical_readiness"], "ready",
                         f"Expected ready. report={report.get('technical_readiness')}")
        self.assertEqual(report["status"], "awaiting_human_approval")
        self.assertEqual(report["merge_recommendation"], "awaiting_human_approval")
        sec = report["security_applicability"]
        self.assertEqual(sec["security_review_status"], "completed")
        self.assertTrue(sec["security_gate_satisfied"])


# ---------------------------------------------------------------------------
# Scenario 7: Risk-floor run + blocked/medium → not_ready even with QA pass
# ---------------------------------------------------------------------------

class FloorRunBlockedEvidenceTest(unittest.TestCase):
    """Risk-floor run with blocked evidence must stay not_ready."""

    def setUp(self):
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.target = Path(self.tmpdir_obj.name)
        make_git_repo(self.target)

    def tearDown(self):
        self.tmpdir_obj.cleanup()

    def test_risk_floor_blocked_medium_not_ready(self):
        """Scenario 7: Risk-floor run + blocked/medium → not_ready even with QA pass."""
        risky_objective = "Add REST API endpoint with JWT authorization"
        neutral_override = "Refactor utility"

        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target), "--objective", risky_objective])
        run_ops([
            "generate-task-graph",
            "--target", str(self.target),
            "--delivery-type", "backend_utility",
            "--objective", neutral_override,
        ])

        _, run_id = _read_run_state(self.target)
        _mark_all_tasks_verified(self.target, run_id)
        _set_qa_gates(self.target, run_id)

        evidence_path = _create_security_report(self.target, "floor-blocked-report.md")
        run_ops([
            "record-security-evidence",
            "--target", str(self.target),
            "--verdict", "blocked",
            "--max-severity", "medium",
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
# Scenario 8: State, report, scorecard consistent effective security decision
# ---------------------------------------------------------------------------

class FloorConsistencyTest(unittest.TestCase):
    """State JSON, report JSON, scorecard must agree on effective security decision."""

    def setUp(self):
        self.tmpdir_obj = tempfile.TemporaryDirectory()
        self.target = Path(self.tmpdir_obj.name)
        make_git_repo(self.target)

    def tearDown(self):
        self.tmpdir_obj.cleanup()

    def test_state_report_scorecard_consistent_floor_triggered(self):
        """Scenario 8: Floor-triggered run → all three sources agree on security_review_required=True."""
        risky_objective = "Add REST API endpoint with JWT authorization"
        neutral_override = "Refactor utility"

        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target), "--objective", risky_objective])
        run_ops([
            "generate-task-graph",
            "--target", str(self.target),
            "--delivery-type", "backend_utility",
            "--objective", neutral_override,
        ])

        _, run_id = _read_run_state(self.target)
        _mark_all_tasks_verified(self.target, run_id)
        _set_qa_gates(self.target, run_id)

        evidence_path = _create_security_report(self.target, "consistency-floor-report.md")
        run_ops([
            "record-security-evidence",
            "--target", str(self.target),
            "--verdict", "pass",
            "--max-severity", "low",
            "--evidence-path", evidence_path,
        ])
        run_ops(["generate-run-report", "--target", str(self.target)])

        run_file = self.target / ".devflow" / "runs" / f"{run_id}.json"
        run_state = json.loads(run_file.read_text())

        report_file = self.target / ".devflow" / "reports" / f"{run_id}-report.json"
        report = json.loads(report_file.read_text())

        scorecard_file = self.target / ".devflow" / "reports" / f"{run_id}-scorecard.md"
        scorecard_text = scorecard_file.read_text()

        # State must show required=True
        self.assertTrue(run_state["security_review_required"])
        self.assertTrue(run_state["security_gate_satisfied"])

        # Report must agree
        sec = report["security_applicability"]
        self.assertTrue(sec["security_review_required"])
        self.assertTrue(sec["security_gate_satisfied"])
        self.assertEqual(sec["security_review_status"], "completed")

        # Report must carry floor metadata
        self.assertTrue(sec["launch_risk_floor_required"])

        # Scorecard must show gate satisfied
        self.assertIn("security_gate_satisfied: True", scorecard_text)
        self.assertIn("security_review_status: completed", scorecard_text)

    def test_floor_metadata_in_report_security_applicability(self):
        """Floor metadata appears in report.security_applicability for audit."""
        risky_objective = "Deploy service with migration schema changes"
        neutral_override = "Cleanup"

        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target), "--objective", risky_objective])
        run_ops([
            "generate-task-graph",
            "--target", str(self.target),
            "--delivery-type", "backend_utility",
            "--objective", neutral_override,
        ])
        run_ops(["generate-run-report", "--target", str(self.target)])

        _, run_id = _read_run_state(self.target)
        report_file = self.target / ".devflow" / "reports" / f"{run_id}-report.json"
        report = json.loads(report_file.read_text())

        sec = report["security_applicability"]
        self.assertIn("launch_risk_floor_required", sec)
        self.assertIn("launch_risk_floor_reason", sec)
        self.assertTrue(sec["launch_risk_floor_required"])
        self.assertNotEqual(sec["launch_risk_floor_reason"], "low_risk_local_utility")


if __name__ == "__main__":
    unittest.main()
