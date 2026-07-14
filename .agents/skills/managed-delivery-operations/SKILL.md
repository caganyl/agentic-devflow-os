---
name: managed-delivery-operations
description: Enforces the managed Git worktree and run boundaries for Codex delivery operations while deferring runtime launch automation.
---

# Managed Delivery Operations

Use this skill before a real delivery run or any planned Git operation.

## Boundary checks

1. Verify that `git rev-parse --show-toplevel` equals the intended target repository root.
2. Verify the current branch is the run-assigned feature branch, not a protected branch.
3. Require the real delivery run to be inside a DevFlow-managed worktree. Do not create, switch, remove, or navigate to another worktree from the run.
4. Establish and record these run boundary variables before writes:
   - `DEVFLOW_RUN_WORKTREE`: the only writable repository root for the run.
   - `DEVFLOW_RUN_BRANCH`: the only permitted branch for the run.
   - `DEVFLOW_OPERATIONS_SCRIPT`: the authoritative operations-gate script path when supplied by the runtime.
5. Confirm the current root and branch match those variables. Fail closed on missing variables or mismatch.

The Codex sandbox, managed-worktree isolation, repository hook policy, and DevFlow operations gate are complementary controls; none replaces the others.

## Operations gates

Commit, merge, push, deployment, destructive operations, and external side effects require explicit human approval. Never treat a dry run, plan, agent summary, or MCP result as evidence that an operation occurred.

Phase 1A provides declarative instructions only. It does not claim that a Codex operations launcher exists. Runtime launch automation is deferred to Phase 1C.
