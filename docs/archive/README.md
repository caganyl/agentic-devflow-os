# Arşiv

Bu klasördeki belgeler **güncel gerçek değildir**. Tarihsel bağlam için
saklanır; ajanlara context olarak verilmez ve kural kaynağı sayılmaz.
Klasör yapısı belgelerin eski konumunu korur (`architecture/adr/` →
eskiden `docs/architecture/adr/` vb.).

## MCP audit zinciri (REQ-001…003)

Gerçek MCP bağlantısı kurmayan, simüle dispatch kullanan deneysel bir MCP
denetim altyapısı için yazılmış belgeler. Yerini
[ADR-009](../architecture/adr/ADR-009-mcp-policy-simplified.md) aldı
(Claude Code izin kuralları + isteğe bağlı `mcp__*` PreToolUse hook'u).

| Belge | Durum |
|---|---|
| `architecture/adr/ADR-005-…`, `ADR-006-…` | Superseded (ADR-009) |
| `architecture/adr/ADR-007-…` | Withdrawn |
| `decisions/MCP_AGENT_CAPABILITY_MATRIX.md`, `decisions/MCP_AUDIT_EVENT_CONTRACT.md` | Arşiv |
| `quality/security-reports/SEC-ADR-005-MCP-CONNECTION-PRECONDITIONS.md` | Arşiv |
| `product/requirements/REQ-001…003`, `product/acceptance-criteria/AC-REQ-001…003` | Tamamlanmış / arşiv |
| `handoffs/REQ-001.md`, `handoffs/REQ-002.md` | Arşiv |

Bu belgelerin tarif ettiği kod — `src/mcp_audit_runtime/` ile
`tests/mcp_audit_runtime/` ve `tests/mcp_hook_lifecycle/` — repodan
kaldırıldı; son hâlleri git geçmişinde durur
(`git log --diff-filter=D -- src/mcp_audit_runtime`).

`docs/ownership/REQ-001.json` ve `REQ-003.json` manifestleri yerinde
bırakıldı (authority manifesti yalnızca `ownership-REQ-NNN-*` registry
branch'inde değiştirilebilir); referans verdikleri dosyalar artık bu
klasördedir, bu yüzden validator onları geçersiz sayar ve bu REQ'ler için
implementer yazımı açılmaz. Emekliye ayırmak bir insan registry PR'ıdır.

## Birleştirilen belgeler

| Eski belge | Yeni yer |
|---|---|
| `SYSTEM_OVERVIEW.md` | [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) |
| `decisions/DEVFLOW_AUTONOMOUS_DELIVERY_MODEL.md` | [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) |
| `decisions/DEVFLOW_TARGET_PROJECT_RUNTIME.md` | [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) |
| `decisions/DEVFLOW_NATIVE_TEAM_RUNTIME_AND_SAFETY_ENVELOPE.md` | [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) |
| `ownership/REGISTRY_BRANCH_RUNBOOK.md` | [`docs/ownership/README.md`](../ownership/README.md) |
| `operations/REQ_LIFECYCLE_RUNBOOK.md` | [`docs/ownership/README.md`](../ownership/README.md) |
| `operations/HUMAN_MERGE_CHECKLIST.md` | [`docs/ownership/README.md`](../ownership/README.md) |

Bu eski belgeler birbirleriyle çelişiyordu (plugin'de hook'lar, kurulum
yöntemi, `.devflow/` yapısı, `git commit` yetkisi); güncel hâli yalnızca
yeni yerlerindedir.
