# ADR-009 — Basitleştirilmiş MCP Politikası

## Status
Proposed

<!-- Accepted yalnızca insan maintainer tarafından yazılır. -->

## Context

ADR-005, ADR-006 ve ADR-007 (REQ-001…003) MCP araç erişimi için ayrı bir
kontrol düzlemi, kanonik audit event contract'ı ve `src/mcp_audit_runtime`
adlı yerel bir runtime tasarladı. Runtime hiçbir gerçek MCP bağlantısı
kurmadı (simüle dispatch), bakım ve token maliyeti yüksekti ve tasarım
döngüsünü besledi. Runtime ve testleri kaldırıldı; belgeler
`docs/archive/` altındadır. Claude Code'un yerleşik izin kuralları ve
PreToolUse hook'ları aynı amacı ek kod olmadan karşılar.

## Decision

MCP araç kullanımı Claude Code'un kendi mekanizmalarıyla sınırlanır:

1. İzin kuralları: `mcp__<server>__<tool>` adlarıyla `permissions`
   `allow` / `ask` / `deny` listeleri; varsayılan `ask`.
2. İsteğe bağlı bir PreToolUse hook'u `mcp__.*` araç adlarını bir allowlist'e
   karşı kontrol eder; governed ajanlar için listede olmayan araç reddedilir
   (fail-closed).
3. İsteğe bağlı JSONL log: yalnızca zaman, ajan tipi, araç adı ve karar;
   argüman, çıktı veya içerik yazılmaz. Konum `.devflow/logs/` (gitignore).
4. Gerçek bir MCP sunucusu bağlamak insan onayıdır; plugin MCP sunucusu
   tanımlamaz. MCP çıktısı güvenilmeyen bağlamdır, teslimat kanıtı değildir.

## Alternatives Considered

- ADR-007 runtime'ını sürdürmek: gerçek bağlantı olmadan bakım maliyeti
  ve kanıt değeri düşük; reddedildi.
- MCP'yi tamamen yasaklamak: NotebookLM/Playwright gibi okuma araçlarının
  insan onaylı kullanımını engeller; reddedildi.

## Consequences

- Özel audit şeması ve SQLite sink yok; denetim izi Claude Code izin
  kayıtları ve isteğe bağlı JSONL log ile sınırlıdır.
- ADR-005 ve ADR-006 Superseded, ADR-007 Withdrawn.

## Implementation Impact

Bu ADR kod değiştirmez. Hook ve allowlist ayrı bir REQ ile, hook sahipliği
alanında (`.claude/hooks/`, `hooks/hooks.json`) uygulanır.

## Approval

İnsan onayı: bu ADR'nin `Accepted` yapılması, allowlist içeriği ve herhangi
bir gerçek MCP bağlantısı.
