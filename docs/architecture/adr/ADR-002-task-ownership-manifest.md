# ADR-002: Task Ownership Manifest

- **Status:** Accepted
- **Date:** 2026-06-25
- **Acceptance Date:** 2026-06-25
- **Owner:** Human maintainer
- **Related controls:** PROJECT_CONSTITUTION.md, CLAUDE.md,
  ADR-001-role-based-hook-enforcement.md

## Context

ADR-001, Delivery Lead ve doküman/review rolleri için `.claude/hooks/
enforce-role-boundaries.sh` üzerinden path allowlist enforcement getirdi.
Ancak Frontend Engineer, Backend Engineer, Database Engineer, QA Automation
ve AI/Data Engineer için bu enforcement bilerek eklenmedi: bu roller
feature'dan feature'a farklı uygulama klasörlerine yazar ve task-level
ownership bilgisi olmadan sabit bir path allowlist koymak gerçek geliştirme
işini yanlışlıkla bloke etme riski taşır.

Aynı zamanda agent prompt'ları (`.claude/agents/*.md`) zaten şu kuralları
tarif eder: implementer agent'lar REQ-ID ve acceptance criteria olmadan
implementation başlatmaz, contract olmadan frontend/backend paralel
geliştirme başlamaz, ve her branch/worktree'de yalnızca bir writer agent
çalışır. Bu kurallar yönlendiricidir; teknik olarak zorlanmaz.

## Decision

`docs/ownership/REQ-XXX.json` adında, insan maintainer tarafından oluşturulan
ve yönetilen bir **task ownership manifest** standardı tanımlanır:

- Manifest, `docs/ownership/schema.json` ile doğrulanan bir JSON Schema'ya
  uyar ve `docs/ownership/TEMPLATE.json` üzerinden başlatılır.
- Her manifest bir REQ-ID, durum (`draft`/`approved`/`superseded`/`closed`),
  insan onay kaydı, requirement/acceptance-criteria/contract referansları ve
  agent başına `write_paths` listesi taşır.
- Manifest yalnızca `frontend-engineer`, `backend-engineer`,
  `database-engineer`, `qa-automation`, `ai-data-engineer` rollerini
  agent değeri olarak kabul eder.
- `scripts/validate_ownership_manifest.py`, yalnızca Python standard
  library kullanarak manifesti doğrular ve isteğe bağlı bir
  `--authorize-agent`/`--branch`/`--target` modunda belirli bir agent'ın
  belirli bir dosyaya yazma yetkisi olup olmadığını teknik olarak
  hesaplayabilir.

Validator, forbidden directory-prefix kontrollerine ek olarak normalize
edilmiş repository-relative path üzerinde çalışan bir **tam-path (exact-path)
koruma listesi** uygular (`CLAUDE.md`, `PROJECT_CONSTITUTION.md`, `AGENTS.md`,
`.claude/settings.json`, ilgili hook dosyaları, `scripts/validate_ownership_
manifest.py`, `docs/ownership/README.md|TEMPLATE.json|schema.json`). Bu, bir
implementer manifestinin `./CLAUDE.md` gibi normalize edilince aynı governance
dosyasına işaret eden bir yazımla bu korumayı atlamasını önler; prefix
kontrollerinin yerini almaz, üzerine ek bir katmandır. Ayrıca `--authorize-agent`
modundaki branch eşleşmesi, `REQ-XXX` rakamlarıyla branch'teki rakamları
karakter karakter (zero-padding dahil) karşılaştırır; `REQ-042` için
`req-42-login-flow` gibi sıfır eksik bir branch reddedilir.

Bu ADR ve bu paket **henüz herhangi bir hook veya `.claude/settings.json`
enforcement eklemez.** Bu aşamanın kapsamı, sonraki bir enforcement
aşamasının üzerine inşa edeceği manifest sözleşmesini ve validator/authorize
aracını oluşturmaktır. Hedef, ileride Frontend, Backend, Database, QA ve
AI/Data Engineer'ların yalnızca `approved` durumda bir manifest ve o
manifestte tanımlı `write_paths` kapsamında yazabilmesini teknik olarak
zorlamaktır; bu enforcement adımı ayrı bir ADR/PR ile eklenecektir.

İnsan onayı olmadan bir manifest `approved` kabul edilmez: `approved`
durumunda `approval.approved_by` ve `approval.approved_at` alanlarının
boş olmaması validator tarafından zorunlu kılınır, ancak bu alanların
doğruluğunun (gerçekten bir insanın onayladığının) garantisi süreçseldir,
hook seviyesinde değildir.

## Alternatives Considered

1. **Doğrudan path allowlist'i hook'a sabit kodlamak**
   - Reddedildi. Task'tan task'a değişen uygulama path'leri için sabit bir
     allowlist, gerçek feature geliştirmesini hatalı biçimde bloke eder
     veya aşırı geniş tutulup hiçbir koruma sağlamaz.

2. **Manifesti implementer agent'ların kendisinin oluşturup onaylamasına
   izin vermek**
   - Reddedildi. Bu, yazma yetkisini tanımlayan kaydı yazma yetkisi istenen
     tarafın kontrolüne verir; insan onay kapısını anlamsızlaştırır.

3. **Manifest ile birlikte aynı PR'da hook/CI enforcement'ı eklemek**
   - Ertelendi. Enforcement, manifest sözleşmesi ve validator davranışı
     stabilize olmadan eklenirse hatalı bir kontrat üzerine kilitleme
     riski taşır. Bu nedenle bu ADR yalnızca sözleşme ve validator'ı
     kapsar.

## Consequences

- İnsan maintainer artık her REQ-ID için açık, makine tarafından
  doğrulanabilir bir ownership kaydı tutar.
- Validator, manifest hatalarını (eksik referans, path overlap, yasak
  path, desteklenmeyen agent) implementation başlamadan önce yakalar.
- `--authorize-agent` modu, ileride hook/CI içinde tek bir komutla "bu
  agent bu dosyaya şu an yazabilir mi" sorusuna teknik cevap üretmeyi
  mümkün kılar; ancak bu PR bu modu hiçbir hook'a bağlamaz.
- Bu aşamada hâlâ best-effort'tür: validator'ı çalıştırmayı unutan bir
  insan veya agent, manifesti yine de yanlış kullanabilir. Teknik
  zorunluluk, sonraki enforcement ADR'si ile gelir.

## Evidence

- PROJECT_CONSTITUTION.md (branching policy, human approval gates,
  documentation policy)
- CLAUDE.md (delivery rules, quality rules)
- ADR-001-role-based-hook-enforcement.md
- `.claude/agents/frontend-engineer.md`,
  `.claude/agents/backend-engineer.md`,
  `.claude/agents/database-engineer.md`,
  `.claude/agents/qa-automation.md`,
  `.claude/agents/ai-data-engineer.md`

## Implementation Impact

- Yeni dosyalar: `docs/ownership/README.md`, `docs/ownership/TEMPLATE.json`,
  `docs/ownership/schema.json`, `scripts/validate_ownership_manifest.py`,
  `tests/test_validate_ownership_manifest.py`.
- `.claude/hooks/**`, `.claude/settings.json`, `.claude/agents/**`,
  `CLAUDE.md`, `PROJECT_CONSTITUTION.md` ve mevcut requirement/contract/ADR
  dosyaları bu PR kapsamında değiştirilmez.
- Gerçek REQ-XXX manifest dosyaları bu PR'da oluşturulmaz; bu PR yalnızca
  standart ve şablonu tanımlar.

## Acceptance Evidence

- PR #5 ile task ownership manifest sözleşmesi merge edildi.
- `docs/ownership/REQ-XXX.json` yapısı, schema/template ve validator
  eklendi.
- Branch/REQ-ID eşleşmesi, owner path overlap koruması ve governance
  dosyası koruması test edildi.

## Approval

- **Required approver:** Human maintainer
- **Approval status:** Accepted
- **Approval evidence:** PR #5 reviewed and merged to main (2026-06-25)
