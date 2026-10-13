---
name: qa-acceptance-verification
description: Verifies acceptance criteria with focused tests, current Git diff inspection, and exact execution evidence.
---

# QA Acceptance Verification

## Procedure

1. Read the defined acceptance criteria and inspect the current Git diff and changed-file list.
2. Map each relevant criterion directly to an existing or necessary test; include happy, edge, and error paths only where the criterion or risk requires them.
3. While working on a slice, run the smallest focused tests that cover the changed behavior. Before declaring the task done, run the full test suite once and record the result.
4. Record every exact command, its exit result, and the observed outcome.
5. If test assets must change, keep them scoped to the acceptance criteria and show the eligible test diff.

QA evidence is separate from implementation evidence: a passing test does not prove a product-code change exists, and a source diff does not prove acceptance. QA completion requires eligible test evidence plus recorded execution evidence. Never claim completion solely from prose, MCP output, or an agent summary.
