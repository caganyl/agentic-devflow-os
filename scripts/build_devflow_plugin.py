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
}

PLUGIN_MANIFEST_VERSION = "1.0.0"

EXCLUDED_FILES = {".gitkeep", ".DS_Store"}
EXCLUDED_AGENTS = {"settings.json"}


def collect_agents(src: Path) -> list[dict]:
    agents = []
    for f in sorted(src.glob("*.md")):
        if f.name in EXCLUDED_FILES:
            continue
        agents.append({"name": f.stem, "source": str(f.relative_to(REPO_ROOT))})
    return agents


def collect_skills(src: Path) -> list[dict]:
    skills = []
    for skill_dir in sorted(src.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if skill_file.exists():
            skills.append({
                "name": skill_dir.name,
                "source": str(skill_file.relative_to(REPO_ROOT)),
            })
    return skills


def collect_templates(src: Path) -> list[dict]:
    templates = []
    for f in sorted(src.glob("*")):
        if f.name in EXCLUDED_FILES or not f.is_file():
            continue
        templates.append({"name": f.name, "source": str(f.relative_to(REPO_ROOT))})
    return templates


def collect_workflows(src: Path) -> list[dict]:
    workflows = []
    for f in sorted(src.glob("*.md")):
        if f.name in EXCLUDED_FILES:
            continue
        workflows.append({"name": f.stem, "source": str(f.relative_to(REPO_ROOT))})
    return workflows


def collect_rules(src: Path) -> list[dict]:
    rules = []
    for f in sorted(src.glob("*.md")):
        if f.name in EXCLUDED_FILES:
            continue
        rules.append({"name": f.stem, "source": str(f.relative_to(REPO_ROOT))})
    return rules


def copy_source_tree(sources: dict, output_dir: Path) -> None:
    for key, src_path in sources.items():
        if not src_path.exists():
            print(f"  [skip] {key}: source not found at {src_path}", file=sys.stderr)
            continue
        dest = output_dir / key
        if src_path.is_dir():
            shutil.copytree(
                src_path,
                dest,
                ignore=shutil.ignore_patterns(*EXCLUDED_FILES),
                dirs_exist_ok=True,
            )
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest)


def build_manifest(output_dir: Path) -> dict:
    return {
        "schema_version": "1",
        "plugin_version": PLUGIN_MANIFEST_VERSION,
        "name": "devflow-plugin",
        "description": (
            "Agentic DevFlow OS plugin — agent roles, skills, "
            "templates, workflows and rules."
        ),
        "agents": collect_agents(SOURCES["agents"]),
        "skills": collect_skills(SOURCES["skills"]),
        "templates": collect_templates(SOURCES["templates"]),
        "workflows": collect_workflows(SOURCES["workflows"]),
        "rules": collect_rules(SOURCES["rules"]),
        "notes": [
            "This plugin does NOT include settings.json, hooks, or credentials.",
            "MCP server configuration must be set up separately in the target project.",
            "Security hooks must be manually reviewed and installed in the target project.",
        ],
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

    manifest = build_manifest(plugin_dir)
    manifest_path = claude_plugin_dir / "plugin.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"  agents:    {len(manifest['agents'])}")
    print(f"  skills:    {len(manifest['skills'])}")
    print(f"  templates: {len(manifest['templates'])}")
    print(f"  workflows: {len(manifest['workflows'])}")
    print(f"  rules:     {len(manifest['rules'])}")
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
