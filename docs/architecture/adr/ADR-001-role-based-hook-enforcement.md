# ADR-001: Role-Based Hook Enforcement

- **Status:** Accepted
- **Date:** 2026-06-25
- **Acceptance Date:** 2026-06-25
- **Owner:** Human maintainer
- **Related controls:** PROJECT_CONSTITUTION.md, CLAUDE.md, AGENT_CAPABILITY_MATRIX.md

## Context

Custom agent frontmatter ve `CLAUDE.md` role sınırlarını tarif eder, ancak
tek başına teknik olarak zorlayıcı değildir. Bazı roller yalnızca belirli
dokümantasyon veya evaluation alanlarına yazabilmeli; Delivery Lead ise
planlama dışında dosya veya shell değişikliği yapmamalıdır.

Claude Code PreToolUse hooks, araç çağrısı çalışmadan önce `agent_type`,
tool adı ve araç girdisini inceleyerek çağrıyı engelleyebilir.

## Decision

Project-level `PreToolUse` hook zincirine merkezi
`.claude/hooks/enforce-role-boundaries.sh` eklenecektir.

Hook aşağıdaki ilk kapsamı teknik olarak uygular:

- Delivery Lead için dosya değişikliği ve Bash yasağı.
- Product Analyst, Solution Architect, Contract Broker, Security Red Team,
  Integration/Release, EvalOps Reviewer ve Design Reviewer için role bazlı
  dosya yolu allowlist'i.
- Security Red Team için yalnızca daraltılmış, non-mutating inspection/scanning
  Bash komutları.
- Tüm custom agent'lar için Git mutation, destructive filesystem,
  dependency-install, merge, deployment, production migration, permission
  değişikliği ve redirected-write içeren Bash komutlarının engellenmesi.

Frontend, Backend, Database, QA Automation ve AI/Data Engineer için
task-level ownership manifest standardı henüz bulunmadığından bu ADR onların
uygulama kodu path'lerini sert biçimde kilitlemez. Bu roller için ownership
enforcement sonraki ADR ile eklenecektir.

## Alternatives Considered

1. **Yalnızca agent prompt'larına güvenmek**
   - Reddedildi. Prompt kuralları yönlendiricidir; teknik enforcement değildir.

2. **Tüm agent'larda Bash'i tamamen kapatmak**
   - Reddedildi. EvalOps, QA, Integration ve implementer rollerinin kontrollü
     test/evidence toplama ihtiyaçları vardır.

3. **İlk aşamada tüm uygulama klasörlerine path allowlist koymak**
   - Ertelendi. Task-level ownership manifest olmadan gerçek feature
     geliştirmesini yanlışlıkla bloke etme riski yüksektir.

## Consequences

- Documentation ve review rollerinin dosya alanları teknik olarak ayrılır.
- Hatalı role/path kullanımı erken aşamada engellenir.
- Hook'lar proje kurallarını güçlendirir fakat insanın normal terminal
  yetkisini veya kötü niyetli bir repo sahibini kısıtlayan bir güvenlik sınırı
  değildir.
- Bash kontrolü best-effort'tür; uygulama ownership enforcement için sonraki
  aşamada task manifest ve CI kontrolleri eklenecektir.

## Evidence

- Claude Code Hooks Reference
- Claude Code Settings and Permissions Reference
- Mevcut Project Constitution, CLAUDE.md ve Agent Capability Matrix

## Implementation Impact

- `.claude/settings.json` içine Edit, Write ve Bash çağrıları için merkezi
  role-boundary hook eklenir.
- Hook dosyaları Claude tarafından değil, insan maintainer tarafından
  değiştirilir.
- Hook testleri gerçek tool çağrısından önce manuel JSON probe'ları ve
  smoke testlerle doğrulanır.

## Acceptance Evidence

- PR #4 ile role-based hook enforcement merge edildi.
- Merkezi `.claude/hooks/enforce-role-boundaries.sh` eklendi.
- Role path sınırları, Bash sınırları ve planning-only Delivery Lead
  davranışı test edildi.
- İnsan maintainer, hook ve `.claude/settings.json` gibi governance
  dosyaları için son yetki sahibi olmaya devam eder; bu ADR'nin kabulü bu
  sınırı değiştirmez.

## Approval

- **Required approver:** Human maintainer
- **Approval status:** Accepted
- **Approval evidence:** PR #4 reviewed and merged to main (2026-06-25)
