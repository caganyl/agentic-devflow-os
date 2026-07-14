#!/usr/bin/env python3
"""Validate that a PR diff stays within base-approved ownership manifest paths.

Standard library only. See docs/ownership/README.md ("CI Diff Enforcement")
for the contract this script enforces. Unlike
scripts/validate_ownership_manifest.py (which authorizes a single Claude
Edit/Write call at runtime), this script is meant to run in CI against the
full diff of a pull request and never trusts the PR head's own ownership
manifest as a source of authority -- only the manifest as it existed in the
base commit.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import validate_ownership_manifest as vom  # noqa: E402

REQ_BRANCH_RE = re.compile(r"^req-([0-9]{3,})-.+$")
OWNERSHIP_REGISTRY_BRANCH_RE = re.compile(r"^ownership-REQ-([0-9]{3,})-.+$")
AUTHORITY_MANIFEST_PATH_RE = re.compile(r"^docs/ownership/REQ-[0-9]{3,}\.json$")

FORBIDDEN_GIT_MODES = {
    "120000": "symlink",
    "160000": "gitlink/submodule",
}

GOVERNANCE_ALLOWED_PREFIXES = (
    ".agents/plugins/",
    ".agents/skills/",
    ".claude/",
    ".codex/agents/",
    ".github/",
    "docs/",
    "scripts/",
    "tests/",
    "design/",
    "evals/",
)

GOVERNANCE_ALLOWED_EXACT_PATHS = frozenset(
    {
        ".gitignore",
        ".codex/config.toml",
        ".codex/hooks.json",
        "README.md",
        "PROJECT_CONSTITUTION.md",
        "CLAUDE.md",
        "AGENTS.md",
        "hooks/hooks.json",
    }
)

# Bootstrap PR: additional write-path restrictions on top of what
# validate_ownership_manifest.py already enforces (e.g. .claude/, docs/ownership/).
BOOTSTRAP_FORBIDDEN_WRITE_PREFIXES = (
    ".github/",
    "scripts/",
)

BOOTSTRAP_FORBIDDEN_WRITE_EXACT_PATHS = frozenset(
    {
        "README.md",
        ".gitignore",
    }
)

# Single-component root paths that are too broad for bootstrap write authority.
BOOTSTRAP_OVERLY_BROAD_SINGLE_PATHS = frozenset(
    {
        "src",
        "tests",
        "docs",
        "apps",
        "lib",
        "evals",
    }
)

# Two-component domain-root paths that are too broad for bootstrap write authority.
# Narrow feature-scoped paths under these roots are allowed; only the bare
# domain root itself is rejected (e.g. docs/contracts/openapi/req-NNN-name is
# allowed, docs/contracts is not).
BOOTSTRAP_OVERLY_BROAD_DOMAIN_ROOTS = frozenset(
    {
        "docs/contracts",
    }
)

# Required prefix per reference field — checked individually so swapped paths are caught.
_REQUIRED_REF_PREFIX = {
    "requirement": "docs/product/requirements/",
    "acceptance_criteria": "docs/product/acceptance-criteria/",
}


class DiffValidationError(Exception):
    """Raised with all accumulated diff validation errors."""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("\n".join(self.errors))


def run_git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
    )


def validate_git_repo(root):
    result = run_git(root, "rev-parse", "--is-inside-work-tree")
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise DiffValidationError([f"--root {str(root)!r} is not a git repository"])


def validate_revision(root, sha, flag_name):
    result = run_git(root, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")
    if result.returncode != 0:
        raise DiffValidationError([f"{flag_name} is not a valid git revision: {sha!r}"])


def parse_raw_diff(output):
    """Parse `git diff --raw -z` output into entries carrying old/new git
    file modes alongside status and paths, so callers can fail closed on
    symlink (120000) and gitlink/submodule (160000) entries without relying
    on path heuristics."""
    tokens = output.split("\0")
    entries = []
    i = 0
    n = len(tokens)
    while i < n:
        header = tokens[i]
        i += 1
        if header == "":
            continue
        if not header.startswith(":"):
            continue
        fields = header[1:].split(" ")
        old_mode, new_mode, _old_sha, _new_sha, status = fields[:5]
        if status[0] in ("R", "C"):
            old_path = tokens[i]
            i += 1
            new_path = tokens[i]
            i += 1
            entries.append(
                {
                    "status": status,
                    "paths": [old_path, new_path],
                    "old_mode": old_mode,
                    "new_mode": new_mode,
                }
            )
        else:
            path = tokens[i]
            i += 1
            entries.append(
                {
                    "status": status,
                    "paths": [path],
                    "old_mode": old_mode,
                    "new_mode": new_mode,
                }
            )
    return entries


def compute_diff(root, base_sha, head_sha):
    result = run_git(
        root,
        "diff",
        "--raw",
        "-z",
        "--find-renames",
        "--find-copies",
        base_sha,
        head_sha,
    )
    if result.returncode != 0:
        raise DiffValidationError([f"git diff failed: {result.stderr.strip()}"])
    return parse_raw_diff(result.stdout)


def validate_no_unsafe_git_modes(diff_entries):
    errors = []
    for entry in diff_entries:
        paths = entry["paths"]
        old_mode = entry.get("old_mode") or "000000"
        new_mode = entry.get("new_mode") or "000000"
        if entry["status"][0] in ("R", "C") and len(paths) == 2:
            mode_pairs = [(paths[0], old_mode), (paths[1], new_mode)]
        else:
            mode_pairs = [(paths[0], old_mode), (paths[0], new_mode)]

        seen = set()
        for path, mode in mode_pairs:
            kind = FORBIDDEN_GIT_MODES.get(mode)
            if kind is None or (path, mode) in seen:
                continue
            seen.add((path, mode))
            errors.append(
                f"path {path!r} has forbidden git mode {mode!r} ({kind}); "
                f"symlink and gitlink/submodule changes are rejected by the "
                f"ownership diff validator"
            )
    if errors:
        raise DiffValidationError(errors)


def normalize_path(raw_path):
    return PurePosixPath(raw_path).as_posix()


def all_diff_paths(diff_entries):
    paths = []
    for entry in diff_entries:
        paths.extend(entry["paths"])
    return paths


def is_authority_manifest_path(normalized_path):
    """True only for the exact docs/ownership/REQ-<digits>.json authority
    manifest pattern. Static ownership control-plane documents (README.md,
    TEMPLATE.json, schema.json) and non-manifest files under
    docs/ownership/ are intentionally excluded -- those are governed by the
    normal governance allowlist instead, since they are not a source of
    write authority."""
    return bool(AUTHORITY_MANIFEST_PATH_RE.match(normalized_path))


def is_governance_allowed(path):
    normalized = normalize_path(path)
    if is_authority_manifest_path(normalized):
        return False
    if normalized in GOVERNANCE_ALLOWED_EXACT_PATHS:
        return True
    return any(
        normalized == prefix.rstrip("/") or normalized.startswith(prefix)
        for prefix in GOVERNANCE_ALLOWED_PREFIXES
    )


def validate_governance_branch(diff_entries):
    errors = []
    for path in all_diff_paths(diff_entries):
        normalized = normalize_path(path)
        if is_authority_manifest_path(normalized):
            errors.append(
                f"generic governance branch diff must not modify ownership authority "
                f"manifest docs/ownership/REQ-<digits>.json: {path!r} (manifest lifecycle "
                f"is restricted to ownership-REQ-<id>-* branches)"
            )
        elif not is_governance_allowed(path):
            errors.append(
                f"governance branch diff contains a path outside governance/control-plane "
                f"prefixes: {path!r}"
            )
    if errors:
        raise DiffValidationError(errors)


def git_show(root, sha, rel_path):
    result = run_git(root, "show", f"{sha}:{rel_path}")
    if result.returncode != 0:
        return None
    return result.stdout


def materialize_references(root, sha, manifest, temp_root):
    references = manifest.get("references") or {}
    candidates = []

    requirement = references.get("requirement")
    if requirement:
        candidates.append(requirement)

    acceptance_criteria = references.get("acceptance_criteria")
    if acceptance_criteria:
        candidates.append(acceptance_criteria)

    for contract_path in references.get("contracts") or []:
        candidates.append(contract_path)

    for adr_path in references.get("adrs") or []:
        candidates.append(adr_path)

    for rel_path in candidates:
        if not vom.is_relative_safe_path(rel_path):
            continue
        resolved = vom.resolve_under_root(temp_root, rel_path)
        if resolved is None:
            continue
        content = git_show(root, sha, rel_path)
        if content is None:
            continue
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")


def path_under(path, write_path):
    target = PurePosixPath(path)
    owned = PurePosixPath(write_path)
    return target == owned or owned in target.parents


def load_base_manifest(root, base_sha, manifest_rel_path):
    manifest_text = git_show(root, base_sha, manifest_rel_path)
    if manifest_text is None:
        raise DiffValidationError(
            [
                f"base commit {base_sha} does not contain ownership manifest "
                f"{manifest_rel_path!r}"
            ]
        )
    try:
        return manifest_text, json.loads(manifest_text)
    except json.JSONDecodeError as exc:
        raise DiffValidationError(
            [f"base manifest {manifest_rel_path!r} is not valid JSON: {exc}"]
        ) from exc


def load_head_manifest(root, head_sha, manifest_rel_path):
    manifest_text = git_show(root, head_sha, manifest_rel_path)
    if manifest_text is None:
        raise DiffValidationError(
            [
                f"head commit {head_sha} does not contain ownership manifest "
                f"{manifest_rel_path!r}"
            ]
        )
    try:
        return manifest_text, json.loads(manifest_text)
    except json.JSONDecodeError as exc:
        raise DiffValidationError(
            [f"head manifest {manifest_rel_path!r} is not valid JSON: {exc}"]
        ) from exc


def validate_head_manifest(root, base_sha, req_id, manifest_text, manifest):
    """Validate a manifest as it exists at the PR head (used by ownership
    registry branches, which are the one branch class authorized to create
    or update a manifest). References are still materialized only from the
    base snapshot, since a registry branch must not be able to fabricate its
    own requirement/contract/ADR evidence alongside the manifest."""
    with tempfile.TemporaryDirectory() as tmp:
        temp_root = Path(tmp)
        manifest_dir = temp_root / "docs" / "ownership"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_temp_path = manifest_dir / f"{req_id}.json"
        manifest_temp_path.write_text(manifest_text, encoding="utf-8")

        materialize_references(root, base_sha, manifest, temp_root)

        try:
            vom.validate_manifest(manifest, str(manifest_temp_path), temp_root)
        except vom.ManifestError as exc:
            raise DiffValidationError(
                [f"head manifest {req_id} failed validation: {error}" for error in exc.errors]
            ) from exc


def validate_base_manifest(root, base_sha, req_id, manifest_text, manifest):
    with tempfile.TemporaryDirectory() as tmp:
        temp_root = Path(tmp)
        manifest_dir = temp_root / "docs" / "ownership"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_temp_path = manifest_dir / f"{req_id}.json"
        manifest_temp_path.write_text(manifest_text, encoding="utf-8")

        materialize_references(root, base_sha, manifest, temp_root)

        try:
            vom.validate_manifest(manifest, str(manifest_temp_path), temp_root)
        except vom.ManifestError as exc:
            raise DiffValidationError(
                [f"base manifest {req_id} failed validation: {error}" for error in exc.errors]
            ) from exc

    if manifest.get("status") != "approved":
        raise DiffValidationError(
            [
                f"base manifest {req_id} status must be 'approved' to authorize a CI diff, "
                f"got: {manifest.get('status')!r}"
            ]
        )


def collect_owner_write_paths(manifest):
    owner_write_paths = []
    for owner in manifest.get("owners") or []:
        write_paths = []
        for write_path in owner.get("write_paths") or []:
            if vom.is_relative_safe_path(write_path):
                write_paths.append(normalize_path(write_path))
        owner_write_paths.append(write_paths)
    return owner_write_paths


def matching_owner_indexes(normalized_path, owner_write_paths):
    return [
        index
        for index, write_paths in enumerate(owner_write_paths)
        if any(path_under(normalized_path, write_path) for write_path in write_paths)
    ]


def validate_diff_ownership(diff_entries, owner_write_paths, req_id):
    errors = []
    for entry in diff_entries:
        matches_per_path = []
        for path in entry["paths"]:
            normalized = normalize_path(path)
            matches = matching_owner_indexes(normalized, owner_write_paths)
            if len(matches) == 0:
                errors.append(
                    f"path {path!r} is not under any owner write_paths in base manifest {req_id}"
                )
            elif len(matches) > 1:
                errors.append(
                    f"path {path!r} matches more than one owner write_paths in base manifest "
                    f"{req_id}"
                )
            matches_per_path.append(matches)

        if entry["status"][0] in ("R", "C") and all(len(m) == 1 for m in matches_per_path):
            old_owner, new_owner = matches_per_path[0][0], matches_per_path[1][0]
            if old_owner != new_owner:
                old_path, new_path = entry["paths"]
                errors.append(
                    f"rename/copy from {old_path!r} to {new_path!r} crosses owner boundaries "
                    f"in base manifest {req_id}"
                )
    if errors:
        raise DiffValidationError(errors)


_SECRET_LIKE_KEYWORDS = (
    "secret",
    "secrets",
    "credential",
    "credentials",
    "private_key",
    "private-key",
    ".pem",
    ".key",
    ".p12",
)


def _is_secret_like_write_path(normalized_path):
    """True if any path component looks like a secret or credential file/directory."""
    for part in PurePosixPath(normalized_path).parts:
        if part == ".env" or part.startswith(".env."):
            return True
        part_lower = part.lower()
        if any(kw in part_lower for kw in _SECRET_LIKE_KEYWORDS):
            return True
    return False


def validate_bootstrap_write_paths(manifest, req_id):
    """Check that bootstrap manifest write_paths don't grant forbidden authority."""
    errors = []
    for idx, owner in enumerate(manifest.get("owners") or []):
        for write_path in owner.get("write_paths") or []:
            if not vom.is_relative_safe_path(write_path):
                continue  # vom.validate_manifest already reports this
            normalized = normalize_path(write_path)
            for prefix in BOOTSTRAP_FORBIDDEN_WRITE_PREFIXES:
                if normalized == prefix.rstrip("/") or normalized.startswith(prefix):
                    errors.append(
                        f"bootstrap manifest {req_id} owners[{idx}] write_paths {write_path!r} "
                        f"targets a forbidden area {prefix!r}"
                    )
                    break
            else:
                if normalized in BOOTSTRAP_FORBIDDEN_WRITE_EXACT_PATHS:
                    errors.append(
                        f"bootstrap manifest {req_id} owners[{idx}] write_paths {write_path!r} "
                        f"targets a protected file"
                    )
                elif _is_secret_like_write_path(normalized):
                    errors.append(
                        f"bootstrap manifest {req_id} owners[{idx}] write_paths {write_path!r} "
                        f"resembles a secret or credential path"
                    )
                else:
                    parts = PurePosixPath(normalized).parts
                    if len(parts) == 1 and normalized in BOOTSTRAP_OVERLY_BROAD_SINGLE_PATHS:
                        errors.append(
                            f"bootstrap manifest {req_id} owners[{idx}] write_paths {write_path!r} "
                            f"is an overly broad root-level path; use a narrower feature-scoped path "
                            f"(e.g. src/features/req-{req_id[4:]}-name instead of src)"
                        )
                    elif normalized in BOOTSTRAP_OVERLY_BROAD_DOMAIN_ROOTS:
                        errors.append(
                            f"bootstrap manifest {req_id} owners[{idx}] write_paths {write_path!r} "
                            f"is an overly broad domain-root path; use a narrower feature-scoped path "
                            f"(e.g. docs/contracts/openapi/req-{req_id[4:]}-name instead of docs/contracts)"
                        )
    if errors:
        raise DiffValidationError(errors)


def validate_bootstrap_references(root, head_sha, manifest, req_id, diff_paths_set):
    """Validate that bootstrap requirement and AC references are safe, exist in HEAD, and are in the diff."""
    errors = []
    references = manifest.get("references") or {}
    for field in ("requirement", "acceptance_criteria"):
        ref_path = references.get(field)
        if not ref_path:
            continue  # vom.validate_manifest already reports missing required refs
        if not vom.is_relative_safe_path(ref_path):
            continue  # vom.validate_manifest already reports this
        normalized_ref = normalize_path(ref_path)
        required_prefix = _REQUIRED_REF_PREFIX[field]
        if not normalized_ref.startswith(required_prefix):
            errors.append(
                f"bootstrap manifest {req_id} references.{field} {ref_path!r} must be under "
                f"{required_prefix.rstrip('/')}"
            )
            continue
        if git_show(root, head_sha, ref_path) is None:
            errors.append(
                f"bootstrap manifest {req_id} references.{field} {ref_path!r} "
                f"does not exist in the PR head commit"
            )
            continue
        if normalized_ref not in diff_paths_set:
            errors.append(
                f"bootstrap manifest {req_id} references.{field} {ref_path!r} "
                f"must be added or modified in this PR diff"
            )
    if errors:
        raise DiffValidationError(errors)


def validate_bootstrap_diff_coverage(diff_entries, owner_write_paths, manifest_rel_path,
                                     exempt_paths, req_id):
    """Every non-exempt file in the diff must be covered by exactly one owner write_path."""
    errors = []
    norm_manifest = normalize_path(manifest_rel_path)
    norm_exempt = {normalize_path(p) for p in exempt_paths}
    for entry in diff_entries:
        for path in entry["paths"]:
            normalized = normalize_path(path)
            if normalized == norm_manifest:
                continue
            if normalized in norm_exempt:
                continue
            if normalized.startswith("docs/ownership/"):
                errors.append(
                    f"bootstrap PR diff must not modify other docs/ownership/ files alongside "
                    f"the new manifest; found: {path!r}"
                )
                continue
            matches = matching_owner_indexes(normalized, owner_write_paths)
            if len(matches) == 0:
                errors.append(
                    f"path {path!r} is not under any owner write_paths in bootstrap manifest {req_id}"
                )
            elif len(matches) > 1:
                errors.append(
                    f"path {path!r} matches more than one owner write_paths in bootstrap "
                    f"manifest {req_id}"
                )
        if entry["status"][0] in ("R", "C") and len(entry["paths"]) == 2:
            norm_old = normalize_path(entry["paths"][0])
            norm_new = normalize_path(entry["paths"][1])
            skip_old = norm_old == norm_manifest or norm_old in norm_exempt or norm_old.startswith("docs/ownership/")
            skip_new = norm_new == norm_manifest or norm_new in norm_exempt or norm_new.startswith("docs/ownership/")
            if not skip_old and not skip_new:
                old_matches = matching_owner_indexes(norm_old, owner_write_paths)
                new_matches = matching_owner_indexes(norm_new, owner_write_paths)
                if (len(old_matches) == 1 and len(new_matches) == 1
                        and old_matches[0] != new_matches[0]):
                    errors.append(
                        f"rename/copy from {entry['paths'][0]!r} to {entry['paths'][1]!r} "
                        f"crosses owner boundaries in bootstrap manifest {req_id}"
                    )
    if errors:
        raise DiffValidationError(errors)


def validate_bootstrap_head_manifest(root, head_sha, req_id, manifest_text, manifest):
    """Validate bootstrap manifest using HEAD for reference materialization."""
    with tempfile.TemporaryDirectory() as tmp:
        temp_root = Path(tmp)
        manifest_dir = temp_root / "docs" / "ownership"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_temp_path = manifest_dir / f"{req_id}.json"
        manifest_temp_path.write_text(manifest_text, encoding="utf-8")
        materialize_references(root, head_sha, manifest, temp_root)
        try:
            vom.validate_manifest(manifest, str(manifest_temp_path), temp_root)
        except vom.ManifestError as exc:
            raise DiffValidationError(
                [f"bootstrap manifest {req_id} failed validation: {e}" for e in exc.errors]
            ) from exc

    if manifest.get("status") != "approved":
        raise DiffValidationError(
            [
                f"bootstrap manifest {req_id} status must be 'approved', "
                f"got: {manifest.get('status')!r}"
            ]
        )


def validate_bootstrap_req_branch(root, base_sha, head_sha, branch_match, diff_entries):
    """Validate a first-time feature bootstrap PR.

    Allowed when a req-NNN branch has no manifest in base and adds one in head.
    The head manifest authority is used (instead of base) to cover the full
    bootstrap bundle: requirement, acceptance-criteria, contracts, source, tests,
    handoff and design files.
    """
    digits = branch_match.group(1)
    req_id = f"REQ-{digits}"
    manifest_rel_path = f"docs/ownership/{req_id}.json"

    manifest_text, manifest = load_head_manifest(root, head_sha, manifest_rel_path)

    validate_bootstrap_head_manifest(root, head_sha, req_id, manifest_text, manifest)
    validate_bootstrap_write_paths(manifest, req_id)

    diff_paths_set = {normalize_path(p) for p in all_diff_paths(diff_entries)}

    validate_bootstrap_references(root, head_sha, manifest, req_id, diff_paths_set)

    references = manifest.get("references") or {}
    exempt_ref_paths = []
    for field in ("requirement", "acceptance_criteria"):
        ref = references.get(field)
        if ref and vom.is_relative_safe_path(ref):
            exempt_ref_paths.append(ref)
    # contracts and adrs are NOT exempt: they must be covered by owner write_paths

    owner_write_paths = collect_owner_write_paths(manifest)
    validate_bootstrap_diff_coverage(
        diff_entries, owner_write_paths, manifest_rel_path, exempt_ref_paths, req_id
    )


def validate_req_branch(root, base_sha, head_sha, branch_match, diff_entries):
    digits = branch_match.group(1)
    req_id = f"REQ-{digits}"
    manifest_rel_path = f"docs/ownership/{req_id}.json"

    base_has_manifest = git_show(root, base_sha, manifest_rel_path) is not None
    head_has_manifest = git_show(root, head_sha, manifest_rel_path) is not None

    if not base_has_manifest and head_has_manifest:
        validate_bootstrap_req_branch(root, base_sha, head_sha, branch_match, diff_entries)
        return

    ownership_dir_errors = [
        f"req branch diff must not modify files under docs/ownership/: {path!r}"
        for path in all_diff_paths(diff_entries)
        if normalize_path(path).startswith("docs/ownership/")
    ]
    if ownership_dir_errors:
        raise DiffValidationError(ownership_dir_errors)

    manifest_text, manifest = load_base_manifest(root, base_sha, manifest_rel_path)
    validate_base_manifest(root, base_sha, req_id, manifest_text, manifest)

    owner_write_paths = collect_owner_write_paths(manifest)
    validate_diff_ownership(diff_entries, owner_write_paths, req_id)


def validate_ownership_registry_branch(root, base_sha, head_sha, branch_match, diff_entries):
    digits = branch_match.group(1)
    req_id = f"REQ-{digits}"
    manifest_rel_path = f"docs/ownership/{req_id}.json"

    if not diff_entries:
        raise DiffValidationError(
            [
                f"ownership registry branch diff must modify {manifest_rel_path!r}, "
                f"found no changes"
            ]
        )

    errors = []
    for entry in diff_entries:
        for path in entry["paths"]:
            if normalize_path(path) != manifest_rel_path:
                errors.append(
                    f"ownership registry branch diff must only modify {manifest_rel_path!r}, "
                    f"found unrelated path: {path!r}"
                )
        if entry["status"][0] == "D":
            errors.append(
                f"ownership registry branch must not delete manifest {manifest_rel_path!r}"
            )
    if errors:
        raise DiffValidationError(errors)

    manifest_text, manifest = load_head_manifest(root, head_sha, manifest_rel_path)
    validate_head_manifest(root, base_sha, req_id, manifest_text, manifest)


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Validate that a PR diff between --base-sha and --head-sha stays within "
            "the base-approved ownership manifest's owner write_paths."
        )
    )
    parser.add_argument("--root", required=True, help="Git repository root")
    parser.add_argument("--base-sha", required=True, help="Base commit/revision of the diff")
    parser.add_argument("--head-sha", required=True, help="Head commit/revision of the diff")
    parser.add_argument("--branch", required=True, help="Branch name under review")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    root = Path(args.root)

    try:
        validate_git_repo(root)
        validate_revision(root, args.base_sha, "--base-sha")
        validate_revision(root, args.head_sha, "--head-sha")

        diff_entries = compute_diff(root, args.base_sha, args.head_sha)
        validate_no_unsafe_git_modes(diff_entries)

        registry_match = OWNERSHIP_REGISTRY_BRANCH_RE.match(args.branch or "")
        req_match = REQ_BRANCH_RE.match(args.branch or "")
        if registry_match:
            validate_ownership_registry_branch(
                root, args.base_sha, args.head_sha, registry_match, diff_entries
            )
        elif req_match:
            validate_req_branch(root, args.base_sha, args.head_sha, req_match, diff_entries)
        else:
            validate_governance_branch(diff_entries)
    except DiffValidationError as exc:
        for error in exc.errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
