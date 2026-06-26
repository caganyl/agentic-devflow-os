# Task Ownership Manifest

## Amaç

Bu dizin, her REQ-ID için hangi implementer agent'ın hangi dosya yollarına
yazabileceğini tanımlayan **canonical görev ownership kaydını** içerir.
Manifest, `docs/ownership/REQ-XXX.json` dosyası olarak tutulur ve
`docs/ownership/schema.json` ile doğrulanır.

Bu paket, henüz hook veya CI enforcement eklemez. Bu aşamada yalnızca
manifest sözleşmesi (schema, template) ve manifesti doğrulayan/yetkilendiren
`scripts/validate_ownership_manifest.py` aracı tanımlanır. Hook ve CI
enforcement bu manifesti kullanacak şekilde sonraki aşamada eklenecektir
(bkz. `docs/architecture/adr/ADR-002-task-ownership-manifest.md`).

## Manifestin Sahibi

Manifest dosyası yalnızca **insan maintainer** tarafından oluşturulur ve
`approved` duruma geçirilir. Implementer agent'lar (Frontend Engineer,
Backend Engineer, Database Engineer, QA Automation, AI/Data Engineer)
manifesti **değiştiremez**; manifest onların yazma yetkisinin girdisidir,
çıktısı değildir.

Bir manifest taslak (`draft`) durumdayken implementer agent o REQ-ID
kapsamında kod yazamaz. İnsan maintainer gerekli referansları doldurup
durumu `approved` yaptıktan sonra implementasyon başlayabilir.

## Ön Koşullar

Bir implementer agent, ilgili REQ-ID için aşağıdakiler olmadan dosya
yazamaz:

- Onaylı (`approved`) bir ownership manifest.
- `references.requirement` ve `references.acceptance_criteria` alanlarının
  repository içinde gerçekten var olan dosyalara işaret etmesi.
- En az bir contract referansı (`references.contracts`) **veya**
  `references.contract_exception` içinde boş olmayan `reason`,
  `approved_by` ve `approved_at` alanları.

Bu koşullardan biri eksikse manifest `approved` olarak kabul edilmemelidir
ve implementer agent yazma yetkisi alamaz.

## Branch ve Writer Kuralı

- Branch standardı: `req-XXX-kisa-aciklama` (örnek: `req-042-login-flow`).
- `XXX`, manifestteki `REQ-XXX` değerindeki rakamlarla **karakter karakter
  aynı** olmalıdır; baştaki sıfırlar korunur. Örnek: `REQ-042` için geçerli
  branch `req-042-login-flow`'tur, `req-42-login-flow` **geçersizdir** ve
  `--authorize-agent` modu bu branch'i reddeder.
- Her branch ve worktree'de yalnızca **bir writer agent** çalışır
  (PROJECT_CONSTITUTION.md ile uyumlu).
- Aynı REQ-ID için birden fazla branch/worktree kullanılabilir (örnek:
  frontend ve backend için ayrı branch'ler). Ancak manifest içinde
  owner'lar arasında **path overlap yasaktır** — iki farklı owner aynı veya
  iç içe geçen bir yola yazamaz. Bu, hangi branch'te çalışıldığından
  bağımsız olarak geçerlidir.

## Manifest Alanları

| Alan | Açıklama |
| --- | --- |
| `schema_version` | Şu an yalnızca `1`. |
| `req_id` | `REQ-XXX` biçiminde, dosya adıyla eşleşmeli. |
| `status` | `draft`, `approved`, `superseded` veya `closed`. |
| `approval` | `approved` durumda `approved_by` ve `approved_at` zorunlu. |
| `references.requirement` | Requirement dosyasına repository-relative yol. |
| `references.acceptance_criteria` | Acceptance criteria dosyasına yol. |
| `references.contracts` | Onaylı contract dosya yolları (en az biri **veya** exception gerekir). |
| `references.contract_exception` | Contract yoksa insan onaylı istisna kaydı. |
| `references.adrs` | İlgili ADR dosya yolları (boş olabilir, verilenler mevcut olmalı). |
| `owners[].agent` | `frontend-engineer`, `backend-engineer`, `database-engineer`, `qa-automation`, `ai-data-engineer`'den biri. |
| `owners[].write_paths` | Bu agent'ın yazabileceği göreli, repository içi yol(lar)ı. |
| `owners[].notes` | Kapsam notu (opsiyonel). |

## Validator Kullanımı

Manifesti doğrulamak için:

```bash
python3 scripts/validate_ownership_manifest.py \
  --manifest docs/ownership/REQ-042.json \
  --root .
```

Bir agent'ın belirli bir dosyaya yazma yetkisi olup olmadığını kontrol etmek
için (gelecekteki hook/CI enforcement bu modu kullanacaktır):

```bash
python3 scripts/validate_ownership_manifest.py \
  --manifest docs/ownership/REQ-042.json \
  --root . \
  --branch req-042-login-flow \
  --authorize-agent frontend-engineer \
  --target apps/web/src/features/example/LoginForm.tsx
```

Bu mod yalnızca manifest `approved` durumdaysa, branch adı `req_id` ile
eşleşiyorsa, agent manifestte tanımlıysa ve target path o agent'ın kendi
`write_paths` alanlarından birinin altındaysa başarılı olur.

## Korunan Governance/Enforcement Dosyaları

Validator, `write_paths` içindeki her yolu normalize edilmiş
(repository-relative, `./` öneki temizlenmiş, `..` içermeyen) biçimiyle
kontrol eder. Bu normalize edilmiş yol aşağıdaki tam-path listesindeki bir
girdiyle eşleşirse manifest reddedilir; `./CLAUDE.md` gibi bir yazım da
`CLAUDE.md` ile aynı şekilde reddedilir:

- `PROJECT_CONSTITUTION.md`
- `CLAUDE.md`
- `AGENTS.md`
- `.claude/settings.json`
- `.claude/hooks/enforce-role-boundaries.sh`
- `.claude/hooks/protect-main.sh`
- `.claude/hooks/protect-sensitive-paths.sh`
- `scripts/validate_ownership_manifest.py`
- `docs/ownership/README.md`
- `docs/ownership/TEMPLATE.json`
- `docs/ownership/schema.json`

Bu tam-path kontrolü, mevcut forbidden directory-prefix kontrollerine
(`.claude/`, `docs/ownership/`, vb.) **ek bir güvenlik katmanıdır**; prefix
kontrollerinin yerini almaz.

## Sonraki Aşama

`ADR-001-role-based-hook-enforcement.md`, Frontend/Backend/Database/QA/
AI-Data Engineer rolleri için path enforcement'ı bu manifest standardı
oluşturulana kadar erteledi. `ADR-003-ownership-runtime-enforcement.md` ile
bu erteleme sona erdi: runtime enforcement artık aktiftir.

`.claude/hooks/enforce-role-boundaries.sh`, bu beş implementer agent'ın
(`frontend-engineer`, `backend-engineer`, `database-engineer`,
`qa-automation`, `ai-data-engineer`) her `Edit`/`Write` çağrısında bu
script'in `--authorize-agent` modunu çağırarak şu koşulları birlikte
kontrol eder: mevcut branch `req-XXX-kisa-aciklama` desenine uyuyor mu,
branch'teki `XXX`'e karşılık gelen `docs/ownership/REQ-XXX.json` manifesti
var mı, manifest `approved` durumda mı, çağrıyı yapan agent manifestte
owner olarak tanımlı mı ve hedef dosya yolu o agent'ın kendi `write_paths`
alanının altında mı. Bu koşullardan biri sağlanmazsa çağrı reddedilir
(fail-closed); ayrıntılar için `ADR-003-ownership-runtime-enforcement.md`'e
bakın.

Bu runtime enforcement yalnızca Claude'un `Edit`/`Write` araç çağrılarını
kapsar. Bash üzerinden yapılan dosya değişikliklerini veya normal
terminalden yapılan manuel değişiklikleri tek başına kapsamaz; bu boşluğu
aşağıdaki CI diff enforcement katmanı kapatır.

## CI Diff Enforcement

`ADR-003-ownership-runtime-enforcement.md` ile bağlanan runtime hook ve bu
bölümde tarif edilen CI diff gate, iki farklı katmandır ve birbirinin
yerini almaz:

- **Runtime hook** (`.claude/hooks/enforce-role-boundaries.sh`), yalnızca
  Claude'un `Edit`/`Write` araç çağrılarını PreToolUse aşamasında, çağrıyı
  yapan agent'ın kimliğini bilerek denetler. Bash üzerinden veya normal
  terminalden yapılan değişiklikleri kapsamaz.
- **CI diff gate** (`scripts/validate_ownership_diff.py`,
  `docs/architecture/adr/ADR-004-ownership-ci-diff-enforcement.md`),
  merge-time'da bir PR'ın tam diff'ini denetler. Bash veya terminal
  üzerinden yapılmış olsa bile manifest dışı her değişikliği yakalar.
  Ancak CI, hangi Claude agent'ının diff'i ürettiğini **bilemez**; bu
  nedenle agent kimliği değil, **değişen path'in owner alanına aitliğini**
  doğrular.

CI diff gate'in temel kuralı: bir `req-XXX-kisa-aciklama` branch'inde
değişen her dosya, **base commit**'teki insan onaylı
`docs/ownership/REQ-XXX.json` manifestinin owner `write_paths`
alanlarından tam olarak birinin altında olmalıdır. Yetki kaynağı
yalnızca base commit'teki manifesttir:

- Manifest, `git show <base-sha>:docs/ownership/REQ-XXX.json` ile
  okunur; PR head'indeki manifest hiçbir biçimde yetki kaynağı olarak
  kullanılmaz. Bu, bir implementation PR'ının kendi manifestini
  değiştirerek kendine yeni write authority vermesini önler.
- Diff'te `docs/ownership/` altında herhangi bir değişiklik varsa
  reddedilir (req branch davranışı bu konuda değişmemiştir):
  implementation PR'ları manifesti değiştiremez.
- Base manifest `approved` değilse, mevcut değilse veya
  `validate_ownership_manifest.py` içindeki `validate_manifest`
  doğrulamasından geçemiyorsa reddedilir.
- Rename/copy durumunda hem eski hem yeni path denetlenir; bir dosya bir
  owner'ın alanından başka bir owner'ın alanına taşınıyorsa reddedilir.

Branch `req-XXX-kisa-aciklama` veya `ownership-REQ-XXX-kisa-aciklama`
desenlerinden hiçbirine uymuyorsa **generic governance/control-plane
branch** olarak ele alınır (örnek: bu paketin geliştirildiği
`ownership-ci-diff-enforcement`). Bu branch'lerde ownership manifesti
aranmaz; yalnızca `.claude/`, `.github/`, `docs/`, `scripts/`, `tests/`,
`design/`, `evals/` önekli path'lere veya kök seviyede `.gitignore`,
`README.md`, `PROJECT_CONSTITUTION.md`, `CLAUDE.md`, `AGENTS.md`
tam-path'lerine değişiklik kabul edilir; bunların dışındaki her path
(örnek: `apps/web/src/App.tsx`) reddedilir. Bu, application kodunun
governance branch'lerinden kaçırılmasını önler.

**Generic governance branch'ler authority manifest dosyalarını
(`docs/ownership/REQ-<en az 3 rakam>.json`) değiştiremez.** Validator,
`docs/ownership/` öneki yerine yalnızca tam olarak `REQ-` + en az üç rakam +
`.json` ile eşleşen dosya adını **authority manifest** kabul eder ve bu
sınıfı bu branch'lerde açıkça reddeder (örnek: `docs/ownership/REQ-042.json`
reddedilir; `docs/ownership/REQ-999-login.json` bu pattern'e uymadığı için
authority manifest sayılmaz ve generic `docs/` allowlist'i altında zaten
kabul edilir). Bunun nedeni, ownership manifest lifecycle'ının ayrı ve özel
bir branch sınıfına (aşağıdaki "Ownership Registry Branch") ayrılmış
olmasıdır; aksi halde `req-XXX-*` olmayan herhangi bir branch sahte veya
genişletilmiş bir manifest oluşturup bunu daha sonra bir req branch için
base authority haline getirebilirdi (Security Red Team review'da tespit
edilen kritik bir authority-escalation riski).

**Statik ownership control-plane dokümanları generic governance branch'te
değiştirilebilir.** `docs/ownership/README.md`, `docs/ownership/
TEMPLATE.json` ve `docs/ownership/schema.json` authority manifest değildir
(dosya adları `REQ-<digits>.json` pattern'ine uymaz); bu dosyalar genel
`docs/` allowlist'i altında generic governance branch'lerde normal şekilde
güncellenebilir ve nihai onayları diğer governance değişiklikleri gibi
GitHub PR review/insan review boundary'sindedir. Bu dosyalar **ownership
registry branch'te** değiştirilemez — registry branch yalnızca kendi exact
REQ manifest dosyasını değiştirebilir (aşağıya bakın).

CLI kullanımı:

```bash
python3 scripts/validate_ownership_diff.py \
  --root . \
  --base-sha <base-sha> \
  --head-sha <head-sha> \
  --branch req-042-login-flow
```

Bu script ve testleri hazır; CI workflow bağlama bekliyor. Bir sonraki
adımda bu script `.github/workflows/ownership-governance.yml` olarak
bağlanacaktır (bkz.
`docs/architecture/adr/ADR-004-ownership-ci-diff-enforcement.md`).

## Feature Bootstrap PR

`req-NNN-feature-name` branch'inde `docs/ownership/REQ-NNN.json` base
commit'te yoksa ve PR head'inde eklenmişse, CI diff gate bu PR'ı
**bootstrap feature PR** olarak ele alır. Bu mod, requirement onayını ve
implementation'ı aynı PR'a sığdırmanın desteklenen yoludur; REQ-003'te
zorunlu olan "önce manifest PR, sonra implementation PR" çift adımına
gerek kalmaz.

### Bootstrap PR'da birlikte taşınabilecek dosyalar

| Alan | Yol örnekleri |
| --- | --- |
| Requirement | `docs/product/requirements/REQ-NNN.md` |
| Acceptance criteria | `docs/product/acceptance-criteria/REQ-NNN.md` |
| Contract | `docs/contracts/openapi/REQ-NNN.yaml` |
| Handoff | `docs/handoffs/REQ-NNN.md` |
| Source code | `src/features/req-NNN-name/...` |
| Tests | `tests/features/req-NNN-name/...` |
| Design | `design/req-NNN-name/...` |
| Evals | `evals/req-NNN-name/...` |

Manifest dışındaki her değişen dosya, head manifest içindeki tam olarak
bir owner `write_paths` kuralı tarafından kapsanmalıdır.
Yalnızca `references.requirement` ve `references.acceptance_criteria`
alanlarındaki dosyalar coverage denetiminden muaftır; ancak PR head'inde
mevcut olmalı ve diff içinde değiştirilmiş olmalıdır.
`references.contracts`, `references.adrs` ve diğer tüm dosyalar
**coverage denetiminden muaf değildir** — ilgili owner `write_paths`
altında olmak zorundadır.

### Bootstrap güvenlik sınırları

Bootstrap manifestleri aşağıdaki alanlara write authority **veremez**:

- `.claude/`, `.github/`, `scripts/`, `docs/ownership/`
- `docs/architecture/adr/` ve `docs/architecture/` altındaki tüm path'ler
  (ADR değişiklikleri ayrı governance akışına aittir)
- `CLAUDE.md`, `AGENTS.md`, `PROJECT_CONSTITUTION.md`, `README.md`,
  `.gitignore`
- `.env` ve secret/credential benzeri path'ler
- `src`, `tests`, `docs`, `apps`, `lib`, `evals` gibi tek başına geniş
  root path'ler ve `docs/contracts` gibi alan root path'leri
  (bunların altındaki `src/features/req-NNN-name`,
  `docs/contracts/openapi/req-NNN-name` veya
  `evals/datasets/golden/req-NNN-name` gibi dar namespace path'leri
  kabul edilir)

`references.requirement` ve `references.acceptance_criteria` yalnızca
`docs/product/requirements/` veya `docs/product/acceptance-criteria/`
altında olabilir.

Bootstrap manifest `approved` durumuyla, `approval.approved_by` ve
`approval.approved_at` alanlarıyla birlikte gelmek zorundadır. `req_id`
branch numarasıyla tam eşleşmelidir.

Diff'te `docs/ownership/REQ-NNN.json` dışında başka bir
`docs/ownership/` dosyası bulunursa PR reddedilir.

### Ownership kapsamını sonradan genişletmek

Bootstrap PR merge edildikten sonra ownership kapsamını genişletmek
(yeni bir agent veya path eklemek) ayrı bir
`ownership-REQ-NNN-aciklama` branch'i gerektirir. Bunun nedeni, base
commit'te manifest artık var olduğundan `req-NNN-*` branch'inin
manifest değiştirme izninin olmamasıdır (aşağıdaki "Ownership Registry
Branch" ve "CI Diff Enforcement" bölümlerine bakın).

## Ownership Registry Branch

Bir ownership manifesti oluşturmak veya `draft` ↔ `approved` lifecycle'ı
kapsamında güncellemek için kullanılan ayrı bir control-plane branch
sınıfıdır. Bu sınıf, generic governance branch'lerden ve implementation
(`req-XXX-*`) branch'lerinden tamamen ayrıdır:

- **Sıra önemlidir.** Product requirement, acceptance criteria ve contract
  (varsa) **önce base branch'te** bulunur; bunlar manifestten önce
  gelmelidir. Registry branch kendi içinde bir requirement veya contract
  icat edemez — manifestin `references` alanları yalnızca base commit
  snapshot'ından materialize edilip doğrulanır.
- **İnsan maintainer**, requirement/contract base branch'te hazır
  olduktan sonra `ownership-REQ-XXX-kisa-aciklama` branch'i üzerinden
  (örnek: `ownership-REQ-042-login-flow`) manifesti oluşturur veya
  günceller.
- Bu branch **yalnızca** `docs/ownership/REQ-XXX.json` dosyasını
  değiştirebilir (`XXX`, branch adındaki REQ-ID ile tam eşleşmelidir).
  Diff'te bu exact path dışında herhangi bir değişiklik — application
  kodu, script, workflow, `.claude`, başka bir manifest, README,
  requirement, contract, ADR, test, ek dosya — reddedilir.
- Manifestin silinmesi reddedilir; manifest head commit'te mevcut
  olmalıdır.
- **Generic governance branch'ler `docs/ownership/**` değiştiremez** —
  yukarıdaki bölümde açıklandığı gibi, bu yetki yalnızca ownership
  registry branch'lerine aittir.
- **Implementation branch (`req-XXX-*`) yalnızca base branch'te önceden
  var olan, `approved` durumdaki manifesti kullanabilir.** Bir req branch
  kendi manifestini değiştiremez (yukarıdaki "CI Diff Enforcement"
  bölümüne bakın).
- **CI, approval yapan kişinin insan olduğunu kanıtlamaz.** `status:
  approved` ve `approval.approved_by`/`approved_at` alanlarının doluluğu
  `validate_ownership_manifest.py` ile teknik olarak doğrulanır, ancak bu
  approval'ın gerçekten bir insan maintainer tarafından verildiğini CI tek
  başına kriptografik olarak kanıtlayamaz. Bu garanti PR review, branch
  protection ve CODEOWNERS modelinden gelir; bunlar ileride GitHub
  governance tarafında bağlanacaktır.
- **Symlink ve submodule/gitlink değişimleri ownership diff gate
  tarafından reddedilir.** Bu kontrol branch sınıfından bağımsız olarak
  her zaman uygulanır (bkz. `docs/architecture/adr/
  ADR-004-ownership-ci-diff-enforcement.md`).

CLI kullanımı (registry branch'te de aynı script çalışır, branch adı diff
validator'ına hangi kuralların uygulanacağını belirler):

```bash
python3 scripts/validate_ownership_diff.py \
  --root . \
  --base-sha <base-sha> \
  --head-sha <head-sha> \
  --branch ownership-REQ-042-login-flow
```
