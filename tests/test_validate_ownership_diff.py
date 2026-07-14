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


    # -- bootstrap PR tests -----------------------------------------------

    def _bootstrap_manifest(self, req_id="REQ-099", write_paths=None):
        if write_paths is None:
            write_paths = [f"src/features/req-{req_id[4:]}-feat"]
        return {
            "$schema": "./schema.json",
            "schema_version": 1,
            "req_id": req_id,
            "title": "New feature",
            "status": "approved",
            "approval": {
                "approved_by": "human-maintainer",
                "approved_at": "2026-06-26",
            },
            "references": {
                "requirement": f"docs/product/requirements/{req_id}.md",
                "acceptance_criteria": f"docs/product/acceptance-criteria/{req_id}.md",
                "contracts": [],
                "contract_exception": {
                    "reason": "no external contract needed",
                    "approved_by": "human-maintainer",
                    "approved_at": "2026-06-26",
                },
                "adrs": [],
            },
            "owners": [
                {
                    "agent": "backend-engineer",
                    "write_paths": write_paths,
                    "notes": "Feature scope",
                },
            ],
        }

    def _write_empty_base(self):
        self._write("README.md", "project readme\n")
        return self._commit("initial commit without manifest")

    def test_bootstrap_pr_succeeds_with_full_bundle(self):
        """Scenario 1: successful bootstrap with req + AC + manifest + source + test + handoff."""
        base_sha = self._write_empty_base()
        self._checkout_branch("req-099-new-feat")
        req_id = "REQ-099"
        manifest = self._bootstrap_manifest(
            req_id,
            write_paths=[
                "src/features/req-099-feat",
                "tests/features/req-099-feat",
                "docs/handoffs/REQ-099.md",
            ],
        )
        self._write(f"docs/ownership/{req_id}.json", json.dumps(manifest))
        self._write(f"docs/product/requirements/{req_id}.md", "# REQ-099\n")
        self._write(f"docs/product/acceptance-criteria/{req_id}.md", "# AC\n")
        self._write("src/features/req-099-feat/service.py", "# service\n")
        self._write("tests/features/req-099-feat/test_service.py", "# test\n")
        self._write("docs/handoffs/REQ-099.md", "# handoff\n")
        head_sha = self._commit("bootstrap feature PR")

        result = self._run_validator(base_sha, head_sha, "req-099-new-feat")

        self._assert_allowed(result)

    def test_bootstrap_manifest_forbidden_write_path_claude_rejected(self):
        """Scenario 2a: bootstrap manifest requesting write under .claude/ is rejected."""
        base_sha = self._write_empty_base()
        self._checkout_branch("req-099-new-feat")
        req_id = "REQ-099"
        manifest = self._bootstrap_manifest(req_id, write_paths=[".claude/settings.json"])
        self._write(f"docs/ownership/{req_id}.json", json.dumps(manifest))
        self._write(f"docs/product/requirements/{req_id}.md", "# REQ-099\n")
        self._write(f"docs/product/acceptance-criteria/{req_id}.md", "# AC\n")
        head_sha = self._commit("bootstrap with forbidden .claude write path")

        result = self._run_validator(base_sha, head_sha, "req-099-new-feat")

        self._assert_rejected(result)

    def test_bootstrap_manifest_forbidden_write_path_scripts_rejected(self):
        """Scenario 2b: bootstrap manifest requesting write under scripts/ is rejected."""
        base_sha = self._write_empty_base()
        self._checkout_branch("req-099-new-feat")
        req_id = "REQ-099"
        manifest = self._bootstrap_manifest(req_id, write_paths=["scripts/my_tool.py"])
        self._write(f"docs/ownership/{req_id}.json", json.dumps(manifest))
        self._write(f"docs/product/requirements/{req_id}.md", "# REQ-099\n")
        self._write(f"docs/product/acceptance-criteria/{req_id}.md", "# AC\n")
        head_sha = self._commit("bootstrap with forbidden scripts write path")

        result = self._run_validator(base_sha, head_sha, "req-099-new-feat")

        self._assert_rejected(result)

    def test_bootstrap_manifest_overly_broad_write_path_rejected(self):
        """Scenario 2c: bootstrap manifest with overly broad root-level write path is rejected."""
        base_sha = self._write_empty_base()
        self._checkout_branch("req-099-new-feat")
        req_id = "REQ-099"
        manifest = self._bootstrap_manifest(req_id, write_paths=["src"])
        self._write(f"docs/ownership/{req_id}.json", json.dumps(manifest))
        self._write(f"docs/product/requirements/{req_id}.md", "# REQ-099\n")
        self._write(f"docs/product/acceptance-criteria/{req_id}.md", "# AC\n")
        head_sha = self._commit("bootstrap with overly broad src write path")

        result = self._run_validator(base_sha, head_sha, "req-099-new-feat")

        self._assert_rejected(result)

    def test_bootstrap_extra_ownership_file_in_diff_rejected(self):
        """Scenario 3: bootstrap diff containing another docs/ownership/ file is rejected."""
        base_sha = self._write_empty_base()
        self._checkout_branch("req-099-new-feat")
        req_id = "REQ-099"
        manifest = self._bootstrap_manifest(req_id)
        self._write(f"docs/ownership/{req_id}.json", json.dumps(manifest))
        self._write(f"docs/product/requirements/{req_id}.md", "# REQ-099\n")
        self._write(f"docs/product/acceptance-criteria/{req_id}.md", "# AC\n")
        self._write("src/features/req-099-feat/service.py", "# service\n")
        # Sneak in a second ownership manifest
        other_manifest = self._bootstrap_manifest("REQ-001")
        self._write("docs/ownership/REQ-001.json", json.dumps(other_manifest))
        head_sha = self._commit("bootstrap with extra ownership file")

        result = self._run_validator(base_sha, head_sha, "req-099-new-feat")

        self._assert_rejected(result)

    def test_bootstrap_ref_file_not_in_diff_rejected(self):
        """Scenario 4: requirement referenced in bootstrap manifest but not in diff is rejected."""
        # Requirement exists only in base (not added by this PR)
        self._write("docs/product/requirements/REQ-099.md", "# REQ-099\n")
        base_sha = self._commit("initial with pre-existing requirement")
        self._checkout_branch("req-099-new-feat")
        req_id = "REQ-099"
        manifest = self._bootstrap_manifest(req_id)
        self._write(f"docs/ownership/{req_id}.json", json.dumps(manifest))
        # AC is added in this PR but requirement is not (it was already in base)
        self._write(f"docs/product/acceptance-criteria/{req_id}.md", "# AC\n")
        self._write("src/features/req-099-feat/service.py", "# service\n")
        head_sha = self._commit("bootstrap without requirement in diff")

        result = self._run_validator(base_sha, head_sha, "req-099-new-feat")

        self._assert_rejected(result)

    def test_bootstrap_manifest_not_approved_rejected(self):
        """Scenario 5: bootstrap manifest with status != approved is rejected."""
        base_sha = self._write_empty_base()
        self._checkout_branch("req-099-new-feat")
        req_id = "REQ-099"
        manifest = self._bootstrap_manifest(req_id)
        manifest["status"] = "draft"
        manifest["approval"] = {"approved_by": "", "approved_at": ""}
        self._write(f"docs/ownership/{req_id}.json", json.dumps(manifest))
        self._write(f"docs/product/requirements/{req_id}.md", "# REQ-099\n")
        self._write(f"docs/product/acceptance-criteria/{req_id}.md", "# AC\n")
        self._write("src/features/req-099-feat/service.py", "# service\n")
        head_sha = self._commit("bootstrap with draft manifest")

        result = self._run_validator(base_sha, head_sha, "req-099-new-feat")

        self._assert_rejected(result)

    def test_req_branch_with_base_manifest_cannot_change_manifest(self):
        """Scenario 6: req branch with existing base manifest cannot modify that manifest."""
        base_sha = self._write_base_fixture()
        self._checkout_branch("req-042-login-flow")
        manifest = self._approved_manifest()
        manifest["owners"][0]["write_paths"].append("apps/web/src/features/extra")
        self._write("docs/ownership/REQ-042.json", json.dumps(manifest))
        head_sha = self._commit("attempt to widen write_paths on req branch")

        result = self._run_validator(base_sha, head_sha, "req-042-login-flow")

        self._assert_rejected(result)

    def test_bootstrap_contract_file_in_diff_without_coverage_rejected(self):
        """Contract file in bootstrap diff is rejected when not covered by owner write_paths."""
        base_sha = self._write_empty_base()
        self._checkout_branch("req-099-new-feat")
        req_id = "REQ-099"
        manifest = self._bootstrap_manifest(req_id)
        # Reference a contract that will be in the diff
        manifest["references"]["contracts"] = [f"docs/contracts/openapi/{req_id}.yaml"]
        manifest["references"]["contract_exception"] = {
            "reason": "", "approved_by": "", "approved_at": ""
        }
        self._write(f"docs/ownership/{req_id}.json", json.dumps(manifest))
        self._write(f"docs/product/requirements/{req_id}.md", "# REQ-099\n")
        self._write(f"docs/product/acceptance-criteria/{req_id}.md", "# AC\n")
        self._write("src/features/req-099-feat/service.py", "# service\n")
        self._write(f"docs/contracts/openapi/{req_id}.yaml", "openapi: '3.0'\n")
        head_sha = self._commit("bootstrap with contract in diff but no coverage")

        result = self._run_validator(base_sha, head_sha, "req-099-new-feat")

        self._assert_rejected(result)
        self.assertIn("docs/contracts/openapi/REQ-099.yaml", result.stderr)

    def test_bootstrap_adr_file_in_diff_without_coverage_rejected(self):
        """ADR file in bootstrap diff is rejected when not covered by owner write_paths."""
        base_sha = self._write_empty_base()
        self._checkout_branch("req-099-new-feat")
        req_id = "REQ-099"
        manifest = self._bootstrap_manifest(req_id)
        adr_path = "docs/architecture/adr/ADR-099-feature.md"
        manifest["references"]["adrs"] = [adr_path]
        self._write(f"docs/ownership/{req_id}.json", json.dumps(manifest))
        self._write(f"docs/product/requirements/{req_id}.md", "# REQ-099\n")
        self._write(f"docs/product/acceptance-criteria/{req_id}.md", "# AC\n")
        self._write("src/features/req-099-feat/service.py", "# service\n")
        self._write(adr_path, "# ADR-099\n")
        head_sha = self._commit("bootstrap with ADR in diff but no coverage")

        result = self._run_validator(base_sha, head_sha, "req-099-new-feat")

        self._assert_rejected(result)
        self.assertIn("ADR-099-feature.md", result.stderr)

    def test_bootstrap_nested_secrets_write_path_rejected(self):
        """Nested secret-like path (secrets/runtime) in write_paths is rejected."""
        base_sha = self._write_empty_base()
        self._checkout_branch("req-099-new-feat")
        req_id = "REQ-099"
        manifest = self._bootstrap_manifest(req_id, write_paths=["secrets/runtime"])
        self._write(f"docs/ownership/{req_id}.json", json.dumps(manifest))
        self._write(f"docs/product/requirements/{req_id}.md", "# REQ-099\n")
        self._write(f"docs/product/acceptance-criteria/{req_id}.md", "# AC\n")
        head_sha = self._commit("bootstrap with secrets/ write path")

        result = self._run_validator(base_sha, head_sha, "req-099-new-feat")

        self._assert_rejected(result)

    def test_bootstrap_nested_credentials_write_path_rejected(self):
        """Nested credential-like path (credentials/provider) in write_paths is rejected."""
        base_sha = self._write_empty_base()
        self._checkout_branch("req-099-new-feat")
        req_id = "REQ-099"
        manifest = self._bootstrap_manifest(req_id, write_paths=["credentials/provider"])
        self._write(f"docs/ownership/{req_id}.json", json.dumps(manifest))
        self._write(f"docs/product/requirements/{req_id}.md", "# REQ-099\n")
        self._write(f"docs/product/acceptance-criteria/{req_id}.md", "# AC\n")
        head_sha = self._commit("bootstrap with credentials/ write path")

        result = self._run_validator(base_sha, head_sha, "req-099-new-feat")

        self._assert_rejected(result)

    def test_bootstrap_swapped_requirement_ac_paths_rejected(self):
        """Requirement path given as AC dir (or vice versa) is rejected by per-field prefix check."""
        base_sha = self._write_empty_base()
        self._checkout_branch("req-099-new-feat")
        req_id = "REQ-099"
        manifest = self._bootstrap_manifest(req_id)
        # Swap: requirement points at AC dir, acceptance_criteria points at requirements dir
        manifest["references"]["requirement"] = f"docs/product/acceptance-criteria/{req_id}.md"
        manifest["references"]["acceptance_criteria"] = f"docs/product/requirements/{req_id}.md"
        self._write(f"docs/ownership/{req_id}.json", json.dumps(manifest))
        # Write files at the swapped locations so vom file-existence check passes
        self._write(f"docs/product/acceptance-criteria/{req_id}.md", "# AC used as req\n")
        self._write(f"docs/product/requirements/{req_id}.md", "# REQ used as AC\n")
        self._write("src/features/req-099-feat/service.py", "# service\n")
        head_sha = self._commit("bootstrap with swapped req/AC paths")

        result = self._run_validator(base_sha, head_sha, "req-099-new-feat")

        self._assert_rejected(result)
        self.assertIn("docs/product/requirements/", result.stderr)

    def test_bootstrap_normal_req_branch_behavior_unbroken(self):
        """Scenario 8: normal req branch (with base manifest) still validates correctly."""
        base_sha = self._write_base_fixture()
        self._checkout_branch("req-042-login-flow")
        self._write(
            "apps/web/src/features/example/LoginForm.tsx", "export const LoginForm = () => null;\n"
        )
        head_sha = self._commit("add login form")

        result = self._run_validator(base_sha, head_sha, "req-042-login-flow")

        self._assert_allowed(result)

    # -- contracts / evals narrow-path allowance tests ---------------------

    def test_bootstrap_narrow_contracts_write_path_succeeds(self):
        """Bootstrap manifest with narrow docs/contracts/... write_path succeeds."""
        base_sha = self._write_empty_base()
        self._checkout_branch("req-099-new-feat")
        req_id = "REQ-099"
        contract_path = f"docs/contracts/openapi/req-099-feat/{req_id}.yaml"
        manifest = self._bootstrap_manifest(req_id)
        manifest["owners"][0]["write_paths"] = [
            "src/features/req-099-feat",
            "docs/contracts/openapi/req-099-feat",
        ]
        manifest["references"]["contracts"] = [contract_path]
        manifest["references"]["contract_exception"] = {
            "reason": "", "approved_by": "", "approved_at": ""
        }
        self._write(f"docs/ownership/{req_id}.json", json.dumps(manifest))
        self._write(f"docs/product/requirements/{req_id}.md", "# REQ-099\n")
        self._write(f"docs/product/acceptance-criteria/{req_id}.md", "# AC\n")
        self._write("src/features/req-099-feat/service.py", "# service\n")
        self._write(contract_path, "openapi: '3.0'\n")
        head_sha = self._commit("bootstrap with narrow docs/contracts write path")

        result = self._run_validator(base_sha, head_sha, "req-099-new-feat")

        self._assert_allowed(result)

    def test_bootstrap_narrow_evals_write_path_succeeds(self):
        """Bootstrap manifest with narrow evals/... write_path succeeds."""
        base_sha = self._write_empty_base()
        self._checkout_branch("req-099-new-feat")
        req_id = "REQ-099"
        manifest = self._bootstrap_manifest(req_id)
        manifest["owners"][0]["write_paths"] = [
            "src/features/req-099-feat",
            "evals/datasets/golden/req-099-feat",
        ]
        self._write(f"docs/ownership/{req_id}.json", json.dumps(manifest))
        self._write(f"docs/product/requirements/{req_id}.md", "# REQ-099\n")
        self._write(f"docs/product/acceptance-criteria/{req_id}.md", "# AC\n")
        self._write("src/features/req-099-feat/service.py", "# service\n")
        self._write("evals/datasets/golden/req-099-feat/cases.json", "{}\n")
        head_sha = self._commit("bootstrap with narrow evals write path")

        result = self._run_validator(base_sha, head_sha, "req-099-new-feat")

        self._assert_allowed(result)

    def test_bootstrap_broad_contracts_root_write_path_rejected(self):
        """docs/contracts as a bare write_path in bootstrap manifest is rejected."""
        base_sha = self._write_empty_base()
        self._checkout_branch("req-099-new-feat")
        req_id = "REQ-099"
        manifest = self._bootstrap_manifest(req_id, write_paths=["docs/contracts"])
        self._write(f"docs/ownership/{req_id}.json", json.dumps(manifest))
        self._write(f"docs/product/requirements/{req_id}.md", "# REQ-099\n")
        self._write(f"docs/product/acceptance-criteria/{req_id}.md", "# AC\n")
        head_sha = self._commit("bootstrap with overly broad docs/contracts write path")

        result = self._run_validator(base_sha, head_sha, "req-099-new-feat")

        self._assert_rejected(result)

    def test_bootstrap_broad_evals_root_write_path_rejected(self):
        """evals as a bare write_path in bootstrap manifest is rejected."""
        base_sha = self._write_empty_base()
        self._checkout_branch("req-099-new-feat")
        req_id = "REQ-099"
        manifest = self._bootstrap_manifest(req_id, write_paths=["evals"])
        self._write(f"docs/ownership/{req_id}.json", json.dumps(manifest))
        self._write(f"docs/product/requirements/{req_id}.md", "# REQ-099\n")
        self._write(f"docs/product/acceptance-criteria/{req_id}.md", "# AC\n")
        head_sha = self._commit("bootstrap with overly broad evals write path")

        result = self._run_validator(base_sha, head_sha, "req-099-new-feat")

        self._assert_rejected(result)

    def test_bootstrap_adr_write_path_rejected(self):
        """docs/architecture/adr/... as a write_path in bootstrap manifest is rejected."""
        base_sha = self._write_empty_base()
        self._checkout_branch("req-099-new-feat")
        req_id = "REQ-099"
        manifest = self._bootstrap_manifest(
            req_id, write_paths=["docs/architecture/adr/ADR-099-feature.md"]
        )
        self._write(f"docs/ownership/{req_id}.json", json.dumps(manifest))
        self._write(f"docs/product/requirements/{req_id}.md", "# REQ-099\n")
        self._write(f"docs/product/acceptance-criteria/{req_id}.md", "# AC\n")
        head_sha = self._commit("bootstrap with docs/architecture/adr write path")

        result = self._run_validator(base_sha, head_sha, "req-099-new-feat")

        self._assert_rejected(result)

    # -- Codex control-plane narrow governance allowance tests -----------

    def test_governance_branch_codex_control_plane_paths_succeed(self):
        base_sha = self._write_base_fixture()
        self._checkout_branch("governance-allow-codex-control-plane")

        self._write(".agents/plugins/marketplace.json", "{}\n")
        self._write(
            ".agents/skills/example-skill/SKILL.md",
            "---\nname: example-skill\ndescription: Example skill.\n---\n",
        )
        self._write(
            ".codex/agents/example_agent.toml",
            'name = "example-agent"\n',
        )
        self._write(".codex/config.toml", 'model = "example"\n')
        self._write(".codex/hooks.json", '{"hooks": {}}\n')

        head_sha = self._commit("add Codex control-plane files")

        result = self._run_validator(
            base_sha,
            head_sha,
            "governance-allow-codex-control-plane",
        )

        self._assert_allowed(result)

    def test_governance_branch_unrelated_agents_path_rejected(self):
        base_sha = self._write_base_fixture()
        self._checkout_branch("governance-allow-codex-control-plane")
        self._write(".agents/runtime/state.json", "{}\n")
        head_sha = self._commit("add unrelated agents runtime file")

        result = self._run_validator(
            base_sha,
            head_sha,
            "governance-allow-codex-control-plane",
        )

        self._assert_rejected(result)
        self.assertIn(".agents/runtime/state.json", result.stderr)

    def test_governance_branch_unrelated_codex_path_rejected(self):
        base_sha = self._write_base_fixture()
        self._checkout_branch("governance-allow-codex-control-plane")
        self._write(".codex/runtime-state.json", "{}\n")
        head_sha = self._commit("add unrelated Codex runtime file")

        result = self._run_validator(
            base_sha,
            head_sha,
            "governance-allow-codex-control-plane",
        )

        self._assert_rejected(result)
        self.assertIn(".codex/runtime-state.json", result.stderr)

    # -- hooks/hooks.json narrow governance allowance tests ---------------

    def test_governance_branch_hooks_json_change_succeeds(self):
        """hooks/hooks.json is the only hooks/ path allowed on generic governance branches."""
        base_sha = self._write_base_fixture()
        self._checkout_branch("some-governance-branch")
        self._write("hooks/hooks.json", '{"hooks": []}\n')
        head_sha = self._commit("update plugin hooks config on governance branch")

        result = self._run_validator(base_sha, head_sha, "some-governance-branch")

        self._assert_allowed(result)

    def test_governance_branch_other_hooks_file_rejected(self):
        """Any hooks/ file other than hooks/hooks.json is rejected on governance branches."""
        base_sha = self._write_base_fixture()
        self._checkout_branch("some-governance-branch")
        self._write("hooks/other-hook.sh", "#!/bin/sh\necho hi\n")
        head_sha = self._commit("add other hooks file on governance branch")

        result = self._run_validator(base_sha, head_sha, "some-governance-branch")

        self._assert_rejected(result)
        self.assertIn("hooks/other-hook.sh", result.stderr)

    def test_governance_branch_hooks_subdir_file_rejected(self):
        """A file nested under hooks/ (not hooks/hooks.json itself) is rejected."""
        base_sha = self._write_base_fixture()
        self._checkout_branch("some-governance-branch")
        self._write("hooks/subdir/extra.json", "{}\n")
        head_sha = self._commit("add nested hooks subdir file on governance branch")

        result = self._run_validator(base_sha, head_sha, "some-governance-branch")

        self._assert_rejected(result)
        self.assertIn("hooks/subdir/extra.json", result.stderr)


if __name__ == "__main__":
    unittest.main()
