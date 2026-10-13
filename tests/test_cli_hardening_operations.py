"""Hardening tests for scripts/devflow_operations.py (Package B2-B5).

B2  concurrent recorders never lose a run-state write
B3  launch's branch/worktree number and the run state's run_id agree
B4  evidence gates: non-empty + changed-since-base work product, measured QA
    with consistent counts and a real command, implementation dependency order
B5  new_feature graph carries a docs-writer Documentation task
"""

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OPS_SCRIPT = REPO_ROOT / "scripts" / "devflow_operations.py"

WP_EXIT = 19
QA_EXIT = 21
TRANSITION_EXIT = 15


def _load_ops():
    spec = importlib.util.spec_from_file_location("devflow_ops_hardening", OPS_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True,
                          capture_output=True, text=True)


def make_repo(path: Path, feature_branch="feature/hardening") -> None:
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True, capture_output=True)
    _git(path, "config", "user.email", "test@devflow.test")
    _git(path, "config", "user.name", "DevFlow Test")
    (path / "README.md").write_text("hardening test project\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-q", "-m", "init")
    if feature_branch:
        _git(path, "checkout", "-q", "-b", feature_branch)


def run_ops(args, env=None):
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run([sys.executable, str(OPS_SCRIPT), *args],
                          capture_output=True, text=True, env=run_env)


class _RunFixture(unittest.TestCase):
    delivery_type = "new_feature"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.target = self.tmp / "proj"
        self.target.mkdir()
        make_repo(self.target)
        self.mod = _load_ops()
        self._before_run()
        for args in (["init-target"], ["create-run", "--objective", "Hardening fixture"],
                     ["generate-task-graph", "--delivery-type", self.delivery_type]):
            res = run_ops([args[0], "--target", str(self.target), *args[1:]])
            self.assertEqual(res.returncode, 0, res.stderr)
        project = json.loads((self.target / ".devflow" / "project.json").read_text())
        self.run_id = project["current_run_id"]
        self.run_file = self.target / ".devflow" / "runs" / f"{self.run_id}.json"

    def _before_run(self):
        pass

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def state(self):
        return self.mod.read_run_state(self.target, self.run_file)

    def task(self, suffix):
        return f"{self.run_id}-TASK-{suffix}"

    def write(self, rel, content="x = 1\n"):
        p = self.target / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return rel

    def record_wp(self, task_id, rel):
        return run_ops(["record-work-product-evidence", "--target", str(self.target),
                        "--task-id", task_id, "--evidence-path", rel])

    def set_status(self, task_id, *statuses):
        res = None
        for status in statuses:
            res = run_ops(["update-task-status", "--target", str(self.target),
                           "--task-id", task_id, "--status", status])
        return res


# ---------------------------------------------------------------------------
# B2: concurrency
# ---------------------------------------------------------------------------

class ConcurrentRecordersTest(_RunFixture):
    def test_concurrent_recorders_lose_no_writes(self):
        evidence = {
            self.task("005"): self.write("src/backend_api.py"),
            self.task("006"): self.write("src/frontend_view.py"),
            self.task("007"): self.write("tests/test_feature.py"),
            self.task("010"): self.write("docs/handoffs/feature.md", "# handoff\n"),
        }
        procs = [
            subprocess.Popen(
                [sys.executable, str(OPS_SCRIPT), "record-work-product-evidence",
                 "--target", str(self.target), "--task-id", task_id, "--evidence-path", rel],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            for task_id, rel in evidence.items()
        ]
        # Interleave status updates on other tasks with the recorders.
        procs += [
            subprocess.Popen(
                [sys.executable, str(OPS_SCRIPT), "update-task-status",
                 "--target", str(self.target), "--task-id", task_id, "--status", "ready"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            for task_id in (self.task("001"), self.task("002"))
        ]
        for proc in procs:
            _, err = proc.communicate(timeout=120)
            self.assertEqual(proc.returncode, 0, err)

        state = self.state()
        self.assertEqual(set(state["work_product_evidence"]), set(evidence))
        statuses = {t["id"]: t["status"] for t in state["tasks"]}
        self.assertEqual(statuses[self.task("001")], "ready")
        self.assertEqual(statuses[self.task("002")], "ready")

    def test_lock_is_reentrant_and_released(self):
        lock = self.mod.run_state_lock(self.target)
        with lock:
            with self.mod.run_state_lock(self.target):
                pass
        # A second process can take the lock afterwards.
        res = self.set_status(self.task("001"), "ready")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue((self.target / ".devflow" / "cache" / "run-state.lock").exists())

    def test_lock_does_not_create_devflow_for_uninitialized_target(self):
        bare = self.tmp / "bare"
        bare.mkdir()
        with self.mod.run_state_lock(bare):
            pass
        self.assertFalse((bare / ".devflow").exists())


# ---------------------------------------------------------------------------
# B3: run id agreement
# ---------------------------------------------------------------------------

def _fake_claude(directory: Path) -> Path:
    fake = directory / "fake_claude"
    fake.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return fake


class RunIdAgreementTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.target = self.tmp / "proj"
        self.target.mkdir()
        make_repo(self.target, feature_branch=None)
        _git(self.target, "branch", "devflow/run-run-003")

    def tearDown(self):
        listing = subprocess.run(["git", "worktree", "list", "--porcelain"],
                                 cwd=str(self.target), capture_output=True, text=True)
        for line in listing.stdout.splitlines():
            if line.startswith("worktree "):
                path = line.split(" ", 1)[1].strip()
                if Path(path).resolve() != self.target.resolve():
                    subprocess.run(["git", "worktree", "remove", "--force", path],
                                   cwd=str(self.target), capture_output=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_launch_state_matches_branch_and_worktree(self):
        res = run_ops(["launch", "--target", str(self.target)],
                      env={"DEVFLOW_CLAUDE_BINARY": str(_fake_claude(self.tmp))})
        self.assertEqual(res.returncode, 0, res.stderr)

        worktree = self.tmp / ".devflow-worktrees" / "proj" / "run-004"
        self.assertTrue(worktree.exists(), res.stdout)
        branches = _git(self.target, "branch", "--list", "devflow/run-*").stdout
        self.assertIn("devflow/run-run-004", branches)

        project = json.loads((worktree / ".devflow" / "project.json").read_text())
        self.assertEqual(project["current_run_id"], "RUN-004")
        self.assertEqual(project["run_counter"], 4)
        state = json.loads((worktree / ".devflow" / "runs" / "RUN-004.json").read_text())
        self.assertEqual(state["run_id"], "RUN-004")
        self.assertEqual(state["branch_name"], "devflow/run-run-004")

    def test_create_run_counts_past_existing_run_branches(self):
        _git(self.target, "checkout", "-q", "-b", "feature/x")
        self.assertEqual(run_ops(["init-target", "--target", str(self.target)]).returncode, 0)
        res = run_ops(["create-run", "--target", str(self.target)])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("RUN-004", res.stdout)
        self.assertIn("devflow/run-run-004", res.stdout)


# ---------------------------------------------------------------------------
# B4: work-product evidence
# ---------------------------------------------------------------------------

class WorkProductEvidenceHardeningTest(_RunFixture):
    delivery_type = "backend_utility"

    def _before_run(self):
        # Exists and is committed before the run starts: not run work product.
        (self.target / "src").mkdir()
        (self.target / "src" / "preexisting.py").write_text("OLD = 1\n", encoding="utf-8")
        _git(self.target, "add", "src/preexisting.py")
        _git(self.target, "commit", "-q", "-m", "preexisting source")

    def test_base_commit_recorded_at_create_run(self):
        head = _git(self.target, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(self.state()["base_commit"], head)

    def test_empty_file_rejected(self):
        res = self.record_wp(self.task("002"), self.write("src/empty.py", ""))
        self.assertEqual(res.returncode, WP_EXIT, res.stderr)
        self.assertIn("boş", res.stderr)

    def test_whitespace_only_file_rejected(self):
        res = self.record_wp(self.task("002"), self.write("src/blank.py", "\n  \n\t\n"))
        self.assertEqual(res.returncode, WP_EXIT, res.stderr)

    def test_unchanged_since_base_rejected(self):
        res = self.record_wp(self.task("002"), "src/preexisting.py")
        self.assertEqual(res.returncode, WP_EXIT, res.stderr)
        self.assertIn("base commit", res.stderr)

    def test_modified_since_base_accepted(self):
        self.write("src/preexisting.py", "NEW = 2\n")
        res = self.record_wp(self.task("002"), "src/preexisting.py")
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_committed_run_work_still_accepted(self):
        self.write("src/committed.py")
        _git(self.target, "add", "src/committed.py")
        _git(self.target, "commit", "-q", "-m", "run work")
        res = self.record_wp(self.task("002"), "src/committed.py")
        self.assertEqual(res.returncode, 0, res.stderr)


# ---------------------------------------------------------------------------
# B4: QA evidence
# ---------------------------------------------------------------------------

class QaEvidenceHardeningTest(_RunFixture):
    delivery_type = "backend_utility"

    def qa(self, *args):
        return run_ops(["record-qa-evidence", "--target", str(self.target), *args])

    def assert_gates_closed(self):
        gates = self.state()["approval_gates"]
        self.assertFalse(gates["tests_passing"])
        self.assertFalse(gates["qa_sign_off"])

    def test_trivially_true_commands_rejected(self):
        for command in ("true", "/bin/true", "/usr/bin/true", ":", "exit 0",
                        "echo all tests passed", "sh -c true", "bash -c 'exit 0'"):
            with self.subTest(command=command):
                res = self.qa("--test-command", command,
                              "--total", "3", "--passed", "3", "--failed", "0")
                self.assertEqual(res.returncode, QA_EXIT, res.stderr)
                self.assert_gates_closed()
                self.assertNotIn("qa_evidence", self.state())

    def test_trivial_command_helper(self):
        self.assertTrue(self.mod.is_trivial_test_command([]))
        self.assertTrue(self.mod.is_trivial_test_command(["echo"]))
        self.assertFalse(self.mod.is_trivial_test_command(["pytest", "-q"]))
        self.assertFalse(self.mod.is_trivial_test_command(["sh", "-c", "pytest -q"]))

    def test_counts_required_with_test_command(self):
        res = self.qa("--test-command", "python3 -c pass")
        self.assertEqual(res.returncode, QA_EXIT, res.stderr)
        self.assert_gates_closed()

    def test_inconsistent_counts_rejected(self):
        cases = [
            ("0", "0", "0"),     # nothing ran
            ("5", "3", "1"),     # does not add up
            ("2", "-1", "3"),    # negative
        ]
        for total, passed, failed in cases:
            with self.subTest(total=total, passed=passed, failed=failed):
                res = self.qa("--test-command", "python3 -c pass",
                              "--total", total, "--passed", passed, "--failed", failed)
                self.assertEqual(res.returncode, QA_EXIT, res.stderr)
                self.assert_gates_closed()

    def test_self_reported_exit_code_must_match_failures(self):
        for exit_code, failed, passed in (("0", "1", "1"), ("1", "0", "2")):
            with self.subTest(exit_code=exit_code, failed=failed):
                res = self.qa("--allow-self-reported", "--total", "2", "--passed", passed,
                              "--failed", failed, "--exit-code", exit_code)
                self.assertEqual(res.returncode, QA_EXIT, res.stderr)

    def test_passing_run_with_reported_failures_closes_gates(self):
        res = self.qa("--test-command", "python3 -c pass",
                      "--total", "2", "--passed", "1", "--failed", "1")
        self.assertEqual(res.returncode, QA_EXIT, res.stderr)
        self.assert_gates_closed()
        self.assertFalse(self.state()["qa_evidence"]["counts_consistent"])

    def test_failing_run_reported_as_passing_closes_previous_pass(self):
        ok = self.qa("--test-command", "python3 -c pass",
                     "--total", "1", "--passed", "1", "--failed", "0")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertTrue(self.state()["approval_gates"]["qa_sign_off"])
        res = self.qa("--test-command", "python3 -c import sys; sys.exit(1)",
                      "--total", "1", "--passed", "1", "--failed", "0")
        self.assertEqual(res.returncode, QA_EXIT, res.stderr)
        self.assert_gates_closed()

    def test_consistent_measured_pass_opens_gates(self):
        res = self.qa("--test-command", "python3 -c pass",
                      "--total", "4", "--passed", "4", "--failed", "0")
        self.assertEqual(res.returncode, 0, res.stderr)
        evidence = self.state()["qa_evidence"]
        self.assertEqual(evidence["source"], "executed")
        self.assertTrue(evidence["counts_consistent"])
        self.assertTrue(self.state()["approval_gates"]["qa_sign_off"])


# ---------------------------------------------------------------------------
# B4: dependency ordering
# ---------------------------------------------------------------------------

class ImplementationDependencyOrderTest(_RunFixture):
    delivery_type = "backend_utility"

    def test_implementation_waits_for_dependencies(self):
        impl = self.task("002")
        self.set_status(impl, "ready")
        res = self.set_status(impl, "in_progress")
        self.assertEqual(res.returncode, TRANSITION_EXIT, res.stderr)
        self.assertIn(self.task("001"), res.stderr)

        res = self.set_status(self.task("001"), "ready", "in_progress", "completed")
        self.assertEqual(res.returncode, 0, res.stderr)
        res = self.set_status(impl, "in_progress")
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_non_implementation_tasks_not_ordered(self):
        qa = self.task("003")
        res = self.set_status(qa, "ready", "in_progress")
        self.assertEqual(res.returncode, 0, res.stderr)


# ---------------------------------------------------------------------------
# B5: documentation task
# ---------------------------------------------------------------------------

class DocumentationTaskGraphTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_ops()

    def test_new_feature_has_docs_writer_task_before_release(self):
        for needs_adr in (False, True):
            with self.subTest(needs_adr=needs_adr):
                tasks = {t["id"]: t for t in self.mod.generate_task_graph_nodes(
                    "RUN-001", "new_feature", "Add onboarding", needs_adr=needs_adr)}
                docs = tasks["RUN-001-TASK-010"]
                self.assertEqual(docs["assigned_role"], "docs-writer")
                self.assertEqual(docs["task_type"], "documentation")
                self.assertEqual(docs["dependency_ids"], ["RUN-001-TASK-007", "RUN-001-TASK-008"])
                release = tasks["RUN-001-TASK-009"]
                self.assertEqual(release["assigned_role"], "integration-release")
                self.assertEqual(release["dependency_ids"], ["RUN-001-TASK-010"])

    def test_documentation_evidence_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            for rel in ("README.md", "pkg/api/README.md", "docs/handoffs/REQ-001.md",
                        "docs/notes.md", "src/x.py", ".devflow/README.md"):
                p = target / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("content\n", encoding="utf-8")
            check = self.mod.validate_work_product_evidence_path
            for rel in ("README.md", "pkg/api/README.md", "docs/handoffs/REQ-001.md"):
                with self.subTest(accepted=rel):
                    ok, err = check(target, "documentation", rel)
                    self.assertTrue(ok, err)
            for rel in ("docs/notes.md", "src/x.py", ".devflow/README.md"):
                with self.subTest(rejected=rel):
                    ok, _ = check(target, "documentation", rel)
                    self.assertFalse(ok)
            ok, _ = check(target, "implementation", "docs/handoffs/REQ-001.md")
            self.assertFalse(ok, "docs exception must not leak to implementation tasks")


class DocumentationTaskGateTest(_RunFixture):
    def test_documentation_completion_needs_evidence(self):
        docs = self.task("010")
        res = self.set_status(docs, "ready", "in_progress", "completed")
        self.assertEqual(res.returncode, TRANSITION_EXIT, res.stderr)
        self.assertIn("record-work-product-evidence", res.stderr)

        res = self.record_wp(docs, self.write("docs/handoffs/feature.md", "# handoff\n"))
        self.assertEqual(res.returncode, 0, res.stderr)
        res = self.set_status(docs, "completed")
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_unchanged_root_readme_is_not_documentation_evidence(self):
        res = self.record_wp(self.task("010"), "README.md")
        self.assertEqual(res.returncode, WP_EXIT, res.stderr)


if __name__ == "__main__":
    unittest.main()
