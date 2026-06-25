import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_PATH = REPO_ROOT / ".claude" / "hooks" / "enforce-role-boundaries.sh"


class GovernanceOperationsAuthorTestCase(unittest.TestCase):
    """Verifies the narrow runtime boundary for governance operations docs."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        subprocess.run(
            ["git", "init", "-q", str(self.root)],
            check=True,
            capture_output=True,
            text=True,
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def _run_hook(self, tool_name, tool_input):
        payload = {
            "cwd": str(self.root),
            "agent_type": "governance-operations-author",
            "tool_name": tool_name,
            "tool_input": tool_input,
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
            payload["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )

    def test_operations_document_write_is_allowed(self):
        result = self._run_hook(
            "Write",
            {"file_path": "docs/operations/REQ_LIFECYCLE_RUNBOOK.md"},
        )
        self._assert_allowed(result)

    def test_static_ownership_runbook_write_is_allowed(self):
        result = self._run_hook(
            "Write",
            {"file_path": "docs/ownership/REGISTRY_BRANCH_RUNBOOK.md"},
        )
        self._assert_allowed(result)

    def test_product_document_write_is_denied(self):
        result = self._run_hook(
            "Write",
            {"file_path": "docs/product/requirements/REQ-042.md"},
        )
        self._assert_denied(result)

    def test_bash_is_denied(self):
        result = self._run_hook(
            "Bash",
            {"command": "pwd"},
        )
        self._assert_denied(result)


if __name__ == "__main__":
    unittest.main()
