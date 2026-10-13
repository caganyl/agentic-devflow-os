# Architecture Decision Records

Şablon: `.claude/templates/adr.md`. Dosya adı `ADR-NNN-kisa-ad.md`; alt
klasör açılmaz (yalnızca `reviews/`). ADR yalnızca eşik sağlanırsa yazılır
(bkz. `.claude/agents/solution-architect.md`); review kayıtları
`reviews/` altındadır.

## İndeks

| ADR | Konu | Status |
|---|---|---|
| [ADR-001](ADR-001-role-based-hook-enforcement.md) | Rol bazlı hook enforcement | Accepted |
| [ADR-002](ADR-002-task-ownership-manifest.md) | Task ownership manifesti | Accepted |
| [ADR-003](ADR-003-ownership-runtime-enforcement.md) | Ownership runtime enforcement | Accepted |
| [ADR-004](ADR-004-ownership-ci-diff-enforcement.md) | Ownership CI diff gate | Accepted |
| ADR-005 | MCP tooling control plane | Superseded (ADR-009) — [arşiv](../../archive/architecture/adr/ADR-005-mcp-tooling-control-plane.md) |
| ADR-006 | MCP audit logging ve runtime enforcement | Superseded (ADR-009) — [arşiv](../../archive/architecture/adr/ADR-006-mcp-audit-logging-and-runtime-enforcement.md) |
| ADR-007 | Kanonik MCP audit runtime | Withdrawn — [arşiv](../../archive/architecture/adr/ADR-007-canonical-mcp-audit-runtime-architecture.md) |
| [ADR-008](ADR-008-run-scoped-ownership-binding.md) | Run'a bağlı ownership binding | Accepted |
| [ADR-009](ADR-009-mcp-policy-simplified.md) | Basitleştirilmiş MCP politikası | Proposed |
