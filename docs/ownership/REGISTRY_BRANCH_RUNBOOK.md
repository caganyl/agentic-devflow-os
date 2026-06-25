# Ownership Registry Branch Runbook

## Amaç

Bu doküman, `docs/ownership/REQ-XXX.json` **authority manifest**'lerinin
oluşturulma ve `draft` ↔ `approved` lifecycle güncelleme prosedürünü tarif
eder. Bu doküman manifest sözleşmesini (ADR-002), runtime enforcement'ı
(ADR-003) ve CI diff enforcement'ı (ADR-004) **icat etmez**; bu kabul edilmiş
ADR'lerde tanımlanan kuralları operasyonel bir adım listesine dönüştürür.

**Bu doküman, hiçbir manifest dosyası oluşturmaz, düzenlemez, approve etmez
veya lifecycle durumunu değiştirmez.** Governance Operations Author rolü bu
sınır içinde çalışır; manifest yazma ve onaylama yetkisi yalnızca insan
maintainer'a aittir (ADR-002).

## Manifest ile Statik Ownership Dokümanlarının Farkı

| | Authority manifest | Statik ownership dokümanı |
| --- | --- | --- |
| Dosya | `docs/ownership/REQ-XXX.json` | `docs/ownership/README.md`, `TEMPLATE.json`, `schema.json`, bu runbook |
| Rol | Belirli bir REQ için yazma yetkisi kaynağı | Prosedür/şema bilgisi, nasıl kullanılır rehberi |
| Kim yazar | Yalnızca insan maintainer (registry branch üzerinden) | Governance Operations Author (insan review ile) |
| Branch | `ownership-REQ-XXX-kisa-aciklama` | Generic governance branch |
| CI davranışı | Authority manifest pattern'i (`REQ-<3+ rakam>.json`) yalnızca registry branch'te değişebilir | Genel `docs/` allowlist'i altında generic governance branch'te değişebilir |

Bu ayrım ADR-004'ün Security Red Team bulgusuna yanıtıdır: generic governance
branch'lerin authority manifest'i değiştirip sahte/genişletilmiş bir yetki
oluşturmasını önlemek için bu iki dosya sınıfı CI tarafından farklı
muamele görür.

## Yalnızca İnsan Maintainer'ın Approval Sorumluluğu

- Manifest yalnızca insan maintainer tarafından oluşturulur ve `approved`
  duruma getirilir (ADR-002, `docs/ownership/README.md` "Manifestin
  Sahibi").
- Implementer agent'lar (`frontend-engineer`, `backend-engineer`,
  `database-engineer`, `qa-automation`, `ai-data-engineer`) manifesti
  değiştiremez; manifest onların yazma yetkisinin girdisidir, çıktısı
  değildir.
- Governance Operations Author manifest dosyasını oluşturamaz, düzenleyemez
  veya approve edemez; bu rolün yazabileceği alan bu runbook'un kendisi ve
  diğer statik ownership dokümanlarıdır, `REQ-XXX.json` değildir.
- `status: approved` ve `approval.approved_by`/`approved_at` alanlarının
  doluluğu CI tarafından teknik olarak doğrulanır, ancak CI bu approval'ın
  gerçekten bir insan maintainer tarafından verildiğini kriptografik olarak
  kanıtlayamaz (ADR-004). Nihai approval boundary'si GitHub PR review,
  branch protection ve CODEOWNERS sürecindedir.

## Registry Branch Formatı

- Kesin biçim: `ownership-REQ-XXX-kisa-aciklama` (örnek:
  `ownership-REQ-042-login-flow`).
- `XXX`, manifestteki `req_id` alanındaki rakamlarla karakter karakter
  (sıfır dahil) eşleşmelidir.
- Bu branch sınıfı, generic governance branch'lerden ve implementation
  (`req-XXX-*`) branch'lerinden tamamen ayrıdır (ADR-004).

## Registry Branch Üzerinde Yalnızca Kendi Exact Manifest Dosyasının Değişebileceği

- Diff'te **yalnızca** `docs/ownership/REQ-XXX.json` (branch adındaki REQ-ID
  ile tam eşleşen) bulunabilir.
- Manifestin silinmesi (`D` statüsü) reddedilir; manifest head commit'te
  mevcut olmalıdır.
- Bu kontrol `scripts/validate_ownership_diff.py` tarafından CI'da
  uygulanır (ADR-004).

## Yasak Değişiklik Örnekleri

Registry branch'te aşağıdakilerin **hiçbiri** değiştirilemez; biri diff'te
görünürse PR reddedilir:

- Application kodu (örnek: `apps/**`).
- Test dosyaları (`tests/**`).
- Workflow dosyaları (`.github/**`).
- Hook dosyaları (`.claude/**`).
- `docs/ownership/README.md`, `docs/ownership/TEMPLATE.json`,
  `docs/ownership/schema.json` (bunlar generic governance branch'te
  değişir, registry branch'te değil).
- Başka bir manifest (örnek: `docs/ownership/REQ-099.json` iken branch
  `ownership-REQ-042-...` ise).
- Requirement, ADR veya contract dosyaları (`docs/product/**`,
  `docs/architecture/**`, `docs/contracts/**`).

## Manifest Oluşturma Ön Koşulları

Registry branch açılmadan önce **base branch'te** (registry branch'in kendisi
değil) şunlar hazır olmalı:

- Requirement dosyası (`references.requirement`).
- Acceptance criteria dosyası (`references.acceptance_criteria`).
- En az bir onaylı contract referansı **veya** doldurulmuş
  `contract_exception` (`reason`, `approved_by`, `approved_at`).
- Referans verilecek ADR'ler (varsa) "Accepted" durumda.

Registry branch kendi içinde requirement veya contract icat edemez; CI bu
referansları **base** commit snapshot'ından materialize edip doğrular
(ADR-004). Bu nedenle sıra önemlidir: önce requirement/contract base branch'te
olmalı, sonra registry branch manifesti oluşturabilir.

## `approved` Status ve Approval Alanlarının İnsan Kararı Olması

- `status: approved` bir teknik alan değeri değil, bir insan kararının
  kaydıdır.
- `approval.approved_by` ve `approval.approved_at` boş bırakılamaz
  (schema zorunluluğu), ancak bu alanların doğru/gerçek bir insanı
  yansıttığının garantisi süreçseldir — PR review sürecinden gelir, hook
  veya CI'dan değil.
- Bir manifest `draft` durumdayken implementer agent o REQ-ID kapsamında
  kod yazamaz (runtime hook bunu fail-closed reddeder).

## PR Review Akışı

1. İnsan maintainer, base branch'teki requirement/acceptance
   criteria/contract referanslarının hazır olduğunu doğrular.
2. İnsan maintainer `ownership-REQ-XXX-kisa-aciklama` branch'inde manifesti
   `docs/ownership/TEMPLATE.json` üzerinden oluşturur veya mevcut manifesti
   günceller.
3. PR açılır; `PR Quality` ve `Ownership Diff Gate` workflow'ları çalışır.
4. İnsan maintainer `docs/operations/HUMAN_MERGE_CHECKLIST.md`'yi uygular.
5. Her şey doğrulandıktan sonra insan maintainer PR'ı merge eder.

## CI Validator'ın Doğrulayabildiği ve Doğrulayamadığı Şeyler

**Doğrulayabildiği:**

- Diff'in yalnızca exact `docs/ownership/REQ-XXX.json` path'ini içerdiği.
- Manifestin silinmediği.
- Manifest dosya adının branch REQ-ID'siyle eşleştiği.
- Manifestin şema kurallarına (`schema.json`) uyduğu: alan zorunlulukları,
  `status` enum değeri, `approval` alanlarının doluluğu, owner/path yapısı.
- Referans dosyalarının (`requirement`, `acceptance_criteria`, `contracts`,
  `adrs`) **base** snapshot'ta gerçekten var olduğu.
- Symlink/gitlink mode değişikliği olmadığı.

**Doğrulayamadığı:**

- `approval.approved_by` alanındaki değerin gerçekten o insanı temsil ettiği.
- Approval kararının gerçekten bir insan maintainer tarafından, doğru bir
  değerlendirmeyle verildiği (CI bunu kriptografik olarak kanıtlayamaz).
- Manifestteki `write_paths` kapsamının iş gereksinimine göre "doğru"
  genişlikte olup olmadığı (bu bir insan judgment'ıdır).
- PR'ı gerçekten kimin (hangi GitHub hesabının) açtığı dışında, commit
  author/committer bilgisinin güvenilir bir kimlik kanıtı olduğu.

## Manifest Merge Sonrası Implementation Branch'in Base Authority Modeli

- Registry branch merge edildikten sonra, `main`'deki (veya ilgili base
  commit'teki) manifest, `req-XXX-kisa-aciklama` implementation branch'i
  için **tek yetki kaynağı** olur.
- İmplementation branch PR'ının diff'i değerlendirilirken manifest
  **yalnızca base commit'ten** okunur; PR head'indeki manifest hiçbir
  biçimde yetki kaynağı olarak kullanılmaz (ADR-004). Bu, bir implementation
  PR'ının kendi manifestini değiştirerek kendine yeni yetki vermesini
  önler.
- İmplementation branch diff'inde `docs/ownership/` altında herhangi bir
  değişiklik varsa CI tarafından reddedilir.

## Hatalı Manifest veya Scope Değişikliği Durumunda Ne Yapılır

- Manifestte hata (yanlış path, eksik referans, dar/geniş scope) fark
  edilirse **yeni bir registry branch** (`ownership-REQ-XXX-...`) açılır ve
  manifest güncellenir; implementation branch'inden doğrudan düzeltme
  yapılmaz.
- Scope değişikliği gerekiyorsa (örnek: yeni bir `write_paths` eklenmesi)
  bu da bir registry branch güncellemesi olarak insan maintainer tarafından
  yapılır, asla implementation branch içinden değil.
- Manifest `superseded` veya `closed` duruma geçirilecekse bu da insan
  maintainer kararıyla registry branch üzerinden yapılır.
- Eğer hata zaten merge edilmiş bir implementation PR'ında fark edildiyse,
  bu durum bir handoff'ta ve gerekiyorsa bir Security Red Team incelemesinde
  not edilir; bu runbook bu geri-dönüş kararını insan maintainer'a bırakır.

## Human Approval Checklist

- [ ] Requirement ve acceptance criteria base branch'te mevcut ve
      tamamlanmış.
- [ ] Contract referansı mevcut veya `contract_exception` insan onaylı
      şekilde doldurulmuş.
- [ ] `owners[].write_paths` arasında overlap yok.
- [ ] `write_paths` korunan governance/enforcement dosyalarını
      (`docs/ownership/README.md` listesi) içermiyor.
- [ ] Branch adı `ownership-REQ-XXX-kisa-aciklama` formatına ve manifestteki
      `req_id`'ye tam uyuyor.
- [ ] Diff'te yalnızca exact manifest dosyası var.
- [ ] `PR Quality` ve `Ownership Diff Gate` başarılı.
- [ ] Onaylayan kişi (insan maintainer) ve onay tarihi kayıt altında.
- [ ] Manuel merge insan maintainer tarafından yapılıyor (branch protection
      mevcut planda aktif değil; bu adım manuel telafi edici kontroldür,
      bkz. `docs/operations/HUMAN_MERGE_CHECKLIST.md`).

## Açık Kararlar

- Manifest hatası merge sonrası fark edilirse hangi ek inceleme (Security
  Red Team, Delivery Lead) zorunlu kılınacağı bu runbook'ta tanımlanmamıştır.
- REQ-ID'nin kim tarafından ve ne zaman rezerve edileceği (registry branch
  açılmadan önce) ayrı bir operasyonel karardır; bkz.
  `docs/operations/REQ_LIFECYCLE_RUNBOOK.md` Açık Kararlar.
- Branch protection/ruleset ile `Ownership Diff Gate`'in required check
  olarak bağlanması GitHub Pro/uygun plan erişimine bağlıdır; bu an itibarıyla
  tamamlanmamış bir takip kalemidir (ADR-004).
