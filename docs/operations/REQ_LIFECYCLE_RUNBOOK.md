# REQ Lifecycle Runbook

## Amaç ve Kapsam

Bu runbook, bir fikrin REQ-ID'li bir requirement'a dönüşmesinden, ownership
manifestinin onaylanmasına, implementation branch'inde çalışmaya, test/evidence
toplanmasına ve insan onaylı main merge'e kadar olan operasyonel akışı tarif
eder.

Bu doküman:

- Yeni requirement, contract, ADR veya ownership manifesti üretmez.
- Mevcut accepted ADR'lerin (ADR-001, ADR-002, ADR-003, ADR-004) ve
  `PROJECT_CONSTITUTION.md` / `CLAUDE.md` kurallarının üzerine yeni teknik
  politika icat etmez; bu kaynaklarda tanımlı sınırları operasyonel adımlara
  döker.
- Statik bir prosedür referansıdır; belirli bir REQ'nin gerçek durumu için
  ilgili `docs/ownership/REQ-XXX.json` manifesti ve `docs/handoffs/REQ-XXX.md`
  handoff'u canonical kaynaktır.

## Lifecycle Özeti

```
Fikir
  -> Requirement taslağı (Product Analyst)
  -> Acceptance criteria + scope (Product Analyst)
  -> [Gerekirse] Architecture/Contract değerlendirmesi (Solution Architect / Contract Broker)
  -> Ownership manifest ön koşullarının sağlanması
  -> Registry branch: ownership-REQ-XXX-kisa-aciklama (insan maintainer onayı)
  -> Implementation branch: req-XXX-kisa-aciklama (implementer agent + runtime enforcement)
  -> Test / evidence / handoff
  -> Human merge boundary (Human Merge Checklist)
  -> Main merge (insan maintainer)
  -> Release / deploy sınırları (insan onayı)
```

Her ok bir insan veya teknik kapıyı temsil eder; bir adım atlanarak
sonraki adıma geçilemez.

## Başlangıç Koşulları

- Source of truth hiyerarşisi netleşmiş olmalı: PROJECT_CONSTITUTION.md →
  accepted ADR → onaylı contract → requirement/acceptance criteria → kod/test
  → handoff → NotebookLM → Obsidian.
- NotebookLM ve Obsidian bu akışın hiçbir adımında onay veya karar kaynağı
  olarak kullanılmaz; yalnızca açıkça kaynak gösterilen destekleyici bilgi
  olabilir.
- Bir Claude session main branch üzerinde başlamışsa bu session branch
  oluşturmaz, branch değiştirmez veya worktree yaratmaz (CLAUDE.md). Yeni bir
  REQ akışı için kullanıcı normal terminalde uygun worktree'yi açar.

## 1. Fikirden REQ'ye Geçiş

- Fikir, ham haliyle requirement değildir. Bir REQ-ID atanmadan implementation
  başlamaz (CLAUDE.md: "Requirement ID olmadan yeni ürün davranışı icat
  etme.").
- REQ-ID formatı mevcut sistemde `REQ-XXX` (en az 3 rakam) olarak kullanılır
  (`docs/ownership/schema.json` pattern: `^REQ-[0-9]{3,}$`).
- **Human Decision Required:** REQ-ID'nin ne zaman ve kim tarafından
  numaralandırılacağı (sıralı atama, kayıt defteri vb.) bu runbook'ta
  tanımlanmamıştır; bu, insan maintainer/Delivery Lead operasyonel kararıdır.

## 2. Product Analyst Sorumluluğu

Product Analyst, REQ-ID altında şu çıktıları üretir (`docs/product/`
alanında):

- **Requirement**: amaç, kullanıcı problemi, beklenen davranış.
- **User story**: rol, ihtiyaç, fayda.
- **Acceptance criteria**: doğrulanabilir, test edilebilir kriter listesi.
- **Scope / out-of-scope**: bu REQ'nin neyi kapsadığı ve kapsamadığı.
- **Risk ve dependency**: bilinen riskler, bağımlı diğer REQ'ler veya
  sistemler.

Bu adımın çıktısı olmadan:

- Ownership manifesti `approved` duruma geçemez (`docs/ownership/README.md`
  "Ön Koşullar").
- Implementer agent runtime enforcement koşulu sağlanamaz.

## 3. Architecture / Contract Değerlendirmesi Gerektiren Karar Noktaları

Aşağıdaki durumlarda Product Analyst aşamasından sonra, ownership manifesti
oluşturulmadan önce ek değerlendirme gerekir:

- Yeni veya değişen bir mimari karar gerekiyorsa → Solution Architect bir ADR
  taslağı hazırlar; ADR insan maintainer tarafından "Accepted" duruma
  getirilmeden bu karar canonical sayılmaz.
- Yeni veya değişen bir API/event/database contract gerekiyorsa → Contract
  Broker contract'ı hazırlar; onaylı contract olmadan frontend/backend paralel
  geliştirme başlamaz (CLAUDE.md).
- Contract gerekmiyorsa, manifestin `references.contract_exception` alanında
  insan onaylı `reason`/`approved_by`/`approved_at` doldurulmalıdır
  (`docs/ownership/README.md` Ön Koşullar).

**ADR eşiği:** ADR yalnızca şu durumlardan en az biri varsa yazılır: yeni dış
bağımlılık/servis, bounded context'ler arası veri modeli veya migration
değişikliği, auth/güvenlik sınırı değişikliği, geriye uyumsuz public
API/event contract değişikliği, geri alınması pahalı karar. Eşiği Delivery
Lead uygular; tereddütte insan maintainer karar verir. Eşik yoksa
`docs/decisions/` altında kısa bir karar notu yeterlidir.

**Review döngüsü:** ADR'yi `adr-reviewer` inceler (VERDICT: APPROVE |
APPROVE_WITH_NOTES | BLOCK). En fazla 2 tur yapılır; ikinci turdan sonra açık
BLOCKER kalırsa karar insana geçer. Accepted ADR dondurulur. Bu sınırlar
`.claude/hooks/enforce-role-boundaries.sh` içindeki ADR loop breaker ile
zorlanır.

## 4. Ownership Manifest Ön Koşulları

İmplementer agent yazma yetkisi alabilmesi için manifestin `approved` olmadan
önce şunlar doğrulanmalıdır (`docs/ownership/README.md`):

- `references.requirement` ve `references.acceptance_criteria` repository
  içinde gerçekten var olan dosyalara işaret etmeli.
- En az bir `references.contracts` girdisi **veya** doldurulmuş
  `references.contract_exception` bulunmalı.
- `owners[].write_paths` arasında overlap olmamalı.
- Manifest yalnızca insan maintainer tarafından oluşturulur ve `approved`
  duruma getirilir; implementer agent'lar manifesti değiştiremez
  (ADR-002, ADR-003).

Bu ön koşullar sağlanmadan registry branch açılması anlamsızdır; çünkü
`validate_ownership_manifest.py` manifesti reddedecektir.

## 5. Registry Branch Aşaması

- Branch formatı: `ownership-REQ-XXX-kisa-aciklama` (örnek:
  `ownership-REQ-042-login-flow`) — bu, mevcut sistemde tanımlı kesin biçimdir
  (ADR-004, `docs/ownership/README.md`).
- Bu branch **yalnızca** `docs/ownership/REQ-XXX.json` dosyasını değiştirebilir.
  Detaylar için `docs/ownership/REGISTRY_BRANCH_RUNBOOK.md`.
- Manifestin `status: approved` olması ve `approval.approved_by`/
  `approved_at` alanlarının doldurulması insan maintainer kararıdır; CI bu
  doluluğu teknik olarak doğrular ama approval'ın gerçekten bir insan
  tarafından verildiğini kriptografik olarak kanıtlayamaz (ADR-004).
- Registry branch PR'ı insan maintainer tarafından review edilip merge edilir.
  Bu da bir main merge işlemi olduğundan human merge boundary geçerlidir.

## 6. Implementation Branch Aşaması

- Branch formatı: `req-XXX-kisa-aciklama` (örnek: `req-042-login-flow`) —
  mevcut sistemde tanımlı kesin biçim (ADR-003, `docs/ownership/README.md`).
  `XXX`, manifestteki rakamlarla karakter karakter (sıfır dahil) eşleşmelidir.
- Yalnızca implementer agent'lar (`frontend-engineer`, `backend-engineer`,
  `database-engineer`, `qa-automation`, `ai-data-engineer`) bu branch'te
  Edit/Write yapabilir; her branch/worktree'de bir writer agent çalışır
  (PROJECT_CONSTITUTION.md).
- Runtime hook (`.claude/hooks/enforce-role-boundaries.sh`), her Edit/Write
  çağrısında şu zinciri sırayla doğrular (ADR-003):
  1. Branch deseni `req-XXX-...` ile eşleşmeli.
  2. Branch'teki REQ-ID'ye karşılık gelen `docs/ownership/REQ-XXX.json`
     bulunmalı.
  3. Manifest `approved` durumda olmalı.
  4. Çağrıyı yapan agent manifestte owner olarak tanımlı olmalı.
  5. Hedef path, o agent'ın `write_paths` alanı altında olmalı.
  Bu beşi sağlanmazsa çağrı fail-closed reddedilir.
- **Runtime hook ile CI diff gate farkı:** Runtime hook yalnızca Claude'un
  Edit/Write araç çağrısını ve çağrıyı yapan agent kimliğini denetler. Bash
  üzerinden veya normal terminalden yapılan değişiklikler bu hook'un kapsamı
  dışındadır. CI diff gate (`scripts/validate_ownership_diff.py`), agent
  kimliğini bilmez; PR'ın tam diff'ini base commit'teki approved manifestin
  `write_paths` alanlarına göre merge-time'da denetler (ADR-004). İkisi
  birbirinin yerini almaz, tamamlayıcıdır.
- İmplementation branch kendi `docs/ownership/REQ-XXX.json` manifestini
  değiştiremez; böyle bir diff CI tarafından reddedilir (ADR-004).

## 7. Test / Evidence / Handoff Aşaması

- İlgili rol (implementer veya QA Automation) testleri çalıştırır; lint,
  typecheck ve hedef test suite sonuçları raporlanır (CLAUDE.md Quality
  Rules).
- Non-trivial her iş sonunda `docs/handoffs/REQ-XXX.md` formatında bir
  handoff güncellenir (`docs/handoffs/README.md`). Şablon için
  `docs/templates/REQ_HANDOFF_TEMPLATE.md` kullanılır.
- Integration/Release agent (varsa) release-readiness kanıtını ve handoff'ı
  hazırlar; merge yapmaz (`AGENT_CAPABILITY_MATRIX.md`).

## 8. Human Merge Boundary

- Hiçbir agent main branch'e doğrudan yazamaz veya merge yapamaz
  (PROJECT_CONSTITUTION.md, AGENT_CAPABILITY_MATRIX.md).
- Merge öncesi `docs/operations/HUMAN_MERGE_CHECKLIST.md` insan maintainer
  tarafından uygulanır.
- **Repository plan sınırlaması:** Private repository'nin mevcut planında
  branch protection/rulesets API erişimi engellidir; required status check
  zorlaması teknik olarak aktif değildir (ADR-004 Acceptance Evidence). Bu
  nedenle `Ownership Diff Gate` ve `PR Quality` workflow sonuçlarının başarılı
  olduğunun manuel insan doğrulaması zorunludur.

## 9. Main Sonrası Release / Deploy Sınırları

- Production deploy, production database migration ve secret/API key/cloud
  resource değişiklikleri yalnızca insan onayıyla yapılır
  (PROJECT_CONSTITUTION.md §3).
- Hiçbir agent bu işlemleri kendi kararıyla gerçekleştiremez
  (AGENT_CAPABILITY_MATRIX.md "Evrensel Kurallar").
- Release sonrası evidence, handoff'a eklenir; rollback/recovery notları
  handoff şablonunda ayrı bir alandır.

## 10. Başarısızlık / Eksik Kanıt Durumunda Geri Dönüş Akışı

| Durum | Geri dönüş |
| --- | --- |
| Acceptance criteria eksik/belirsiz | Implementation durur, Product Analyst'e geri döner. |
| Contract eksik ve exception onaylanmamış | Manifest `approved` olamaz; Contract Broker veya insan onayı beklenir. |
| Manifest `draft`/`superseded`/`closed` | Implementer runtime hook tarafından reddedilir; registry branch'te güncellenmesi gerekir. |
| Runtime hook deny | Agent, branch/manifest/owner/path uyuşmazlığını düzeltmeden ilerleyemez. |
| CI `Ownership Diff Gate` veya `PR Quality` başarısız | Merge reddedilir; PR düzeltilip yeniden çalıştırılır (Human Merge Checklist). |
| Test/evidence eksik | Handoff "Go" olarak işaretlenemez; Integration/Release "No-Go" veya "Conditional Go" önerir. |
| Manifest hatalı/scope dışı | `docs/ownership/REGISTRY_BRANCH_RUNBOOK.md` "Hatalı manifest" bölümüne göre yeni registry branch ile düzeltilir. |

## Sorumluluk Matrisi

| Aşama | Sorumlu | Onay |
| --- | --- | --- |
| Requirement / acceptance criteria | Product Analyst | İnsan onayı (Açık Karar: kesin onaycı rolü) |
| ADR | Solution Architect | İnsan maintainer ("Accepted") |
| Contract | Contract Broker | İnsan onayı |
| Ownership manifest | İnsan maintainer | İnsan maintainer (manifesti yalnızca insan oluşturur/approve eder) |
| Implementation | İlgili implementer agent | Runtime hook + CI diff gate teknik kontrolü |
| Test/evidence/handoff | İlgili implementer / QA Automation / Integration-Release | İnsan review |
| Main merge | İnsan maintainer | Zorunlu insan onayı |
| Production deploy/migration/secret | İnsan maintainer | Zorunlu insan onayı |

## Açık Kararlar

- REQ-ID numaralandırma sahibi ve mekanizması bu runbook'ta tanımlanmamıştır.
- Contract gerekliliği eşiği hâlâ açık bir sorudur (ADR eşiği §3'te tanımlandı).
- Branch protection/rulesets teknik enforcement'ı GitHub Pro/uygun plan
  erişimi sağlanana kadar devreye alınmamıştır (ADR-004); bu süre boyunca
  Human Merge Boundary zorunlu telafi edici kontroldür.
- Bu runbook'ta tarif edilen "kisa-aciklama" branch segmentinin biçimi
  (kebab-case, uzunluk vb.) için takım konvansiyonu mevcut ADR'lerde
  tanımlanmamıştır; önerilen ekip konvansiyonu olarak kısa, kebab-case bir
  açıklama kullanılabilir, ancak bu zorunlu bir kural değildir.
