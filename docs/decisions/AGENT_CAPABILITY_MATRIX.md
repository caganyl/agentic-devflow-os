# Agent Capability Matrix

Bu dosya, Agentic DevFlow OS içindeki rollerin hangi tür değişiklikleri yapabileceğini ve bu sınırların `.claude/hooks/enforce-role-boundaries.sh` tarafından runtime'da ne ölçüde teknik olarak zorlandığını tanımlar.

| Agent | Prompt sınırı | Runtime enforcement | Yazma alanı | Bash | Human approval boundary |
|---|---|---|---|---|---|
| Delivery Lead | Planlama-only | Hook: tüm `Edit`/`Write` ve `Bash` deny | Yok | Hayır | Plan, kod veya komut üretemez |
| Product Analyst | Yalnızca product doküman alanı | Hook: path allowlist (`docs/product`, `docs/decisions`); Bash deny | `docs/product/**`, `docs/decisions/**` | Hayır | Requirement onayı insanda |
| Solution Architect | Yalnızca architecture doküman alanı | Hook: path allowlist (`docs/architecture`, `docs/decisions`); Bash deny | `docs/architecture/**`, `docs/decisions/**` | Hayır | ADR onayı insanda |
| Contract Broker | Yalnızca contract alanı | Hook: path allowlist (`docs/contracts`); Bash deny | `docs/contracts/**` | Hayır | Contract onayı insanda |
| Frontend Engineer | REQ-ID + approved manifest gerektirir | Hook: `--authorize-agent` ile branch + approved manifest + owner + `write_paths` kontrolü (fail-closed); Bash mutation/deploy/migration blok listesi | Manifestte tanımlı `write_paths` | Sınırlı (mutation/deploy/migration komutları blok) | main merge insanda |
| Backend Engineer | REQ-ID + approved manifest gerektirir | Aynı (yukarıdaki implementer enforcement) | Manifestte tanımlı `write_paths` | Sınırlı | main merge insanda |
| Database Engineer | REQ-ID + approved manifest gerektirir | Aynı (yukarıdaki implementer enforcement) | Manifestte tanımlı `write_paths` | Sınırlı | Production migration insanda |
| QA Automation | REQ-ID + approved manifest gerektirir | Aynı (yukarıdaki implementer enforcement) | Manifestte tanımlı `write_paths` (tipik: `tests/**`) | Sınırlı | main merge insanda |
| AI/Data Engineer | REQ-ID + approved manifest gerektirir | Aynı (yukarıdaki implementer enforcement) | Manifestte tanımlı `write_paths` | Sınırlı | main merge insanda |
| Security Red Team | Rapor-only | Hook: path allowlist (`docs/quality/security-reports`); Bash yalnızca dar non-mutating inspection komutları | `docs/quality/security-reports/**` | Dar, non-mutating inspection izni | Fix implementer'da, onay insanda |
| Design Reviewer | Rapor-only | Hook: path allowlist (`design/reviews`, `docs/quality/accessibility`); Bash deny | `design/reviews/**`, `docs/quality/accessibility/**` | Hayır | UX kararı insanda |
| EvalOps Reviewer | Rapor/eval-only | Hook: path allowlist (`evals/**`, `docs/ai/**`); Bash global mutation/deploy/migration bloklarıyla sınırlı | `evals/**`, `docs/ai/**` | Sınırlı (non-production eval/test; mutating Bash blok) | Release kalite önerisi insanda |
| Integration / Release | Release/handoff-only | Hook: path allowlist (`docs/release`, `docs/handoffs`); Bash global mutation/deploy/migration bloklarıyla sınırlı | `docs/release/**`, `docs/handoffs/**` | Sınırlı (read/test; mutating Bash blok) | Main merge ve deploy insanda |

## Runtime Enforcement Notları

- Implementer agent satırlarındaki ("Aynı" yazan) enforcement,
  `docs/ownership/REQ-XXX.json` manifestini kullanır: branch
  `req-XXX-kisa-aciklama` desenine uymalı, manifest `approved` durumda
  olmalı, çağrıyı yapan agent manifestte owner olarak tanımlı olmalı ve
  hedef path o agent'ın `write_paths` alanı altında olmalı. Bkz.
  `docs/architecture/adr/ADR-002-task-ownership-manifest.md` (sözleşme) ve
  `docs/architecture/adr/ADR-003-ownership-runtime-enforcement.md`
  (runtime bağlama).
- Bu runtime hook, yalnızca Claude'un `Edit`/`Write`/`Bash` araç çağrılarını
  kontrol eder. Bash üzerinden yapılan dosya yazımını veya normal
  terminalden yapılan manuel değişiklikleri tam olarak kapsamaz; bu
  boşluğu kapatacak merge-time CI diff enforcement sıradaki katmandır ve
  henüz eklenmemiştir.

## Evrensel Kurallar

- Hiçbir agent `main` branch'e doğrudan yazamaz.
- Hiçbir agent kendi implementasyonunu tek başına approve edemez.
- Security Red Team bulguyu üretir; fix ilgili implementer tarafından yapılır.
- Integration / Release agent merge yapmaz; release-readiness kanıtını ve handoff'ı hazırlar. Nihai merge insan onayındadır.
- Hiçbir agent main merge, production deploy, production migration veya secret işlemi yapamaz; bunlar yalnızca insan onayıyla yapılır.
- Her non-trivial değişiklik REQ-ID, test kanıtı ve handoff ile bağlanır.
