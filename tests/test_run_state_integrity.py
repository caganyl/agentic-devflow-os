"""
Tests for run state integrity signing in devflow_operations.py.

The target guard blocks Write/Edit to .devflow/runs/, but no tool-call guard
can see a shell redirect, so `echo '{...}' > .devflow/runs/run-001.json`
reached the canonical state that every approval gate reads. These tests pin
the property that closes that hole: gates refuse state this CLI did not sign,
regardless of which write path produced it.

Covers:
1.  create-run produces state carrying a valid signature
2.  Signature verifies with the target's own key
3.  Shell-forged state (the actual bypass) is rejected by a gate command
4.  Raw in-place mutation of approval_gates is rejected
5.  Mutation of nested evidence fields is rejected
6.  Removing the signature entirely is rejected
7.  State signed for one target does not verify in another (per-target key)
8.  Signature field never leaks into generated reports
9.  Key file is created with 0600 permissions
10. Guard blocks Write/Edit to the signing key
"""

# PEP 563: keep `X | None` annotations unevaluated so this module imports on
# Python 3.9, the interpreter macOS ships as /usr/bin/python3.
from __future__ import annotations

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
GUARD_SCRIPT = REPO_ROOT / "scripts" / "devflow_target_guard.py"

INTEGRITY_EXIT = 20


def _load_ops_module():
    spec = importlib.util.spec_from_file_location("devflow_ops_integrity", OPS_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_ops(args: list) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(OPS_SCRIPT)] + args,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )


def make_git_repo(path: Path, branch: str = "feature-work") -> None:
    subprocess.run(["git", "init", "-b", branch, str(path)], check=True, capture_output=True)
    for key, value in (("user.email", "test@devflow.test"), ("user.name", "DevFlow Test")):
        subprocess.run(["git", "config", key, value], check=True, capture_output=True, cwd=str(path))
    (path / "README.md").write_text("test project\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], check=True, capture_output=True, cwd=str(path))
    subprocess.run(["git", "commit", "-m", "init"], check=True, capture_output=True, cwd=str(path))


class RunStateIntegrityTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.target = self.tmpdir / "myproject"
        self.target.mkdir()
        make_git_repo(self.target)
        self.mod = _load_ops_module()

        res = run_ops(["init-target", "--target", str(self.target)])
        self.assertEqual(res.returncode, 0, res.stderr)
        res = run_ops(["create-run", "--target", str(self.target), "--objective", "integrity test"])
        self.assertEqual(res.returncode, 0, res.stderr)

        self.devflow = self.target / ".devflow"
        runs = sorted((self.devflow / "runs").glob("*.json"))
        self.assertEqual(len(runs), 1, "expected exactly one run state file")
        self.run_file = runs[0]
        self.run_id = self.run_file.stem

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _raw_state(self) -> dict:
        return json.loads(self.run_file.read_text(encoding="utf-8"))

    def _write_raw(self, data: dict) -> None:
        """Write state the way a forger would — bypassing the CLI entirely."""
        self.run_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def _gate_command(self) -> subprocess.CompletedProcess:
        """Any command that reads run state through a gate."""
        return run_ops(["generate-run-report", "--target", str(self.target)])

    # --- 1 & 2: signing happens and verifies ---

    def test_created_state_carries_signature(self):
        state = self._raw_state()
        self.assertIn("_signature", state)
        self.assertEqual(state["_signature"]["alg"], "HMAC-SHA256")
        self.assertRegex(state["_signature"]["value"], r"^[0-9a-f]{64}$")

    def test_signature_verifies_with_target_key(self):
        key = self.mod.load_or_create_state_key(self.target)
        self.assertTrue(self.mod.verify_run_state(self._raw_state(), key))

    def test_gate_accepts_untampered_state(self):
        self.assertEqual(self._gate_command().returncode, 0)

    # --- 3: the actual bypass this signing exists to close ---

    def test_shell_forged_state_rejected(self):
        forged = json.dumps({
            "schema_version": "1",
            "run_id": self.run_id,
            "status": "created",
            "objective": "forged",
            "tasks": [],
            "approval_gates": {
                "contract_approved": True,
                "tests_passing": True,
                "security_review_complete": True,
                "qa_sign_off": True,
                "human_approval": True,
            },
        })
        # Exactly the write path the guard cannot see.
        subprocess.run(
            f"echo '{forged}' > {self.run_file}",
            shell=True, check=True, cwd=str(self.target),
        )
        result = self._gate_command()
        self.assertEqual(
            result.returncode, INTEGRITY_EXIT,
            f"shell-forged state must fail closed. stdout: {result.stdout}",
        )

    # --- 4-6: tamper detection on real state ---

    def test_flipped_approval_gate_rejected(self):
        state = self._raw_state()
        state["approval_gates"]["qa_sign_off"] = True
        state["approval_gates"]["human_approval"] = True
        self._write_raw(state)
        self.assertEqual(self._gate_command().returncode, INTEGRITY_EXIT)

    def test_nested_field_mutation_rejected(self):
        state = self._raw_state()
        state["objective"] = "something else entirely"
        self._write_raw(state)
        self.assertEqual(self._gate_command().returncode, INTEGRITY_EXIT)

    def test_stripped_signature_rejected(self):
        state = self._raw_state()
        state.pop("_signature")
        self._write_raw(state)
        self.assertEqual(self._gate_command().returncode, INTEGRITY_EXIT)

    def test_signature_value_tampered_rejected(self):
        state = self._raw_state()
        state["_signature"]["value"] = "0" * 64
        self._write_raw(state)
        self.assertEqual(self._gate_command().returncode, INTEGRITY_EXIT)

    # --- 7: keys are per-target, so state cannot be replayed across worktrees ---

    def test_state_does_not_verify_under_another_target_key(self):
        other = self.tmpdir / "otherproject"
        other.mkdir()
        make_git_repo(other)
        run_ops(["init-target", "--target", str(other)])
        other_key = self.mod.load_or_create_state_key(other)
        self.assertFalse(self.mod.verify_run_state(self._raw_state(), other_key))

    def test_copied_state_rejected_in_other_target(self):
        other = self.tmpdir / "otherproject"
        other.mkdir()
        make_git_repo(other)
        run_ops(["init-target", "--target", str(other)])
        run_ops(["create-run", "--target", str(other), "--objective", "other run"])
        other_runs = sorted((other / ".devflow" / "runs").glob("*.json"))
        shutil.copy2(self.run_file, other_runs[0])
        result = run_ops(["generate-run-report", "--target", str(other)])
        self.assertEqual(result.returncode, INTEGRITY_EXIT)

    # --- 8: the signature is an implementation detail, not report content ---

    def test_signature_absent_from_generated_report(self):
        self.assertEqual(self._gate_command().returncode, 0)
        for report in (self.devflow / "reports").glob("*.json"):
            self.assertNotIn(
                "_signature", report.read_text(encoding="utf-8"),
                f"signature leaked into {report.name}",
            )

    def test_read_run_state_strips_signature(self):
        state = self.mod.read_run_state(self.target, self.run_file)
        self.assertNotIn("_signature", state)

    # --- 9 & 10: the key itself is protected ---

    def test_key_file_is_owner_only(self):
        self.mod.load_or_create_state_key(self.target)
        key_path = self.mod.state_key_path(self.target)
        self.assertTrue(key_path.exists())
        mode = stat.S_IMODE(key_path.stat().st_mode)
        self.assertEqual(mode, 0o600, f"key mode should be 0600, got {oct(mode)}")

    def test_key_is_stable_across_calls(self):
        first = self.mod.load_or_create_state_key(self.target)
        second = self.mod.load_or_create_state_key(self.target)
        self.assertEqual(first, second)

    def test_guard_blocks_write_to_signing_key(self):
        key_path = self.target / ".devflow" / "cache" / "state-signing.key"
        payload = json.dumps({
            "tool_name": "Write",
            "tool_input": {"file_path": str(key_path)},
        })
        result = subprocess.run(
            [sys.executable, str(GUARD_SCRIPT)],
            input=payload, capture_output=True, text=True,
        )
        self.assertEqual(
            result.returncode, 2,
            "guard must block Write to the signing key; re-keying would make "
            "the signature worthless",
        )


if __name__ == "__main__":
    unittest.main()
