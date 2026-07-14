---
name: visual-design-review
description: Performs a read-only UI review against acceptance criteria, changed-file scope, viewport coverage, interaction states, and accessibility.
---

# Visual Design Review

Review only when acceptance criteria and the changed-file scope are defined. If either is missing, report the gap and do not approve.

## Review scope

- Inspect the current UI diff and affected routes or components without modifying repository files.
- Check visual hierarchy, typography, spacing, design-system consistency, and interaction feedback.
- Cover representative mobile, tablet, and desktop viewports relevant to the product.
- Review loading, empty, error, success, and disabled states where relevant.
- Verify keyboard navigation, visible focus, labels and semantics, contrast, non-color cues, and accessible error feedback.
- Tie each finding to an acceptance criterion, file, component, state, or viewport.

## Findings

Separate blocking defects from non-blocking recommendations. For each finding record severity, affected scope, evidence, user impact, and a concise remediation. The reviewer produces findings only and must not edit repository files. Visual approval is not QA evidence or implementation evidence.
