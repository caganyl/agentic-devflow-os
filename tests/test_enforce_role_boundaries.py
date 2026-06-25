import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_PATH = REPO_ROOT / ".claude" / "hooks" / "enforce-role-boundaries.sh"
VALIDATOR_PATH = REPO_ROOT / "scripts" / "validate_ownership_manifest.py"


class EnforceRoleBoundariesOwnershipTestCase(unittest.TestCase):
    """Exercises the implementer ownership-enforcement branch of
    .claude/hooks/enforce-role-boundaries.sh against isolated fixture
    repositories. No real repository or worktree files are touched."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self._init_fixture_repo()

    def tearDown(self):
        self.tmpdir.cleanup()

    # -- fixture helpers ----------------------------------------------

    def _run_git(self, *args):
        subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    def _init_fixture_repo(self):
        self._run_git("init", "-q")
        self._run_git("config", "user.email", "test@example.com")
        self._run_git("config", "user.name", "Test")
        self._run_git("checkout", "-q", "-b", "req-042-login-flow")

        scripts_dir = self.root / "scripts"
        scripts_dir.mkdir(parents=True)
        shutil.copyfile(VALIDATOR_PATH, scripts_dir / "validate_ownership_manifest.py")

        (self.root / "docs" / "product" / "requirements").mkdir(parents=True)
        (self.root / "docs" / "product" / "acceptance-criteria").mkdir(parents=True)
        (self.root / "docs" / "contracts" / "openapi").mkdir(parents=True)
        (self.root / "docs" / "ownership").mkdir(parents=True)

        self.requirement_path = "docs/product/requirements/REQ-042.md"
        self.acceptance_criteria_path = "docs/product/acceptance-criteria/REQ-042.md"
        self.contract_path = "docs/contracts/openapi/REQ-042.yaml"

        (self.root / self.requirement_path).write_text("requirement\n")
        (self.root / self.acceptance_criteria_path).write_text("acceptance criteria\n")
        (self.root / self.contract_path).write_text("contract\n")

    def _approved_manifest(self):
        return {
            "$schema": "./schema.json",
            "schema_version": 1,
            "req_id": "REQ-042",
            "title": "Login flow",
            "status": "approved",
            "approval": {
                "approved_by": "human-maintainer",
                "approved_at": "2026-06-25",
            },
            "references": {
                "requirement": self.requirement_path,
                "acceptance_criteria": self.acceptance_criteria_path,
                "contracts": [self.contract_path],
                "contract_exception": {
                    "reason": "",
                    "approved_by": "",
                    "approved_at": "",
                },
                "adrs": [],
            },
            "owners": [
                {
                    "agent": "frontend-engineer",
                    "write_paths": ["apps/web/src/features/auth"],
                    "notes": "Frontend auth scope",
                },
                {
                    "agent": "backend-engineer",
                    "write_paths": ["apps/api/src/routes/auth"],
                    "notes": "Backend auth scope",
                },
                {
                    "agent": "qa-automation",
                    "write_paths": ["tests/e2e/auth"],
                    "notes": "QA auth scope",
                },
                {
                    "agent": "ai-data-engineer",
                    "write_paths": ["apps/api/src/ai/auth"],
                    "notes": "AI/Data auth scope",
                },
            ],
        }

    def _write_manifest(self, manifest, filename="REQ-042.json"):
        manifest_path = self.root / "docs" / "ownership" / filename
        manifest_path.write_text(json.dumps(manifest))
        return manifest_path

    def _run_hook(self, agent_type, file_path, tool_name="Write"):
        payload = {
            "cwd": str(self.root),
            "agent_type": agent_type,
            "tool_name": tool_name,
            "tool_input": {"file_path": file_path},
        }
        return subprocess.run(
            ["bash", str(HOOK_PATH)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
        )

    def _assert_allowed(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def _assert_denied(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            payload["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    # -- tests ----------------------------------------------------------

    def test_approved_manifest_frontend_owner_allowed(self):
        self._write_manifest(self._approved_manifest())

        result = self._run_hook(
            "frontend-engineer",
            "apps/web/src/features/auth/LoginForm.tsx",
        )

        self._assert_allowed(result)

    def test_approved_manifest_backend_agent_on_frontend_path_denied(self):
        self._write_manifest(self._approved_manifest())

        result = self._run_hook(
            "backend-engineer",
            "apps/web/src/features/auth/LoginForm.tsx",
        )

        self._assert_denied(result)

    def test_approved_manifest_frontend_agent_outside_owned_path_denied(self):
        self._write_manifest(self._approved_manifest())

        result = self._run_hook(
            "frontend-engineer",
            "apps/api/src/routes/auth.py",
        )

        self._assert_denied(result)

    def test_draft_manifest_denied(self):
        manifest = self._approved_manifest()
        manifest["status"] = "draft"
        manifest["approval"] = {"approved_by": "", "approved_at": ""}
        self._write_manifest(manifest)

        result = self._run_hook(
            "frontend-engineer",
            "apps/web/src/features/auth/LoginForm.tsx",
        )

        self._assert_denied(result)

    def test_branch_without_manifest_denied(self):
        result = self._run_hook(
            "frontend-engineer",
            "apps/web/src/features/auth/LoginForm.tsx",
        )

        self._assert_denied(result)

    def test_non_zero_padded_branch_denied(self):
        self._write_manifest(self._approved_manifest())
        self._run_git("checkout", "-q", "-b", "req-42-login-flow")

        result = self._run_hook(
            "frontend-engineer",
            "apps/web/src/features/auth/LoginForm.tsx",
        )

        self._assert_denied(result)

    def test_qa_automation_owned_path_allowed(self):
        self._write_manifest(self._approved_manifest())

        result = self._run_hook(
            "qa-automation",
            "tests/e2e/auth/login.spec.ts",
        )

        self._assert_allowed(result)

    def test_ai_data_engineer_owned_path_allowed(self):
        self._write_manifest(self._approved_manifest())

        result = self._run_hook(
            "ai-data-engineer",
            "apps/api/src/ai/auth/risk_model.py",
        )

        self._assert_allowed(result)


if __name__ == "__main__":
    unittest.main()
