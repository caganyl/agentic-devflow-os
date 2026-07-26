"""
Tests for Contract-First Evidence Gate for New Feature Delivery.

Covers 10 scenarios:
 1. new_feature graph has contract_definition task; implementation depends on it
 2. backend_utility graph has no contract task; state = not_applicable
 3. Contract evidence absent → implementation state transition rejected (exit 15)
 4. Valid docs/quality/contracts/... path accepted
 5. Absolute, traversal, .devflow, .claude, secret/credential, nonexistent paths rejected
 6. After recording evidence: contract_status=completed, gate=True
 7. Without contract evidence → finalization not_ready
 8. Contract evidence + other valid gates → human approval state machine preserved
 9. State JSON, report JSON, scorecard consistent on contract projection
10. Regression: native delegation, risk floor, QA/security evidence, immutable graph, target guard
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
    spec = importlib.util.spec_from_file_location("devflow_ops_contract_ev", OPS_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _verified_report(mod, run_data, run_id="RUN-001"):
    """build_run_report for a run whose evidence was actually measured.

    The report holds at "unverified_evidence" unless delegation was observed
    and QA was executed rather than self-reported. Tests about contract and
    human-approval semantics should not have to restate that each time, so it
    is supplied here; tests that care about the unverified path call
    build_run_report directly.
    """
    data = dict(run_data)
    data.setdefault(
        "qa_evidence", {"source": "executed", "qa_passed": True, "exit_code": 0}
    )
    return mod.build_run_report(data, run_id, delegation_events=[{
        "hook_event": "SubagentStart",
        "lifecycle_state": "started",
        "run_id": run_id,
        "agent_type": "backend-engineer",
    }])


def make_git_repo(path: Path, branch: str = "feature-contract-test") -> None:
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
    readme.write_text("contract evidence test project\n", encoding="utf-8")
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


def _setup_new_feature_run(target: Path, objective: str = "Add user onboarding flow") -> str:
    """Init, create-run, generate-task-graph for new_feature. Returns run_id."""
    run_ops(["init-target", "--target", str(target)])
    run_ops(["create-run", "--target", str(target), "--objective", objective])
    run_ops([
        "generate-task-graph",
        "--target", str(target),
        "--delivery-type", "new_feature",
        "--objective", objective,
    ])
    devflow = target / ".devflow"
    project = json.loads((devflow / "project.json").read_text())
    return project["current_run_id"]


def _setup_backend_utility_run(target: Path, objective: str = "Parse CSV files") -> str:
    """Init, create-run, generate-task-graph for backend_utility. Returns run_id."""
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


def _create_contract_file(target: Path, filename: str = "api-contract.md") -> str:
    """Create a dummy contract evidence file and return its relative path."""
    contract_dir = target / "docs" / "quality" / "contracts"
    contract_dir.mkdir(parents=True, exist_ok=True)
    contract_file = contract_dir / filename
    contract_file.write_text(
        "# API Contract\n\nEndpoint definitions for REQ-001.\n", encoding="utf-8"
    )
    return f"docs/quality/contracts/{filename}"


def _verified_new_feature_tasks(mod) -> list:
    """Return a full new_feature task list with all tasks verified."""
    tasks = mod.generate_task_graph_nodes("RUN-001", "new_feature", "Add user onboarding flow")
    for t in tasks:
        t["status"] = "verified"
    return tasks


def _make_wp_evidence(tasks: list) -> dict:
    """Return mock work_product_evidence for all implementation/QA tasks in a task list."""
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


# ---------------------------------------------------------------------------
# Test 1 & 2: Task graph contract task structure
# ---------------------------------------------------------------------------

class ContractTaskGraphTest(unittest.TestCase):
    """Tests 1 and 2: contract_definition task in new_feature; absent in backend_utility."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_ops_module()

    def test_new_feature_has_contract_definition_task(self):
        """Test 1a: new_feature graph has a task with task_type=contract_definition."""
        tasks = self.mod.generate_task_graph_nodes("RUN-001", "new_feature", "Add user onboarding")
        types = [t["task_type"] for t in tasks]
        self.assertIn("contract_definition", types, (
            f"new_feature must have a contract_definition task. Got: {types}"
        ))

    def test_new_feature_contract_definition_assigned_to_contract_broker(self):
        """Contract Definition task is assigned to contract-broker role."""
        tasks = self.mod.generate_task_graph_nodes("RUN-001", "new_feature", "Add user onboarding")
        contract_tasks = [t for t in tasks if t["task_type"] == "contract_definition"]
        self.assertEqual(len(contract_tasks), 1, "Expected exactly one contract_definition task")
        self.assertEqual(contract_tasks[0]["assigned_role"], "contract-broker")

    def test_new_feature_contract_definition_output_path(self):
        """Contract Definition task output_path points to docs/quality/contracts/."""
        tasks = self.mod.generate_task_graph_nodes("RUN-001", "new_feature", "Add user onboarding")
        contract_task = next(t for t in tasks if t["task_type"] == "contract_definition")
        self.assertIn("docs/quality/contracts", contract_task.get("output_path", ""))

    def test_new_feature_implementation_depends_on_contract_definition(self):
        """Test 1b: Implementation tasks depend on the contract_definition task."""
        tasks = self.mod.generate_task_graph_nodes("RUN-001", "new_feature", "Add user onboarding")
        contract_task = next(t for t in tasks if t["task_type"] == "contract_definition")
        impl_tasks = [t for t in tasks if t["task_type"] == "implementation"]
        self.assertTrue(impl_tasks, "Expected implementation tasks in new_feature graph")
        for impl in impl_tasks:
            self.assertIn(
                contract_task["id"],
                impl["dependency_ids"],
                f"Implementation task {impl['id']} must depend on contract_definition. "
                f"deps={impl['dependency_ids']}",
            )

    def test_backend_utility_has_no_contract_task(self):
        """Test 2a: backend_utility graph has no contract_definition task."""
        tasks = self.mod.generate_task_graph_nodes("RUN-001", "backend_utility", "Parse CSV files")
        types = [t["task_type"] for t in tasks]
        self.assertNotIn("contract_definition", types, (
            f"backend_utility must NOT have a contract_definition task. Got: {types}"
        ))

    def test_backend_utility_contract_state_not_applicable(self):
        """Test 2b: backend_utility generate-task-graph sets contract_status=not_applicable."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target, "feature-contract-test")
            run_id = _setup_backend_utility_run(target)
            devflow = target / ".devflow"
            run_data = json.loads((devflow / "runs" / f"{run_id}.json").read_text())
            self.assertFalse(run_data.get("contract_required", True),
                             "backend_utility must have contract_required=False")
            self.assertEqual(run_data.get("contract_status"), "not_applicable")
            self.assertTrue(run_data.get("contract_gate_satisfied"),
                            "backend_utility must have contract_gate_satisfied=True")

    def test_new_feature_initial_contract_state_pending(self):
        """new_feature generate-task-graph sets contract_status=pending, gate=False."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target, "feature-contract-test")
            run_id = _setup_new_feature_run(target)
            devflow = target / ".devflow"
            run_data = json.loads((devflow / "runs" / f"{run_id}.json").read_text())
            self.assertTrue(run_data.get("contract_required"),
                            "new_feature must have contract_required=True")
            self.assertEqual(run_data.get("contract_status"), "pending")
            self.assertFalse(run_data.get("contract_gate_satisfied"),
                             "new_feature must start with contract_gate_satisfied=False")


# ---------------------------------------------------------------------------
# Test 3: Implementation gate enforcement
# ---------------------------------------------------------------------------

class ContractGateEnforcementTest(unittest.TestCase):
    """Test 3: Contract evidence absent → implementation task transition rejected."""

    def test_implementation_cannot_start_without_contract_evidence_unit(self):
        """Unit: contract_required=True, gate=False blocks implementation transition."""
        mod = _load_ops_module()
        tasks = mod.generate_task_graph_nodes("RUN-001", "new_feature", "Add user onboarding")
        impl_task = next(t for t in tasks if t["task_type"] == "implementation")
        impl_task["status"] = "ready"

        run_data = {
            "run_id": "RUN-001",
            "objective": "Add user onboarding",
            "execution_mode": "subagents",
            "requested_agent_teams": False,
            "tasks": tasks,
            "approval_gates": {},
            "contract_required": True,
            "contract_status": "pending",
            "contract_gate_satisfied": False,
        }
        # Verify cmd_update_task_status would reject in_progress for this task
        # The gate check uses contract_required and contract_gate_satisfied from run_data.
        self.assertTrue(run_data.get("contract_required"))
        self.assertFalse(run_data.get("contract_gate_satisfied"))
        # Simulate the gate condition check (mirrors cmd_update_task_status logic)
        blocked_statuses = mod.CONTRACT_GATE_BLOCKED_STATUSES
        self.assertIn("in_progress", blocked_statuses)
        # Gate should block in_progress for implementation tasks
        would_block = (
            "in_progress" in blocked_statuses
            and impl_task["task_type"] == "implementation"
            and run_data.get("contract_required", False)
            and not run_data.get("contract_gate_satisfied", False)
        )
        self.assertTrue(would_block,
                        "Contract gate should block implementation task from entering in_progress")

    def test_implementation_transition_rejected_via_cli(self):
        """Test 3 (CLI): update-task-status to in_progress for implementation fails without evidence."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target, "feature-contract-test")
            run_id = _setup_new_feature_run(target)
            devflow = target / ".devflow"
            run_data = json.loads((devflow / "runs" / f"{run_id}.json").read_text())

            # Find an implementation task
            impl_tasks = [t for t in run_data["tasks"] if t["task_type"] == "implementation"]
            self.assertTrue(impl_tasks, "new_feature must have implementation tasks")
            impl_task_id = impl_tasks[0]["id"]

            # Transition implementation task to ready (allowed — gate is only for in_progress+)
            res = run_ops([
                "update-task-status",
                "--target", str(target),
                "--task-id", impl_task_id,
                "--status", "ready",
            ])
            # Note: this may fail if the contract_definition dep task blocks it through
            # the dependency model — but update-task-status doesn't check deps, only gate.
            # The gate is only on in_progress/completed/verified, so ready is allowed.
            # (contract gate does NOT block planned→ready)

            # Now try to transition to in_progress — should be blocked
            res = run_ops([
                "update-task-status",
                "--target", str(target),
                "--task-id", impl_task_id,
                "--status", "in_progress",
            ])
            self.assertNotEqual(res.returncode, 0,
                                "update-task-status to in_progress must fail without contract evidence")
            self.assertEqual(res.returncode, 15,
                             f"Expected exit 15 for contract gate block. stderr: {res.stderr}")

    def test_non_implementation_task_not_blocked_by_contract_gate(self):
        """Contract gate only blocks implementation tasks, not planning/qa/release."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target, "feature-contract-test")
            run_id = _setup_new_feature_run(target)
            devflow = target / ".devflow"
            run_data = json.loads((devflow / "runs" / f"{run_id}.json").read_text())

            # Find a planning task (contract gate should NOT block it)
            planning_tasks = [t for t in run_data["tasks"] if t["task_type"] == "planning"]
            self.assertTrue(planning_tasks, "new_feature must have planning tasks")
            planning_task_id = planning_tasks[0]["id"]

            # planned → ready is the valid transition from planned (not planned → in_progress)
            res = run_ops([
                "update-task-status",
                "--target", str(target),
                "--task-id", planning_task_id,
                "--status", "ready",
            ])
            self.assertEqual(res.returncode, 0,
                             f"Planning task should not be blocked by contract gate. stderr: {res.stderr}")


# ---------------------------------------------------------------------------
# Test 4 & 5: Path validation
# ---------------------------------------------------------------------------

class ContractEvidencePathValidationTest(unittest.TestCase):
    """Tests 4 and 5: validate_contract_evidence_path unit tests."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_ops_module()
        cls.tmpdir_obj = tempfile.TemporaryDirectory()
        cls.target = Path(cls.tmpdir_obj.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir_obj.cleanup()

    def _create_contract(self, filename: str = "contract.md") -> str:
        contract_dir = cls = self.target / "docs" / "quality" / "contracts"
        contract_dir.mkdir(parents=True, exist_ok=True)
        (contract_dir / filename).write_text("# Contract\n", encoding="utf-8")
        return f"docs/quality/contracts/{filename}"

    def test_valid_path_accepted(self):
        """Test 4: Valid docs/quality/contracts/... path is accepted."""
        rel_path = self._create_contract("valid-contract.md")
        ok, err = self.mod.validate_contract_evidence_path(self.target, rel_path)
        self.assertTrue(ok, f"Expected valid path to be accepted. Error: {err}")
        self.assertEqual(err, "")

    def test_absolute_path_rejected(self):
        """Test 5a: Absolute path is rejected."""
        abs_path = str(self.target / "docs" / "quality" / "contracts" / "contract.md")
        ok, err = self.mod.validate_contract_evidence_path(self.target, abs_path)
        self.assertFalse(ok, "Absolute path must be rejected")
        self.assertIn("mutlak", err.lower())

    def test_traversal_rejected(self):
        """Test 5b: Path traversal (..) is rejected."""
        ok, err = self.mod.validate_contract_evidence_path(
            self.target, "docs/quality/contracts/../../etc/passwd"
        )
        self.assertFalse(ok, "Traversal path must be rejected")
        self.assertIn("..", err)

    def test_wildcard_rejected(self):
        """Test 5c: Wildcard in path is rejected."""
        ok, err = self.mod.validate_contract_evidence_path(
            self.target, "docs/quality/contracts/*.md"
        )
        self.assertFalse(ok, "Wildcard path must be rejected")
        self.assertIn("wildcard", err.lower())

    def test_devflow_path_rejected(self):
        """Test 5d: .devflow/ path is rejected."""
        ok, err = self.mod.validate_contract_evidence_path(
            self.target, ".devflow/runs/RUN-001.json"
        )
        self.assertFalse(ok, ".devflow/ path must be rejected")
        self.assertIn("docs/quality/contracts", err)

    def test_claude_path_rejected(self):
        """Test 5e: .claude/ path is rejected."""
        ok, err = self.mod.validate_contract_evidence_path(
            self.target, ".claude/settings.json"
        )
        self.assertFalse(ok, ".claude/ path must be rejected")
        self.assertIn("docs/quality/contracts", err)

    def test_wrong_prefix_rejected(self):
        """Test 5f: Path not under docs/quality/contracts/ is rejected."""
        ok, err = self.mod.validate_contract_evidence_path(
            self.target, "docs/contracts/openapi/REQ-001.yaml"
        )
        self.assertFalse(ok, "Wrong prefix path must be rejected")
        self.assertIn("docs/quality/contracts", err)

    def test_nonexistent_file_rejected(self):
        """Test 5g: Non-existent file path is rejected."""
        ok, err = self.mod.validate_contract_evidence_path(
            self.target, "docs/quality/contracts/nonexistent-file.md"
        )
        self.assertFalse(ok, "Non-existent file must be rejected")
        self.assertIn("bulunamadı", err)

    def test_empty_path_rejected(self):
        """Empty evidence path is rejected."""
        ok, err = self.mod.validate_contract_evidence_path(self.target, "")
        self.assertFalse(ok, "Empty path must be rejected")

    def test_secret_path_rejected(self):
        """Test 5h: Credential/secret-like path is rejected (not under docs/quality/contracts/)."""
        ok, err = self.mod.validate_contract_evidence_path(
            self.target, "secrets/api-key.txt"
        )
        self.assertFalse(ok, "Secret path must be rejected")
        self.assertIn("docs/quality/contracts", err)


# ---------------------------------------------------------------------------
# Test 6: Recording evidence updates state correctly
# ---------------------------------------------------------------------------

class ContractEvidenceRecordingTest(unittest.TestCase):
    """Test 6: After recording evidence: contract_status=completed, gate=True."""

    def test_record_contract_evidence_updates_state(self):
        """Test 6: record-contract-evidence sets status=completed, gate=True."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target, "feature-contract-test")
            run_id = _setup_new_feature_run(target)
            evidence_path = _create_contract_file(target)

            res = run_ops([
                "record-contract-evidence",
                "--target", str(target),
                "--run-id", run_id,
                "--evidence-path", evidence_path,
            ])
            self.assertEqual(res.returncode, 0,
                             f"record-contract-evidence must succeed. stderr: {res.stderr}")

            devflow = target / ".devflow"
            run_data = json.loads((devflow / "runs" / f"{run_id}.json").read_text())
            self.assertEqual(run_data.get("contract_status"), "completed")
            self.assertTrue(run_data.get("contract_gate_satisfied"))

    def test_contract_evidence_dict_structure(self):
        """Evidence dict contains only evidence_path, recorded_at, provenance."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target, "feature-contract-test")
            run_id = _setup_new_feature_run(target)
            evidence_path = _create_contract_file(target)

            run_ops([
                "record-contract-evidence",
                "--target", str(target),
                "--evidence-path", evidence_path,
            ])

            devflow = target / ".devflow"
            run_data = json.loads((devflow / "runs" / f"{run_id}.json").read_text())
            evidence = run_data.get("contract_evidence", {})
            self.assertEqual(evidence.get("evidence_path"), evidence_path)
            self.assertEqual(evidence.get("provenance"), "generated_in_run")
            self.assertIn("recorded_at", evidence)
            # Must NOT contain raw content, prompts, session IDs, URLs, tokens, free text
            self.assertNotIn("content", evidence)
            self.assertNotIn("prompt", evidence)
            self.assertNotIn("session_id", evidence)
            self.assertNotIn("url", evidence)
            self.assertNotIn("token", evidence)

    def test_record_contract_evidence_rejected_for_non_new_feature_run(self):
        """record-contract-evidence must be rejected for backend_utility (exit 18)."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target, "feature-contract-test")
            run_id = _setup_backend_utility_run(target)
            # Create the file (even if it exists, the command should reject first on contract_required)
            evidence_path = _create_contract_file(target)

            res = run_ops([
                "record-contract-evidence",
                "--target", str(target),
                "--evidence-path", evidence_path,
            ])
            self.assertNotEqual(res.returncode, 0,
                                "record-contract-evidence must fail for backend_utility")
            self.assertEqual(res.returncode, 18,
                             f"Expected exit 18. stderr: {res.stderr}")

    def test_record_contract_evidence_wrong_run_id_rejected(self):
        """--run-id mismatch with active run must be rejected (exit 18)."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target, "feature-contract-test")
            run_id = _setup_new_feature_run(target)
            evidence_path = _create_contract_file(target)

            res = run_ops([
                "record-contract-evidence",
                "--target", str(target),
                "--run-id", "RUN-999",
                "--evidence-path", evidence_path,
            ])
            self.assertNotEqual(res.returncode, 0)
            self.assertEqual(res.returncode, 18,
                             f"Expected exit 18 for run-id mismatch. stderr: {res.stderr}")

    def test_record_contract_evidence_invalid_path_exit18(self):
        """Invalid evidence path must be rejected with exit 18."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target, "feature-contract-test")
            run_id = _setup_new_feature_run(target)

            res = run_ops([
                "record-contract-evidence",
                "--target", str(target),
                "--evidence-path", "docs/contracts/openapi/wrong-prefix.yaml",
            ])
            self.assertEqual(res.returncode, 18,
                             f"Expected exit 18 for wrong path prefix. stderr: {res.stderr}")

    def test_implementation_allowed_after_contract_evidence(self):
        """After recording contract evidence, implementation task can enter in_progress."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target, "feature-contract-test")
            run_id = _setup_new_feature_run(target)
            evidence_path = _create_contract_file(target)

            # Record contract evidence
            run_ops([
                "record-contract-evidence",
                "--target", str(target),
                "--evidence-path", evidence_path,
            ])

            devflow = target / ".devflow"
            run_data = json.loads((devflow / "runs" / f"{run_id}.json").read_text())
            impl_tasks = [t for t in run_data["tasks"] if t["task_type"] == "implementation"]
            self.assertTrue(impl_tasks, "new_feature must have implementation tasks")
            impl_task_id = impl_tasks[0]["id"]

            # Transition to ready first
            run_ops([
                "update-task-status",
                "--target", str(target),
                "--task-id", impl_task_id,
                "--status", "ready",
            ])

            # Now in_progress should be allowed
            res = run_ops([
                "update-task-status",
                "--target", str(target),
                "--task-id", impl_task_id,
                "--status", "in_progress",
            ])
            self.assertEqual(res.returncode, 0,
                             f"Implementation task must be allowed after contract evidence. "
                             f"stderr: {res.stderr}")


# ---------------------------------------------------------------------------
# Tests: Contract Definition task status updated by record-contract-evidence
# ---------------------------------------------------------------------------

class ContractEvidenceTaskStatusTest(unittest.TestCase):
    """
    record-contract-evidence must update the contract_definition task to
    verified atomically, reject when the task is absent, and enable
    readiness without a separate manual task-status update.
    """

    def test_record_contract_evidence_makes_contract_task_verified(self):
        """Successful evidence recording sets contract_definition task status to verified."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target, "feature-contract-test")
            run_id = _setup_new_feature_run(target)
            evidence_path = _create_contract_file(target)

            res = run_ops([
                "record-contract-evidence",
                "--target", str(target),
                "--run-id", run_id,
                "--evidence-path", evidence_path,
            ])
            self.assertEqual(res.returncode, 0,
                             f"record-contract-evidence must succeed. stderr: {res.stderr}")

            devflow = target / ".devflow"
            run_data = json.loads((devflow / "runs" / f"{run_id}.json").read_text())
            contract_tasks = [t for t in run_data["tasks"] if t["task_type"] == "contract_definition"]
            self.assertEqual(len(contract_tasks), 1)
            self.assertEqual(
                contract_tasks[0]["status"], "verified",
                "contract_definition task must be verified after record-contract-evidence",
            )

    def test_record_contract_evidence_rejected_no_contract_task(self):
        """Rejected with exit 18 when no contract_definition task exists; state unchanged."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target, "feature-contract-test")
            run_id = _setup_new_feature_run(target)
            evidence_path = _create_contract_file(target)

            # Remove the contract_definition task from run state
            devflow = target / ".devflow"
            run_path = devflow / "runs" / f"{run_id}.json"
            run_before = json.loads(run_path.read_text())
            run_before["tasks"] = [
                t for t in run_before["tasks"] if t["task_type"] != "contract_definition"
            ]
            # Signed, not raw: the gates reject run state this CLI did not write.
            _load_ops_module().write_run_state(target, run_path, run_before)

            res = run_ops([
                "record-contract-evidence",
                "--target", str(target),
                "--evidence-path", evidence_path,
            ])
            self.assertEqual(res.returncode, 18,
                             f"Expected exit 18 when no contract_definition task. stderr: {res.stderr}")

            # State must be unchanged — contract_status still pending
            run_after = json.loads(run_path.read_text())
            self.assertNotEqual(run_after.get("contract_status"), "completed",
                                "State must not be mutated after rejection")
            self.assertFalse(run_after.get("contract_gate_satisfied", False),
                             "contract_gate_satisfied must remain False after rejection")

    def test_record_contract_evidence_idempotent_on_verified_task(self):
        """Second call when task is already verified succeeds without error."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target, "feature-contract-test")
            run_id = _setup_new_feature_run(target)
            evidence_path = _create_contract_file(target)

            # First call
            run_ops([
                "record-contract-evidence",
                "--target", str(target),
                "--evidence-path", evidence_path,
            ])
            # Second call — idempotent
            res = run_ops([
                "record-contract-evidence",
                "--target", str(target),
                "--evidence-path", evidence_path,
            ])
            self.assertEqual(res.returncode, 0,
                             f"Second record-contract-evidence must be idempotent. stderr: {res.stderr}")

            devflow = target / ".devflow"
            run_data = json.loads((devflow / "runs" / f"{run_id}.json").read_text())
            contract_tasks = [t for t in run_data["tasks"] if t["task_type"] == "contract_definition"]
            self.assertEqual(contract_tasks[0]["status"], "verified")
            self.assertEqual(run_data.get("contract_status"), "completed")
            self.assertTrue(run_data.get("contract_gate_satisfied"))

    def test_readiness_without_manual_contract_task_update(self):
        """
        After record-contract-evidence, no additional Contract Definition task update needed.
        When all other tasks and gates are satisfied, run reaches awaiting_human_approval.
        """
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target, "feature-contract-test")
            run_id = _setup_new_feature_run(target)
            evidence_path = _create_contract_file(target)

            # Record contract evidence — contract_definition task becomes verified
            res = run_ops([
                "record-contract-evidence",
                "--target", str(target),
                "--run-id", run_id,
                "--evidence-path", evidence_path,
            ])
            self.assertEqual(res.returncode, 0)

            devflow = target / ".devflow"
            run_path = devflow / "runs" / f"{run_id}.json"
            run_data = json.loads(run_path.read_text())

            # Verify contract_definition task is already verified — no manual step needed
            contract_task = next(
                t for t in run_data["tasks"] if t["task_type"] == "contract_definition"
            )
            self.assertEqual(contract_task["status"], "verified",
                             "contract_definition task must already be verified; no manual update needed")

            # Set all other tasks to verified (simulate full delivery completion)
            for t in run_data["tasks"]:
                if t["task_type"] != "contract_definition":
                    t["status"] = "verified"

            # Set all required gates (simulate QA and security completion)
            run_data["approval_gates"].update({
                "tests_passing": True,
                "qa_sign_off": True,
                "security_review_complete": True,
                "human_approval": False,
            })
            run_data["security_review_required"] = False
            run_data["security_applicability_reason"] = "low_risk_local_utility"
            run_data["work_product_evidence"] = _make_wp_evidence(run_data["tasks"])

            # Signed, not raw: the gates reject run state this CLI did not write.
            _load_ops_module().write_run_state(target, run_path, run_data)
            _create_wp_stub_files(target)

            # Measured QA and observed delegation, otherwise the report holds at
            # "unverified_evidence" regardless of the contract gate.
            events_dir = devflow / "delegation-events"
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
            run_ops([
                "record-qa-evidence", "--target", str(target),
                "--test-command", "python3 -c pass",
            ])

            res_report = run_ops(["generate-run-report", "--target", str(target)])
            self.assertEqual(res_report.returncode, 0)

            report = json.loads((devflow / "reports" / f"{run_id}-report.json").read_text())
            self.assertIn(
                report["status"],
                {"awaiting_human_approval", "ready_for_human_merge"},
                f"Run must reach human approval state. Got: {report['status']}. "
                f"technical_readiness={report.get('technical_readiness')}",
            )


# ---------------------------------------------------------------------------
# Test 7: Finalization not_ready without contract evidence
# ---------------------------------------------------------------------------

class ContractGateReadinessTest(unittest.TestCase):
    """Test 7: Without contract evidence, finalization produces not_ready."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_ops_module()

    def _new_feature_verified_tasks(self):
        tasks = self.mod.generate_task_graph_nodes("RUN-001", "new_feature", "Add user onboarding")
        for t in tasks:
            t["status"] = "verified"
        return tasks

    def test_not_ready_without_contract_evidence(self):
        """Test 7: new_feature run with all tasks verified but no contract evidence → not_ready."""
        tasks = self._new_feature_verified_tasks()
        run_data = {
            "run_id": "RUN-001",
            "objective": "Add user onboarding",
            "execution_mode": "subagents",
            "agent_teams_requested": False,
            "tasks": tasks,
            "approval_gates": {
                "contract_approved": False,
                "tests_passing": True,
                "security_review_complete": True,
                "qa_sign_off": True,
                "human_approval": False,
            },
            "contract_required": True,
            "contract_status": "pending",
            "contract_gate_satisfied": False,
            "security_review_required": False,
            "security_applicability_reason": "low_risk_local_utility",
        }
        report = _verified_report(self.mod, run_data)
        self.assertEqual(report["technical_readiness"], "not_ready",
                         "Without contract evidence, technical_readiness must be not_ready")
        self.assertNotEqual(report["merge_recommendation"], "ready_for_human_merge")
        self.assertNotEqual(report["merge_recommendation"], "awaiting_human_approval")

    def test_contract_applicability_in_report(self):
        """contract_applicability block is present in build_run_report output."""
        tasks = self._new_feature_verified_tasks()
        run_data = {
            "run_id": "RUN-001",
            "objective": "Add user onboarding",
            "execution_mode": "subagents",
            "agent_teams_requested": False,
            "tasks": tasks,
            "approval_gates": {"tests_passing": True, "qa_sign_off": True},
            "contract_required": True,
            "contract_status": "pending",
            "contract_gate_satisfied": False,
        }
        report = _verified_report(self.mod, run_data)
        self.assertIn("contract_applicability", report,
                      "build_run_report must include contract_applicability block")
        cont = report["contract_applicability"]
        self.assertTrue(cont.get("contract_required"))
        self.assertEqual(cont.get("contract_status"), "pending")
        self.assertFalse(cont.get("contract_gate_satisfied"))

    def test_backend_utility_contract_gate_not_applicable_not_blocking(self):
        """backend_utility run: contract gate not applicable, not_ready not caused by contract."""
        tasks = self.mod.generate_task_graph_nodes(
            "RUN-001", "backend_utility", "Parse CSV files"
        )
        for t in tasks:
            t["status"] = "verified"
        run_data = {
            "run_id": "RUN-001",
            "objective": "Parse CSV files",
            "execution_mode": "subagents",
            "agent_teams_requested": False,
            "tasks": tasks,
            "approval_gates": {
                "tests_passing": True,
                "qa_sign_off": True,
                "security_review_complete": False,
                "human_approval": False,
            },
            "contract_required": False,
            "contract_status": "not_applicable",
            "contract_gate_satisfied": True,
            "security_review_required": False,
            "security_applicability_reason": "low_risk_local_utility",
            "work_product_evidence": _make_wp_evidence(tasks),
        }
        report = _verified_report(self.mod, run_data)
        cont = report["contract_applicability"]
        self.assertFalse(cont.get("contract_required"))
        self.assertEqual(cont.get("contract_status"), "not_applicable")
        self.assertTrue(cont.get("contract_gate_satisfied"))
        # technical_readiness should be ready (all other gates OK)
        self.assertEqual(report["technical_readiness"], "ready")


# ---------------------------------------------------------------------------
# Test 8: Human approval state machine preserved after contract evidence
# ---------------------------------------------------------------------------

class ContractGateHumanApprovalTest(unittest.TestCase):
    """Test 8: With evidence + other gates → human approval state machine preserved."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_ops_module()

    def _verified_tasks(self):
        tasks = self.mod.generate_task_graph_nodes("RUN-001", "new_feature", "Add user onboarding")
        for t in tasks:
            t["status"] = "verified"
        return tasks

    def test_awaiting_human_when_all_gates_except_human(self):
        """Test 8a: Contract evidence + QA + security done, human=False → awaiting_human_approval."""
        tasks = self._verified_tasks()
        run_data = {
            "run_id": "RUN-001",
            "objective": "Add user onboarding",
            "execution_mode": "subagents",
            "agent_teams_requested": False,
            "tasks": tasks,
            "approval_gates": {
                "contract_approved": True,
                "tests_passing": True,
                "security_review_complete": True,
                "qa_sign_off": True,
                "human_approval": False,
            },
            "contract_required": True,
            "contract_status": "completed",
            "contract_gate_satisfied": True,
            "contract_evidence": {
                "evidence_path": "docs/quality/contracts/api-contract.md",
                "recorded_at": "2026-06-28T12:00:00Z",
                "provenance": "generated_in_run",
            },
            "security_review_required": False,
            "security_applicability_reason": "low_risk_local_utility",
            "work_product_evidence": _make_wp_evidence(tasks),
        }
        report = _verified_report(self.mod, run_data)
        self.assertEqual(report["technical_readiness"], "ready")
        self.assertEqual(report["status"], "awaiting_human_approval")
        self.assertEqual(report["merge_recommendation"], "awaiting_human_approval")

    def test_ready_for_human_merge_when_all_gates_including_human(self):
        """Test 8b: Contract evidence + all gates including human → ready_for_human_merge."""
        tasks = self._verified_tasks()
        run_data = {
            "run_id": "RUN-001",
            "objective": "Add user onboarding",
            "execution_mode": "subagents",
            "agent_teams_requested": False,
            "tasks": tasks,
            "approval_gates": {
                "contract_approved": True,
                "tests_passing": True,
                "security_review_complete": True,
                "qa_sign_off": True,
                "human_approval": True,
            },
            "contract_required": True,
            "contract_status": "completed",
            "contract_gate_satisfied": True,
            "contract_evidence": {
                "evidence_path": "docs/quality/contracts/api-contract.md",
                "recorded_at": "2026-06-28T12:00:00Z",
                "provenance": "generated_in_run",
            },
            "security_review_required": False,
            "security_applicability_reason": "low_risk_local_utility",
            "work_product_evidence": _make_wp_evidence(tasks),
        }
        report = _verified_report(self.mod, run_data)
        self.assertEqual(report["merge_recommendation"], "ready_for_human_merge")

    def test_no_automatic_merge_ever(self):
        """Merge recommendation is never 'auto_merge' or similar — always requires human."""
        tasks = self._verified_tasks()
        run_data = {
            "run_id": "RUN-001",
            "objective": "Add user onboarding",
            "execution_mode": "subagents",
            "agent_teams_requested": False,
            "tasks": tasks,
            "approval_gates": {
                "contract_approved": True,
                "tests_passing": True,
                "security_review_complete": True,
                "qa_sign_off": True,
                "human_approval": True,
            },
            "contract_required": True,
            "contract_status": "completed",
            "contract_gate_satisfied": True,
            "security_review_required": False,
            "work_product_evidence": _make_wp_evidence(tasks),
        }
        report = _verified_report(self.mod, run_data)
        recommendation = report["merge_recommendation"]
        self.assertNotIn("auto", recommendation.lower(),
                         f"Merge recommendation must never be automatic: {recommendation}")
        self.assertIn("human", recommendation.lower(),
                      f"Merge recommendation must reference human action: {recommendation}")


# ---------------------------------------------------------------------------
# Test 9: Canonical projection consistency (state JSON, report JSON, scorecard)
# ---------------------------------------------------------------------------

class ContractProjectionConsistencyTest(unittest.TestCase):
    """Test 9: State, report, scorecard all show consistent contract gate values."""

    def test_state_report_scorecard_consistent(self):
        """Test 9: After recording evidence, generate-run-report produces consistent projection."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target, "feature-contract-test")
            run_id = _setup_new_feature_run(target)
            evidence_path = _create_contract_file(target)

            # Record contract evidence
            run_ops([
                "record-contract-evidence",
                "--target", str(target),
                "--evidence-path", evidence_path,
            ])

            # Generate report (which also writes back to run state)
            run_ops(["generate-run-report", "--target", str(target)])

            devflow = target / ".devflow"

            # State JSON
            run_data = json.loads((devflow / "runs" / f"{run_id}.json").read_text())
            self.assertEqual(run_data.get("contract_status"), "completed")
            self.assertTrue(run_data.get("contract_gate_satisfied"))

            # Report JSON
            report_path = devflow / "reports" / f"{run_id}-report.json"
            self.assertTrue(report_path.exists(), "Report JSON must exist")
            report = json.loads(report_path.read_text())
            cont = report.get("contract_applicability", {})
            self.assertTrue(cont.get("contract_required"))
            self.assertEqual(cont.get("contract_status"), "completed")
            self.assertTrue(cont.get("contract_gate_satisfied"))
            cont_evidence = cont.get("contract_evidence", {})
            self.assertEqual(cont_evidence.get("evidence_path"), evidence_path)
            self.assertEqual(cont_evidence.get("provenance"), "generated_in_run")

            # Scorecard markdown
            scorecard_path = devflow / "reports" / f"{run_id}-scorecard.md"
            self.assertTrue(scorecard_path.exists(), "Scorecard MD must exist")
            scorecard = scorecard_path.read_text()
            self.assertIn("## Contract Gate", scorecard)
            self.assertIn("contract_required: True", scorecard)
            self.assertIn("contract_status: completed", scorecard)
            self.assertIn("contract_gate_satisfied: True", scorecard)
            self.assertIn(evidence_path, scorecard)
            self.assertIn("generated_in_run", scorecard)
            # Disclaimer about local artefact, no causal binding
            self.assertIn("NOT a claim", scorecard)

    def test_report_without_contract_evidence_shows_pending(self):
        """Without evidence, report shows contract_status=pending, gate=False."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target, "feature-contract-test")
            run_id = _setup_new_feature_run(target)

            # Generate report without recording evidence
            run_ops(["generate-run-report", "--target", str(target)])

            devflow = target / ".devflow"
            report_path = devflow / "reports" / f"{run_id}-report.json"
            self.assertTrue(report_path.exists())
            report = json.loads(report_path.read_text())
            cont = report.get("contract_applicability", {})
            self.assertEqual(cont.get("contract_status"), "pending")
            self.assertFalse(cont.get("contract_gate_satisfied"))
            self.assertEqual(report["technical_readiness"], "not_ready")

    def test_evidence_provenance_is_generated_in_run(self):
        """Evidence provenance in contract_applicability is 'generated_in_run'."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target, "feature-contract-test")
            run_id = _setup_new_feature_run(target)
            evidence_path = _create_contract_file(target)

            run_ops([
                "record-contract-evidence",
                "--target", str(target),
                "--evidence-path", evidence_path,
            ])
            run_ops(["generate-run-report", "--target", str(target)])

            devflow = target / ".devflow"
            report = json.loads(
                (devflow / "reports" / f"{run_id}-report.json").read_text()
            )
            cont_evidence = report["contract_applicability"].get("contract_evidence", {})
            self.assertEqual(cont_evidence.get("provenance"), "generated_in_run")

    def test_evidence_provenance_in_report_evidence_provenance_dict(self):
        """evidence_provenance.contract_review reflects contract gate state."""
        mod = _load_ops_module()
        tasks = mod.generate_task_graph_nodes("RUN-001", "new_feature", "Add user onboarding")
        for t in tasks:
            t["status"] = "verified"
        run_data = {
            "run_id": "RUN-001",
            "objective": "Add user onboarding",
            "execution_mode": "subagents",
            "agent_teams_requested": False,
            "tasks": tasks,
            "approval_gates": {"tests_passing": True, "qa_sign_off": True},
            "contract_required": True,
            "contract_status": "completed",
            "contract_gate_satisfied": True,
            "security_review_required": False,
        }
        report = mod.build_run_report(run_data, "RUN-001")
        self.assertIn("contract_review", report["evidence_provenance"])
        self.assertEqual(report["evidence_provenance"]["contract_review"], "generated_in_run")


# ---------------------------------------------------------------------------
# Test 10: Regression guard
# ---------------------------------------------------------------------------

class ContractGateRegressionTest(unittest.TestCase):
    """Test 10: Existing behaviors not broken by contract gate changes."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_ops_module()

    # --- Security gate regression ---

    def test_security_gate_still_required_for_new_feature(self):
        """Security gate still applies to new_feature (not removed by contract changes)."""
        self.assertIn(
            "new_feature",
            self.mod.DELIVERY_TYPES_WITH_MANDATORY_SECURITY_REVIEW,
            "new_feature must still require security review",
        )

    def test_security_evidence_path_prefix_unchanged(self):
        """Security evidence path prefix unchanged."""
        self.assertEqual(
            self.mod.SECURITY_EVIDENCE_PATH_PREFIX,
            "docs/quality/security-reports/",
        )

    def test_contract_evidence_path_prefix_correct(self):
        """Contract evidence path prefix is docs/quality/contracts/."""
        self.assertEqual(
            self.mod.CONTRACT_EVIDENCE_PATH_PREFIX,
            "docs/quality/contracts/",
        )

    def test_delivery_types_with_contract_gate(self):
        """Only new_feature is in contract gate set."""
        self.assertIn("new_feature", self.mod.DELIVERY_TYPES_WITH_CONTRACT_GATE)
        self.assertNotIn("backend_utility", self.mod.DELIVERY_TYPES_WITH_CONTRACT_GATE)
        self.assertNotIn("ai_rag", self.mod.DELIVERY_TYPES_WITH_CONTRACT_GATE)

    # --- Immutable task graph regression ---

    def test_generate_task_graph_force_rejected_on_active_run(self):
        """generate-task-graph --force still rejected when tasks are active (exit 16)."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target, "feature-contract-test")
            run_id = _setup_new_feature_run(target)
            devflow = target / ".devflow"
            run_data = json.loads((devflow / "runs" / f"{run_id}.json").read_text())
            # Activate a task: planned → ready is the valid transition that makes run active.
            planning_task = next(t for t in run_data["tasks"] if t["task_type"] == "planning")
            run_ops([
                "update-task-status",
                "--target", str(target),
                "--task-id", planning_task["id"],
                "--status", "ready",
            ])

            res = run_ops([
                "generate-task-graph",
                "--target", str(target),
                "--delivery-type", "new_feature",
                "--force",
            ])
            self.assertEqual(res.returncode, 16,
                             f"Expected exit 16 for immutable graph. stderr: {res.stderr}")

    # --- Risk floor regression ---

    def test_risk_floor_security_review_required_still_set(self):
        """Security risk floor still sets security_review_required for risky objectives."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target, "feature-contract-test")
            objective = "Add REST API endpoint with JWT auth"
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
            run_id = project["current_run_id"]
            run_data = json.loads((devflow / "runs" / f"{run_id}.json").read_text())
            self.assertTrue(run_data.get("security_review_required"),
                            "Risky backend_utility still requires security review")

    # --- Native delegation regression ---

    def test_native_delegation_constants_present(self):
        """Native delegation constants not removed."""
        self.assertTrue(hasattr(self.mod, "VALID_HOOK_EVENTS"),
                        "VALID_HOOK_EVENTS constant must still exist")

    # --- QA evidence regression ---

    def test_record_qa_evidence_still_works(self):
        """record-qa-evidence CLI still functions correctly."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            make_git_repo(target, "feature-contract-test")
            _setup_backend_utility_run(target)
            res = run_ops([
                "record-qa-evidence",
                "--target", str(target),
                "--total", "10",
                "--passed", "10",
                "--failed", "0",
                "--exit-code", "0",
                # Reported counts are no longer accepted silently; the caller
                # has to put on the record that nothing was measured.
                "--allow-self-reported",
            ])
            self.assertEqual(res.returncode, 0,
                             f"record-qa-evidence must still work. stderr: {res.stderr}")

    # --- Backward compatibility ---

    def test_old_run_state_without_contract_fields_not_blocked(self):
        """Old run states without contract_required default to gate satisfied."""
        tasks = self.mod.generate_task_graph_nodes("RUN-001", "backend_utility", "Parse CSV")
        for t in tasks:
            t["status"] = "verified"
        run_data = {
            "run_id": "RUN-001",
            "objective": "Parse CSV",
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
            # NOTE: no contract_required, contract_status, or contract_gate_satisfied
        }
        report = _verified_report(self.mod, run_data)
        cont = report["contract_applicability"]
        # Backward compat: defaults to not_applicable and gate satisfied
        self.assertFalse(cont.get("contract_required"))
        self.assertEqual(cont.get("contract_status"), "not_applicable")
        self.assertTrue(cont.get("contract_gate_satisfied"))
        # technical_readiness must not be not_ready due to contract alone
        self.assertEqual(report["technical_readiness"], "ready")

    def test_new_feature_task_graph_has_nine_tasks(self):
        """new_feature task graph still has 9 tasks after contract_definition rename."""
        tasks = self.mod.generate_task_graph_nodes("RUN-001", "new_feature", "Add user onboarding")
        self.assertEqual(len(tasks), 9,
                         f"new_feature must have 9 tasks. Got: {len(tasks)}")


if __name__ == "__main__":
    unittest.main()
