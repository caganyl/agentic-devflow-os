#!/usr/bin/env python3
"""Validate and authorize task ownership manifests.

Standard library only. See docs/ownership/README.md for the manifest
contract this script enforces.
"""

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath

SUPPORTED_AGENTS = (
    "frontend-engineer",
    "backend-engineer",
    "database-engineer",
    "qa-automation",
    "ai-data-engineer",
)

ALLOWED_STATUSES = ("draft", "approved", "superseded", "closed")

REQ_ID_RE = re.compile(r"^REQ-[0-9]{3,}$")
BRANCH_RE = re.compile(r"^req-([0-9]+)-.+$")

FORBIDDEN_WRITE_PREFIXES = (
    ".claude/",
    "docs/ownership/",
    "docs/product/",
    "docs/architecture/",
    "docs/decisions/",
    "docs/release/",
    "docs/quality/security-reports/",
    "docs/ai/",
    "design/reviews/",
)

# Exact-path governance/enforcement files that must never be writable by an
# implementer manifest, checked against the normalized repository-relative
# path. This is an additional safety layer on top of
# FORBIDDEN_WRITE_PREFIXES, not a replacement for it: some of these paths
# already fall under a forbidden prefix above, but listing them explicitly
# protects them even if the prefix list changes later.
FORBIDDEN_WRITE_EXACT_PATHS = frozenset(
    {
        "PROJECT_CONSTITUTION.md",
        "CLAUDE.md",
        "AGENTS.md",
        ".claude/settings.json",
        ".claude/hooks/enforce-role-boundaries.sh",
        ".claude/hooks/protect-main.sh",
        ".claude/hooks/protect-sensitive-paths.sh",
        "scripts/validate_ownership_manifest.py",
        "docs/ownership/README.md",
        "docs/ownership/TEMPLATE.json",
        "docs/ownership/schema.json",
    }
)


class ManifestError(Exception):
    """Raised with all accumulated validation errors."""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("\n".join(self.errors))


def load_manifest(manifest_path):
    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError as exc:
        raise ManifestError([f"Manifest not found: {manifest_path}"]) from exc
    except json.JSONDecodeError as exc:
        raise ManifestError([f"Manifest is not valid JSON: {exc}"]) from exc


def is_relative_safe_path(raw_path):
    """True if raw_path is a relative, non-wildcard, non-escaping path."""
    if not isinstance(raw_path, str) or not raw_path.strip():
        return False
    if raw_path.startswith("/") or raw_path.startswith("~"):
        return False
    if any(ch in raw_path for ch in ("*", "?", "[", "]")):
        return False
    p = PurePosixPath(raw_path)
    if p.is_absolute():
        return False
    if ".." in p.parts:
        return False
    return True


def resolve_under_root(root, raw_path):
    """Return resolved absolute Path if raw_path stays under root, else None."""
    if not is_relative_safe_path(raw_path):
        return None
    root_resolved = root.resolve(strict=False)
    candidate = (root_resolved / raw_path).resolve(strict=False)
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        return None
    return candidate


def paths_overlap(path_a, path_b):
    pa = PurePosixPath(path_a)
    pb = PurePosixPath(path_b)
    if pa == pb:
        return True
    if pa in pb.parents:
        return True
    if pb in pa.parents:
        return True
    return False


def validate_manifest(manifest, manifest_path, root):
    errors = []

    schema_version = manifest.get("schema_version")
    if schema_version != 1:
        errors.append(
            f"schema_version must be 1, got: {schema_version!r}"
        )

    req_id = manifest.get("req_id")
    if not isinstance(req_id, str) or not REQ_ID_RE.match(req_id):
        errors.append(
            f"req_id must match 'REQ-' followed by at least 3 digits, got: {req_id!r}"
        )

    status = manifest.get("status")
    if status not in ALLOWED_STATUSES:
        errors.append(
            f"status must be one of {ALLOWED_STATUSES}, got: {status!r}"
        )

    approval = manifest.get("approval") or {}
    if status == "approved":
        approved_by = approval.get("approved_by")
        approved_at = approval.get("approved_at")
        if not approved_by:
            errors.append("approval.approved_by is required when status is 'approved'")
        if not approved_at:
            errors.append("approval.approved_at is required when status is 'approved'")

    references = manifest.get("references") or {}

    requirement = references.get("requirement")
    if not requirement:
        errors.append("references.requirement is required")
    else:
        resolved = resolve_under_root(root, requirement)
        if resolved is None:
            errors.append(f"references.requirement is not a safe repository-relative path: {requirement!r}")
        elif not resolved.is_file():
            errors.append(f"references.requirement does not point to an existing file: {requirement!r}")

    acceptance_criteria = references.get("acceptance_criteria")
    if not acceptance_criteria:
        errors.append("references.acceptance_criteria is required")
    else:
        resolved = resolve_under_root(root, acceptance_criteria)
        if resolved is None:
            errors.append(
                f"references.acceptance_criteria is not a safe repository-relative path: {acceptance_criteria!r}"
            )
        elif not resolved.is_file():
            errors.append(
                f"references.acceptance_criteria does not point to an existing file: {acceptance_criteria!r}"
            )

    contracts = references.get("contracts") or []
    contract_exception = references.get("contract_exception") or {}
    exception_reason = contract_exception.get("reason")
    exception_approved_by = contract_exception.get("approved_by")
    exception_approved_at = contract_exception.get("approved_at")
    has_exception = bool(exception_reason) and bool(exception_approved_by) and bool(exception_approved_at)

    if not contracts and not has_exception:
        errors.append(
            "references.contracts must contain at least one entry, or "
            "references.contract_exception must have non-empty reason, "
            "approved_by and approved_at"
        )

    for contract_path in contracts:
        resolved = resolve_under_root(root, contract_path)
        if resolved is None:
            errors.append(f"references.contracts entry is not a safe repository-relative path: {contract_path!r}")
        elif not resolved.is_file():
            errors.append(f"references.contracts entry does not point to an existing file: {contract_path!r}")

    adrs = references.get("adrs") or []
    for adr_path in adrs:
        resolved = resolve_under_root(root, adr_path)
        if resolved is None:
            errors.append(f"references.adrs entry is not a safe repository-relative path: {adr_path!r}")
        elif not resolved.is_file():
            errors.append(f"references.adrs entry does not point to an existing file: {adr_path!r}")

    owners = manifest.get("owners") or []
    if not owners:
        errors.append("owners must contain at least one entry")

    owner_paths_by_agent = []
    for index, owner in enumerate(owners):
        agent = owner.get("agent")
        if agent not in SUPPORTED_AGENTS:
            errors.append(
                f"owners[{index}].agent must be one of {SUPPORTED_AGENTS}, got: {agent!r}"
            )

        write_paths = owner.get("write_paths") or []
        if not write_paths:
            errors.append(f"owners[{index}] ({agent!r}) must declare at least one write_paths entry")

        valid_owner_paths = []
        for write_path in write_paths:
            if not is_relative_safe_path(write_path):
                errors.append(
                    f"owners[{index}] ({agent!r}) write_paths entry must be a relative, "
                    f"non-wildcard, non-escaping path: {write_path!r}"
                )
                continue

            normalized = PurePosixPath(write_path).as_posix()

            if normalized in FORBIDDEN_WRITE_EXACT_PATHS:
                errors.append(
                    f"owners[{index}] ({agent!r}) write_paths entry {write_path!r} targets a "
                    f"protected governance/enforcement file: {normalized!r}"
                )
                continue

            forbidden = next(
                (
                    prefix
                    for prefix in FORBIDDEN_WRITE_PREFIXES
                    if normalized == prefix.rstrip("/") or normalized.startswith(prefix)
                ),
                None,
            )
            if forbidden is not None:
                errors.append(
                    f"owners[{index}] ({agent!r}) write_paths entry {write_path!r} falls under "
                    f"a reserved documentation/evaluation path: {forbidden!r}"
                )
                continue

            valid_owner_paths.append(normalized)

        owner_paths_by_agent.append((index, agent, valid_owner_paths))

    for i in range(len(owner_paths_by_agent)):
        index_a, agent_a, paths_a = owner_paths_by_agent[i]
        for j in range(i + 1, len(owner_paths_by_agent)):
            index_b, agent_b, paths_b = owner_paths_by_agent[j]
            for path_a in paths_a:
                for path_b in paths_b:
                    if paths_overlap(path_a, path_b):
                        errors.append(
                            f"owners[{index_a}] ({agent_a!r}) write_paths entry {path_a!r} overlaps "
                            f"with owners[{index_b}] ({agent_b!r}) write_paths entry {path_b!r}"
                        )

    if isinstance(req_id, str) and REQ_ID_RE.match(req_id):
        expected_name = f"{req_id}.json"
        actual_name = Path(manifest_path).name
        if actual_name != expected_name:
            errors.append(
                f"manifest filename {actual_name!r} must match req_id: expected {expected_name!r}"
            )

    if errors:
        raise ManifestError(errors)


MANAGED_RUN_BRANCH_PREFIX = "devflow/run-"


def authorize(manifest, root, branch, authorize_agent, target, managed_run=False):
    """Authorize one implementer write against an approved manifest.

    managed_run=True is used for DevFlow managed runs (``launch``), whose
    branches live in the ``devflow/run-*`` namespace. The REQ binding then
    comes from the signed run state (``--req-id`` at create-run/launch), not
    from the branch name, so the ``req-<digits>-`` branch pattern check is
    replaced by a ``devflow/run-`` prefix check. Status, owner and
    write_paths checks are unchanged.
    """
    errors = []

    status = manifest.get("status")
    if status != "approved":
        errors.append(f"manifest status must be 'approved' to authorize writes, got: {status!r}")

    req_id = manifest.get("req_id") or ""
    req_digits = req_id[len("REQ-"):] if req_id.startswith("REQ-") else ""

    branch_match = BRANCH_RE.match(branch or "")
    if managed_run:
        if not (branch or "").startswith(MANAGED_RUN_BRANCH_PREFIX):
            errors.append(
                f"managed-run authorization requires a '{MANAGED_RUN_BRANCH_PREFIX}*' branch, got: {branch!r}"
            )
    elif not branch_match:
        errors.append(
            f"branch must match 'req-<digits>-<description>', got: {branch!r}"
        )
    elif branch_match.group(1) != req_digits:
        errors.append(
            f"branch req number {branch_match.group(1)!r} does not match manifest req_id {req_id!r}"
        )

    owners = manifest.get("owners") or []
    owner = next((o for o in owners if o.get("agent") == authorize_agent), None)
    if owner is None:
        errors.append(f"agent {authorize_agent!r} is not defined as an owner in this manifest")

    if owner is not None:
        target_resolved = resolve_under_root(root, target)
        if target_resolved is None:
            errors.append(f"target is not a safe repository-relative path: {target!r}")
        else:
            target_normalized = PurePosixPath(target).as_posix()
            write_paths = owner.get("write_paths") or []
            authorized = False
            for write_path in write_paths:
                if not is_relative_safe_path(write_path):
                    continue
                wp_normalized = PurePosixPath(write_path).as_posix()
                wp_path = PurePosixPath(wp_normalized)
                target_path = PurePosixPath(target_normalized)
                if target_path == wp_path or wp_path in target_path.parents:
                    authorized = True
                    break
            if not authorized:
                errors.append(
                    f"target {target!r} is not under any write_paths owned by {authorize_agent!r}"
                )

    if errors:
        raise ManifestError(errors)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Validate task ownership manifests and optionally authorize an agent write.",
    )
    parser.add_argument("--manifest", required=True, help="Path to the ownership manifest JSON file")
    parser.add_argument("--root", required=True, help="Repository root used to resolve relative references")
    parser.add_argument("--branch", help="Current branch name, required with --authorize-agent")
    parser.add_argument(
        "--managed-run",
        action="store_true",
        help="Branch is a DevFlow managed run branch (devflow/run-*) bound to this REQ via run state",
    )
    parser.add_argument(
        "--authorize-agent",
        help="Agent name requesting write authorization, required with --branch and --target",
    )
    parser.add_argument("--target", help="Target file path the agent wants to write, repository-relative")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    root = Path(args.root)
    manifest_path = args.manifest

    authorize_requested = any((args.branch, args.authorize_agent, args.target))
    if authorize_requested and not all((args.branch, args.authorize_agent, args.target)):
        print(
            "error: --branch, --authorize-agent and --target must all be provided together",
            file=sys.stderr,
        )
        return 2

    try:
        manifest = load_manifest(manifest_path)
        validate_manifest(manifest, manifest_path, root)
        if authorize_requested:
            authorize(manifest, root, args.branch, args.authorize_agent, args.target, managed_run=args.managed_run)
    except ManifestError as exc:
        for error in exc.errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
