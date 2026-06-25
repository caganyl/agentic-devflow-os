# Human Merge Checklist

Bu checklist, `main` branch'e merge edilecek her pull request için insan
maintainer tarafından uygulanır. Hiçbir agent bu checklist'i kendi kararıyla
tamamlayamaz veya atlatamaz; main merge yalnızca insan maintainer onayıyla
gerçekleşir (PROJECT_CONSTITUTION.md §3, AGENT_CAPABILITY_MATRIX.md
"Evrensel Kurallar").

## Ne Zaman Kullanılır

- `req-XXX-kisa-aciklama` (implementation) branch'inden açılan her PR için.
- `ownership-REQ-XXX-kisa-aciklama` (registry) branch'inden açılan her PR
  için (bkz. ayrıca `docs/ownership/REGISTRY_BRANCH_RUNBOOK.md` "Human
  Approval Checklist").
- Generic governance/control-plane branch'lerden açılan PR'lar için de bu
  checklist'in genel bölümleri (PR kapsamı, GitHub Actions, security)
  uygulanır.

## Merge Öncesi Giriş Koşulları

- [ ] PR, hedef `main` branch'i gösteriyor.
- [ ] PR'ın base ve head SHA'ları görünür ve doğrulanabilir.
- [ ] PR açıklaması ilgili REQ-ID'yi (varsa) ve handoff bağlantısını içeriyor.

## PR Kapsam ve Diff İncelemesi

- [ ] Diff'teki her dosya, PR'ın amaçladığı kapsamla tutarlı.
- [ ] Beklenmeyen/açıklanamayan dosya değişikliği yok.
- [ ] Diff'te secret, token, private key veya kişisel veri yok.
- [ ] Diff'te symlink (`120000`) veya gitlink/submodule (`160000`) mode
      değişikliği yok (varsa CI zaten reddeder; insan olarak da teyit edin).

## Branch Türü Doğrulaması

- [ ] Branch adı üç sınıftan birine uyuyor ve davranış buna göre
      değerlendiriliyor:
  - `req-XXX-kisa-aciklama` → implementation branch.
  - `ownership-REQ-XXX-kisa-aciklama` → ownership registry branch (yalnızca
    kendi exact manifest dosyasını değiştirebilir).
  - Diğer her şey → generic governance/control-plane branch (yalnızca
    `.claude/`, `.github/`, `docs/`, `scripts/`, `tests/`, `design/`,
    `evals/` önekli path'ler veya izinli kök dosyalar; authority manifest
    pattern'i `docs/ownership/REQ-<3+ rakam>.json` bu sınıfta her zaman
    reddedilir).
- [ ] Implementation branch PR'ı kendi `docs/ownership/REQ-XXX.json`
      manifestini değiştirmiyor (ADR-004; değiştiriyorsa reddet).
- [ ] Registry branch PR'ı yalnızca kendi exact `docs/ownership/REQ-XXX.json`
      dosyasını değiştiriyor, başka hiçbir path'i değiştirmiyor.

## Requirement ve Acceptance Criteria Doğrulaması

- [ ] İlgili REQ-ID'nin requirement dosyası repository'de mevcut.
- [ ] Acceptance criteria dosyası mevcut ve PR'ın teslim ettiği davranışla
      eşleşiyor.
- [ ] Scope/out-of-scope ihlali yok; varsa bu PR'da açıkça not edilmiş.

## Manifest / Ownership Authority Doğrulaması

- [ ] İlgili `docs/ownership/REQ-XXX.json` base commit'te mevcut ve
      `status: approved`.
- [ ] `approval.approved_by` ve `approved_at` alanları dolu.
- [ ] PR diff'indeki her path, manifestteki ilgili owner'ın `write_paths`
      alanlarından **tam olarak biri** altında.
- [ ] Contract referansı veya onaylı `contract_exception` mevcut
      (`docs/ownership/README.md` Ön Koşullar).
- [ ] **Not:** CI, `status: approved` alanının dolu olduğunu teknik olarak
      doğrular ama bu approval'ın gerçekten bir insan tarafından verildiğini
      kriptografik olarak kanıtlayamaz (ADR-004). Bu kanıtı insan maintainer
      burada manuel olarak sağlar.

## Test ve Evidence Doğrulaması

- [ ] İlgili testler çalıştırılmış ve sonuçlar PR/handoff içinde raporlanmış.
- [ ] Lint, typecheck ve hedef test suite sonuçları raporlanmış
      (CLAUDE.md Quality Rules).
- [ ] UI değişikliği varsa loading, empty, error, permission ve mobile
      state'leri kontrol edilmiş.
- [ ] AI feature değişikliği varsa eval/regression kontrolü güncellenmiş.
- [ ] `docs/handoffs/REQ-XXX.md` güncel ve bu PR'ın kapsamını yansıtıyor.

## GitHub Actions Doğrulaması

- [ ] `PR Quality` workflow job'u başarılı (yeşil).
- [ ] `Ownership Diff Gate` workflow job'u başarılı (yeşil) — implementation
      veya registry branch ise zorunlu; generic governance branch'te de
      çalışır ve başarılı olmalı.
- [ ] Her iki job da PR'ın **son** commit'i için çalışmış (eski/stale check
      değil).

## Security, Data, Migration, Secret ve External Integration Kontrolleri

- [ ] PR production altyapısını, database'i veya deployment'ı değiştirmiyor
      (CLAUDE.md Security Rules) — değiştiriyorsa bu PR reddedilir veya ayrı
      bir insan onaylı sürece yönlendirilir.
- [ ] Database migration varsa rollback notu mevcut.
- [ ] Secret/API key/cloud resource değişikliği yok; varsa bu PR'da
      yapılmaz, ayrı insan onaylı bir kanal kullanılır (PROJECT_CONSTITUTION
      §3).
- [ ] Dış sistem entegrasyonu, kullanıcı verisi veya ödeme akışı varsa insan
      onayı ayrıca kayıt altına alınmış.
- [ ] Security Red Team bulgusu varsa fix uygulanmış ve doğrulanmış; bulgu
      kapatma kararı insan onayında.

## Human Decision Kaydı

- [ ] Reviewer adı/kimliği kayıtlıdır.
- [ ] Onay tarihi kayıtlıdır.
- [ ] Onay gerekçesi (kısa not) PR yorumu veya handoff'a eklenmiştir.

## Merge Reddetme / Geri Gönderme Kriterleri

Aşağıdaki durumlardan biri varsa PR merge edilmez, ilgili role geri
gönderilir:

- Manifest base commit'te `approved` değil veya mevcut değil.
- Diff, manifestteki `write_paths` dışına çıkıyor.
- `docs/ownership/REQ-XXX.json` implementation branch'te değiştirilmiş.
- Registry branch'te exact manifest dışında herhangi bir path değişmiş.
- `PR Quality` veya `Ownership Diff Gate` başarısız.
- Acceptance criteria karşılanmamış veya test kanıtı eksik.
- Secret, production değişikliği veya onaysız contract sapması tespit
  edilmiş.
- Handoff güncellenmemiş.

## Merge Sonrası Kontrol

- [ ] Merge sonrası `main` branch'te `PR Quality`/`Ownership Diff Gate`
      eşdeğeri bir doğrulama (varsa) tekrar kontrol edilmiş.
- [ ] Handoff "merged" veya equivalent bir durumla güncellenmiş.
- [ ] Release/deploy gerekiyorsa bu, ayrı bir insan onaylı adım olarak
      planlanmış (bu checklist deploy onayı vermez).

## Private Repo Plan Sınırlaması Nedeniyle Manuel Uygulanacak Human Merge Boundary

- **Branch protection durumu:** Repository'nin mevcut private planında
  branch protection ve rulesets API erişimi engellidir; bu nedenle
  `Ownership Diff Gate` ve `PR Quality` şu anda GitHub tarafından "required
  check" olarak teknik zorlanmamaktadır (ADR-004 Acceptance Evidence).
- Bu kısıtlama nedeniyle yukarıdaki "GitHub Actions Doğrulaması" bölümü
  **manuel olarak** insan maintainer tarafından her merge öncesinde
  uygulanmalıdır; check'lerin yeşil olduğunu görmeden merge yapılmaz.
- GitHub Pro veya uygun bir plana geçildiğinde, `Ownership Diff Gate`
  branch protection/ruleset üzerinde required check olarak bağlanmalıdır;
  bu açık bir takip kalemidir (ADR-004).
- Bu manuel telafi mevcut olduğu sürece, bu checklist'in atlanması (örnek:
  check'leri görmeden merge etmek) governance modelini fiilen devre dışı
  bırakır; bu nedenle bu adım zorunlu kabul edilmelidir.
