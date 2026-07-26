"""
Security hooks must fail closed when a tool they depend on is missing.

protect-main.sh, protect-sensitive-paths.sh and enforce-role-boundaries.sh
parse their stdin with `jq` (and the role hook shells out to `python3`). Under
`set -euo pipefail` a missing `jq` crashed the first extraction with exit 127
before any decision was emitted -- and a PreToolUse hook that exits without a
deny lets the tool call proceed. So a machine without jq silently disabled
every one of these guards (fail-open).

These tests run each hook with a PATH that omits jq and assert it still denies.
"""

import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / ".claude" / "hooks"

# Everything the fail-closed path could touch, EXCEPT jq. The hooks read stdin
# with `cat` and may shell to git/python3 before the check, so provide those.
_ESSENTIAL_TOOLS = ("bash", "sh", "cat", "env", "git", "python3", "grep", "sed", "tr")


def _make_jqless_bindir(tmp: Path) -> Path:
    bindir = tmp / "bin"
    bindir.mkdir()
    for tool in _ESSENTIAL_TOOLS:
        resolved = shutil.which(tool)
        if resolved:
            os.symlink(resolved, bindir / tool)
    # Guard the premise: jq must not be reachable through this bin.
    assert not (bindir / "jq").exists()
    return bindir


def _run_hook_without_jq(hook_name: str, payload: dict) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as td:
        bindir = _make_jqless_bindir(Path(td))
        return subprocess.run(
            [shutil.which("bash"), str(HOOKS_DIR / hook_name)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env={"PATH": str(bindir), "HOME": os.environ.get("HOME", "")},
        )


class HookFailClosedWithoutJqTest(unittest.TestCase):

    def _assert_denied(self, result: subprocess.CompletedProcess):
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            self.fail(f"hook emitted no decision JSON; stdout={result.stdout!r} "
                      f"stderr={result.stderr!r}")
        self.assertEqual(
            payload["hookSpecificOutput"]["permissionDecision"], "deny",
            "hook must deny when jq is unavailable",
        )

    def test_protect_main_denies_without_jq(self):
        self._assert_denied(_run_hook_without_jq("protect-main.sh", {
            "tool_name": "Write",
            "cwd": str(REPO_ROOT),
            "tool_input": {"file_path": "docs/x.md"},
        }))

    def test_protect_sensitive_denies_without_jq(self):
        self._assert_denied(_run_hook_without_jq("protect-sensitive-paths.sh", {
            "tool_name": "Write",
            "cwd": str(REPO_ROOT),
            "tool_input": {"file_path": "docs/x.md"},
        }))

    def test_enforce_role_denies_without_jq(self):
        self._assert_denied(_run_hook_without_jq("enforce-role-boundaries.sh", {
            "tool_name": "Write",
            "agent_type": "backend-engineer",
            "cwd": str(REPO_ROOT),
            "tool_input": {"file_path": "docs/product/x.md"},
        }))

    def test_deny_reason_names_the_missing_tool(self):
        result = _run_hook_without_jq("enforce-role-boundaries.sh", {
            "tool_name": "Write",
            "agent_type": "backend-engineer",
            "cwd": str(REPO_ROOT),
            "tool_input": {"file_path": "docs/product/x.md"},
        })
        reason = json.loads(result.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("jq", reason.lower())
        self.assertIn("fail-closed", reason.lower())


class HookStillFunctionsWithJqTest(unittest.TestCase):
    """Guard against the fail-closed check swallowing the normal path."""

    def _run(self, hook_name: str, payload: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(HOOKS_DIR / hook_name)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
        )

    @unittest.skipIf(shutil.which("jq") is None, "jq not installed on this machine")
    def test_role_hook_still_denies_out_of_lane_write_with_jq(self):
        # backend-engineer writing a product doc: denied on any non-req branch.
        result = self._run("enforce-role-boundaries.sh", {
            "tool_name": "Write",
            "agent_type": "backend-engineer",
            "cwd": str(REPO_ROOT),
            "tool_input": {"file_path": "docs/product/x.md"},
        })
        payload = json.loads(result.stdout)
        self.assertEqual(payload["hookSpecificOutput"]["permissionDecision"], "deny")

    @unittest.skipIf(shutil.which("jq") is None, "jq not installed on this machine")
    def test_role_hook_ignores_calls_without_agent_type(self):
        # No agent_type (main-session supervisor) → not a governed role → allow.
        result = self._run("enforce-role-boundaries.sh", {
            "tool_name": "Write",
            "cwd": str(REPO_ROOT),
            "tool_input": {"file_path": "docs/product/x.md"},
        })
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
