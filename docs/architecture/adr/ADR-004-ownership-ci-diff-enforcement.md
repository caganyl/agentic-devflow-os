# ADR-004: Ownership CI Diff Enforcement

- **Status:** Proposed
- **Date:** 2026-06-25
- **Owner:** Human maintainer
- **Related controls:** PROJECT_CONSTITUTION.md, CLAUDE.md,
  AGENT_CAPABILITY_MATRIX.md, ADR-001-role-based-hook-enforcement.md,
  ADR-002-task-ownership-manifest.md,
  ADR-003-ownership-runtime-enforcement.md

## Context

ADR-003 bağladığı `.claude/hooks/enforce-role-boundaries.sh` ownership
bloğu, yalnızca Claude'un kendi `Edit`/`Write` araç çağrılarını PreToolUse
aşamasında denetler. Bu mekanizma, bir implementer agent'ın `req-XXX-kisa-
aciklama` branch'inde, approved bir manifest ve manifestte tanımlı
`write_paths` dışına Claude üzerinden yazmasını önceden engeller.

Ancak bu runtime enforcement'ın kapsamadığı bir boşluk vardır: bir agent
Bash üzerinden (`sed -i`, `tee`, yönlendirmeli yazma vb.) veya bir insan
normal terminalden doğrudan dosya değiştirirse, hook hiç çalışmaz ve
manifest dışı bir değişiklik PR diff'ine kadar fark edilmeden ilerleyebilir.
ADR-002 ve ADR-003 bu boşluğu bilerek bir sonraki ADR/PR'a bıraktı.

Ayrıca CI ortamı, Claude runtime'ından farklı bir güven sınırındadır: CI bir
custom agent identity'sine (`frontend-engineer`, `backend-engineer` vb.)
sahip değildir ve hangi "agent"in diff'i ürettiğini bilemez. Bu nedenle CI
katmanı agent kimliği değil, **path ownership** denetleyebilir: değişen her
dosya, base commit'teki insan onaylı manifestin owner `write_paths`
alanlarından tam olarak birinin altında mı?

Kritik bir tehdit modeli: bir implementation PR, kendi `docs/ownership/
REQ-XXX.json` manifestini PR head'inde değiştirerek kendine yeni write
authority verebilir (örnek: yeni bir `write_paths` ekleyip ardından o yola
yazabilir). Bu nedenle yetki kaynağı PR head'i değil, yalnızca PR'ın
**base commit**'indeki manifest olmalıdır.

## Security Red Team Review

Bu ADR'nin ilk sürümünde, generic governance branch allowlist'i `docs/`
prefix'ini kabul ettiği için `docs/ownership/` da örtük olarak kabul
ediliyordu. Security Red Team review bunu kritik bir
**authority-escalation** bulgusu olarak işaretledi: `req-XXX-*` olmayan
herhangi bir branch (örnek: bir governance/dokümantasyon branch'i) sahte
veya genişletilmiş bir ownership manifesti oluşturabilir ya da mevcut bir
manifesti değiştirebilirdi; bu manifest daha sonra bir req branch için base
authority haline gelebilirdi. Bu bulgu aşağıdaki kararlarla fail-closed
olarak ele alınmıştır:

- **Generic governance branch'ler authority manifest dosyalarını
  (`docs/ownership/REQ-<en az 3 rakam>.json`) değiştiremez.**
  `is_authority_manifest_path`/`is_governance_allowed`/
  `validate_governance_branch`, `docs/` öneki altında olsa bile yalnızca
  tam olarak `REQ-` + en az üç rakam + `.json` ile eşleşen dosya adını
  authority manifest kabul edip açıkça reddeder; bu, genel `docs/`
  allowlist'inin örtük olarak ownership manifestine yetki vermesini önler.
  Statik ownership control-plane dokümanları (`docs/ownership/README.md`,
  `docs/ownership/TEMPLATE.json`, `docs/ownership/schema.json`) bu pattern'e
  uymadığı için authority manifest sayılmaz ve genel `docs/` allowlist'i
  altında generic governance branch'lerde normal şekilde değiştirilebilir;
  bunların nihai onayı diğer governance değişiklikleri gibi insan review
  boundary'sindedir (GitHub PR review/branch protection/CODEOWNERS).
- **Ownership manifest lifecycle yalnızca `ownership-REQ-XXX-*`
  branch'lerinde yürür.** Yeni bir üçüncü branch sınıfı olan **ownership
  registry branch** (`ownership-REQ-<en az 3 rakam>-<açıklama>`, örnek:
  `ownership-REQ-042-login-flow`) tanımlanmıştır.
- **Registry branch yalnızca exact REQ manifest dosyasını değiştirebilir.**
  Diff'teki her path tam olarak `docs/ownership/REQ-XXX.json` olmalıdır
  (`XXX`, branch adındaki REQ-ID); başka herhangi bir path (application
  kodu, script, workflow, `.claude`, başka bir manifest, README,
  requirement, contract, ADR, test) varsa diff reddedilir. Manifestin
  silinmesi (`D` statüsü) reddedilir. Manifest head commit'te mevcut
  olmalıdır; manifest dosya adı branch'teki REQ-ID ile tam eşleşmelidir
  (eşleşmezse "yalnızca exact path" kontrolü diff'i zaten reddeder).
  Manifest, mevcut `validate_ownership_manifest.validate_manifest`
  fonksiyonuyla **head** snapshot'ından doğrulanır (registry branch'in
  manifesti yazma yetkisi vardır), ancak manifestin
  requirement/acceptance-criteria/contract/ADR referansları yalnızca
  **base** snapshot'tan materialize edilir — registry branch kendi içinde
  requirement veya contract icat edemez; bunlar manifestten önce base
  branch'te bulunmalıdır.
- **Registry branch teknik olarak manifest validity denetler; insan
  approval kimliğini CI kanıtlayamaz.** `status: approved` alanı ve
  `approval.approved_by`/`approved_at` alanlarının doluluğu
  `validate_manifest` ile teknik olarak doğrulanabilir, ancak CI bu
  approval'ın gerçekten bir insan maintainer tarafından verildiğini
  kriptografik olarak kanıtlayamaz (commit author/committer bilgisi
  güvenilir bir kimlik değildir). Nihai insan review/approval boundary'si
  bu ADR'de açıkça GitHub PR review sürecine bırakılmıştır.
- **Ownership registry PR'ları ileride GitHub branch protection ve
  CODEOWNERS/human reviewer ile korunmalıdır.** Bu paket bunu teknik
  olarak bağlamaz; bu, GitHub governance tarafında ayrı bir adımdır (bkz.
  "Consequences" altındaki workflow notu).
- **Symlink ve gitlink/submodule değişimleri ownership diff validator
  tarafından reject edilir.** Diff hesaplaması artık
  `git diff --raw -z --find-renames --find-copies` kullanır ve her
  add/modify/delete/rename/copy girdisinin old/new git file mode'unu
  taşır. `120000` (symlink) veya `160000` (gitlink/submodule) mode'u
  görülen herhangi bir path, branch sınıfından bağımsız olarak (req,
  registry veya governance branch) fail-closed reddedilir. Bu, sembolik
  link veya submodule eklenerek path-prefix tabanlı kontrollerin
  atlanmasını önler.
- **Control-plane dosyaları (`.claude`, `.github`, `scripts`) hâlâ insan
  review boundary'sine tabidir.** Bu paket, bu dosyaların gerçekten bir
  insan tarafından değiştirildiğini kriptografik olarak kanıtlamaz; bu
  garanti GitHub branch protection/CODEOWANERS/PR review sürecinden gelir,
  CI diff validator'ından değil.

Bu bulgular Security Red Team review sonucunda ele alınmıştır.

## Decision

`scripts/validate_ownership_diff.py` adında, yalnızca Python standard
library kullanan bir CI diff validator eklenir. CLI biçimi:

```bash
python3 scripts/validate_ownership_diff.py \
  --root . \
  --base-sha <base-sha> \
  --head-sha <head-sha> \
  --branch req-042-login-flow
```

Davranış:

1. `--root` geçerli bir Git repository olmalı; `--base-sha` ve `--head-sha`
   geçerli Git revizyonları olmalı. Aksi halde `error:` önekli, anlaşılır
   bir mesajla non-zero exit code dönülür.
2. Diff, `git diff --raw -z --find-renames --find-copies <base-sha>
   <head-sha>` ile hesaplanır. Bu, `--name-status` yerine her diff
   girdisinin old/new git file mode'unu da taşımasını sağlar. Rename/copy
   durumunda hem eski hem yeni path denetlenir.
3. **Git mode güvenliği (branch sınıfından bağımsız, her zaman çalışır):**
   diff'teki herhangi bir add/modify/delete/rename/copy girdisinde old
   veya new mode `120000` (symlink) ya da `160000` (gitlink/submodule) ise
   ilgili path ve mode açıkça raporlanarak fail-closed reddedilir. Bu
   kontrol branch sınıfı belirlenmeden önce uygulanır; sembolik link veya
   submodule eklenerek aşağıdaki path-prefix tabanlı kontrollerin
   atlanması önlenir. Normal executable bit değişimi (`100644` ↔
   `100755`) bu kontrol kapsamında reddedilmez.
4. Branch `req-<en az 3 rakam>-<açıklama>` desenine uyuyorsa **req
   (implementation) branch** olarak ele alınır:
   - Branch numarasından türetilen `REQ-XXX` manifesti **yalnızca base
     commit'ten** (`git show <base-sha>:docs/ownership/REQ-XXX.json`)
     okunur. PR head'indeki manifest hiçbir biçimde yetki kaynağı olarak
     kullanılmaz.
   - Base commit'te manifest yoksa veya `approved` değilse fail-closed
     hata verilir.
   - Base manifestin requirement, acceptance criteria, contract ve ADR
     referansları, `git show` ile bir temporary directory'ye base commit
     snapshot'ından materialize edilip ardından ADR-002'nin
     `validate_manifest` fonksiyonuyla doğrulanır. Head branch dosyaları
     bu doğrulamada kullanılmaz.
   - Diff'te `docs/ownership/` altında herhangi bir değişiklik varsa açık
     hata verilir: bir implementation PR'ı kendi manifestini değiştiremez.
   - Değişen her path, base manifestteki owner `write_paths`
     alanlarından **tam olarak birinin** altında olmalı. Hiçbir owner
     alanına ait olmayan veya birden çok owner alanına ait görünen bir
     path reddedilir (overlap zaten manifest validator'ında engellense
     de, bu ikinci bir güvenlik katmanıdır).
   - Rename/copy durumunda eski path bir owner'a, yeni path başka bir
     owner'a aitse (owner sınırını aşan taşıma) reddedilir; her iki path
     de aynı owner'a ait olmalıdır.
5. Branch `ownership-REQ-<en az 3 rakam>-<açıklama>` desenine uyuyorsa
   (örnek: `ownership-REQ-042-login-flow`) **ownership registry branch**
   olarak ele alınır. Bu branch sınıfı, yalnızca ownership manifest
   lifecycle (oluşturma veya draft ↔ approved güncelleme) içindir:
   - Branch numarasından türetilen tam path olan
     `docs/ownership/REQ-XXX.json` dışında diff'te **hiçbir** path
     bulunamaz; bulunursa (application kodu, script, workflow, `.claude`,
     başka bir manifest, README, requirement, contract, ADR, test, ek
     dosya) diff reddedilir.
   - Manifestin silinmesi (`D` statüsü) reddedilir; manifest head
     commit'te mevcut olmalıdır.
   - Manifest dosya adı, branch'teki REQ-ID ile tam eşleşmelidir; bu zaten
     yukarıdaki "yalnızca exact path" kontrolüyle dolaylı olarak sağlanır
     (branch REQ-042 derken `docs/ownership/REQ-099.json` değiştirilirse
     bu path beklenen exact path'le eşleşmediği için reddedilir).
   - Manifest **head commit'ten** (`git show <head-sha>:...`) okunur ve
     `validate_ownership_manifest.validate_manifest` ile doğrulanır —
     registry branch'in kendi manifestini yazma yetkisi vardır. Ancak
     manifestin requirement/acceptance-criteria/contract/ADR referansları
     yalnızca **base** snapshot'tan materialize edilir; registry branch
     kendi içinde requirement veya contract oluşturamaz, bunlar
     manifestten önce base branch'te bulunmalıdır.
   - `status: approved` teknik olarak `validate_manifest` ile
     doğrulanabilir (örnek: `approval.approved_by`/`approved_at` doluluğu),
     ancak CI bu approval'ın gerçekten bir insan tarafından verildiğini
     kriptografik olarak kanıtlayamaz; nihai approval boundary'si GitHub
     PR review/branch protection/CODEOWNERS sürecindedir.
6. Branch yukarıdaki iki desene de uymuyorsa **generic governance/
   control-plane branch** olarak ele alınır: ownership manifesti aranmaz.
   Yalnızca `.claude/`, `.github/`, `docs/`, `scripts/`, `tests/`,
   `design/`, `evals/` önekli path'lere veya kök seviyede `.gitignore`,
   `README.md`, `PROJECT_CONSTITUTION.md`, `CLAUDE.md`, `AGENTS.md`
   tam-path'lerine değişiklik kabul edilir. **Yalnızca authority manifest
   pattern'ine (`docs/ownership/REQ-<en az 3 rakam>.json`) tam eşleşen
   path'ler, `docs/` öneki altında olsa bile açıkça reddedilir** —
   ownership manifest lifecycle yalnızca ownership registry branch'lerinde
   yürür. Statik ownership dokümanları (`docs/ownership/README.md`,
   `docs/ownership/TEMPLATE.json`, `docs/ownership/schema.json`) bu
   pattern'e uymadığı için genel `docs/` allowlist'i altında kabul edilir.
   Bunların dışındaki her path de reddedilir.

Bu mekanizma **fail-closed** çalışır: belirsiz, eksik veya hatalı her
durumda sonuç deny'dir ve hata mesajları stderr'e `error:` önekiyle yazılır.

## Alternatives Considered

1. **PR head'indeki manifesti yetki kaynağı kabul etmek**
   - Reddedildi. Bu, bir implementation PR'ının kendi manifestini
     değiştirerek kendine yeni write authority vermesine izin verir ve
     insan onay kapısını anlamsızlaştırır.

2. **CI'da agent kimliğini de doğrulamaya çalışmak**
   - Reddedildi. CI'nin diff'i hangi Claude agent'ının ürettiğini bilmesi
     için bir teknik mekanizma yoktur (commit author/committer bilgisi
     güvenilir bir agent kimliği değildir). Bu nedenle CI yalnızca path
     ownership'i, runtime hook ise agent kimliğini denetler; ikisi
     birbirini tamamlar, biri diğerinin yerini almaz.

3. **Runtime hook'u yeterli kabul edip CI diff kontrolünü eklememek**
   - Reddedildi. Runtime hook yalnızca Claude'un `Edit`/`Write`
     çağrılarını kapsar; Bash üzerinden veya normal terminalden yapılan
     manuel değişiklikler bu kontrolün dışında kalır ve PR'a kadar fark
     edilmeyebilir.

4. **Validator mantığını `validate_ownership_manifest.py`'den ayrıştırıp
   yeniden yazmak**
   - Reddedildi. Base manifestin kendisinin geçerliliği (referans
     dosyaları, owner tanımları, path overlap, forbidden path) zaten
     ADR-002'nin `validate_manifest` fonksiyonunda tanımlı; bu script o
     fonksiyonu base commit snapshot'ı üzerinde tekrar kullanır, mantığı
     kopyalamaz.

## Consequences

- Bir `req-XXX-kisa-aciklama` branch'indeki PR diff'i, base commit'teki
  approved manifestin owner `write_paths` alanları dışında bir dosyayı
  değiştiriyorsa CI seviyesinde reddedilir; bu, Bash veya terminal
  üzerinden yapılan manifest-dışı değişiklikleri de yakalar.
- Bir implementation PR'ı kendi `docs/ownership/REQ-XXX.json` manifestini
  değiştiremez; böyle bir değişiklik diff kontrolünde açıkça reddedilir.
- Generic governance/control-plane branch'ler (req-XXX veya
  ownership-REQ-XXX desenine uymayan branch'ler, örnek: bu paketin
  geliştirildiği `ownership-ci-diff-enforcement`) yalnızca governance
  path'lerinde değişiklik yapabilir; application kodunun bu branch'lerden
  kaçırılması önlenir. Authority manifest pattern'i
  (`docs/ownership/REQ-<en az 3 rakam>.json`) bu branch sınıfı için her
  zaman açıkça reddedilir — genel `docs/` allowlist'i ownership
  manifestine örtük yetki vermez. Statik ownership dokümanları
  (`docs/ownership/README.md`, `TEMPLATE.json`, `schema.json`) bu
  pattern'e uymadığından genel `docs/` allowlist'i altında bu branch
  sınıfında değiştirilebilir; nihai onay insan review boundary'sindedir.
- Ownership manifest oluşturma/güncelleme yalnızca
  `ownership-REQ-XXX-kisa-aciklama` branch'lerinde, yalnızca kendi exact
  manifest dosyası üzerinde yapılabilir; bu branch sınıfı başka hiçbir
  path'i değiştiremez ve manifesti silemez.
- Diff hesaplaması `git diff --raw` ile mode bilgisini taşıdığından,
  symlink (`120000`) veya gitlink/submodule (`160000`) içeren herhangi bir
  diff girdisi, branch sınıfından bağımsız olarak fail-closed reddedilir.
- CI bu aşamada **custom agent identity'sini hâlâ doğrulamaz**; yalnızca
  diff'in path ownership kurallarına uyup uymadığını doğrular. Agent
  kimliği doğrulaması runtime hook'un (ADR-003) sorumluluğunda kalır.
- Bu paket henüz bir GitHub Actions workflow YAML'ı eklemez. Otoriter
  workflow, ileride `pull_request_target` üzerinde **yalnızca trusted base
  branch'teki** `scripts/validate_ownership_diff.py` script'ini
  çalıştıracak şekilde tasarlanmalıdır; PR head kodu hiçbir biçimde
  checkout veya execute edilmemelidir — aksi halde bir saldırgan PR head'i
  üzerinden bu validator'ı kendi lehine değiştirebilir. Workflow token'ı
  least privilege/read-only olmalıdır (örnek: `contents: read`,
  `pull-requests: read`).
- Nihai merge kararı insan onayında kalır; bu ADR ve script tek başına bir
  merge yetkisi vermez. CI diff validator yalnızca bir **gate**'tir, merge
  butonunu otomatik basmaz.
- Control-plane dosyaları (`.claude`, `.github`, `scripts`) hâlâ insan
  review boundary'sine tabidir; bu paket bunların gerçekten bir insan
  tarafından değiştirildiğini kriptografik olarak kanıtlamaz. Bu garanti,
  ileride bağlanacak GitHub branch protection ve CODEOWNERS modelinden
  gelecektir.

## Evidence

- ADR-001-role-based-hook-enforcement.md
- ADR-002-task-ownership-manifest.md
- ADR-003-ownership-runtime-enforcement.md
- `scripts/validate_ownership_manifest.py` (`validate_manifest`
  fonksiyonu, bu ADR'de base commit snapshot'ı üzerinde yeniden kullanılır)
- `scripts/validate_ownership_diff.py` ve
  `tests/test_validate_ownership_diff.py`
- PROJECT_CONSTITUTION.md (branching policy, human approval gates)
- CLAUDE.md (delivery rules)

## Implementation Impact

- Yeni dosya: `scripts/validate_ownership_diff.py`. Yalnızca Python
  standard library kullanır; `scripts/validate_ownership_manifest.py`
  içindeki `validate_manifest`, `is_relative_safe_path` ve
  `resolve_under_root` yardımcılarını içe aktarır, mantığı kopyalamaz.
- Yeni test dosyası: `tests/test_validate_ownership_diff.py`. Her test
  kendi temporary directory'sinde bağımsız bir Git repository kurar
  (`git init`, base commit, topic branch, commit); gerçek repository veya
  worktree dosyalarına yazmaz.
- `docs/ownership/README.md` ve `docs/decisions/AGENT_CAPABILITY_MATRIX.md`
  bu CI diff enforcement davranışını yansıtacak şekilde güncellenir.
- Bu ADR `.claude/**`, `.github/**`,
  `scripts/validate_ownership_manifest.py`,
  `tests/test_validate_ownership_manifest.py`,
  `tests/test_enforce_role_boundaries.py`, `CLAUDE.md`,
  `PROJECT_CONSTITUTION.md`, `docs/ownership/schema.json`,
  `docs/ownership/TEMPLATE.json`, mevcut ADR-001/ADR-002/ADR-003 veya
  requirement/contract/handoff/release dosyalarını değiştirmez.
- CI diff validator ve testleri hazır; workflow bağlama bekliyor. Otoriter
  GitHub Actions workflow'u (`.github/workflows/ownership-governance.yml`)
  ayrı bir ADR/PR kapsamında eklenecektir.
- Security Red Team review'ın authority-escalation bulgusuna yanıt olarak:
  `tests/test_validate_ownership_diff.py`'ye generic governance branch'in
  `docs/ownership/REQ-XXX.json` değiştirememesi, ownership registry
  branch'in yalnızca kendi exact manifest dosyasını değiştirebilmesi,
  registry branch'te ekstra dosya değişikliğinin reddedilmesi, branch
  REQ-ID'siyle manifest dosya adı uyuşmazlığının reddedilmesi, manifest
  silmenin reddedilmesi ve req branch'te owner path altında symlink/
  gitlink eklenmesinin reddedilmesi senaryolarını kapsayan testler
  eklenmiştir.
- Self-consistency düzeltmesi olarak: `tests/test_validate_ownership_diff.py`'ye
  generic governance branch'in `docs/ownership/README.md`,
  `docs/ownership/TEMPLATE.json` ve `docs/ownership/schema.json`
  değişikliklerini kabul etmesini, ownership registry branch'in ise aynı
  statik dosyaları (README, schema) reddetmeye devam etmesini doğrulayan
  testler eklenmiştir. Bu, validator'ın `docs/ownership/**` altındaki her
  şeyi değil yalnızca `REQ-<en az 3 rakam>.json` authority manifest
  pattern'ini koruduğunu doğrular.

## Approval

- **Required approver:** Human maintainer
- **Approval status:** Pending
- **Approval evidence:** Reviewed pull request and merge to main
