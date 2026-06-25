# AC-REQ-001 — Acceptance Criteria: MCP Hook Lifecycle Synthetic Validation

## Metadata

| Alan              | Değer                                                                             |
|-------------------|-----------------------------------------------------------------------------------|
| **REQ ID**        | REQ-001                                                                           |
| **AC Dokümanı**   | AC-REQ-001                                                                        |
| **Status**        | Proposed                                                                          |
| **Date**          | 2026-06-25                                                                        |
| **REQ Referansı** | `docs/product/requirements/REQ-001-mcp-hook-lifecycle-synthetic-validation.md`    |

---

> **Önemli:** Bu AC dokümanı yalnızca sentetik validation test paketinin
> davranışını tanımlar. Gerçek MCP bağlantısı, hook implementasyonu,
> credential veya audit logging altyapısı bu kriterlerin kapsamı dışındadır.
> İnsan onayı olmadan implementation başlamaz.

---

## AC-001 — Known Tool Identity Sınıflandırması

**Başlık:** Allowlist'teki bir MCP tool identity, sentetik `PreToolUse`
payload'ından doğru biçimde sınıflandırılabilir.

**Given:**
`MCP_AGENT_CAPABILITY_MATRIX.md` allowlist'inde tanımlı, geçerli bir
`mcp_server` ve `mcp_tool` değeri içeren sentetik bir `PreToolUse` payload'ı
test fixture'ı olarak hazırlanmıştır. Fixture yalnızca sentetik değerler
içerir; gerçek endpoint, token, credential veya PII bulunmaz.

**When:**
Bu sentetik payload, tool identity sınıflandırma mantığına iletilir.

**Then:**
- Sınıflandırma sonucu `"unclassified"` değil, allowlist'te karşılık
  bulunan canonical etiket olmalıdır.
- Üretilen `mcp_server` ve `mcp_tool` alanları, `^[a-z0-9][a-z0-9._-]{0,63}$`
  formatına uyan, yalnızca lowercase ASCII karakterlerden oluşan canonical
  değerler içermelidir.
- Ham payload string'i audit alanlarına doğrudan kopyalanmamış olmalıdır;
  canonical etiket local allowlist/map üzerinden üretilmelidir.
- `policy_decision` alanı `"deny"` veya `"not_evaluated"` olmamalıdır
  (başarılı sınıflandırma durumunda).

**Evidence:**
Test çalıştırıldığında PASS sonucu ve canonical etiketin `"unclassified"`
olmadığını gösteren açık assertion çıktısı.

**Failure Condition:**
- Sınıflandırma `"unclassified"` döndürüyorsa.
- Ham payload string'i audit alanına doğrudan yazılmışsa.
- `mcp_server` veya `mcp_tool` alanı 64 karakteri aşıyorsa veya
  `^[a-z0-9][a-z0-9._-]{0,63}$` formatına uymuyorsa.
- Assertion belirsiz veya yoksa.

---

## AC-002 — Unknown / Allowlist-Dışı Tool Identity → Sentinel Model

**Başlık:** `MCP_AGENT_CAPABILITY_MATRIX.md` dışında kalan bir tool identity,
ham string persist edilmeden sentinel değerlerle reddedilir.

**Given:**
`MCP_AGENT_CAPABILITY_MATRIX.md` allowlist'inde **bulunmayan** bir
`mcp_server` ve/veya `mcp_tool` değeri içeren sentetik bir `PreToolUse`
payload'ı hazırlanmıştır (örn. `"unknown-mcp-server"`, `"undocumented-tool"`
gibi tamamen sentetik değerler). Fixture yalnızca sentetik değerler içerir.

**When:**
Bu payload tool identity sınıflandırma mantığına iletilir ve audit event
üretme süreci çalıştırılır.

**Then:**
Üretilen audit event şu **sabit sentinel değerleri** içermelidir:

- `mcp_server: "unclassified"`
- `mcp_tool: "unclassified"`
- `policy_decision: "deny"`
- `failure_category: "unclassified_tool_identity"`
- `outcome: "blocked"` veya `"denied"`

Ek olarak:
- Gelen unknown string (`"unknown-mcp-server"` vb.) hiçbir audit alanına,
  serbest metin alana veya human-visible signal'e yazılmamış olmalıdır.
- Dış MCP çağrısı dispatch edilmemiş olmalıdır.

**Evidence:**
PASS sonucu; audit event'in tam olarak dört sentinel alanı içerdiğini
gösteren assertion çıktısı; ham string'in hiçbir alanda bulunmadığını
gösteren negatif assertion.

**Failure Condition:**
- `mcp_server` veya `mcp_tool` alanında `"unclassified"` yerine ham
  runtime string bulunuyorsa.
- `policy_decision` `"deny"` değilse.
- `failure_category` `"unclassified_tool_identity"` değilse.
- Ham string herhangi bir alana, serbest metin'e veya failure signal'e
  yazılmışsa.
- Assertion belirsiz veya yoksa.

---

## AC-003 — PermissionDenied ve PostToolUseFailure Lifecycle Yolu Ayrımı

**Başlık:** `PermissionDenied`, `PostToolUseFailure`'dan ayrı bir lifecycle
dalı olarak test edilir ve birbirine indirgenmez.

**Given:**
İki bağımsız sentetik senaryo hazırlanmıştır:

- **Senaryo A:** İzin reddedilen bir çağrı — tool hiç çalışmaz.
- **Senaryo B:** İzin verilen ancak gerçek execution sırasında hata oluşan
  bir çağrı (tool çalışmaya başlar ama başarısız olur).

Her iki senaryo tamamen sentetik fixture değerleri içerir; gerçek tool
execution yoktur.

**When:**
Her senaryo ayrı ayrı çalıştırılır.

**Then:**
- **Senaryo A (PermissionDenied):**
  - `event_phase: "PermissionDenied"` event'i üretilmelidir.
  - `PostToolUse` veya `PostToolUseFailure` event'i **üretilmemelidir**.
  - `outcome: "denied"` olmalıdır.
  - `policy_decision: "deny"` olmalıdır.
  - Dış MCP çağrısı dispatch edilmemiş olmalıdır.

- **Senaryo B (PostToolUseFailure):**
  - `event_phase: "PostToolUseFailure"` event'i üretilmelidir.
  - `PermissionDenied` event'i **üretilmemelidir**.
  - `outcome: "failure"` olmalıdır.
  - Gerçek execution başladıktan sonra hata oluştuğunu belirtmelidir.

**Evidence:**
Her iki senaryo için ayrı PASS sonuçları; Senaryo A'da
`PostToolUseFailure`'ın olmadığını, Senaryo B'de `PermissionDenied`'ın
olmadığını gösteren negatif assertion'lar.

**Failure Condition:**
- Senaryo A'da `PostToolUseFailure` veya `PostToolUse` event'i üretilmişse.
- Senaryo B'de `PermissionDenied` event'i üretilmişse.
- Her iki senaryo aynı event_phase ile sonuçlanmışsa (lifecycle yolları
  birleşmişse).
- Assertion belirsiz, birleşik veya yoksa.

---

## AC-004 — 15 Alanlık Kapalı Şema Doğrulaması

**Başlık:** Üretilen audit event payload'ı tam olarak 15 zorunlu alandan
oluşur; ne eksik alan ne de 15 dışında ek alan bulunur.

**Given:**
`MCP_AUDIT_EVENT_CONTRACT.md`'de tanımlı 15 zorunlu alan listesi temel
alınarak sentetik bir audit event fixture'ı hazırlanmıştır.

15 alan: `schema_version`, `event_id`, `timestamp`, `session_reference`,
`operation_reference`, `agent_type`, `event_phase`, `mcp_server`,
`mcp_tool`, `action_class`, `environment_scope`, `policy_decision`,
`outcome`, `failure_category`, `audit_record_version`.

**When:**
Sentetik payload işlenerek bir audit event üretilir ve bu event'in alan
listesi programatik olarak sayılır/doğrulanır.

**Then:**
- Event payload'ındaki alan sayısı tam olarak **15** olmalıdır.
- Yukarıdaki 15 alan listesindeki her alan event'te bulunmalıdır.
- 15 alan dışında hiçbir ek alan (`note`, `notes`, `message`,
  `error_message`, `details`, `description`, `context`, `metadata`,
  `debug`, `raw_input`, `raw_output`, `prompt`, `url`, `header`,
  `file_path`, `exception` veya başka herhangi bir alan) payload'da
  bulunmamalıdır.
- `failure_category` alanı, `outcome` `failure` veya `blocked` olmadığı
  durumlarda `null` veya yoksa bu durum kabul edilir; ancak bu durumda
  alan **sayısı 14'e düşmemelidir** (alan var ama `null`'dur).

**Evidence:**
PASS sonucu; alan sayısını gösteren açık assertion (örn. "field count: 15,
expected: 15, PASS"); yasak alanların yokluğunu doğrulayan negatif
assertion listesi.

**Failure Condition:**
- Event'teki alan sayısı 15'ten fazla veya az ise.
- 15 zorunlu alandan herhangi biri eksikse.
- Yasak alan listesindeki herhangi bir isimde alan event'te bulunuyorsa.
- Assertion belirsiz, tahmini veya yoksa.

---

## AC-005 — Yasak Veri Dışlanması

**Başlık:** Audit output'a raw tool input/output, prompt, URL, header,
token/secret, PII, dosya yolu, error/exception metni veya serbest metin
sızmaz.

**Given:**
Aşağıdaki sentetik girdileri içeren bir test fixture'ı hazırlanmıştır.
Her girdi gerçek veri **değildir**; yalnızca test için üretilmiş sentetik
karakter dizileridir:

- Sentetik ham tool input simülasyonu (örn. `"SYNTHETIC_INPUT_PAYLOAD"`)
- Sentetik ham tool output simülasyonu (örn. `"SYNTHETIC_OUTPUT_PAYLOAD"`)
- Sentetik prompt simülasyonu (örn. `"SYNTHETIC_PROMPT_TEXT"`)
- Sentetik URL simülasyonu (örn. `"https://synthetic-test.invalid/path"`)
- Sentetik authorization header simülasyonu (örn. `"Bearer SYNTHETIC_TOKEN_VALUE"`)
- Sentetik PII simülasyonu (örn. `"synthetic-user@test.invalid"`)
- Sentetik dosya yolu simülasyonu (örn. `"/synthetic/path/to/file.txt"`)
- Sentetik exception metni simülasyonu (örn. `"SyntheticError: test_exception_text"`)

**When:**
Bu fixture'lar audit event üretim sürecine girdi olarak iletilir ve
üretilen event payload'ı incelenir.

**Then:**
Üretilen audit event payload'ında aşağıdakilerin **hiçbirinin** bulunmaması
gerekir:

- Yukarıdaki sentetik girdi değerlerinden herhangi biri (ham veya kısmi)
- Sentetik URL, header, token veya hata metni içeren herhangi bir dize
- Sentetik PII değerleri
- Sentetik dosya yolu içeriği
- `note`, `notes`, `message`, `error_message`, `details`, `description`,
  `context`, `metadata`, `debug` veya başka herhangi bir serbest metin alanı

Audit event yalnızca `MCP_AUDIT_EVENT_CONTRACT.md`'deki 15 alanlı kapalı
şemadaki değerleri (enum değerleri, canonical etiketler, timestamp, UUID
gibi meta alanlar) içermelidir.

**Evidence:**
PASS sonucu; her yasak veri kategorisinin event payload'ında bulunmadığını
gösteren ayrı negatif assertion'lar.

**Failure Condition:**
- Sentetik girdi değerlerinden herhangi biri (tam veya kısmi) audit alanında
  tespit edilirse.
- Serbest metin içerikli herhangi bir alan event'te bulunursa.
- Redaction mekanizması uygulandığı halde veri hâlâ kısmi biçimde
  (örn. truncated/masked) alanda görünüyorsa.
- Assertion belirsiz veya yoksa.

---

## AC-006 — operation_reference Collision-Resistance (Paralel Operasyonlar)

**Başlık:** Paralel yürütülen iki sentetik operasyonun `operation_reference`
değerleri çakışmaz.

**Given:**
Aynı sentetik oturum içinde (aynı `session_reference`) eşzamanlı olarak
başlatılmış iki bağımsız sentetik MCP operasyonu simüle edilmiştir
(örn. Operasyon A ve Operasyon B). Her operasyon için `PreToolUse`
lifecycle event'leri üretilecektir. Her iki operasyon da tamamen sentetik
fixture değerleri kullanır.

**When:**
İki operasyon eşzamanlı (veya hızlı ardışık) biçimde işlenir ve her biri
için `operation_reference` üretilir.

**Then:**
- Operasyon A'nın `operation_reference` değeri, Operasyon B'ninkinden
  **farklı** olmalıdır.
- Operasyon A'ya ait tüm lifecycle event'leri (örn. `PreToolUse`,
  `PostToolUse`) yalnızca Operasyon A'nın `operation_reference` değerini
  taşımalıdır.
- Operasyon B'ye ait tüm lifecycle event'leri yalnızca Operasyon B'nin
  `operation_reference` değerini taşımalıdır.
- İki operasyonun event'leri aynı `operation_reference` altında
  birleşmemelidir.

**Evidence:**
PASS sonucu; Operasyon A ve B'nin `operation_reference` değerlerinin farklı
olduğunu gösteren açık eşitsizlik assertion'ı; her operasyonun event
setinin doğru `operation_reference` altında gruplandığını gösteren
korelasyon assertion'ı.

**Failure Condition:**
- İki operasyonun `operation_reference` değerleri eşitse (collision).
- Operasyon A'nın event'leri Operasyon B'nin `operation_reference` değerini
  taşıyorsa (lifecycle event'leri karışmışsa).
- Assertion belirsiz, tek operasyona ait veya yoksa.

---

## AC-007 — Sentetik Hata Senaryoları → Deny / Blocked

**Başlık:** Parser failure, malformed payload, capability mismatch ve
audit unavailable senaryolarının tamamı `deny` veya `blocked` ile
sonuçlanır; dış MCP çağrısı hiçbirinde dispatch edilmez.

**Given:**
Aşağıdaki dört bağımsız sentetik hata senaryosu hazırlanmıştır:

- **Senaryo H1 — Parser failure:** Geçersiz JSON veya beklenmeyen format
  içeren malformed `PreToolUse` payload.
- **Senaryo H2 — Malformed payload:** Zorunlu alan(lar) eksik olan veya
  yanlış tipte değer içeren payload (örn. `event_phase` alanı yok).
- **Senaryo H3 — Capability mismatch:** `MCP_AGENT_CAPABILITY_MATRIX.md`
  ile uyumsuz agent/tool/environment üçlüsü (örn. izinsiz bir agent
  rolünün izinsiz bir environment'ta tool çağırması).
- **Senaryo H4 — Audit unavailable:** Audit sink erişilemez veya durable
  write acknowledgment alınamaz simülasyonu.

**When:**
Her senaryo bağımsız olarak çalıştırılır.

**Then:**
Her senaryo için:
- Sonuç `policy_decision: "deny"` veya `outcome: "blocked"` olmalıdır.
- Dış MCP çağrısı dispatch edilmemiş olmalıdır (simülasyonda bu, dispatch
  flag'inin `false` olarak kalması veya dispatch adımının hiç çağrılmaması
  ile doğrulanır).
- Audit event (mümkünse) üretilmiş olmalıdır; audit event senaryoya uygun
  `failure_category` değeri içermelidir:
  - H1 ve H2: `failure_category: "unclassified_tool_identity"` veya
    `"policy_violation"` (hangisi uygunsa).
  - H3: `failure_category: "capability_mismatch"`.
  - H4: `failure_category: "audit_unavailable"`.
- Hata senaryolarında ham error/exception metni audit event alanlarına
  yazılmamalıdır.

**Evidence:**
Her senaryo için ayrı PASS sonuçları; `policy_decision` ve `outcome`
alanlarını doğrulayan assertion'lar; dispatch'ın gerçekleşmediğini gösteren
assertion; `failure_category`'nin doğru enum değerini içerdiğini gösteren
assertion.

**Failure Condition:**
- Herhangi bir senaryoda `policy_decision` `"allow"` ise.
- Herhangi bir senaryoda dış MCP çağrısı dispatch edilmişse.
- `failure_category` tanımlı enum dışında bir değer (serbest metin dahil)
  içeriyorsa.
- Ham error/exception metni herhangi bir audit alanında görünüyorsa.
- Assertion belirsiz, eksik veya yoksa.

---

## AC-008 — Offline ve Deterministik Yürütme

**Başlık:** Test paketi tamamen offline çalışır ve aynı fixture girdileriyle
her seferinde aynı sonucu üretir.

**Given:**
Test paketi izole bir ortamda çalıştırılmaya hazırdır:

- Network erişimi devre dışı bırakılmış (veya hiç bulunmayan) bir
  ortamda.
- Test fixture'ları sabit, değişmeyen sentetik değerler içermektedir.

**When:**
Test paketi iki ayrı çalıştırma oturumunda (aynı fixture'larla, farklı
zamanlarda) çalıştırılır. İlk çalıştırmada network kapalıdır.

**Then:**
- Her iki çalıştırmada tüm test sonuçları (PASS/FAIL listesi, assertion
  çıktıları) **birebir aynı** olmalıdır.
- Herhangi bir test, network kapalıyken başarısız olmamalıdır; ağ
  bağlantısına bağımlı hiçbir assertion bulunmamalıdır.
- Test sonuçları tarih/saat veya rastlantısal değerlere bağlı değil;
  fixture girdilerine dayalı olmalıdır.

**Evidence:**
İki çalıştırmanın sonuç listesinin birebir eşleştiğini gösteren karşılaştırma
çıktısı; network kapalıyken alınan PASS sonuçları.

**Failure Condition:**
- Bir test network erişimi olmadan başarısız oluyorsa (veya timeout/bağlantı
  hatası veriyorsa).
- İki çalıştırma arasında herhangi bir test sonucunda farklılık varsa
  (flaky test).
- Sonuçlar sabit fixture değilse çalışma zamanı değerlerine (rastlantısal,
  tarih/saate bağlı) göre değişiyorsa.

---

## AC-009 — Gerçek MCP Bağımlılığı Olmadan Yürütme

**Başlık:** Test paketi gerçek MCP server, credential, endpoint, network
çağrısı veya Claude Code hook config gerektirmez.

**Given:**
Test paketi şu bileşenler **olmadan** çalıştırılmaktadır:

- Herhangi bir gerçek MCP server (NotebookLM, Obsidian, Playwright,
  GitHub MCP, Context7 veya başka herhangi bir MCP).
- Gerçek credential, token, API key veya endpoint.
- `.claude/hooks/` implementasyonu veya `.claude/settings.json`
  konfigürasyonu.
- Claude Code'un gerçek `PreToolUse`/`PostToolUse` hook runtime'ı.

**When:**
Test paketi yukarıdaki bileşenlerden hiçbiri mevcut olmadan çalıştırılır.

**Then:**
- Tüm testler başarıyla çalışmalıdır (PASS veya beklenen FAIL assertion
  üretmelidir).
- Hiçbir test "MCP bağlantısı yok", "credential eksik", "hook
  konfigürasyon hatası" veya benzer bir bağlantı/yapılandırma hatasıyla
  başarısız olmamalıdır.
- Test fixture'ları tamamen sentetik değerler içermelidir; gerçek
  endpoint, credential değeri veya PII bulunmamalıdır.

**Evidence:**
PASS sonuçları; test fixture kaynak kodunun/içeriğinin gerçek credential
veya endpoint içermediğini gösteren statik inceleme notu veya assertion.

**Failure Condition:**
- Herhangi bir test gerçek MCP bağlantısı, credential veya hook config
  eksikliğinden kaynaklanan hatayla başarısız oluyorsa.
- Test fixture'larında gerçek API key, endpoint, PII veya credential
  tespit edilirse.
- Test, `.claude/hooks/` veya `.claude/settings.json` varlığına bağlı
  davranış sergiliyorsa.

---

## AC-010 — Açık PASS/FAIL Assertion

**Başlık:** Her test senaryosu belirsizlik bırakmayan, açık PASS veya FAIL
assertion üretir.

**Given:**
REQ-001 kapsamındaki her test senaryosu (AC-001'den AC-009'a kadar) için
bağımsız test durumları hazırlanmıştır.

**When:**
Test paketi çalıştırılır.

**Then:**
Her test senaryosu için:
- Sonuç açıkça **PASS** veya **FAIL** olarak raporlanmalıdır.
- "SKIP", "PENDING", "UNKNOWN", "WARNING" veya belirsiz sonuçlar kabul
  edilmez.
- PASS/FAIL kararı, test girdisi ile beklenen değerin programatik
  karşılaştırmasına dayanmalıdır; insan yorumuna bırakılmamalıdır.
- Her assertion "ne beklendi — ne bulundu" bilgisini içermelidir.

**Evidence:**
Tüm test senaryolarının PASS veya FAIL sonucuyla listelendiği test özet
çıktısı; her assertion'ın "expected" ve "actual" değerlerini içermesi.

**Failure Condition:**
- Herhangi bir test SKIP, PENDING veya sonuçsuz bitiyor ise.
- Assertion çıktısı "expected" veya "actual" bilgisi içermiyorsa.
- PASS/FAIL kararı programatik değil, yoruma açık bir eşiğe dayanıyorsa.

---

## AC-011 — Implementation Tamamlanınca Test Evidence Kaydı

**Başlık:** Test paketinin implementation'ı tamamlandığında, insan
maintainer tarafından incelenebilir bir test evidence kaydı üretilir.

**Given:**
REQ-001 kapsamındaki tüm testler (AC-001'den AC-010'a kadar) implement
edilmiş ve çalıştırılmıştır.

**When:**
Tüm testler başarıyla (veya beklenen FAIL senaryoları dahil, deterministik
biçimde) tamamlanır.

**Then:**
Test evidence kaydı aşağıdakileri içermelidir:

- Her test senaryosunun (AC-001'den AC-010'a karşılık gelen) PASS/FAIL
  sonucu.
- Test çalıştırma tarihi ve ortam bilgisi (offline, sentetik fixture).
- Her assertion sonucunun özeti.
- Test fixture'larının gerçek credential veya PII içermediğinin onayı.
- Bu kaydın insan maintainer tarafından incelenmesini ve "sentetik
  validation tamamlandı" kararını gerektirdiğine dair açık not.

Bu kanıt kaydı **gerçek MCP bağlantısı için otomatik izin vermez**;
yalnızca sentetik validation milestone'unun tamamlandığını belgeler.
Gerçek bağlantı kararı ayrı insan onayı gerektirir (bkz. REQ-001
"Human Approval Gates" ve `SEC-ADR-005-MCP-CONNECTION-PRECONDITIONS.md`).

**Evidence:**
Mevcut test evidence kaydının referansı (dosya yolu veya kayıt konumu);
kaydın insan maintainer tarafından imzalandığına veya incelendiğine dair
onay notu.

**Failure Condition:**
- Test evidence kaydı mevcut değilse.
- Kaydın içeriği eksikse (hangi testlerin PASS/FAIL olduğu belirtilmemişse).
- Kayıt, gerçek MCP bağlantısının otomatik olarak yetkilendirildiğini ima
  ediyorsa.
- Kaydın insan maintainer tarafından incelenmesi yapılmamışsa.

---

## Quality Gate Özeti

Aşağıdaki tablo, her quality gate'in hangi AC ile karşılandığını özetler:

| Quality Gate                                                          | Karşılayan AC |
|-----------------------------------------------------------------------|---------------|
| Network erişimi olmadan test çalışır                                  | AC-008        |
| Test fixture'ları yalnızca sentetik değer içerir                      | AC-009        |
| Test sonucu deterministiktir                                          | AC-008        |
| Test edilen audit event'ler 15 alan dışında alan taşımaz              | AC-004        |
| Yasaklı veri değerleri test çıktılarına girmez                        | AC-005        |
| Unknown identity ham runtime string olarak persist edilmez            | AC-002        |
| PermissionDenied ve PostToolUseFailure aynı event/lifecycle yolu değil | AC-003       |
| Parallel operation testinde `operation_reference` çakışmaz            | AC-006        |
| Her test sonucu açık PASS/FAIL assertion üretir                       | AC-010        |
| Implementation tamamlandığında test evidence kaydı gereklidir         | AC-011        |

---

## Human Approval Gates

Bu acceptance criteria paketinin implementation'a geçmeden önce insan
maintainer tarafından onaylanması zorunludur. Her AC için:

- Senaryonun doğru anlaşıldığı (Given/When/Then tutarlılığı) insan
  tarafından teyit edilmelidir.
- Test evidence (AC-011) insan maintainer tarafından incelenmeli ve
  "sentetik validation tamamlandı" kararı açıkça kaydedilmelidir.

**REQ-001'in tamamlanması, gerçek MCP bağlantısı veya audit hook
implementasyonu için otomatik izin vermez. Gerçek bağlantı; audit sink
seçimi, append-only/tamper-evident doğrulama, out-of-band/non-recursive
writer doğrulaması, capability validation, environment-specific smoke test,
credential storage onayı ve MCP bazlı human maintainer onayı gerektirir.**

Gerçek bağlantı için gerekli zorunlu kapıların tam listesi:
`docs/quality/security-reports/SEC-ADR-005-MCP-CONNECTION-PRECONDITIONS.md`

---

## İlgili Dokümanlar

- `docs/product/requirements/REQ-001-mcp-hook-lifecycle-synthetic-validation.md`
- `docs/architecture/adr/ADR-005-mcp-tooling-control-plane.md`
- `docs/architecture/adr/ADR-006-mcp-audit-logging-and-runtime-enforcement.md`
- `docs/decisions/MCP_AUDIT_EVENT_CONTRACT.md`
- `docs/decisions/MCP_AGENT_CAPABILITY_MATRIX.md`
- `docs/quality/security-reports/SEC-ADR-005-MCP-CONNECTION-PRECONDITIONS.md`
- `PROJECT_CONSTITUTION.md`
