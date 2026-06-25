import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR_PATH = REPO_ROOT / "scripts" / "validate_ownership_diff.py"


class OwnershipDiffTestCase(unittest.TestCase):
    """Exercises scripts/validate_ownership_diff.py against isolated fixture
    git repositories created under a temporary directory. No real repository
    or worktree files are touched."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self._run_git("init", "-q", "-b", "main")
        self._run_git("config", "user.email", "test@example.com")
        self._run_git("config", "user.name", "Test")

    def tearDown(self):
        self.tmpdir.cleanup()

    # -- git fixture helpers ---------------------------------------------

    def _run_git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    def _rev_parse(self, ref="HEAD"):
        return self._run_git("rev-parse", ref).stdout.strip()

    def _write(self, rel_path, content):
        path = self.root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def _commit(self, message):
        self._run_git("add", "-A")
        self._run_git("commit", "-q", "-m", message)
        return self._rev_parse()

    def _approved_manifest(self, req_id="REQ-042"):
        return {
            "$schema": "./schema.json",
            "schema_version": 1,
            "req_id": req_id,
            "title": "Login flow",
            "status": "approved",
            "approval": {
                "approved_by": "human-maintainer",
                "approved_at": "2026-06-25",
            },
            "references": {
                "requirement": f"docs/product/requirements/{req_id}.md",
                "acceptance_criteria": f"docs/product/acceptance-criteria/{req_id}.md",
                "contracts": [f"docs/contracts/openapi/{req_id}.yaml"],
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
                    "write_paths": ["apps/web/src/features/example"],
                    "notes": "Frontend scope",
                },
                {
                    "agent": "backend-engineer",
                    "write_paths": ["apps/api/src/services/example"],
                    "notes": "Backend scope",
                },
            ],
        }

    def _write_base_fixture(self, manifest=None, req_id="REQ-042"):
        manifest = manifest if manifest is not None else self._approved_manifest(req_id)
        self._write(f"docs/product/requirements/{req_id}.md", "requirement\n")
        self._write(f"docs/product/acceptance-criteria/{req_id}.md", "acceptance criteria\n")
        self._write(f"docs/contracts/openapi/{req_id}.yaml", "contract\n")
        self._write(f"docs/ownership/{req_id}.json", json.dumps(manifest))
        return self._commit(f"base commit for {req_id}")

    def _checkout_branch(self, branch):
        self._run_git("checkout", "-q", "-b", branch)

    # -- validator invocation --------------------------------------------

    def _run_validator(self, base_sha, head_sha, branch):
        return subprocess.run(
            [
                sys.executable,
                str(VALIDATOR_PATH),
                "--root",
                str(self.root),
                "--base-sha",
                base_sha,
                "--head-sha",
                head_sha,
                "--branch",
                branch,
            ],
            capture_output=True,
            text=True,
        )

    def _assert_allowed(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)

    def _assert_rejected(self, result):
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("error:", result.stderr)

    # -- tests -------------------------------------------------------------

    def test_req_branch_frontend_owned_path_change_succeeds(self):
        base_sha = self._write_base_fixture()
        self._checkout_branch("req-042-login-flow")
        self._write(
            "apps/web/src/features/example/LoginForm.tsx", "export const LoginForm = () => null;\n"
        )
        head_sha = self._commit("add login form")

        result = self._run_validator(base_sha, head_sha, "req-042-login-flow")

        self._assert_allowed(result)

    def test_req_branch_unowned_application_path_rejected(self):
        base_sha = self._write_base_fixture()
        self._checkout_branch("req-042-login-flow")
        self._write("apps/random/unowned/file.py", "print('hi')\n")
        head_sha = self._commit("add unowned file")

        result = self._run_validator(base_sha, head_sha, "req-042-login-flow")

        self._assert_rejected(result)

    def test_req_branch_manifest_modification_rejected(self):
        base_sha = self._write_base_fixture()
        self._checkout_branch("req-042-login-flow")
        manifest = self._approved_manifest()
        manifest["owners"][0]["write_paths"].append("apps/web/src/features/extra")
        self._write("docs/ownership/REQ-042.json", json.dumps(manifest))
        head_sha = self._commit("self-modify ownership manifest")

        result = self._run_validator(base_sha, head_sha, "req-042-login-flow")

        self._assert_rejected(result)

    def test_req_branch_draft_base_manifest_rejected(self):
        manifest = self._approved_manifest()
        manifest["status"] = "draft"
        manifest["approval"] = {"approved_by": "", "approved_at": ""}
        base_sha = self._write_base_fixture(manifest=manifest)
        self._checkout_branch("req-042-login-flow")
        self._write(
            "apps/web/src/features/example/LoginForm.tsx", "export const LoginForm = () => null;\n"
        )
        head_sha = self._commit("add login form")

        result = self._run_validator(base_sha, head_sha, "req-042-login-flow")

        self._assert_rejected(result)

    def test_req_branch_missing_base_manifest_rejected(self):
        self._write("docs/product/requirements/REQ-042.md", "requirement\n")
        base_sha = self._commit("base commit without manifest")
        self._checkout_branch("req-042-login-flow")
        self._write(
            "apps/web/src/features/example/LoginForm.tsx", "export const LoginForm = () => null;\n"
        )
        head_sha = self._commit("add login form")

        result = self._run_validator(base_sha, head_sha, "req-042-login-flow")

        self._assert_rejected(result)

    def test_non_zero_padded_branch_rejected(self):
        base_sha = self._write_base_fixture()
        self._checkout_branch("req-42-login-flow")
        self._write(
            "apps/web/src/features/example/LoginForm.tsx", "export const LoginForm = () => null;\n"
        )
        head_sha = self._commit("add login form")

        result = self._run_validator(base_sha, head_sha, "req-42-login-flow")

        self._assert_rejected(result)

    def test_rename_across_owner_boundary_rejected(self):
        self._write(
            "apps/web/src/features/example/Shared.tsx", "export const Shared = () => null;\n"
        )
        base_sha = self._write_base_fixture()
        self._checkout_branch("req-042-login-flow")
        (self.root / "apps" / "api" / "src" / "services" / "example").mkdir(
            parents=True, exist_ok=True
        )
        self._run_git(
            "mv",
            "apps/web/src/features/example/Shared.tsx",
            "apps/api/src/services/example/Shared.tsx",
        )
        head_sha = self._commit("move shared file into backend owner path")

        result = self._run_validator(base_sha, head_sha, "req-042-login-flow")

        self._assert_rejected(result)

    def test_governance_branch_workflow_and_docs_change_succeeds(self):
        base_sha = self._write_base_fixture()
        self._checkout_branch("ownership-ci-diff-enforcement")
        self._write(".github/workflows/example.yml", "name: example\n")
        self._write("docs/architecture/notes.md", "notes\n")
        head_sha = self._commit("add governance files")

        result = self._run_validator(base_sha, head_sha, "ownership-ci-diff-enforcement")

        self._assert_allowed(result)

    def test_governance_branch_application_path_rejected(self):
        base_sha = self._write_base_fixture()
        self._checkout_branch("ownership-ci-diff-enforcement")
        self._write("apps/web/src/App.tsx", "export const App = () => null;\n")
        head_sha = self._commit("add application file on governance branch")

        result = self._run_validator(base_sha, head_sha, "ownership-ci-diff-enforcement")

        self._assert_rejected(result)

    def test_two_owner_domains_changed_succeeds_when_manifest_valid(self):
        base_sha = self._write_base_fixture()
        self._checkout_branch("req-042-login-flow")
        self._write(
            "apps/web/src/features/example/LoginForm.tsx", "export const LoginForm = () => null;\n"
        )
        self._write(
            "apps/api/src/services/example/handler.py", "def handler():\n    return None\n"
        )
        head_sha = self._commit("add frontend and backend files")

        result = self._run_validator(base_sha, head_sha, "req-042-login-flow")

        self._assert_allowed(result)

    # -- authority-escalation regression coverage -------------------------

    def test_generic_governance_branch_ownership_manifest_change_rejected(self):
        base_sha = self._write_base_fixture()
        self._checkout_branch("some-governance-branch")
        manifest = self._approved_manifest()
        manifest["owners"][0]["write_paths"].append("apps/web/src/features/extra")
        self._write("docs/ownership/REQ-042.json", json.dumps(manifest))
        head_sha = self._commit("attempt to forge ownership manifest on governance branch")

        result = self._run_validator(base_sha, head_sha, "some-governance-branch")

        self._assert_rejected(result)

    def test_generic_governance_branch_ownership_readme_change_succeeds(self):
        base_sha = self._write_base_fixture()
        self._checkout_branch("some-governance-branch")
        self._write("docs/ownership/README.md", "updated readme\n")
        head_sha = self._commit("update ownership readme on governance branch")

        result = self._run_validator(base_sha, head_sha, "some-governance-branch")

        self._assert_allowed(result)

    def test_generic_governance_branch_ownership_template_and_schema_change_succeeds(self):
        base_sha = self._write_base_fixture()
        self._checkout_branch("some-governance-branch")
        self._write("docs/ownership/TEMPLATE.json", "{}\n")
        self._write("docs/ownership/schema.json", "{}\n")
        head_sha = self._commit("update ownership template and schema on governance branch")

        result = self._run_validator(base_sha, head_sha, "some-governance-branch")

        self._assert_allowed(result)

    def test_ownership_registry_branch_readme_change_rejected(self):
        base_sha = self._write_base_fixture()
        self._checkout_branch("ownership-REQ-042-login-flow")
        self._write("docs/ownership/README.md", "updated readme\n")
        head_sha = self._commit("attempt to change readme on registry branch")

        result = self._run_validator(base_sha, head_sha, "ownership-REQ-042-login-flow")

        self._assert_rejected(result)

    def test_ownership_registry_branch_schema_change_rejected(self):
        base_sha = self._write_base_fixture()
        self._checkout_branch("ownership-REQ-042-login-flow")
        self._write("docs/ownership/schema.json", "{}\n")
        head_sha = self._commit("attempt to change schema on registry branch")

        result = self._run_validator(base_sha, head_sha, "ownership-REQ-042-login-flow")

        self._assert_rejected(result)

    def test_ownership_registry_branch_valid_manifest_change_succeeds(self):
        base_sha = self._write_base_fixture()
        self._checkout_branch("ownership-REQ-042-login-flow")
        manifest = self._approved_manifest()
        manifest["title"] = "Login flow (updated)"
        self._write("docs/ownership/REQ-042.json", json.dumps(manifest))
        head_sha = self._commit("update ownership manifest")

        result = self._run_validator(base_sha, head_sha, "ownership-REQ-042-login-flow")

        self._assert_allowed(result)

    def test_ownership_registry_branch_extra_file_change_rejected(self):
        base_sha = self._write_base_fixture()
        self._checkout_branch("ownership-REQ-042-login-flow")
        manifest = self._approved_manifest()
        manifest["title"] = "Login flow (updated)"
        self._write("docs/ownership/REQ-042.json", json.dumps(manifest))
        self._write("apps/web/src/App.tsx", "export const App = () => null;\n")
        head_sha = self._commit("update manifest and sneak in an extra file")

        result = self._run_validator(base_sha, head_sha, "ownership-REQ-042-login-flow")

        self._assert_rejected(result)

    def test_ownership_registry_branch_req_id_filename_mismatch_rejected(self):
        base_sha = self._write_base_fixture()
        self._checkout_branch("ownership-REQ-042-login-flow")
        manifest = self._approved_manifest(req_id="REQ-099")
        self._write(
            "docs/product/requirements/REQ-099.md", "requirement\n"
        )
        self._write(
            "docs/product/acceptance-criteria/REQ-099.md", "acceptance criteria\n"
        )
        self._write("docs/contracts/openapi/REQ-099.yaml", "contract\n")
        self._write("docs/ownership/REQ-099.json", json.dumps(manifest))
        head_sha = self._commit("create manifest under a different REQ-ID than the branch")

        result = self._run_validator(base_sha, head_sha, "ownership-REQ-042-login-flow")

        self._assert_rejected(result)

    def test_ownership_registry_branch_manifest_deletion_rejected(self):
        base_sha = self._write_base_fixture()
        self._checkout_branch("ownership-REQ-042-login-flow")
        self._run_git("rm", "-q", "docs/ownership/REQ-042.json")
        head_sha = self._commit("delete ownership manifest")

        result = self._run_validator(base_sha, head_sha, "ownership-REQ-042-login-flow")

        self._assert_rejected(result)

    def test_req_branch_symlink_under_owner_path_rejected(self):
        base_sha = self._write_base_fixture()
        self._checkout_branch("req-042-login-flow")
        target = self.root / "apps" / "web" / "src" / "features" / "example" / "Real.tsx"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("export const Real = () => null;\n")
        link = self.root / "apps" / "web" / "src" / "features" / "example" / "Link.tsx"
        link.symlink_to(target)
        head_sha = self._commit("add symlink under owner path")

        result = self._run_validator(base_sha, head_sha, "req-042-login-flow")

        self._assert_rejected(result)

    def test_req_branch_gitlink_under_owner_path_rejected(self):
        base_sha = self._write_base_fixture()
        self._checkout_branch("req-042-login-flow")
        nested_repo = self.root / "apps" / "web" / "src" / "features" / "example" / "submodule"
        nested_repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(nested_repo)], check=True)
        subprocess.run(
            ["git", "-C", str(nested_repo), "config", "user.email", "test@example.com"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(nested_repo), "config", "user.name", "Test"], check=True
        )
        (nested_repo / "f.txt").write_text("nested\n")
        subprocess.run(["git", "-C", str(nested_repo), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(nested_repo), "commit", "-q", "-m", "nested base"], check=True
        )
        nested_sha = subprocess.run(
            ["git", "-C", str(nested_repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self._run_git(
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{nested_sha},apps/web/src/features/example/submodule",
        )
        self._run_git("commit", "-q", "-m", "add gitlink under owner path")
        head_sha = self._rev_parse()

        result = self._run_validator(base_sha, head_sha, "req-042-login-flow")

        self._assert_rejected(result)


if __name__ == "__main__":
    unittest.main()
