#!/usr/bin/env python3
"""
DevFlow Plugin Builder

Builds a distributable plugin package from the framework repo's
agent, skill, template and workflow sources.

Output: dist/devflow-plugin/

Usage:
    python3 scripts/build_devflow_plugin.py [--output-dir PATH]
"""

import argparse
import json
import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_DIR = REPO_ROOT / ".claude"

SOURCES = {
    "agents": CLAUDE_DIR / "agents",
    "skills": CLAUDE_DIR / "skills",
    "templates": CLAUDE_DIR / "templates",
    "workflows": CLAUDE_DIR / "workflows",
    "rules": CLAUDE_DIR / "rules",
    "scripts": REPO_ROOT / "scripts",
    "hooks": REPO_ROOT / "hooks",
}

PLUGIN_VERSION = "1.0.0"

EXCLUDED_FILES = {".gitkeep", ".DS_Store"}
INCLUDED_SCRIPTS = frozenset({
    "devflow_operations.py",
    "devflow_target_guard.py",
    "devflow_delegation_recorder.py",
    # Shipped so enforce-role-boundaries.sh can authorize implementer writes in
    # a target project (it resolves the validator from the plugin root).
    "validate_ownership_manifest.py",
})
INCLUDED_HOOKS = frozenset({"hooks.json"})

# Shell scripts shipped under the plugin's scripts/. devflow_bootstrap.sh is the
# zero-step target provisioner the `claude-devflow` launcher runs before starting
# a session, so it must travel with the plugin rather than assume a framework
# repo checkout is present.
INCLUDED_SHELL_SCRIPTS = frozenset({
    "devflow_bootstrap.sh",
    "devflow_new_manifest.sh",
})

# Runtime enforcement shell hooks. Shipping these makes claude-devflow apply the
# same role-boundary / main-branch / sensitive-path protection in any target
# project that the framework repo dogfoods on itself. Registered in hooks.json
# under ${CLAUDE_PLUGIN_ROOT}/hooks/.
INCLUDED_SHELL_HOOKS = frozenset({
    "protect-main.sh",
    "protect-sensitive-paths.sh",
    "enforce-role-boundaries.sh",
    "session-start.sh",
})


def copy_source_tree(sources: dict, output_dir: Path) -> None:
    for key, src_path in sources.items():
        if not src_path.exists():
            print(f"  [skip] {key}: source not found at {src_path}", file=sys.stderr)
            continue
        dest = output_dir / key
        if key == "scripts":
            dest.mkdir(parents=True, exist_ok=True)
            for fname in INCLUDED_SCRIPTS:
                src_file = src_path / fname
                if src_file.exists():
                    shutil.copy2(src_file, dest / fname)
                else:
                    print(f"  [skip] scripts/{fname}: not found", file=sys.stderr)
            for fname in INCLUDED_SHELL_SCRIPTS:
                src_file = src_path / fname
                if src_file.exists():
                    dest_file = dest / fname
                    shutil.copy2(src_file, dest_file)
                    dest_file.chmod(0o755)
                else:
                    print(f"  [skip] scripts/{fname}: not found", file=sys.stderr)
        elif key == "hooks":
            dest.mkdir(parents=True, exist_ok=True)
            for fname in INCLUDED_HOOKS:
                src_file = src_path / fname
                if src_file.exists():
                    shutil.copy2(src_file, dest / fname)
                else:
                    print(f"  [skip] hooks/{fname}: not found", file=sys.stderr)
            # Runtime enforcement shell hooks live under .claude/hooks/, not the
            # hooks/ source dir; copy them into the plugin's hooks/ so hooks.json
            # can reference ${CLAUDE_PLUGIN_ROOT}/hooks/<name>.sh.
            for fname in INCLUDED_SHELL_HOOKS:
                src_file = CLAUDE_DIR / "hooks" / fname
                if src_file.exists():
                    dest_file = dest / fname
                    shutil.copy2(src_file, dest_file)
                    dest_file.chmod(0o755)
                else:
                    print(f"  [skip] hooks/{fname}: not found", file=sys.stderr)
        elif src_path.is_dir():
            shutil.copytree(
                src_path,
                dest,
                ignore=shutil.ignore_patterns(*EXCLUDED_FILES),
                dirs_exist_ok=True,
            )
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest)


def build_manifest() -> dict:
    return {
        "name": "devflow-plugin",
        "description": (
            "Agentic DevFlow OS: autonomous delivery workflows, skills and specialist agents."
        ),
        "version": PLUGIN_VERSION,
    }


def build(output_dir: Path) -> None:
    plugin_dir = output_dir / "devflow-plugin"
    claude_plugin_dir = plugin_dir / ".claude-plugin"

    if plugin_dir.exists():
        shutil.rmtree(plugin_dir)

    plugin_dir.mkdir(parents=True)
    claude_plugin_dir.mkdir(parents=True)

    print(f"Building DevFlow plugin to: {plugin_dir}")

    copy_source_tree(SOURCES, plugin_dir)

    manifest = build_manifest()
    manifest_path = claude_plugin_dir / "plugin.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")

    try:
        manifest_rel = manifest_path.relative_to(REPO_ROOT)
    except ValueError:
        manifest_rel = manifest_path
    print(f"  manifest:  {manifest_rel}")
    print("Build complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "dist",
        help="Output directory (default: dist/)",
    )
    args = parser.parse_args()
    build(args.output_dir)


if __name__ == "__main__":
    main()
