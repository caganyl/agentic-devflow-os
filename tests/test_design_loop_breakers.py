"""
Tests for the two design-phase loop breakers in
.claude/hooks/enforce-role-boundaries.sh:

1. Managed-run implementer binding: `launch` runs live on devflow/run-* branches.
   Implementer writes there were always denied (branch had to be req-XXX-*),
   which pushed managed runs back into endless ADR/review work. The hook now
   binds a managed run branch to the REQ recorded in the run state.

2. ADR loop breaker: review rounds are capped, accepted ADRs are frozen, ADR
   size is budgeted and only adr-reviewer writes immutable review files.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_PATH = REPO_ROOT / ".claude" / "hooks" / "enforce-role-boundaries.sh"
VALIDATOR_PATH = REPO_ROOT / "scripts" / "validate_ownership_manifest.py"

RUN_BRANCH = "devflow/run-run-001"


class _HookFixture(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self._git("init", "-q")
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "T")
        (self.root / "README.md").write_text("x\n")
        self._git("add", "README.md")
        self._git("commit", "-q", "-m", "init")

        scripts = self.root / "scripts"
        scripts.mkdir()
        shutil.copyfile(VALIDATOR_PATH, scripts / "validate_ownership_manifest.py")

        for rel in ("docs/product/requirements", "docs/product/acceptance-criteria",
                    "docs/contracts/openapi", "docs/ownership",
                    "docs/architecture/adr/reviews"):
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        (self.root / "docs/product/requirements/REQ-042.md").write_text("r\n")
        (self.root / "docs/product/acceptance-criteria/REQ-042.md").write_text("a\n")
        (self.root / "docs/contracts/openapi/REQ-042.yaml").write_text("c\n")

    def tearDown(self):
        self.tmpdir.cleanup()

    def _git(self, *args):
        subprocess.run(["git", "-C", str(self.root), *args],
                       check=True, capture_output=True, text=True)

    def _write_manifest(self, status="approved"):
        manifest = {
            "$schema": "./schema.json",
            "schema_version": 1,
            "req_id": "REQ-042",
            "title": "Login flow",
            "status": status,
            "approval": {"approved_by": "human-maintainer", "approved_at": "2026-06-25"},
            "references": {
                "requirement": "docs/product/requirements/REQ-042.md",
                "acceptance_criteria": "docs/product/acceptance-criteria/REQ-042.md",
                "contracts": ["docs/contracts/openapi/REQ-042.yaml"],
                "contract_exception": {"reason": "", "approved_by": "", "approved_at": ""},
                "adrs": [],
            },
            "owners": [
                {"agent": "backend-engineer", "write_paths": ["apps/api/src"], "notes": "be"},
            ],
        }
        (self.root / "docs/ownership/REQ-042.json").write_text(json.dumps(manifest))

    def _write_run_state(self, req_id):
        devflow = self.root / ".devflow"
        (devflow / "runs").mkdir(parents=True, exist_ok=True)
        (devflow / "project.json").write_text(json.dumps({"current_run_id": "run-001"}))
        (devflow / "runs" / "run-001.json").write_text(json.dumps({"run_id": "run-001", "req_id": req_id}))

    def _hook(self, agent, file_path, tool="Write", tool_input=None, env_extra=None):
        ti = {"file_path": file_path}
        if tool_input:
            ti.update(tool_input)
        payload = {"cwd": str(self.root), "agent_type": agent, "tool_name": tool, "tool_input": ti}
        env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")}
        if env_extra:
            env.update(env_extra)
        return subprocess.run(["bash", str(HOOK_PATH)], input=json.dumps(payload),
                              capture_output=True, text=True, env=env)

    def _decision(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        if not result.stdout.strip():
            return "allow", ""
        out = json.loads(result.stdout)["hookSpecificOutput"]
        return out["permissionDecision"], out.get("permissionDecisionReason", "")


class ManagedRunImplementerBindingTest(_HookFixture):
    def setUp(self):
        super().setUp()
        self._git("checkout", "-q", "-b", RUN_BRANCH)
        self.env = {"DEVFLOW_RUN_BRANCH": RUN_BRANCH}

    def test_bound_run_allows_owner_write(self):
        self._write_manifest()
        self._write_run_state("REQ-042")
        decision, reason = self._decision(
            self._hook("backend-engineer", "apps/api/src/login.cs", env_extra=self.env))
        self.assertEqual(decision, "allow", reason)

    def test_plugin_scoped_agent_on_bound_run_allowed(self):
        self._write_manifest()
        self._write_run_state("REQ-042")
        decision, reason = self._decision(
            self._hook("devflow-plugin:backend-engineer", "apps/api/src/login.cs", env_extra=self.env))
        self.assertEqual(decision, "allow", reason)

    def test_bound_run_still_enforces_write_paths(self):
        self._write_manifest()
        self._write_run_state("REQ-042")
        decision, _ = self._decision(
            self._hook("backend-engineer", "apps/web/src/page.tsx", env_extra=self.env))
        self.assertEqual(decision, "deny")

    def test_bound_run_requires_approved_manifest(self):
        self._write_manifest(status="draft")
        self._write_run_state("REQ-042")
        decision, _ = self._decision(
            self._hook("backend-engineer", "apps/api/src/login.cs", env_extra=self.env))
        self.assertEqual(decision, "deny")

    def test_unbound_run_denied_with_actionable_reason(self):
        self._write_manifest()
        self._write_run_state("")
        decision, reason = self._decision(
            self._hook("backend-engineer", "apps/api/src/login.cs", env_extra=self.env))
        self.assertEqual(decision, "deny")
        self.assertIn("launch --req-id", reason)
        self.assertIn("do not loop back", reason)

    def test_run_branch_without_matching_env_denied(self):
        self._write_manifest()
        self._write_run_state("REQ-042")
        decision, _ = self._decision(self._hook("backend-engineer", "apps/api/src/login.cs"))
        self.assertEqual(decision, "deny")

    def test_validator_managed_flag_rejects_non_run_branch(self):
        self._write_manifest()
        result = subprocess.run(
            ["python3", str(VALIDATOR_PATH), "--manifest", str(self.root / "docs/ownership/REQ-042.json"),
             "--root", str(self.root), "--branch", "feature/x", "--managed-run",
             "--authorize-agent", "backend-engineer", "--target", "apps/api/src/a.cs"],
            capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)


class AdrLoopBreakerTest(_HookFixture):
    ADR = "docs/architecture/adr/ADR-010-cache.md"

    def setUp(self):
        super().setUp()
        self._git("checkout", "-q", "-b", "req-042-login-flow")

    def _adr(self, status="Proposed", body="Decision text.\n"):
        (self.root / self.ADR).write_text(
            f"# ADR-010 — Cache\n\n## Status\n{status}\n\n## Decision\n{body}",
            encoding="utf-8")

    def _review(self, rnd, verdict="BLOCK"):
        (self.root / f"docs/architecture/adr/reviews/ADR-010-review-{rnd}.md").write_text(
            f"VERDICT: {verdict}\n")

    def test_architect_can_create_new_adr(self):
        decision, reason = self._decision(self._hook(
            "solution-architect", self.ADR, tool_input={"content": "# ADR-010\n\n## Status\nProposed\n"}))
        self.assertEqual(decision, "allow", reason)

    def test_accepted_adr_is_frozen(self):
        self._adr(status="Accepted")
        decision, reason = self._decision(self._hook(
            "solution-architect", self.ADR, tool="Edit",
            tool_input={"old_string": "Decision text.", "new_string": "Changed."}))
        self.assertEqual(decision, "deny")
        self.assertIn("frozen", reason)

    def test_revision_allowed_after_one_review(self):
        self._adr()
        self._review(1)
        decision, reason = self._decision(self._hook(
            "solution-architect", self.ADR, tool="Edit",
            tool_input={"old_string": "Decision text.", "new_string": "Fixed blocker."}))
        self.assertEqual(decision, "allow", reason)

    def test_revision_blocked_after_max_rounds(self):
        self._adr()
        self._review(1)
        self._review(2)
        decision, reason = self._decision(self._hook(
            "solution-architect", self.ADR, tool="Edit",
            tool_input={"old_string": "Decision text.", "new_string": "Again."}))
        self.assertEqual(decision, "deny")
        self.assertIn("human", reason)

    def test_adr_size_budget(self):
        decision, reason = self._decision(self._hook(
            "solution-architect", self.ADR, tool_input={"content": "x" * 12001}))
        self.assertEqual(decision, "deny")
        self.assertIn("budget", reason)

    def test_shrinking_edit_on_oversized_adr_allowed(self):
        self._adr(body="y" * 13000)
        decision, reason = self._decision(self._hook(
            "solution-architect", self.ADR, tool="Edit",
            tool_input={"old_string": "y" * 2000, "new_string": "z"}))
        self.assertEqual(decision, "allow", reason)

    def test_reviewer_writes_first_round(self):
        self._adr()
        decision, reason = self._decision(self._hook(
            "adr-reviewer", "docs/architecture/adr/reviews/ADR-010-review-1.md",
            tool_input={"content": "VERDICT: APPROVE_WITH_NOTES\nNOTES:\n- x\n"}))
        self.assertEqual(decision, "allow", reason)

    def test_reviewer_third_round_denied(self):
        self._adr()
        self._review(1)
        self._review(2)
        decision, _ = self._decision(self._hook(
            "adr-reviewer", "docs/architecture/adr/reviews/ADR-010-review-3.md",
            tool_input={"content": "VERDICT: BLOCK\n"}))
        self.assertEqual(decision, "deny")

    def test_reviewer_cannot_skip_round(self):
        self._adr()
        decision, _ = self._decision(self._hook(
            "adr-reviewer", "docs/architecture/adr/reviews/ADR-010-review-2.md",
            tool_input={"content": "VERDICT: BLOCK\n"}))
        self.assertEqual(decision, "deny")

    def test_review_requires_verdict_line(self):
        self._adr()
        decision, _ = self._decision(self._hook(
            "adr-reviewer", "docs/architecture/adr/reviews/ADR-010-review-1.md",
            tool_input={"content": "Looks fine overall, a few thoughts...\n"}))
        self.assertEqual(decision, "deny")

    def test_reviews_are_immutable(self):
        self._adr()
        self._review(1)
        decision, _ = self._decision(self._hook(
            "adr-reviewer", "docs/architecture/adr/reviews/ADR-010-review-1.md", tool="Edit",
            tool_input={"old_string": "BLOCK", "new_string": "APPROVE"}))
        self.assertEqual(decision, "deny")

    def test_architect_cannot_write_reviews(self):
        decision, _ = self._decision(self._hook(
            "solution-architect", "docs/architecture/adr/reviews/ADR-010-review-1.md",
            tool_input={"content": "VERDICT: APPROVE\n"}))
        self.assertEqual(decision, "deny")

    def test_reviewer_cannot_edit_adr(self):
        self._adr()
        decision, _ = self._decision(self._hook(
            "adr-reviewer", self.ADR, tool="Edit",
            tool_input={"old_string": "Decision text.", "new_string": "Rewritten."}))
        self.assertEqual(decision, "deny")

    def test_reviewer_has_no_bash(self):
        decision, _ = self._decision(self._hook(
            "adr-reviewer", "", tool="Bash", tool_input={"command": "ls"}))
        self.assertEqual(decision, "deny")

    def test_env_overrides_round_limit(self):
        self._adr()
        self._review(1)
        self._review(2)
        decision, reason = self._decision(self._hook(
            "solution-architect", self.ADR, tool="Edit",
            tool_input={"old_string": "Decision text.", "new_string": "Third."},
            env_extra={"DEVFLOW_ADR_MAX_REVIEW_ROUNDS": "3"}))
        self.assertEqual(decision, "allow", reason)


class ImplementerBashRedirectTest(_HookFixture):
    """Stream merges must not be mistaken for file writes."""

    def _bash(self, command):
        return self._decision(self._hook("backend-engineer", "", tool="Bash",
                                         tool_input={"command": command}))

    def test_stderr_merge_allowed(self):
        decision, reason = self._bash("dotnet test 2>&1 | tail -50")
        self.assertEqual(decision, "allow", reason)

    def test_dev_null_discard_allowed(self):
        decision, reason = self._bash("npm test 2>/dev/null")
        self.assertEqual(decision, "allow", reason)

    def test_file_redirect_still_denied(self):
        decision, _ = self._bash("echo secret > out.txt")
        self.assertEqual(decision, "deny")

    def test_append_redirect_still_denied(self):
        decision, _ = self._bash("dotnet test 2>&1 >> log.txt")
        self.assertEqual(decision, "deny")

    def test_stdin_redirect_still_denied(self):
        decision, _ = self._bash("python3 script.py < input.txt")
        self.assertEqual(decision, "deny")


if __name__ == "__main__":
    unittest.main()
