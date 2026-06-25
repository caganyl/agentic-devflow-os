# Agent Capability Matrix

Bu dosya, Agentic DevFlow OS içindeki rollerin hangi tür değişiklikleri yapabileceğini ve bu sınırların `.claude/hooks/enforce-role-boundaries.sh` tarafından runtime'da ve `scripts/validate_ownership_diff.py` tarafından CI merge-time'da ne ölçüde teknik olarak zorlandığını tanımlar.

| Agent | Prompt sınırı | Runtime enforcement | CI merge gate | Yazma alanı | Bash | Human approval boundary |
|---|---|---|---|---|---|---|
| Delivery Lead | Planlama-only | Hook: tüm `Edit`/`Write` ve `Bash` deny | Governance branch path sınırı (agent kimliği değil path denetlenir) | Yok | Hayır | Plan, kod veya komut üretemez |
| Product Analyst | Yalnızca product doküman alanı | Hook: path allowlist (`docs/product`, `docs/decisions`); Bash deny | Governance branch path sınırı | `docs/product/**`, `docs/decisions/**` | Hayır | Requirement onayı insanda |
| Solution Architect | Yalnızca architecture doküman alanı | Hook: path allowlist (`docs/architecture`, `docs/decisions`); Bash deny | Governance branch path sınırı | `docs/architecture/**`, `docs/decisions/**` | Hayır | ADR onayı insanda |
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
  boşluğu CI merge gate kapatır.

## CI Merge Gate Notları

- `scripts/validate_ownership_diff.py`, bir PR'ın `--base-sha` ve
  `--head-sha` arasındaki tam diff'ini merge-time'da denetler. Bkz.
  `docs/architecture/adr/ADR-004-ownership-ci-diff-enforcement.md`.
- **CI agent identity doğrulamaz; yalnızca path authority doğrular.**
  Implementer agent satırlarındaki ("Aynı" yazan) CI merge gate, yetkiyi
  **yalnızca base commit'teki** `docs/ownership/REQ-XXX.json` manifestinden
  alır; PR head'indeki manifest yetki kaynağı olarak kullanılmaz ve
  `docs/ownership/` altındaki herhangi bir diff değişikliği reddedilir. Bu,
  bir implementation PR'ının kendi manifestini değiştirerek kendine yeni
  write authority vermesini önler. Agent kimliği doğrulaması yalnızca
  runtime hook'un (yukarıdaki sütun) sorumluluğundadır.
- Document/review rollerinin ("Governance branch path sınırı" yazan
  satırlar) bulunduğu branch'ler `req-XXX-kisa-aciklama` ve
  `ownership-REQ-XXX-kisa-aciklama` desenlerinin hiçbirine uymadığı için CI
  bunları **generic governance/control-plane branch** olarak ele alır:
  yalnızca `.claude/`, `.github/`, `docs/`, `scripts/`, `tests/`,
  `design/`, `evals/` önekli path'lerde veya kök seviyedeki birkaç sabit
  dosyada değişiklik kabul edilir; bunun dışındaki application path
  değişiklikleri (örnek: `apps/web/src/App.tsx`) reddedilir.
- **Generic governance branch authority manifest dosyalarını
  (`docs/ownership/REQ-<en az 3 rakam>.json`) değiştiremez.** `docs/`
  öneki bu branch sınıfında genel olarak izinli olsa da, yalnızca bu exact
  pattern'e eşleşen dosya adları açıkça reddedilir. Bu, Security Red Team
  review'ın tespit ettiği bir authority-escalation bulgusuna yanıttır:
  düzeltme öncesinde herhangi bir `req-XXX-*` olmayan branch sahte/
  genişletilmiş bir manifest oluşturabilir ve bu manifest daha sonra bir
  req branch için base authority haline gelebilirdi. Statik ownership
  dokümanları (`docs/ownership/README.md`, `TEMPLATE.json`, `schema.json`)
  bu pattern'e uymadığından authority kaynağı değildir ve genel `docs/`
  allowlist'i altında generic governance branch'lerde değiştirilebilir;
  bunların onayı diğer governance değişiklikleri gibi insan review
  boundary'sindedir.
- **Ownership registry branch manifest lifecycle için ayrı bir
  control-plane akışıdır.** `ownership-REQ-XXX-kisa-aciklama` deseniyle
  eşleşen branch'ler yalnızca kendi exact
  `docs/ownership/REQ-XXX.json` dosyasını değiştirebilir; başka hiçbir
  path (application kodu, script, workflow, `.claude`, başka bir
  manifest, README, requirement, contract, ADR, test) bu branch'te
  değişemez ve manifest silinemez.
- **Registry branch değişikliği insan review/approval gerektirir.** CI,
  `status: approved` ve `approval.approved_by`/`approved_at` alanlarını
  teknik olarak doğrulayabilir, ancak approval'ın gerçekten bir insan
  tarafından verildiğini kriptografik olarak kanıtlayamaz; bu garanti
  GitHub PR review/branch protection/CODEOWNERS sürecinden gelir.
- **Symlink ve gitlink/submodule path'leri CI diff gate tarafından reject
  edilir.** Diff `git diff --raw` ile mode bilgisiyle hesaplanır;
  `120000` (symlink) veya `160000` (gitlink/submodule) mode'u görülen
  herhangi bir path, branch sınıfından bağımsız olarak (req, registry
  veya governance) fail-closed reddedilir.
- **`.claude`, `.github` ve `scripts` değişiklikleri için insan review
  boundary'si sürer; CODEOWNERS/branch protection sonraki GitHub
  governance adımında bağlanacaktır.** CI diff validator bu dosyaların
  gerçekten bir insan tarafından değiştirildiğini kriptografik olarak
  kanıtlamaz; bu kontrol path authority'sinin ötesindedir.
- CI diff validator ve testleri hazır; workflow bağlama bekliyor.
  (`.github/workflows/ownership-governance.yml` ayrı bir ADR/PR kapsamında
  eklenecektir.)

## Evrensel Kurallar

- Hiçbir agent `main` branch'e doğrudan yazamaz.
- Hiçbir agent kendi implementasyonunu tek başına approve edemez.
- Security Red Team bulguyu üretir; fix ilgili implementer tarafından yapılır.
- Integration / Release agent merge yapmaz; release-readiness kanıtını ve handoff'ı hazırlar. Nihai merge insan onayındadır.
- Hiçbir agent main merge, production deploy, production migration veya secret işlemi yapamaz; bunlar yalnızca insan onayıyla yapılır.
- Her non-trivial değişiklik REQ-ID, test kanıtı ve handoff ile bağlanır.
