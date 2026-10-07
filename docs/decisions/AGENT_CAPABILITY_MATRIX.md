# Agent Capability Matrix

Bu dosya, Agentic DevFlow OS içindeki rollerin hangi tür değişiklikleri yapabileceğini ve bu sınırların `.claude/hooks/enforce-role-boundaries.sh` tarafından runtime'da ve `scripts/validate_ownership_diff.py` tarafından CI merge-time'da ne ölçüde teknik olarak zorlandığını tanımlar.

| Agent | Prompt sınırı | Runtime enforcement | CI merge gate | Yazma alanı | Bash | Human approval boundary |
|---|---|---|---|---|---|---|
| Delivery Lead | Planlama-only | Hook: tüm `Edit`/`Write` ve `Bash` deny | Governance branch path sınırı (agent kimliği değil path denetlenir) | Yok | Hayır | Plan, kod veya komut üretemez |
| Product Analyst | Yalnızca product doküman alanı | Hook: path allowlist (`docs/product`, `docs/decisions`); Bash deny | Governance branch path sınırı | `docs/product/**`, `docs/decisions/**` | Hayır | Requirement onayı insanda |
| Solution Architect | Yalnızca architecture doküman alanı | Hook: path allowlist (`docs/architecture`, `docs/decisions`); ADR loop breaker (Accepted ADR dondurulur, 2 review turundan sonra revizyon yok, ~12.000 karakter bütçe, `reviews/` yazılamaz); Bash deny | Governance branch path sınırı | `docs/architecture/**`, `docs/decisions/**` | Hayır | ADR onayı insanda |
| ADR Reviewer | Review-only, tek turda VERDICT | Hook: path allowlist (`docs/architecture/adr/reviews`); dosya adı `ADR-NNN-review-<tur>.md`, VERDICT satırı zorunlu, en fazla 2 tur, review dosyaları değiştirilemez; Bash deny | Governance branch path sınırı | `docs/architecture/adr/reviews/**` | Hayır | İkinci turdan sonra karar insanda |
| Contract Broker | Yalnızca contract alanı | Hook: path allowlist (`docs/contracts`); Bash deny | Governance branch path sınırı | `docs/contracts/**` | Hayır | Contract onayı insanda |
| Frontend Engineer | REQ-ID + approved manifest gerektirir | Hook: `--authorize-agent` ile branch + approved manifest + owner + `write_paths` kontrolü (fail-closed); Bash mutation/deploy/migration blok listesi | CI: base-approved manifestteki owner `write_paths` dışında diff merge olamaz | Manifestte tanımlı `write_paths` | Sınırlı (mutation/deploy/migration komutları blok) | main merge insanda |
| Backend Engineer | REQ-ID + approved manifest gerektirir | Aynı (yukarıdaki implementer enforcement) | Aynı (CI: base-approved manifest owner `write_paths` kontrolü) | Manifestte tanımlı `write_paths` | Sınırlı | main merge insanda |
| Database Engineer | REQ-ID + approved manifest gerektirir | Aynı (yukarıdaki implementer enforcement) | Aynı (CI: base-approved manifest owner `write_paths` kontrolü) | Manifestte tanımlı `write_paths` | Sınırlı | Production migration insanda |
| QA Automation | REQ-ID + approved manifest gerektirir | Aynı (yukarıdaki implementer enforcement) | Aynı (CI: base-approved manifest owner `write_paths` kontrolü) | Manifestte tanımlı `write_paths` (tipik: `tests/**`) | Sınırlı | main merge insanda |
| AI/Data Engineer | REQ-ID + approved manifest gerektirir | Aynı (yukarıdaki implementer enforcement) | Aynı (CI: base-approved manifest owner `write_paths` kontrolü) | Manifestte tanımlı `write_paths` | Sınırlı | main merge insanda |
| Security Red Team | Rapor-only | Hook: path allowlist (`docs/quality/security-reports`); Bash yalnızca dar non-mutating inspection komutları | Governance branch path sınırı | `docs/quality/security-reports/**` | Dar, non-mutating inspection izni | Fix implementer'da, onay insanda |
| Design Reviewer | Rapor-only | Hook: path allowlist (`design/reviews`, `docs/quality/accessibility`); Bash deny | Governance branch path sınırı | `design/reviews/**`, `docs/quality/accessibility/**` | Hayır | UX kararı insanda |
| EvalOps Reviewer | Rapor/eval-only | Hook: path allowlist (`evals/**`, `docs/ai/**`); Bash global mutation/deploy/migration bloklarıyla sınırlı | Governance branch path sınırı | `evals/**`, `docs/ai/**` | Sınırlı (non-production eval/test; mutating Bash blok) | Release kalite önerisi insanda |
| Integration / Release | Release/handoff-only | Hook: path allowlist (`docs/release`, `docs/handoffs`); Bash global mutation/deploy/migration bloklarıyla sınırlı | Governance branch path sınırı | `docs/release/**`, `docs/handoffs/**` | Sınırlı (read/test; mutating Bash blok) | Main merge ve deploy insanda |
| Governance Operations Author | Runbook/checklist/template-only | Hook: dar path allowlist; Bash deny | Governance branch path sınırı | `docs/operations/**`, `docs/templates/**`, `docs/ownership/README.md`, `docs/ownership/REGISTRY_BRANCH_RUNBOOK.md` | Hayır | Prosedür ve statik rehber onayı insanda; authority manifesti değiştiremez |

## Runtime Enforcement Notları

- Implementer agent satırlarındaki ("Aynı" yazan) enforcement,
  `docs/ownership/REQ-XXX.json` manifestini kullanır: branch
  `req-XXX-kisa-aciklama` desenine uymalı (veya `launch --req-id` ile REQ'e
  bağlanmış aktif managed run branch'i `devflow/run-*` olmalı; REQ bağı
  imzalı run state'ten okunur), manifest `approved` durumda
  olmalı, çağrıyı yapan agent manifestte owner olarak tanımlı olmalı ve
  hedef path o agent'ın `write_paths` alanı altında olmalı. Bkz.
  `docs/architecture/adr/ADR-002-task-ownership-manifest.md` (sözleşme) ve
  `docs/architecture/adr/ADR-003-ownership-runtime-enforcement.md`
  (runtime bağlama).
- Bu runtime hook, yalnızca Claude'un `Edit`/`Write`/`Bash` araç çağrılarını
  kontrol eder. Bash üzerinden yapılan dosya yazımını veya normal
  terminalden yapılan manuel değişiklikleri tam olarak kapsamaz; bu
  boşluğu CI merge gate kapatır.

## CI Merge Gate Notları

- `scripts/validate_ownership_diff.py`, bir PR'ın `--base-sha` ve
  `--head-sha` arasındaki tam diff'ini merge-time'da denetler. Bkz.
  `docs/architecture/adr/ADR-004-ownership-ci-diff-enforcement.md`.
- **CI agent identity doğrulamaz; yalnızca path authority doğrular.**
  Runtime hook agent kimliğini ve anlık `Edit`/`Write` çağrısını denetler.
  CI ise implementation diff'inin yetkili path alanlarında kalıp kalmadığını
  doğrular.
- `req-XXX-kisa-aciklama` implementation branch'lerinde authority yalnızca
  base commit içindeki approved `docs/ownership/REQ-XXX.json` manifestidir.
  PR head'indeki authority manifest yetki kaynağı olarak kullanılmaz ve
  implementation branch içindeki authority manifest diff'i reddedilir.
- Generic governance/control-plane branch'ler yalnızca `.claude/`,
  `.github/`, `docs/`, `scripts/`, `tests/`, `design/`, `evals/` önekli
  path'lerde veya izinli kök dosyalarda değişiklik yapabilir. Application
  path değişiklikleri reddedilir.
- **Generic governance branch authority manifest dosyalarını**
  (`docs/ownership/REQ-<en az 3 rakam>.json`) değiştiremez. Buna karşılık
  statik ownership dokümanları (`docs/ownership/README.md`,
  `TEMPLATE.json`, `schema.json`) authority kaynağı değildir; generic
  governance branch'te insan review boundary'si altında güncellenebilir.
- `ownership-REQ-XXX-kisa-aciklama` registry branch'leri yalnızca kendi
  exact `docs/ownership/REQ-XXX.json` manifestini değiştirebilir. Başka
  hiçbir dosya değişemez ve manifest silinemez.
- Symlink (`120000`) ve gitlink/submodule (`160000`) diff'leri branch
  sınıfından bağımsız olarak fail-closed reddedilir.
- `Ownership Governance` GitHub Actions workflow'u aktiftir. Draft smoke
  PR #9 üzerinde hem `PR Quality` hem `Ownership Diff Gate` başarılı
  çalışmıştır. Workflow token'ı repository düzeyinde read-only olarak
  doğrulanmıştır.
- Mevcut private repository planında branch protection ve rulesets
  zorlaması kullanılamamaktadır. Bu nedenle required status check teknik
  olarak enforce edilmez; geçiş döneminde insan merge boundary zorunludur:
  `Ownership Diff Gate` başarılı olmalı, `PR Quality` başarılı olmalı,
  insan diff review tamamlanmalı ve merge insan maintainer tarafından
  yapılmalıdır.
- `.claude`, `.github` ve `scripts` değişiklikleri için insan review
  boundary'si sürer. GitHub Pro veya uygun plan erişimi sağlandığında
  CODEOWNERS/branch protection ile `Ownership Diff Gate` required check
  olarak bağlanmalıdır.

## Evrensel Kurallar

- Hiçbir agent `main` branch'e doğrudan yazamaz.
- Hiçbir agent kendi implementasyonunu tek başına approve edemez.
- Security Red Team bulguyu üretir; fix ilgili implementer tarafından yapılır.
- Integration / Release agent merge yapmaz; release-readiness kanıtını ve handoff'ı hazırlar. Nihai merge insan onayındadır.
- Hiçbir agent main merge, production deploy, production migration veya secret işlemi yapamaz; bunlar yalnızca insan onayıyla yapılır.
- Her non-trivial değişiklik REQ-ID, test kanıtı ve handoff ile bağlanır.
