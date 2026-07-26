"""
Tests for evidence verification: measured QA, observed delegation, and
work-product uniqueness.

These pin the three ways a run used to look complete without anyone having
done the work:

  * QA counts were arguments. `--total 412 --passed 412` was accepted by a
    project with no test suite; nothing ever ran a test.
  * The report said "delegation doğrulanmadı" and "awaiting_human_approval"
    at the same time — delegation was reported but never reached the
    recommendation.
  * One src/api.py satisfied both the backend and the frontend implementation
    task: two roles, two acceptance decisions, one file.

Covers:
1.  QA evidence refuses to record without measuring or an explicit disclaimer
2.  --test-command executes and takes the exit code from the real run
3.  A failing test command clears the QA gates
4.  Executed evidence is marked "executed"; reported counts are "self_reported"
5.  Self-reported QA holds the report at unverified_evidence
6.  Unobserved delegation holds the report at unverified_evidence
7.  Observed delegation + executed QA reaches awaiting_human_approval
8.  technical_readiness stays separate from merge_recommendation
9.  One evidence path cannot back two tasks
10. Re-recording the same path for the same task is still allowed
"""

# PEP 563: keep `X | None` annotations unevaluated so this module imports on
# Python 3.9, the interpreter macOS ships as /usr/bin/python3.
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

QA_EVIDENCE_EXIT = 21
WORK_PRODUCT_EXIT = 19


def _load_ops_module():
    spec = importlib.util.spec_from_file_location("devflow_ops_evidence", OPS_SCRIPT)
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
    for key, value in (("user.email", "t@t.t"), ("user.name", "T")):
        subprocess.run(["git", "config", key, value], check=True, capture_output=True, cwd=str(path))
    (path / "README.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], check=True, capture_output=True, cwd=str(path))
    subprocess.run(["git", "commit", "-m", "init"], check=True, capture_output=True, cwd=str(path))


class EvidenceVerificationTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.target = self.tmpdir / "proj"
        self.target.mkdir()
        make_git_repo(self.target)
        self.mod = _load_ops_module()

        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target),
                 "--objective", "Add REST API endpoint with JWT authentication"])
        run_ops(["generate-task-graph", "--target", str(self.target),
                 "--delivery-type", "new_feature"])

        self.devflow = self.target / ".devflow"
        self.run_file = sorted((self.devflow / "runs").glob("*.json"))[0]
        self.run_id = self.run_file.stem

        (self.target / "src").mkdir(exist_ok=True)
        (self.target / "tests").mkdir(exist_ok=True)
        (self.target / "src" / "api.py").write_text("def handler(): return 1\n", encoding="utf-8")
        (self.target / "src" / "ui.py").write_text("def render(): return 2\n", encoding="utf-8")
        (self.target / "tests" / "test_api.py").write_text("def test_x(): pass\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _state(self) -> dict:
        return self.mod.read_run_state(self.target, self.run_file)

    def _tasks_of_type(self, task_type: str) -> list:
        return [t for t in self._state()["tasks"] if t["task_type"] == task_type]

    def _observe_delegation(self) -> None:
        events = self.devflow / "delegation-events"
        events.mkdir(parents=True, exist_ok=True)
        (events / "start-001.json").write_text(json.dumps({
            "hook_event": "SubagentStart", "lifecycle_state": "started",
            "run_id": self.run_id, "agent_type": "backend-engineer",
        }), encoding="utf-8")

    # --- 1-4: QA evidence must be measured ---

    def test_qa_evidence_refuses_bare_counts(self):
        result = run_ops([
            "record-qa-evidence", "--target", str(self.target),
            "--total", "412", "--passed", "412", "--failed", "0", "--exit-code", "0",
        ])
        self.assertEqual(result.returncode, QA_EVIDENCE_EXIT)
        self.assertIn("--test-command", result.stderr)

    def test_qa_evidence_refuses_command_and_disclaimer_together(self):
        result = run_ops([
            "record-qa-evidence", "--target", str(self.target),
            "--test-command", "python3 -c pass", "--allow-self-reported",
            "--total", "1", "--passed", "1", "--failed", "0", "--exit-code", "0",
        ])
        self.assertEqual(result.returncode, QA_EVIDENCE_EXIT)

    def test_qa_evidence_self_reported_requires_all_counts(self):
        result = run_ops([
            "record-qa-evidence", "--target", str(self.target),
            "--allow-self-reported", "--total", "5",
        ])
        self.assertEqual(result.returncode, QA_EVIDENCE_EXIT)

    def test_executed_command_sets_gates_and_source(self):
        result = run_ops([
            "record-qa-evidence", "--target", str(self.target),
            "--test-command", "python3 -c pass",
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        state = self._state()
        self.assertEqual(state["qa_evidence"]["source"], "executed")
        self.assertEqual(state["qa_evidence"]["exit_code"], 0)
        self.assertTrue(state["approval_gates"]["qa_sign_off"])

    def test_failing_command_clears_gates_even_if_caller_expected_pass(self):
        result = run_ops([
            "record-qa-evidence", "--target", str(self.target),
            "--test-command", "python3 -c import sys; sys.exit(3)",
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        state = self._state()
        self.assertNotEqual(state["qa_evidence"]["exit_code"], 0)
        self.assertFalse(state["approval_gates"]["qa_sign_off"])
        self.assertFalse(state["approval_gates"]["tests_passing"])

    def test_self_reported_is_marked_as_such(self):
        run_ops([
            "record-qa-evidence", "--target", str(self.target),
            "--allow-self-reported",
            "--total", "412", "--passed", "412", "--failed", "0", "--exit-code", "0",
        ])
        self.assertEqual(self._state()["qa_evidence"]["source"], "self_reported")

    # --- 5-8: verification reaches the merge recommendation ---

    def _all_gates_run_data(self, human: bool, qa_source: str) -> dict:
        tasks = self.mod.generate_task_graph_nodes(self.run_id, "backend_utility", "utility")
        for t in tasks:
            t["status"] = "verified"
        return {
            "run_id": self.run_id, "objective": "utility",
            "execution_mode": "subagents", "agent_teams_requested": False,
            "tasks": tasks,
            "approval_gates": {
                "contract_approved": True, "tests_passing": True,
                "security_review_complete": True, "qa_sign_off": True,
                "human_approval": human,
            },
            "security_review_required": False,
            "security_applicability_reason": "low_risk_local_utility",
            "qa_evidence": {"source": qa_source, "qa_passed": True, "exit_code": 0},
            "work_product_evidence": {
                t["id"]: {
                    "task_type": t["task_type"],
                    "evidence_path": f"src/{t['id']}.py",
                    "recorded_at": "2026-06-28T12:00:00Z",
                    "git_change_verified_at_record_time": True,
                }
                for t in tasks if t["task_type"] in ("implementation", "qa")
            },
        }

    def _events(self) -> list:
        return [{"hook_event": "SubagentStart", "lifecycle_state": "started",
                 "run_id": self.run_id, "agent_type": "backend-engineer"}]

    def test_self_reported_qa_holds_recommendation(self):
        report = self.mod.build_run_report(
            self._all_gates_run_data(human=False, qa_source="self_reported"),
            self.run_id, delegation_events=self._events(),
        )
        self.assertEqual(report["merge_recommendation"], "unverified_evidence")
        self.assertIn("qa_self_reported",
                      report["evidence_verification"]["unverified_reasons"])

    def test_unobserved_delegation_holds_recommendation(self):
        report = self.mod.build_run_report(
            self._all_gates_run_data(human=False, qa_source="executed"), self.run_id
        )
        self.assertEqual(report["merge_recommendation"], "unverified_evidence")
        self.assertIn("delegation_unobserved",
                      report["evidence_verification"]["unverified_reasons"])

    def test_measured_and_observed_reaches_human_gate(self):
        report = self.mod.build_run_report(
            self._all_gates_run_data(human=False, qa_source="executed"),
            self.run_id, delegation_events=self._events(),
        )
        self.assertEqual(report["merge_recommendation"], "awaiting_human_approval")
        self.assertTrue(report["evidence_verification"]["verified"])
        self.assertEqual(report["evidence_verification"]["unverified_reasons"], [])

    def test_technical_readiness_stays_separate_from_recommendation(self):
        """Gates passing is still reported as ready; only the recommendation holds."""
        report = self.mod.build_run_report(
            self._all_gates_run_data(human=True, qa_source="self_reported"), self.run_id
        )
        self.assertEqual(report["technical_readiness"], "ready")
        self.assertEqual(report["merge_recommendation"], "unverified_evidence")

    # --- 9-10: work-product evidence uniqueness ---

    def _start_task(self, task_id: str) -> None:
        for status in ("ready", "in_progress"):
            run_ops(["update-task-status", "--target", str(self.target),
                     "--task-id", task_id, "--status", status])

    def test_same_path_cannot_back_two_tasks(self):
        impl = self._tasks_of_type("implementation")
        self.assertGreaterEqual(len(impl), 2, "new_feature should have two implementation tasks")
        first, second = impl[0]["id"], impl[1]["id"]

        run_ops(["record-contract-evidence", "--target", str(self.target),
                 "--evidence-path", self._make_contract()])
        self._start_task(first)
        self._start_task(second)

        ok = run_ops(["record-work-product-evidence", "--target", str(self.target),
                      "--task-id", first, "--evidence-path", "src/api.py"])
        self.assertEqual(ok.returncode, 0, ok.stderr)

        clash = run_ops(["record-work-product-evidence", "--target", str(self.target),
                         "--task-id", second, "--evidence-path", "src/api.py"])
        self.assertEqual(clash.returncode, WORK_PRODUCT_EXIT,
                         f"same file must not back two tasks. stdout: {clash.stdout}")
        self.assertIn(first, clash.stderr)

    def test_distinct_paths_are_accepted(self):
        impl = self._tasks_of_type("implementation")
        first, second = impl[0]["id"], impl[1]["id"]
        run_ops(["record-contract-evidence", "--target", str(self.target),
                 "--evidence-path", self._make_contract()])
        self._start_task(first)
        self._start_task(second)

        a = run_ops(["record-work-product-evidence", "--target", str(self.target),
                     "--task-id", first, "--evidence-path", "src/api.py"])
        b = run_ops(["record-work-product-evidence", "--target", str(self.target),
                     "--task-id", second, "--evidence-path", "src/ui.py"])
        self.assertEqual(a.returncode, 0, a.stderr)
        self.assertEqual(b.returncode, 0, b.stderr)

    def test_same_task_may_rerecord_same_path(self):
        impl = self._tasks_of_type("implementation")[0]["id"]
        run_ops(["record-contract-evidence", "--target", str(self.target),
                 "--evidence-path", self._make_contract()])
        self._start_task(impl)
        run_ops(["record-work-product-evidence", "--target", str(self.target),
                 "--task-id", impl, "--evidence-path", "src/api.py"])
        again = run_ops(["record-work-product-evidence", "--target", str(self.target),
                         "--task-id", impl, "--evidence-path", "src/api.py"])
        self.assertEqual(again.returncode, 0, again.stderr)

    def _make_contract(self) -> str:
        rel = "docs/quality/contracts/REQ-001-contract.md"
        path = self.target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# contract\n", encoding="utf-8")
        return rel


if __name__ == "__main__":
    unittest.main()
