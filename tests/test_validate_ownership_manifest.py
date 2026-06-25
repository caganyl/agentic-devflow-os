import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import validate_ownership_manifest as vom  # noqa: E402


class OwnershipManifestTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

        (self.root / "docs" / "product" / "requirements").mkdir(parents=True)
        (self.root / "docs" / "product" / "acceptance-criteria").mkdir(parents=True)
        (self.root / "docs" / "contracts" / "openapi").mkdir(parents=True)
        (self.root / "apps" / "web" / "src" / "features" / "example").mkdir(parents=True)
        (self.root / "apps" / "api" / "src" / "services" / "example").mkdir(parents=True)

        self.requirement_path = "docs/product/requirements/REQ-100.md"
        self.acceptance_criteria_path = "docs/product/acceptance-criteria/REQ-100.md"
        self.contract_path = "docs/contracts/openapi/REQ-100.yaml"

        (self.root / self.requirement_path).write_text("requirement\n")
        (self.root / self.acceptance_criteria_path).write_text("acceptance criteria\n")
        (self.root / self.contract_path).write_text("contract\n")

    def tearDown(self):
        self.tmpdir.cleanup()

    def base_manifest(self):
        return {
            "$schema": "./schema.json",
            "schema_version": 1,
            "req_id": "REQ-100",
            "title": "Example feature",
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

    def write_manifest(self, manifest, filename="REQ-100.json"):
        manifest_dir = self.root / "docs" / "ownership"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / filename
        manifest_path.write_text(json.dumps(manifest))
        return str(manifest_path)

    def test_valid_approved_manifest_succeeds(self):
        manifest_path = self.write_manifest(self.base_manifest())

        exit_code = vom.main(["--manifest", manifest_path, "--root", str(self.root)])

        self.assertEqual(exit_code, 0)

    def test_overlapping_write_paths_across_owners_rejected(self):
        manifest = self.base_manifest()
        manifest["owners"][1]["write_paths"] = ["apps/web/src/features/example/nested"]
        manifest_path = self.write_manifest(manifest)

        exit_code = vom.main(["--manifest", manifest_path, "--root", str(self.root)])

        self.assertEqual(exit_code, 1)

    def test_missing_requirement_reference_rejected(self):
        manifest = self.base_manifest()
        manifest["references"]["requirement"] = "docs/product/requirements/REQ-999-missing.md"
        manifest_path = self.write_manifest(manifest)

        exit_code = vom.main(["--manifest", manifest_path, "--root", str(self.root)])

        self.assertEqual(exit_code, 1)

    def test_missing_acceptance_criteria_reference_rejected(self):
        manifest = self.base_manifest()
        manifest["references"]["acceptance_criteria"] = "docs/product/acceptance-criteria/REQ-999-missing.md"
        manifest_path = self.write_manifest(manifest)

        exit_code = vom.main(["--manifest", manifest_path, "--root", str(self.root)])

        self.assertEqual(exit_code, 1)

    def test_authorize_succeeds_for_correct_branch_agent_and_target(self):
        manifest_path = self.write_manifest(self.base_manifest())

        exit_code = vom.main(
            [
                "--manifest",
                manifest_path,
                "--root",
                str(self.root),
                "--branch",
                "req-100-example-feature",
                "--authorize-agent",
                "frontend-engineer",
                "--target",
                "apps/web/src/features/example/LoginForm.tsx",
            ]
        )

        self.assertEqual(exit_code, 0)

    def test_authorize_rejects_wrong_agent_or_disallowed_target(self):
        manifest_path = self.write_manifest(self.base_manifest())

        wrong_agent_exit = vom.main(
            [
                "--manifest",
                manifest_path,
                "--root",
                str(self.root),
                "--branch",
                "req-100-example-feature",
                "--authorize-agent",
                "database-engineer",
                "--target",
                "apps/web/src/features/example/LoginForm.tsx",
            ]
        )
        self.assertEqual(wrong_agent_exit, 1)

        disallowed_target_exit = vom.main(
            [
                "--manifest",
                manifest_path,
                "--root",
                str(self.root),
                "--branch",
                "req-100-example-feature",
                "--authorize-agent",
                "frontend-engineer",
                "--target",
                "apps/api/src/services/example/handler.py",
            ]
        )
        self.assertEqual(disallowed_target_exit, 1)

    def test_write_paths_claude_md_rejected(self):
        manifest = self.base_manifest()
        manifest["owners"][0]["write_paths"] = ["CLAUDE.md"]
        manifest_path = self.write_manifest(manifest)

        exit_code = vom.main(["--manifest", manifest_path, "--root", str(self.root)])

        self.assertEqual(exit_code, 1)

    def test_write_paths_dot_slash_claude_md_rejected(self):
        manifest = self.base_manifest()
        manifest["owners"][0]["write_paths"] = ["./CLAUDE.md"]
        manifest_path = self.write_manifest(manifest)

        exit_code = vom.main(["--manifest", manifest_path, "--root", str(self.root)])

        self.assertEqual(exit_code, 1)

    def test_write_paths_validator_script_rejected(self):
        manifest = self.base_manifest()
        manifest["owners"][0]["write_paths"] = ["scripts/validate_ownership_manifest.py"]
        manifest_path = self.write_manifest(manifest)

        exit_code = vom.main(["--manifest", manifest_path, "--root", str(self.root)])

        self.assertEqual(exit_code, 1)

    def test_authorize_rejects_non_zero_padded_branch(self):
        manifest = self.base_manifest()
        manifest["req_id"] = "REQ-042"
        manifest_path = self.write_manifest(manifest, filename="REQ-042.json")

        exit_code = vom.main(
            [
                "--manifest",
                manifest_path,
                "--root",
                str(self.root),
                "--branch",
                "req-42-login-flow",
                "--authorize-agent",
                "frontend-engineer",
                "--target",
                "apps/web/src/features/example/LoginForm.tsx",
            ]
        )

        self.assertEqual(exit_code, 1)

    def test_authorize_succeeds_for_zero_padded_branch(self):
        manifest = self.base_manifest()
        manifest["req_id"] = "REQ-042"
        manifest_path = self.write_manifest(manifest, filename="REQ-042.json")

        exit_code = vom.main(
            [
                "--manifest",
                manifest_path,
                "--root",
                str(self.root),
                "--branch",
                "req-042-login-flow",
                "--authorize-agent",
                "frontend-engineer",
                "--target",
                "apps/web/src/features/example/LoginForm.tsx",
            ]
        )

        self.assertEqual(exit_code, 0)

    def test_authorize_rejects_draft_manifest(self):
        manifest = self.base_manifest()
        manifest["status"] = "draft"
        manifest["approval"] = {"approved_by": "", "approved_at": ""}
        manifest_path = self.write_manifest(manifest)

        exit_code = vom.main(
            [
                "--manifest",
                manifest_path,
                "--root",
                str(self.root),
                "--branch",
                "req-100-example-feature",
                "--authorize-agent",
                "frontend-engineer",
                "--target",
                "apps/web/src/features/example/LoginForm.tsx",
            ]
        )

        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
