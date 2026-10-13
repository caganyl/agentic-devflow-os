# AC-REQ-002 — Acceptance Criteria: Local Hook Audit Runtime Spike

## Metadata

| Alan               | Değer                                                                                      |
|--------------------|--------------------------------------------------------------------------------------------|
| **REQ ID**         | REQ-002                                                                                    |
| **AC Dokümanı**    | AC-REQ-002                                                                                 |
| **Status**         | Accepted                                                                                   |
| **Date**           | 2026-06-26                                                                                 |
| **Acceptance Date**| 2026-06-25                                                                                 |
| **REQ Referansı**  | `docs/product/requirements/REQ-002-local-hook-audit-runtime-spike.md`                     |

---

> **Önemli:** Bu AC dokümanı yalnızca disposable local workspace içinde
> built-in `Read` tool kullanılarak yürütülen runtime spike'ın ölçülebilir
> davranışını tanımlar. Gerçek MCP bağlantısı, production audit sink,
> credential veya commit edilebilir hook implementasyonu bu kriterlerin
> kapsamı dışındadır. Bu AC paketi, REQ-002 insan maintainer tarafından
> `Accepted` durumuna alınmıştır (2026-06-25); implementation yalnızca
> disposable local runtime spike kapsamında başlayabilir.

---

## AC-001 — Disposable Local Workspace ve Temporary Configuration Oluşturma Sınırları

**Başlık:** Spike için oluşturulan hook configuration yalnızca geçici,
izole bir workspace içinde yer alır; canonical repository dosyalarını
değiştirmez ve commit edilmez.

**Given:**

- Repository'nin canonical `.claude/settings.json` dosyası ve
  `.claude/hooks/` dizini başlangıç durumunda (baseline) mevcuttur.
- Spike için bir disposable local test workspace belirlenmiştir.

**When:**

Spike için geçici hook configuration oluşturulur.

**Then:**

- Geçici configuration, açıkça belgelenmiş, geçici ve izole bir konumda
  yer alır.
- Repository'nin canonical `.claude/settings.json` dosyası değişmemiş
  olmalıdır; başlangıç içeriğiyle birebir aynı kalmalıdır.
- `.claude/hooks/enforce-role-boundaries.sh` veya diğer canonical hook
  scriptleri değişmemiş olmalıdır.
- Geçici configuration hiçbir koşulda Git'e commit edilmemiş olmalıdır.
- Configuration geçici olduğu; spike sonunda silineceği açıkça
  belgelenmiş olmalıdır.

**Evidence:**

- Canonical `.claude/settings.json` dosyasının spike öncesi ve sonrası
  içeriklerinin değişmediğini gösteren karşılaştırma kaydı (diff veya
  hash).
- Geçici configuration'ın konumunu ve geçicilik statüsünü belgeleyen
  not veya log satırı.
- `git status` veya eşdeğeri çıktısı; geçici configuration'ın
  untracked/unstaged olduğunu göstermeli, commit edilmemiş olmalıdır.

**Failure Condition:**

- Canonical `.claude/settings.json` değişmişse.
- `.claude/hooks/enforce-role-boundaries.sh` veya diğer canonical hook
  scriptleri değişmişse.
- Geçici configuration Git'e commit edilmişse.
- Configuration'ın geçici olduğu belgelenmemişse.
- Configuration disposable workspace dışında bir konuma yerleştirilmişse.

---

## AC-002 — `/hooks` veya Eşdeğer Runtime Doğrulamasıyla Yalnızca `Read` Matcher'lı Hook'un Görünmesi

**Başlık:** Aktif geçici hook configuration çalışırken, hook listeleme
veya eşdeğer runtime doğrulaması yalnızca built-in `Read` tool için
`PreToolUse` matcher'ını gösterir; başka hiçbir matcher aktif değildir.

**Given:**

- Geçici hook configuration aktif durumdadır.
- `Read` tool için `PreToolUse` matcher tanımlanmıştır.
- Başka hiçbir MCP, external tool veya credential gerektiren matcher
  eklenmemiştir.

**When:**

`/hooks` komutu veya Claude Code'un eşdeğer hook listeleme mekanizması
çalıştırılır.

**Then:**

- Görünen hook(lar) yalnızca built-in `Read` tool için tanımlanmış
  `PreToolUse` matcher'ını içermelidir.
- MCP server'lara yönelik hiçbir matcher görünmemelidir.
- Credential, token, API key veya endpoint gerektiren hiçbir matcher
  görünmemelidir.
- Production ya da staging sistemlerine erişimi tetikleyebilecek hiçbir
  matcher aktif olmamalıdır.
- Canonical `.claude/hooks/enforce-role-boundaries.sh` hook'u
  değişmeden yerinde durmalıdır; bu hook'un davranışı etkilenmemiş
  olmalıdır.

**Evidence:**

- `/hooks` veya eşdeğer listeleme çıktısının kaydı; yalnızca
  `Read`/`PreToolUse` matcher'ının görüntülendiğini gösteren metin
  çıktısı.
- Çıktıda MCP server, credential gerektiren veya external tool
  matcher'ı bulunmadığını gösteren doğrulama notu.

**Failure Condition:**

- Çıktıda `Read`/`PreToolUse` dışında başka bir matcher görünüyorsa.
- MCP server matcher'ı aktifse.
- Credential, token veya endpoint içeren bir matcher aktifse.
- Canonical enforcement hook'u değiştirilmişse veya devre dışı
  bırakılmışsa.
- Hook listeleme çıktısı elde edilememişse ya da doğrulanamıyorsa.

---

## AC-003 — Gerçek Built-In `Read` Çağrısında Hook'un Tetiklendiğine ve Sanitised Runtime Evidence Record Üretildiğine Dair Kanıt

**Başlık:** Disposable workspace içinde gerçek bir built-in `Read` tool
çağrısı tetiklendiğinde, hook script çalışır ve non-canonical, sanitised
7 alanlı local runtime evidence record üretilir. Bu kayıt MCP Audit Event
Contract'a uygun canonical audit event değildir.

**Given:**

- Geçici hook configuration aktif durumdadır ve `Read`/`PreToolUse`
  matcher'ı yapılandırılmıştır.
- Hook script çalışmaya hazır durumda ve audit writer erişilebilirdir.
- Disposable workspace içinde test amaçlı, içeriği önemsiz bir dosya
  mevcuttur.

**When:**

Disposable workspace içindeki test dosyasına yönelik gerçek bir
built-in `Read` tool çağrısı yapılır.

**Then:**

- Hook script, `Read` çağrısı gerçekleştiğinde çalıştırılmış olmalıdır.
- Hook script'in stdin üzerinden JSON payload aldığı doğrulanabilir
  olmalıdır (ör. yerel log satırı, artifact'ın üretilmiş olması).
- Non-canonical, sanitised local runtime evidence record (dosya veya log
  girişi) üretilmiş olmalıdır.
- Üretilen evidence record `hook_event: "PreToolUse"` ve
  `tool_class: "builtin_read"` içermelidir.
- Evidence record içinde `mcp_server`, `mcp_tool` veya `unclassified`
  alanları **bulunmamalıdır**; bu kayıt canonical MCP audit event
  değildir ve bu alanları taşımaz.
- Artifact üretim zamanı ile `Read` çağrısının gerçekleştiği zaman
  ilişkilendirilebilir olmalıdır.

**Evidence:**

- Üretilen local evidence artifact'ın içeriği (ham veri içermeksizin);
  `hook_event: "PreToolUse"` ve `tool_class: "builtin_read"` varlığı.
- Hook'un çalıştığını gösteren log satırı veya artifact zaman damgası
  ile `Read` çağrısı zamanının örtüşmesi.
- Evidence record'ın `mcp_server`, `mcp_tool` veya `unclassified` alanı
  **içermediğinin** doğrulama notu.

**Failure Condition:**

- Local evidence artifact üretilmemişse.
- Artifact boşsa veya `hook_event`/`tool_class` içermiyorsa.
- Hook script'in çalışmadığına dair kanıt varsa (artifact oluşmadı,
  log yok).
- Evidence record'da `mcp_server`, `mcp_tool` veya `unclassified`
  alanı bulunuyorsa.
- Artifact'ın `Read` çağrısına değil, başka bir olaya ait olduğu
  belirsizse.

---

## AC-004 — Üretilen Non-Canonical Evidence Record'ın 7 Alanlı Sanitised Schema ile Uyumlu Olması

**Başlık:** Gerçek `Read` çağrısı sonrası hook tarafından üretilen yerel
non-canonical evidence record, tam olarak 7 zorunlu alanı içerir; ne eksik
alan ne de ek alan bulunur. Bu kayıt `MCP_AUDIT_EVENT_CONTRACT.md`'deki
canonical 15 alanlık şemaya uymaz ve uyduğunu iddia etmez.

**Given:**

- AC-003 kapsamında gerçek `Read` çağrısı tetiklenmiş ve local evidence
  artifact üretilmiştir.
- Non-canonical evidence record için zorunlu 7 alan listesi:
  `evidence_schema_version`, `evidence_id`, `timestamp`, `hook_event`,
  `tool_class`, `test_path`, `observation`.

**When:**

Yerel evidence artifact içeriği incelenir (programatik veya manuel) ve
alan listesi sayılır.

**Then:**

- Evidence record payload'ındaki alan sayısı tam olarak **7** olmalıdır.
- Yukarıdaki 7 zorunlu alandan her biri record'da bulunmalıdır.
- `hook_event` değeri `PreToolUse` olmalıdır (sabit).
- `tool_class` değeri `builtin_read` olmalıdır (sabit).
- `test_path` değeri yalnızca `writer_available` veya
  `writer_unavailable` olmalıdır.
- `observation` değeri yalnızca `allow_observed` veya `deny_observed`
  olmalıdır.
- `evidence_id` alanı yalnızca disposable local workspace içinde
  üretilen random test referansı olmalıdır; session_id, tool_use_id
  veya raw agent identity'den türetilmemiş olmalıdır.
- 7 alan dışında hiçbir ek alan — özellikle `mcp_server`, `mcp_tool`,
  `unclassified`, `session_reference`, `operation_reference`,
  `agent_type`, `schema_version`, `event_id`, `action_class`,
  `environment_scope`, `policy_decision`, `outcome`, `failure_category`,
  `audit_record_version`, `note`, `notes`, `message`, `error_message`,
  `details`, `description`, `context`, `metadata`, `debug`,
  `raw_input`, `raw_output`, `prompt`, `url`, `header`, `file_path`,
  `exception`, `reason` veya başka herhangi bir alan —
  payload'da **bulunmamalıdır**.

**Evidence:**

- Artifact içeriğinin alan sayısını gösteren kayıt; "alan sayısı: 7,
  beklenen: 7" formatında doğrulama notu.
- 7 zorunlu alanın tamamının listesi ve artifact'taki karşılıkları.
- Canonical MCP audit contract alanlarının (`mcp_server`, `mcp_tool`,
  `unclassified` dahil) artifact'ta bulunmadığını gösteren negatif
  inceleme notu.

**Failure Condition:**

- Artifact'taki alan sayısı 7'den fazla veya azsa.
- 7 zorunlu alandan herhangi biri eksikse.
- `mcp_server`, `mcp_tool`, `unclassified`, `session_reference`,
  `operation_reference` veya başka canonical MCP audit alanı
  record'da bulunuyorsa.
- `hook_event`, `tool_class`, `test_path` veya `observation` alanında
  izin verilmemiş bir değer varsa.
- Alan sayımı gerçekleştirilmemişse veya belirsizse.

---

## AC-005 — Raw Input, Dosya İçeriği, URL, Prompt, Token, PII, File Path, Reason veya Exception Text Sızıntısının Olmaması

**Başlık:** Yerel audit artifact; raw tool input, okunan dosya içeriği,
prompt, URL, token, secret, PII, dosya yolu, exception metni, reason
veya serbest metin içermez.

**Given:**

- `Read` tool çağrısı belirli bir test dosyasına yönelik yapılmıştır;
  bu dosya bir metin içeriğine sahiptir.
- Hook script, stdin üzerinden gelen `PreToolUse` JSON payload'ını
  işlemiştir; bu payload tool'un okuyacağı dosya yolu bilgisini
  içermektedir.

**When:**

Yerel audit artifact içeriği aşağıdaki yasak veri kategorileri
açısından incelenir:

- Raw tool input (ör. `Read` tool'a iletilen dosya yolu parametresi)
- Okunan dosyanın gerçek içeriği (ham metin)
- Prompt içeriği (sistem prompt'u, kullanıcı mesajı, agent talimatı)
- URL (tam URL veya query değeri)
- `Authorization` header, token, API key, secret veya credential
- Kişisel veri (PII): ad, e-posta, telefon, müşteri kaydı
- Dosya yolu (okunan dosyanın gerçek path'i)
- Error veya exception metni (ham hata mesajı, stack trace)
- Reason alanı veya açıklama dizisi
- Serbest metin not alanı (`note`, `notes`, `message`, `error_message`,
  `details`, `description`, `context`, `metadata`, `debug` vb.)

**Then:**

Yukarıdaki kategorilerin **hiçbiri** yerel audit artifact içinde
bulunmamalıdır:

- Okunan dosyanın gerçek içerik dizesi artifact'ta yer almamalıdır.
- Dosyanın gerçek path'i artifact'ta yer almamalıdır.
- Payload'dan gelen ham parametreler artifact'a kopyalanmamış olmalıdır.
- Serbest metin içerikli hiçbir alan artifact'ta bulunmamalıdır.
- Evidence record içinde `mcp_server`, `mcp_tool` veya `unclassified`
  alanları bulunmamalıdır; bu kayıt MCP Audit Event Contract alanlarını
  taşımaz.

**Evidence:**

- Her yasak veri kategorisi için artifact içeriğinin bu kategoriyi
  içermediğini gösteren ayrı negatif inceleme notu.
- Evidence record'da `mcp_server`, `mcp_tool` veya `unclassified`
  alanının bulunmadığının doğrulama notu.

**Failure Condition:**

- Okunan dosyanın içeriğinden herhangi bir dize artifact'ta tespit
  edilirse.
- Dosya yolu artifact'ta herhangi bir alanda bulunursa.
- Ham tool input (Path parametresi veya eşdeğeri) artifact'ta
  bulunursa.
- Serbest metin içerikli herhangi bir alan artifact'ta bulunursa.
- Evidence record'da `mcp_server`, `mcp_tool` veya `unclassified` alanı
  bulunuyorsa.
- Redaction veya maskeleme mekanizması uygulanmış olsa bile, orijinal
  değer kısmi olarak hâlâ görünüyorsa.

---

## AC-006 — Raw Runtime Identity'nin Hiçbir Evidence Record Alanında Persist Edilmemesi

**Başlık:** Non-canonical local evidence record; raw session kimliği, raw
`tool_use_id`, raw agent identity veya başka bir raw runtime tanımlayıcı
içermez. `evidence_id` yalnızca disposable local workspace içinde üretilen
random test referansıdır.

**Given:**

- Claude Code, çalışma sırasında iç session ve operation kimliklerini
  üretmektedir (bunlar hook'a gelen JSON payload'ında bulunabilir).
- Yerel evidence artifact üretilmiştir (AC-003).

**When:**

Yerel evidence artifact'ın tüm alanları incelenir.

**Then:**

- `evidence_id` alanı Claude Code'un iç session kimliğinden,
  `tool_use_id` değerinden veya başka bir raw runtime tanımlayıcıdan
  türetilmemiş olmalıdır; yalnızca disposable local workspace içinde
  üretilen random test referansı değeri içermelidir.
- Evidence record'ın hiçbir alanında raw session ID, raw tool_use_id,
  raw agent identity veya transcript path bulunmamalıdır.
- Evidence record içinde `session_reference`, `operation_reference` veya
  `agent_type` alanları bulunmamalıdır (bu alanlar canonical MCP Audit
  Event Contract'a aittir; non-canonical evidence record bu alanları
  taşımaz).
- Human maintainer tarafından `evidence_id`'nin raw runtime verisi
  içermediği gözlemlenebilir biçimde doğrulanabilir olmalıdır.

**Evidence:**

- `evidence_id` alanının artifact içindeki değeri; bu değerin raw
  runtime kimliği olmadığını gösterir insan maintainer inceleme notu.
- Artifact'ın `session_reference`, `operation_reference` veya `agent_type`
  alanı içermediğinin doğrulama notu.
- `evidence_id`'nin disposable local referans niteliğini destekleyen
  açıklama (ör. "random UUID", "lokal sayaç değeri").

**Failure Condition:**

- `evidence_id` alanında Claude Code'un iç session tanımlayıcısının ham
  biçimi bulunursa.
- `evidence_id` alanında raw `tool_use_id` veya transcript path tespit
  edilirse.
- Herhangi bir alanda raw session ID, raw tool_use_id veya raw agent
  identity bulunursa.
- Evidence record'da `session_reference`, `operation_reference` veya
  `agent_type` alanı bulunursa.
- `evidence_id`'nin raw runtime verisi içerip içermediği
  doğrulanamıyorsa.

---

## AC-007 — Audit Writer Başarılı Olduğunda Tool Call'ın Gereksiz Deny Almaması

**Başlık:** Audit writer event'i başarıyla yazabildiğinde, built-in
`Read` tool yürütülür ve gereksiz `PreToolUse` deny almaz.

**Given:**

- Geçici hook configuration aktif durumdadır.
- Audit writer script erişilebilir ve çalışır durumdadır.
- Yerel audit artifact yazılabilir konumda mevcuttur.

**When:**

Built-in `Read` tool çağrısı yapılır ve hook tetiklenir; hook, audit
writer'a event yazar; write başarıyla tamamlanır.

**Then:**

- `Read` tool çağrısı başarıyla yürütülmüş olmalıdır; deny ile
  kesilmemelidir.
- Non-canonical evidence record `observation: "allow_observed"` ve
  `test_path: "writer_available"` içermelidir.
- Bu başarılı path kanıtı yalnızca hook/runtime davranışını kanıtlar;
  canonical MCP audit event validation değildir. Evidence record
  `policy_decision`, `outcome`, `mcp_server` veya `mcp_tool` alanları
  içermez.
- Spurious denial (yazma başarılıyken deny üretme) gerçekleşmemiştir.

**Evidence:**

- `Read` tool'un başarıyla tamamlandığına dair gözlem (tool çıktısı
  veya log kaydı).
- Non-canonical evidence record'ın `observation: "allow_observed"` ve
  `test_path: "writer_available"` içerdiğinin gösterimi.
- Unexpected deny davranışı gözlemlenmediğinin doğrulama notu.
- Evidence record'ın canonical MCP audit alanları (`policy_decision`,
  `outcome`, `mcp_server`, `mcp_tool`) içermediğinin doğrulama notu.

**Failure Condition:**

- Audit writer başarılıyken `Read` tool deny alıyorsa.
- Evidence record `observation: "deny_observed"` içeriyorsa (başarılı
  write durumunda).
- Hook false positive deny üretiyorsa (spurious denial).
- Evidence record `observation: "allow_observed"` içermiyorsa.
- Başarılı path kanıtı üretilememişse.

---

## AC-008 — Audit Writer Unavailable Olduğunda `PreToolUse` Deny / Fail-Closed Davranışı

**Başlık:** Audit writer erişilemez veya write başarısız olduğunda, hook
fail-closed davranır: `PreToolUse` deny edilir, `Read` tool yürütülmez
ve dış dispatch gerçekleşmez.

**Given:**

- Geçici hook configuration aktif durumdadır.
- Audit writer kontrollü biçimde unavailable yapılmıştır (ör. script
  başarısız olacak biçimde yapılandırılmış, yazma konumu erişilemez
  veya eşdeğer bir failure simülasyonu uygulanmıştır).
- Bu senaryo tamamen local ve controlled'dır; gerçek bir dış sistem
  veya network erişimi yoktur.

**When:**

Built-in `Read` tool çağrısı yapılır; hook tetiklenir; audit writer
başarısız olur (durable write acknowledgment alınamaz).

**Then:**

- `PreToolUse` deny edilmiş olmalıdır; `Read` tool yürütülmemiş
  olmalıdır.
- Dış dispatch gerçekleşmemiş olmalıdır (MCP çağrısı, network çağrısı
  veya herhangi bir dış sistem erişimi yok).
- Denial, sessiz `allow` sonucu üretmemiş olmalıdır; hook fail-closed
  davranışını açıkça sergilemiş olmalıdır.
- Non-canonical evidence record üretildiyse `observation: "deny_observed"`
  ve `test_path: "writer_unavailable"` içermelidir.
- **Sahte MCP audit event veya `unclassified` sentinel event
  üretilmemiş olmalıdır.** Fail-closed durumunda hiçbir `mcp_server`,
  `mcp_tool`, `unclassified`, `policy_decision`, `outcome` veya canonical
  MCP audit alanı persist edilmez.
- Mümkünse, audit unavailable'ı bildiren bir human-visible failure
  signal üretilmiş olmalıdır; bu signal raw tool identity, raw error
  metni, prompt, URL, token, secret, PII veya serbest metin
  içermemelidir (yalnızca sabit şablon + kapalı enum değeri).
- Human-visible failure signal, yeni bir MCP çağrısı başlatmamış
  ve audit zincirini yeniden tetiklememiş olmalıdır.

**Evidence:**

- `Read` tool'un yürütülmediğine dair kanıt (tool çıktısı yok, deny
  gözlemi veya log kaydı).
- Non-canonical evidence record üretildiyse `observation: "deny_observed"`
  ve `test_path: "writer_unavailable"` içerdiğinin gösterimi.
- Evidence record'da `mcp_server`, `mcp_tool` veya `unclassified` alanı
  bulunmadığının doğrulama notu.
- Failure signal'inin üretildiğine ve içeriğinin yasak veri
  içermediğine dair not.
- Dış dispatch gerçekleşmediğinin doğrulama notu (network call yok,
  MCP server çağrısı yok).
- Fail-closed davranışının gerçekleştiğini gösteren açık bulgu kaydı.

**Failure Condition:**

- Audit writer başarısız olduğunda `Read` tool yürütülüyorsa
  (sessiz allow).
- Dış dispatch gerçekleşmişse.
- Failure signal raw error metni, raw tool identity, prompt, URL,
  token veya serbest metin içeriyorsa.
- Failure signal yeni bir MCP çağrısı veya dış dispatch tetiklemişse.
- Evidence record `unclassified` sentinel, `mcp_server`, `mcp_tool`,
  `policy_decision` veya `outcome` alanı içeriyorsa.
- Fail-closed davranışı gözlemlenemiyorsa veya kanıtlanamıyorsa.

---

## AC-009 — Network, MCP Server, Credential ve External Dependency Olmadan Çalışma

**Başlık:** Spike'ın tüm adımları (hook tetiklenme, audit yazma, fail-closed
davranışı) herhangi bir network erişimi, MCP server bağlantısı, credential
veya dış bağımlılık olmadan çalışır.

**Given:**

- Spike, network erişimi kapalı veya bulunmayan bir ortamda yürütülmeye
  hazırdır.
- Herhangi bir MCP server bağlantısı yoktur.
- Credential, token, API key veya endpoint mevcut değildir.

**When:**

Spike'ın tüm adımları (AC-001'den AC-010'a kadar) yürütülür.

**Then:**

- Hiçbir adım network erişimi gerektirmemeli veya kullanmamalıdır.
- Hiçbir MCP server bağlantısı kurulmamış olmalıdır.
- Hiçbir credential, token veya API key kullanılmamış olmalıdır.
- Yerel audit artifact, hook script veya geçici configuration dosyalarında
  gerçek endpoint, token, API key, credential veya PII bulunmamalıdır.
- Evidence record içinde `mcp_server`, `mcp_tool` veya `unclassified`
  alanları bulunmamalıdır; bu alanlar canonical MCP Audit Event Contract
  kapsamındadır ve non-canonical evidence record içinde yer almaz.

**Evidence:**

- Spike sırasında network çağrısı yapılmadığına dair log veya gözlem.
- MCP server bağlantısı kurulmadığını gösteren doğrulama notu.
- Geçici dosyaların ve artifact'ların incelenmesi sonucu gerçek
  credential veya endpoint içermediğinin kaydı.
- Evidence artifact'ının `mcp_server`, `mcp_tool` veya `unclassified`
  alanı içermediğinin doğrulama notu.

**Failure Condition:**

- Herhangi bir adımda network çağrısı yapılmışsa.
- MCP server bağlantısı kurulmuşsa.
- Artifact, script veya configuration'da gerçek credential, token veya
  API key tespit edilmişse.
- Spike, dış bir servis veya sistemin erişilebilir olmasına bağımlıysa.

---

## AC-010 — Cleanup Kanıtı: Temporary Settings, Script ve Audit Artefact'ların Kaldırılması

**Başlık:** Spike tamamlandığında geçici hook configuration, hook script
ve yerel audit artifact'lar silinir; repository canonical dosyaları ve
durumu değişmemiş olarak kalır.

**Given:**

- Spike yürütülmüştür (AC-001 - AC-009 kapsamındaki adımlar tamamlanmıştır).
- Geçici hook configuration, hook script ve yerel audit artifact dosyaları
  mevcut durumdadır.

**When:**

Cleanup adımı yürütülür.

**Then:**

- Geçici hook configuration dosyası silinmiş olmalıdır.
- Geçici hook script silinmiş olmalıdır.
- Yerel audit artifact dosyası (veya dosyaları) silinmiş olmalıdır.
- Canonical `.claude/settings.json` dosyası cleanup sonrasında başlangıç
  durumunda (baseline) olmalıdır.
- `.claude/hooks/enforce-role-boundaries.sh` ve diğer canonical hook
  scriptleri değişmeden yerinde durmalıdır.
- `git status` veya eşdeğeri, cleanup sonrasında spike ile ilgili
  untracked, modified veya staged dosya göstermemelidir.
- Cleanup'ın eksiksiz tamamlandığına dair açık bulgu kaydı
  mevcuttur.

**Evidence:**

- Cleanup öncesi ve sonrası dosya listesinin karşılaştırması; geçici
  dosyaların silindiğini gösterir.
- `git status` veya eşdeğeri çıktısı; repository'nin temiz (clean)
  durumda olduğunu gösterir.
- Canonical `.claude/settings.json` dosyasının başlangıç durumunda
  kaldığını gösteren hash veya diff.
- Cleanup tamamlandı onay notu.

**Failure Condition:**

- Geçici configuration veya script silinmemişse.
- Yerel audit artifact hâlâ mevcutsa.
- Canonical `.claude/settings.json` değişmişse.
- Canonical hook scriptleri değişmişse.
- `git status` spike kaynaklı modified veya untracked dosya
  gösteriyorsa.
- Cleanup tamamlandığına dair kanıt yoksa.

---

## AC-011 — İnsan Maintainer Evidence İncelemesi ve Açık Karar Kaydı

**Başlık:** Spike tamamlandığında, insan maintainer yerel evidence
artifact'ı inceler ve açık bir karar kaydı oluşturur; bu karar,
spike'ın neyi kanıtladığını ve neyi yetkilendirmediğini açıkça belirtir.

**Given:**

- AC-001 ile AC-010 kapsamındaki tüm adımlar yürütülmüştür.
- Başarılı path ve failure path kanıtları toplanmıştır.
- Cleanup tamamlanmıştır.
- Tüm kanıtlar insan maintainer incelemesine hazır durumda
  sunulmuştur.

**When:**

İnsan maintainer toplanan evidence'ı inceler.

**Then:**

- İnsan maintainer açık bir karar kaydı oluşturmalıdır; bu kayıt
  aşağıdakileri içermelidir:
  - Spike'ın neyi kanıtladığı (örn. "Claude Code command hook gerçek
    `Read` çağrısında tetiklendi / tetiklenmedi").
  - Spike'ın neyi **kanıtlamadığı** veya yetkilendirmediği.
  - Gerçek MCP bağlantısı için No-Go kapılarının bu spike ile
    kapatılmadığının açık ifadesi.
  - Sonraki adım için karar (ör. "daha fazla araştırma gerekiyor",
    "bir sonraki adıma geçilebilir", "bloker tespit edildi").
  - REQ-002'nin ürettiği non-canonical evidence record'ın canonical MCP
    Audit Event Contract doğrulaması **olmadığının** açık ifadesi.
  - Gerçek MCP No-Go kapılarının (`SEC-ADR-005-MCP-CONNECTION-
    PRECONDITIONS.md`) bu spike ile kapatılmadığının teyidi.
- Karar kaydı, gerçek MCP bağlantısının, production audit
  enforcement'ın veya credential kullanımının bu spike ile
  yetkilendirilmediğini açıkça belirtmelidir.
- Karar kaydı, açık kalan No-Go kapılarını (`SEC-ADR-005-MCP-
  CONNECTION-PRECONDITIONS.md`) bu spike'ın kapatmadığını doğrulamalıdır.
- Karar, insan maintainer tarafından imzalanmış veya atfedilmiş
  olmalıdır (ad, tarih).

**Evidence:**

- İnsan maintainer'ın imzaladığı veya açıkça oluşturduğu karar
  kaydının referansı (dosya, yorumlayıcı not veya handoff kaydı).
- Kaydın spike'ın kapsamını, bulgularını ve sonraki adımı içerdiğini
  gösteren özet.
- Kaydın gerçek MCP bağlantısının yetkilendirilmediğini açıkça
  belirttiğinin doğrulama notu.
- Kaydın REQ-002 evidence record'ının canonical MCP Audit Event Contract
  doğrulaması olmadığını açıkça belirttiğinin doğrulama notu.

**Failure Condition:**

- İnsan maintainer karar kaydı oluşturmamışsa.
- Kayıt, gerçek MCP bağlantısının otomatik olarak yetkilendirildiğini
  ima ediyorsa.
- Kayıt, spike'ın neyi kanıtlamadığını belirtmiyorsa.
- No-Go kapılarının hâlâ açık olduğu kaydedilmemişse.
- Karar imzasız, anonim veya makine tarafından otomatik oluşturulmuşsa
  (insan maintainer atfı yoksa).
- Kayıt, REQ-002 evidence record'ının canonical MCP Audit Event Contract
  doğrulaması olduğunu ima ediyorsa.

---

## Quality Gate Özeti

| Quality Gate                                                                              | Karşılayan AC  |
|-------------------------------------------------------------------------------------------|----------------|
| Canonical `.claude/settings.json` ve hook scriptleri değişmeden kalır                     | AC-001, AC-010 |
| Aktif hook listesi yalnızca `Read`/`PreToolUse` matcher'ını içerir                        | AC-002         |
| Gerçek `Read` çağrısında hook tetiklendiği ve sanitised evidence record üretildiği kanıtlanır | AC-003      |
| Üretilen non-canonical evidence record tam olarak 7 alanlı sanitised schema ile uyumludur | AC-004         |
| Artifact raw input, dosya içeriği, prompt, URL, token, PII veya serbest metin içermez     | AC-005         |
| Evidence record içinde raw session ID, tool_use_id veya raw agent identity persist edilmez | AC-006        |
| Audit writer başarılıyken `Read` tool deny almaz                                           | AC-007         |
| Audit writer başarısız olduğunda `PreToolUse` deny ve fail-closed davranışı gözlemlenir   | AC-008         |
| Spike network, MCP server, credential veya dış bağımlılık olmadan çalışır                 | AC-009         |
| Spike sonunda tüm geçici dosyalar ve artifact'lar silinir                                  | AC-010         |
| İnsan maintainer evidence'ı inceleyerek açık karar kaydı oluşturur                        | AC-011         |

---

## Human Approval Gates

Bu acceptance criteria paketinin implementation'a geçmeden önce insan
maintainer tarafından onaylanması zorunludur.

**Spike başlamadan önce (pre-spike):**

- REQ-002 implementation planning `Accepted` durumdadır (2026-06-25).
- AC-001 ile AC-011 değişmeden geçerlidir; hiçbir acceptance criteria
  maddesi azaltılmamış veya gevşetilmemiştir.
- Spike yalnızca disposable local workspace sınırları içinde
  başlayabilir; acceptance bu sınırı değiştirmez.

**Spike tamamlandıktan sonra (post-spike):**

- AC-011 kapsamında insan maintainer evidence'ı inceler ve açık
  karar kaydı oluşturur; bu inceleme spike tamamlandıktan sonra
  ayrıca yapılacaktır.
- Karar kaydı, spike'ın neyi kanıtladığını ve neyi
  yetkilendirmediğini net biçimde ifade eder.

**REQ-002'nin tamamlanması, gerçek MCP bağlantısı veya production audit
enforcement için otomatik izin vermez. Gerçek MCP bağlantısı; append-only
veya kanıtlanabilir tamper-evident audit sink, out-of-band/non-recursive
writer, durable write acknowledgment, MCP bazlı capability validation,
environment-specific MCP smoke test, credential storage onayı ve MCP bazlı
human maintainer onayı gerektirir.**

Gerçek bağlantı için gerekli zorunlu kapıların tam listesi:
`docs/quality/security-reports/SEC-ADR-005-MCP-CONNECTION-PRECONDITIONS.md`

**Acceptance Amendment — 2026-06-25 (Evidence-Model Clarification):**

Human maintainer acceptance kararı aşağıdaki sınırlarla amend edilmiştir;
Accepted statüsü ve acceptance date (2026-06-25) değişmez:

- Built-in `Read`, MCP tool değildir. REQ-002 built-in `Read` spike'ı
  canonical `MCP_AUDIT_EVENT_CONTRACT.md` audit event'i üretmez,
  doğrulamaz veya yerine geçmez.
- REQ-002 yalnızca non-canonical, sanitised local runtime evidence record
  üretir. Bu record tam olarak 7 alan taşır: `evidence_schema_version`,
  `evidence_id`, `timestamp`, `hook_event` (yalnızca `PreToolUse`),
  `tool_class` (yalnızca `builtin_read`), `test_path` (yalnızca
  `writer_available` veya `writer_unavailable`), `observation` (yalnızca
  `allow_observed` veya `deny_observed`).
- `evidence_id`, disposable local workspace içinde üretilen random test
  referansıdır; raw runtime identity'den türetilmez.
- Evidence record içinde `mcp_server`, `mcp_tool`, `unclassified`,
  `session_reference`, `operation_reference`, `agent_type`,
  `policy_decision`, `outcome`, `failure_category`, raw payload, tool
  input, file path, file content, prompt, URL, token, secret, session ID,
  tool use ID, reason, exception text veya serbest metin alanları
  bulunmaz.
- Bu amendment scope'u genişletmez; gerçek MCP bağlantısına, MCP audit
  contract validation'a, production hook'a veya production audit
  enforcement'a izin vermez; AC-011 post-spike human maintainer
  incelemesini kapatmaz; ADR-005, ADR-006, MCP Audit Event Contract ve
  SEC-ADR-005 No-Go kapılarını değiştirmez.

---

## Implementation Handoff

**Sonraki adım:** Disposable local workspace içinde, repository ve production
configuration değiştirilmeden, built-in Read için temporary PreToolUse hook
runtime spike uygulanacaktır.

REQ-002 insan maintainer tarafından accepted olarak onaylanmıştır
(2026-06-25); ownership manifest hazırlanacak ve spike yalnızca onaylı,
disposable workspace sınırları içinde yürütülecektir.

Bu handoff güncellemesinin Delivery Lead veya insan maintainer tarafından
planlanması gerekir; Product Analyst bu güncellemeyi yapmaz.

---

## İlgili Dokümanlar

- `docs/product/requirements/REQ-002-local-hook-audit-runtime-spike.md`
- `docs/architecture/adr/ADR-005-mcp-tooling-control-plane.md`
- `docs/architecture/adr/ADR-006-mcp-audit-logging-and-runtime-enforcement.md`
- `docs/decisions/MCP_AUDIT_EVENT_CONTRACT.md`
- `docs/quality/security-reports/SEC-ADR-005-MCP-CONNECTION-PRECONDITIONS.md`
- `docs/handoffs/REQ-001.md`
- `docs/product/requirements/REQ-001-mcp-hook-lifecycle-synthetic-validation.md`
- `docs/product/acceptance-criteria/AC-REQ-001-mcp-hook-lifecycle-synthetic-validation.md`
- `PROJECT_CONSTITUTION.md`
