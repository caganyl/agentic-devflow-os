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

    def test_non_utf8_accepted_adr_still_frozen(self):
        # A cp1252 byte must not crash the hook into a non-blocking exit.
        (self.root / self.ADR).write_bytes(
            b"# ADR-010 \x97 Cache\n\n## Status\nAccepted\n\n## Decision\nDecision text.\n")
        decision, reason = self._decision(self._hook(
            "solution-architect", self.ADR, tool="Edit",
            tool_input={"old_string": "Decision text.", "new_string": "Changed."}))
        self.assertEqual(decision, "deny")
        self.assertIn("frozen", reason)

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


class ExternalWriteGuardTest(_HookFixture):
    """Governed agents may read PR reviews but not write to external systems."""

    def _bash(self, agent, command):
        return self._decision(self._hook(agent, "", tool="Bash", tool_input={"command": command}))

    def test_read_review_comments_allowed(self):
        for cmd in ("npx --no-install agent-reviews --bots-only --unanswered --expanded",
                    "gh pr view 12 --comments",
                    "gh api repos/acme/app/pulls/12/comments"):
            decision, reason = self._bash("integration-release", cmd)
            self.assertEqual(decision, "allow", f"{cmd}: {reason}")

    def test_reply_and_resolve_denied(self):
        for cmd in ('npx agent-reviews --reply 123 "Fixed in abc" --resolve',
                    "npx agent-reviews --watch --bots-only",
                    'gh pr comment 12 --body "done"',
                    "gh pr review 12 --approve",
                    'gh issue create --title x --body y',
                    "gh api -X POST repos/acme/app/issues/12/comments -f body=hi",
                    "gh api repos/acme/app/pulls/comments/5/replies -f body=hi"):
            decision, _ = self._bash("integration-release", cmd)
            self.assertEqual(decision, "deny", cmd)

    def test_implementer_cannot_post_either(self):
        decision, _ = self._bash("backend-engineer", 'gh pr comment 12 --body "x"')
        self.assertEqual(decision, "deny")

    def test_strix_denied_for_governed_agents(self):
        for agent in ("integration-release", "qa-automation", "backend-engineer"):
            decision, _ = self._bash(agent, "strix --target https://staging.example.com")
            self.assertEqual(decision, "deny", agent)


class ArchitectureProfileGateTest(_HookFixture):
    JSON = "docs/architecture/profile/architecture-profile.json"
    MD = "docs/architecture/profile/ARCHITECTURE_PROFILE.md"

    def setUp(self):
        super().setUp()
        (self.root / "docs/architecture/profile").mkdir(parents=True, exist_ok=True)

    def test_analyst_writes_draft(self):
        decision, reason = self._decision(self._hook(
            "architecture-analyst", self.JSON, tool_input={"content": '{"status": "draft", "rules": {}}'}))
        self.assertEqual(decision, "allow", reason)

    def test_analyst_cannot_confirm(self):
        decision, _ = self._decision(self._hook(
            "architecture-analyst", self.JSON, tool_input={"content": '{"status": "confirmed"}'}))
        self.assertEqual(decision, "deny")

    def test_confirmed_profile_frozen_for_agents(self):
        (self.root / self.MD).write_text("# Profil\n\nStatus: confirmed\n\nKatmanlar...\n")
        for agent in ("architecture-analyst", "solution-architect"):
            decision, _ = self._decision(self._hook(
                agent, self.MD, tool="Edit",
                tool_input={"old_string": "Katmanlar...", "new_string": "Yeni katmanlar"}))
            self.assertEqual(decision, "deny", agent)

    def test_analyst_cannot_write_elsewhere(self):
        decision, _ = self._decision(self._hook(
            "architecture-analyst", "src/Program.cs", tool_input={"content": "x"}))
        self.assertEqual(decision, "deny")

    def test_analyst_bash_scanner_allowed(self):
        for cmd in ('python3 "$DEVFLOW_ARCH_SCAN_SCRIPT" --root . --compact',
                    "python3 scripts/devflow_arch_scan.py --root . --check docs/architecture/profile/architecture-profile.json",
                    "git log --oneline -20"):
            decision, reason = self._decision(self._hook(
                "architecture-analyst", "", tool="Bash", tool_input={"command": cmd}))
            self.assertEqual(decision, "allow", f"{cmd}: {reason}")

    def test_analyst_bash_other_denied(self):
        for cmd in ("python3 other.py", "python3 scripts/devflow_arch_scan.py --root . > out.json",
                    "dotnet build", "npm install"):
            decision, _ = self._decision(self._hook(
                "architecture-analyst", "", tool="Bash", tool_input={"command": cmd}))
            self.assertEqual(decision, "deny", cmd)


class ArchitectureAnalystHardeningTest(_HookFixture):
    """The scanner allowlist must not become a general code-execution path."""

    def _bash(self, cmd):
        return self._decision(self._hook("architecture-analyst", "", tool="Bash",
                                         tool_input={"command": cmd}))

    def test_braced_env_var_allowed(self):
        decision, reason = self._bash('python3 "${DEVFLOW_ARCH_SCAN_SCRIPT}" --root .')
        self.assertEqual(decision, "allow", reason)

    def test_inline_code_and_lookalike_scripts_denied(self):
        for cmd in ('python3 -c "import os" devflow_arch_scan.py',
                    "python3 -c \"__import__('os').remove('README.md')\" scripts/devflow_arch_scan.py",
                    "python3 docs/architecture/profile/devflow_arch_scan.py --root .",
                    "python3 src/scripts/x/devflow_arch_scan.py --root .",
                    "python3 -m devflow_arch_scan --root ."):
            decision, _ = self._bash(cmd)
            self.assertEqual(decision, "deny", cmd)

    def test_analyst_writes_only_the_two_profile_files(self):
        for path in ("docs/architecture/profile/devflow_arch_scan.py",
                     "docs/architecture/profile/scripts/devflow_arch_scan.py",
                     "docs/architecture/profile/notes.md"):
            decision, _ = self._decision(self._hook(
                "architecture-analyst", path, tool_input={"content": "x"}))
            self.assertEqual(decision, "deny", path)

    def test_non_utf8_confirmed_profile_still_frozen(self):
        md = self.root / "docs/architecture/profile/ARCHITECTURE_PROFILE.md"
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_bytes(b"# Profil \x97\n\nStatus: confirmed\n\nKatmanlar...\n")
        decision, _ = self._decision(self._hook(
            "architecture-analyst", "docs/architecture/profile/ARCHITECTURE_PROFILE.md", tool="Edit",
            tool_input={"old_string": "Katmanlar...", "new_string": "Yeni"}))
        self.assertEqual(decision, "deny")


class DocsWriterGateTest(_HookFixture):
    SRC = "src/Orders/OrderService.cs"

    def setUp(self):
        super().setUp()
        p = self.root / self.SRC
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("public class OrderService {\n    public int Total(int a) => a * 2;\n}\n")

    def _edit(self, path, old, new):
        return self._decision(self._hook("docs-writer", path, tool="Edit",
                                         tool_input={"old_string": old, "new_string": new}))

    def test_folder_readme_allowed(self):
        decision, reason = self._decision(self._hook(
            "docs-writer", "src/Orders/README.md", tool_input={"content": "# Orders\n"}))
        self.assertEqual(decision, "allow", reason)

    def test_root_readme_edit_allowed(self):
        decision, reason = self._edit("README.md", "x", "y")
        self.assertEqual(decision, "allow", reason)

    def test_xml_doc_comment_allowed(self):
        decision, reason = self._edit(
            self.SRC, "    public int Total(int a) => a * 2;",
            "    /// <summary>Sipariş toplamını iki katına çıkarır.</summary>\n    public int Total(int a) => a * 2;")
        self.assertEqual(decision, "allow", reason)

    def test_tsx_and_jsx_comments_allowed(self):
        decision, reason = self._edit(
            "web/src/Cart.tsx", "return <div>{items}</div>",
            "// Neden: boş sepet ayrı bileşende ele alınıyor\nreturn <div>{/* liste */}{items}</div>")
        self.assertEqual(decision, "allow", reason)

    def test_code_change_denied(self):
        decision, reason = self._edit(
            self.SRC, "a * 2;", "a * 3; // iki yerine üç")
        self.assertEqual(decision, "deny")
        self.assertIn("comments only", reason)

    def test_commenting_out_code_denied(self):
        decision, _ = self._edit(
            self.SRC, "    public int Total(int a) => a * 2;", "    // public int Total(int a) => a * 2;")
        self.assertEqual(decision, "deny")

    def test_comment_marker_inside_string_is_not_a_comment(self):
        decision, _ = self._edit(
            "web/src/api.ts", 'const base = "https://api";', 'const base = "https://api2";')
        self.assertEqual(decision, "deny")

    def test_source_write_denied(self):
        decision, _ = self._decision(self._hook(
            "docs-writer", self.SRC, tool_input={"content": "// all new\n"}))
        self.assertEqual(decision, "deny")

    def test_other_file_types_denied(self):
        for path in ("src/appsettings.json", "docs/guide.md", "src/Orders/Orders.csproj"):
            decision, _ = self._decision(self._hook(
                "docs-writer", path, tool_input={"content": "x"}))
            self.assertEqual(decision, "deny", path)

    def test_protected_areas_denied(self):
        for path in ("node_modules/x/README.md", "docs/ownership/README.md", "docs/architecture/adr/README.md"):
            decision, _ = self._decision(self._hook(
                "docs-writer", path, tool_input={"content": "x"}))
            self.assertEqual(decision, "deny", path)

    def test_docs_writer_bash_read_only(self):
        decision, reason = self._decision(self._hook(
            "docs-writer", "", tool="Bash", tool_input={"command": "git diff --name-only main"}))
        self.assertEqual(decision, "allow", reason)
        decision, _ = self._decision(self._hook(
            "docs-writer", "", tool="Bash", tool_input={"command": "dotnet format"}))
        self.assertEqual(decision, "deny")


if __name__ == "__main__":
    unittest.main()
