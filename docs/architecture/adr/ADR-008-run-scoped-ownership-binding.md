# ADR-008: Run-Scoped Ownership Binding for Work-Product Evidence

- **Status:** Proposed
- **Date:** 2026-07-26
- **Owner:** Human maintainer (acceptance pending)
- **Related controls:** AGENT_CAPABILITY_MATRIX.md,
  ADR-002-task-ownership-manifest.md,
  ADR-003-ownership-runtime-enforcement.md,
  ADR-004-ownership-ci-diff-enforcement.md

## Context

DevFlow contains two governance tracks that, until now, did not touch each
other:

1. **Ownership track** — `req-XXX-*` branches, human-approved
   `docs/ownership/REQ-XXX.json` manifests, the runtime role hook
   (ADR-003) and the CI diff gate (ADR-004). This binds each implementer
   role to a set of `write_paths`.
2. **Delivery-run track** — `devflow/run-NNN` branches, `.devflow/` state,
   the evidence gates and the `devflow_operations.py` CLI. Tasks carry an
   `assigned_role`, but nothing bound that role to a path.

The delivery-run task graph assigns both the backend and the frontend
implementation task the same coarse output area (`output_path: "src/"`). The
work-product evidence gate therefore could accept `src/api.py` as the evidence
for *either* role — a single file satisfying two roles' acceptance decisions,
and no way to catch "the frontend task recorded a backend file." The coarse
`IMPLEMENTATION_EVIDENCE_PREFIXES` cannot express role→path ownership; only the
manifest can.

The two tracks were deliberately kept separate (different branch namespaces,
different trust boundaries). Fully coupling them — e.g. requiring every run to
be a `req-XXX` branch with an approved manifest — would be a larger, breaking
change and is out of scope here.

## Decision

Add an **opt-in, backward-compatible** binding inside the delivery-run track:

- `create-run` (and `launch`) accept an optional `--req-id REQ-NNN`, stored as
  `req_id` in run state. Runs without it are unchanged.
- `record-work-product-evidence` gains one additional check
  (`authorize_work_product_ownership`): when the run declared a `req_id` **and**
  an **approved** `docs/ownership/<REQ-ID>.json` manifest lists the task's
  `assigned_role` as an owner, the evidence path must fall under that owner's
  `write_paths`. Otherwise the evidence is denied (exit 19).
- The check reuses the manifest's role→`write_paths` authority — the same data
  ADR-003 and ADR-004 enforce — so a run that opts in gets the file→role
  enforcement the coarse prefix cannot express.

### Deliberate boundaries

- **No req-branch check.** The manifest's `authorize()` requires a `req-XXX-*`
  branch; run branches are `devflow/run-*`, a separate namespace. This binding
  reuses only the *path-authorization* core (approved + owner + `write_paths`),
  not the branch coupling.
- **Inert by default.** No `--req-id`, no manifest, an unapproved (draft)
  manifest, or a role the manifest does not list all leave the existing coarse
  checks untouched. The run system never invents a restriction the ownership
  layer did not declare.
- **Self-contained.** The path-authorization logic is inlined in
  `devflow_operations.py` (which ships in the plugin); it does not import
  `validate_ownership_manifest.py` (which does not ship), so the deployed
  plugin needs no new files.

## Consequences

- A run that opts in cannot record `apps/web/**` as backend-engineer work
  product, or `apps/api/**` as frontend-engineer work product — the headline
  gap this ADR closes. Verified end-to-end in
  `tests/test_work_product_ownership_binding.py`.
- Existing runs and tests are unaffected (opt-in). No behavior changes without
  an explicit `--req-id` plus an approved manifest.
- This is a *narrow* bridge, not a merge of the two tracks. It does **not**
  make delivery runs subject to the CI diff gate, nor does it deploy the
  ownership runtime hook to target projects (still framework-only, per
  AGENT_CAPABILITY_MATRIX.md). Those remain open questions for a future ADR.

## Alternatives considered

- **Full coupling** (runs must be `req-XXX` branches with approved manifests):
  rejected as breaking and beyond the intended scope.
- **Per-role task paths in the run graph** (make the graph declare
  `apps/web` vs `apps/api`): rejected because the run system does not know an
  arbitrary target project's layout; only the manifest does.
- **Shipping the ownership validators + CI into target projects:** a broader
  deployment decision, tracked separately.
