#!/usr/bin/env python3
"""Build the deterministic Agentic DevFlow OS Codex plugin."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "codex-devflow-plugin"
PLUGIN_ID = "codex-devflow"
PLUGIN_VERSION = "0.1.0"
BUILD_MARKER_NAME = ".devflow-codex-plugin-build.json"
BUILD_MARKER = {
    "schema_version": 1,
    "generator": "build_codex_devflow_plugin.py",
    "plugin_name": PLUGIN_ID,
    "plugin_version": PLUGIN_VERSION,
}
SKILL_NAMES = (
    "managed-delivery-operations",
    "visual-design-review",
    "qa-acceptance-verification",
)
SCRIPT_NAMES = (
    "devflow_guard_core.py",
    "devflow_codex_target_guard.py",
)
BOOTSTRAP_DENIAL = (
    "DevFlow guard: hook bootstrap failed; tool call blocked by policy."
)


class BuildError(RuntimeError):
    """Raised when the plugin cannot be built safely."""


def _read_json_object(path: Path) -> dict[str, object] | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return content if isinstance(content, dict) else None


def _exact_marker_matches(content: dict[str, object] | None) -> bool:
    if content is None or content.keys() != BUILD_MARKER.keys():
        return False
    return all(
        type(content[key]) is type(expected) and content[key] == expected
        for key, expected in BUILD_MARKER.items()
    )


def _verify_owned_build(final: Path) -> None:
    if final.is_symlink() or not final.is_dir():
        raise BuildError(f"existing output target is not a verified build: {final}")
    marker = _read_json_object(final / BUILD_MARKER_NAME)
    manifest = _read_json_object(final / ".codex-plugin" / "plugin.json")
    if not _exact_marker_matches(marker) or manifest is None:
        raise BuildError(f"existing output target is not a verified build: {final}")
    if (
        type(manifest.get("name")) is not str
        or manifest["name"] != PLUGIN_ID
        or type(manifest.get("version")) is not str
        or manifest["version"] != PLUGIN_VERSION
    ):
        raise BuildError(f"existing output target is not a verified build: {final}")


def _skill_frontmatter(path: Path) -> dict[str, str]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BuildError(f"missing or unreadable source: {path}") from exc
    lines = content.splitlines()
    if not lines or lines[0] != "---":
        raise BuildError(f"invalid skill frontmatter: {path}")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise BuildError(f"invalid skill frontmatter: {path}") from exc

    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or ":" not in line:
            raise BuildError(f"invalid skill frontmatter: {path}")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value or key in metadata:
            raise BuildError(f"invalid skill frontmatter: {path}")
        metadata[key] = value
    if not metadata.get("name") or not metadata.get("description"):
        raise BuildError(f"invalid skill frontmatter: {path}")
    return metadata


def _sources() -> tuple[dict[str, Path], dict[str, Path]]:
    skills = {
        name: REPO_ROOT / ".agents" / "skills" / name / "SKILL.md"
        for name in SKILL_NAMES
    }
    scripts = {name: REPO_ROOT / "scripts" / name for name in SCRIPT_NAMES}
    for name, path in skills.items():
        if not path.is_file():
            raise BuildError(f"missing source file: {path}")
        metadata = _skill_frontmatter(path)
        if metadata["name"] != name:
            raise BuildError(f"invalid skill frontmatter: {path}")
    for path in scripts.values():
        if not path.is_file():
            raise BuildError(f"missing source file: {path}")
    return skills, scripts


def _safe_paths(output_dir: Path) -> tuple[Path, Path]:
    expanded = output_dir.expanduser()
    if not expanded.is_absolute():
        expanded = Path.cwd() / expanded
    parent = expanded.resolve(strict=False)
    final = parent / PLUGIN_NAME

    if parent.exists() and not parent.is_dir():
        raise BuildError(f"unsafe output directory: {output_dir}")
    if parent == Path(parent.anchor) or parent == Path.home().resolve():
        raise BuildError(f"unsafe output directory: {output_dir}")
    try:
        relative = parent.relative_to(REPO_ROOT)
    except ValueError:
        relative = None
    if relative is not None:
        if not relative.parts or relative.parts[0] != "dist":
            raise BuildError(f"unsafe output directory: {output_dir}")
        if PLUGIN_NAME in relative.parts:
            raise BuildError(f"unsafe output directory: {output_dir}")
    if final.is_symlink() or (final.exists() and not final.is_dir()):
        raise BuildError(f"unsafe output target: {final}")
    if final.exists():
        _verify_owned_build(final)
    return parent, final


def _manifest() -> dict[str, object]:
    return {
        "name": PLUGIN_ID,
        "version": PLUGIN_VERSION,
        "description": (
            "Managed delivery skills and target-policy hooks for Agentic DevFlow OS."
        ),
        "skills": "./skills/",
        "hooks": "./hooks/hooks.json",
        "author": {"name": "Agentic DevFlow OS"},
        "interface": {
            "displayName": "Agentic DevFlow OS",
            "shortDescription": "Managed delivery skills and target-policy checks",
            "category": "Productivity",
        },
    }


def _hooks() -> dict[str, object]:
    command = (
        'if [ "${DEVFLOW_CODEX_GUARD_REQUIRED:-}" != "1" ]; then exit 0; fi; '
        f"denial='{BOOTSTRAP_DENIAL}'; "
        'if [ -z "${PLUGIN_ROOT:-}" ]; then printf \'%s\\n\' "$denial" >&2; exit 2; fi; '
        'adapter="$PLUGIN_ROOT/scripts/devflow_codex_target_guard.py"; '
        'if [ ! -f "$adapter" ]; then printf \'%s\\n\' "$denial" >&2; exit 2; fi; '
        'exec /usr/bin/env python3 "$adapter"'
    )
    return {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": r"^(Bash|bash|apply_patch|Edit|Write)$",
                    "hooks": [
                        {
                            "type": "command",
                            "command": command,
                            "timeout": 10,
                            "statusMessage": "Checking DevFlow target policy",
                        }
                    ],
                }
            ]
        }
    }


def _write_json(path: Path, content: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def build(output_dir: Path) -> Path:
    skills, scripts = _sources()
    parent, final = _safe_paths(output_dir)
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{PLUGIN_NAME}-", dir=parent))
    try:
        _write_json(staging / BUILD_MARKER_NAME, BUILD_MARKER)
        _write_json(staging / ".codex-plugin" / "plugin.json", _manifest())
        _write_json(staging / "hooks" / "hooks.json", _hooks())
        for name, source in skills.items():
            destination = staging / "skills" / name / "SKILL.md"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        for name, source in scripts.items():
            destination = staging / "scripts" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        if final.exists():
            _verify_owned_build(final)
            shutil.rmtree(final)
        staging.rename(final)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return final


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "dist",
        help="parent output directory (default: dist/)",
    )
    args = parser.parse_args()
    try:
        final = build(args.output_dir)
    except (BuildError, OSError, shutil.Error) as exc:
        print(f"Codex plugin build failed: {exc}", file=sys.stderr)
        return 1
    print(final)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
