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

## AC-003 — Gerçek Built-In `Read` Çağrısında Hook'un Çalıştığına Dair Local Evidence

**Başlık:** Disposable workspace içinde gerçek bir built-in `Read` tool
çağrısı tetiklendiğinde, hook script çalışır ve yerel audit event kaydı
üretilir.

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
- Yerel audit event kaydı (dosya veya log girişi) üretilmiş olmalıdır.
- Üretilen audit event kaydı `event_phase: "PreToolUse"` içermelidir.
- `mcp_server` ve `mcp_tool` alanları, built-in `Read` tool için
  tanımlanmış canonical etiketlerle doldurulmuş olmalıdır; ham
  runtime string doğrudan yazılmış olmamalıdır.
- Artifact üretim zamanı ile `Read` çağrısının gerçekleştiği zaman
  ilişkilendirilebilir olmalıdır.

**Evidence:**

- Üretilen local audit artifact'ın dosya yolu ve içeriği (ham veri
  içermeksizin); `event_phase: "PreToolUse"` varlığı.
- Hook'un çalıştığını gösteren log satırı veya artifact zaman
  damgası ile `Read` çağrısı zamanının örtüşmesi.
- `mcp_server` ve `mcp_tool` alanlarının `^[a-z0-9][a-z0-9._-]{0,63}$`
  formatına uygun canonical değerler içerdiğinin gösterimi.

**Failure Condition:**

- Yerel audit artifact üretilmemişse.
- Artifact boşsa veya `event_phase` içermiyorsa.
- Hook script'in çalışmadığına dair kanıt varsa (artifact oluşmadı,
  log yok).
- `mcp_server` veya `mcp_tool` alanında ham runtime string doğrudan
  yazılmışsa.
- Artifact'ın `Read` çağrısına değil, başka bir olaya ait olduğu
  belirsizse.

---

## AC-004 — Üretilen Audit Event'in Tam Olarak 15 Alan Taşıması

**Başlık:** Gerçek `Read` çağrısı sonrası hook tarafından üretilen yerel
audit event, `MCP_AUDIT_EVENT_CONTRACT.md`'de tanımlı tam olarak 15
zorunlu alanı içerir; ne eksik alan ne de ek alan bulunur.

**Given:**

- AC-003 kapsamında gerçek `Read` çağrısı tetiklenmiş ve local audit
  artifact üretilmiştir.
- `MCP_AUDIT_EVENT_CONTRACT.md`'deki 15 zorunlu alan listesi referans
  alınmıştır:
  `schema_version`, `event_id`, `timestamp`, `session_reference`,
  `operation_reference`, `agent_type`, `event_phase`, `mcp_server`,
  `mcp_tool`, `action_class`, `environment_scope`, `policy_decision`,
  `outcome`, `failure_category`, `audit_record_version`.

**When:**

Yerel audit artifact içeriği incelenir (programatik veya manuel) ve
alan listesi sayılır.

**Then:**

- Audit event payload'ındaki alan sayısı tam olarak **15** olmalıdır.
- Yukarıdaki 15 zorunlu alandan her biri event'te bulunmalıdır.
- 15 alan dışında hiçbir ek alan (`note`, `notes`, `message`,
  `error_message`, `details`, `description`, `context`, `metadata`,
  `debug`, `raw_input`, `raw_output`, `prompt`, `url`, `header`,
  `file_path`, `exception`, `reason` veya başka herhangi bir alan)
  payload'da bulunmamalıdır.
- `failure_category` alanı, `outcome` `failure` veya `blocked`
  olmadığı durumlarda `null` olabilir; ancak bu durumda alan
  **sayısı 14'e düşmemelidir** (alan var ama `null`'dur).

**Evidence:**

- Artifact içeriğinin alan sayısını gösteren kayıt; "alan sayısı: 15,
  beklenen: 15" formatında doğrulama notu.
- 15 zorunlu alanın tamamının listesi ve artifact'taki karşılıkları.
- Yasak alan adlarının artifact'ta bulunmadığını gösteren negatif
  inceleme notu.

**Failure Condition:**

- Artifact'taki alan sayısı 15'ten fazla veya azsa.
- 15 zorunlu alandan herhangi biri eksikse.
- Yasak alan listesindeki herhangi bir isimde alan event'te bulunuyorsa.
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
- `mcp_server` ve `mcp_tool` alanlarında yalnızca canonical etiket
  bulunmalıdır; ham runtime string ya da dosya adı türevleri
  bulunmamalıdır.

**Evidence:**

- Her yasak veri kategorisi için artifact içeriğinin bu kategoriyi
  içermediğini gösteren ayrı negatif inceleme notu.
- `mcp_server` ve `mcp_tool` alanlarının gerçek dosya yolu, URL veya
  ham string değil; yalnızca lowercase ASCII canonical etiket
  içerdiğinin gösterimi.

**Failure Condition:**

- Okunan dosyanın içeriğinden herhangi bir dize artifact'ta tespit
  edilirse.
- Dosya yolu artifact'ta herhangi bir alanda bulunursa.
- Ham tool input (Path parametresi veya eşdeğeri) artifact'ta
  bulunursa.
- Serbest metin içerikli herhangi bir alan artifact'ta bulunursa.
- Redaction veya maskeleme mekanizması uygulanmış olsa bile, orijinal
  değer kısmi olarak hâlâ görünüyorsa.

---

## AC-006 — Raw Runtime Reference'ların Persist Edilmemesi

**Başlık:** Yerel audit artifact'taki `session_reference` ve
`operation_reference` alanları; raw session kimliği, raw `tool_use_id`
veya başka bir raw runtime tanımlayıcı içermez; yalnızca test-only
privacy-preserving referanslar kullanılır.

**Given:**

- Claude Code, çalışma sırasında iç session ve operation kimliklerini
  üretmektedir (bunlar hook'a gelen JSON payload'ında bulunabilir).
- Yerel audit artifact üretilmiştir (AC-003).

**When:**

Yerel audit artifact'taki `session_reference` ve `operation_reference`
alanları incelenir.

**Then:**

- `session_reference` alanı, Claude Code'un iç session kimliğinin ham
  biçimini içermemelidir; yalnızca test-only, privacy-preserving bir
  referans değeri (ör. sabit prefix, local sayaç, hash türevi veya
  eşdeğer) içermelidir.
- `operation_reference` alanı, raw `tool_use_id`, transcript path,
  prompt içeriği veya ham runtime tanımlayıcısı içermemelidir; yalnızca
  test-only, privacy-preserving bir referans değeri içermelidir.
- İki alan birbirinden farklı granülaritede olmalıdır
  (`session_reference` oturum seviyesinde, `operation_reference` çağrı
  seviyesinde); ancak her ikisi de raw runtime verisi taşımamalıdır.
- Her iki alanın değeri insan maintainer tarafından ham runtime verisi
  içermediği gözlemlenebilir biçimde doğrulanabilir olmalıdır.

**Evidence:**

- `session_reference` ve `operation_reference` alanlarının artifact
  içindeki değerleri; bu değerlerin test-only niteliğini gösterir
  insan maintainer inceleme notu.
- Alanların raw runtime kimliği olmadığını destekleyen açıklama (ör.
  "sabit test prefix kullanıldı", "lokal sayaç değeri", "hash türevi").

**Failure Condition:**

- `session_reference` veya `operation_reference` alanında Claude Code'un
  iç session tanımlayıcısının ham biçimi bulunursa.
- `operation_reference` alanında raw `tool_use_id` veya transcript path
  tespit edilirse.
- Alanların raw runtime verisi içerip içermediği doğrulanamıyorsa
  (belirsizse).
- İki alanın farklı granülarite taşıdığı görülmüyorsa ve birbirinin
  kopyası ise.

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
- Yerel audit artifact `policy_decision: "allow"` veya eşdeğer bir
  "proceed" sinyali içermelidir; ya da başarılı yürütme kanıtı
  (ör. `outcome: "success"`) görünür olmalıdır.
- Hook'un başarılı write path'ini takip ettiğine dair kanıt
  mevcuttur (artifact üretildi, deny event'i yok).
- Spurious denial (yazma başarılıyken deny üretme) gerçekleşmemiştir.

**Evidence:**

- `Read` tool'un başarıyla tamamlandığına dair gözlem (tool çıktısı
  veya log kaydı).
- Yerel audit artifact'ın `policy_decision: "allow"` veya `outcome:
  "success"` içerdiğinin gösterimi.
- Unexpected deny event'i üretilmediğinin doğrulama notu.

**Failure Condition:**

- Audit writer başarılıyken `Read` tool deny alıyorsa.
- Artifact `policy_decision: "deny"` veya `outcome: "blocked"/"denied"`
  içeriyorsa (başarılı write durumunda).
- Hook false positive deny üretiyorsa (spurious denial).
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
- Mümkünse, audit unavailable'ı bildiren bir human-visible failure
  signal üretilmiş olmalıdır; bu signal raw tool identity, raw error
  metni, prompt, URL, token, secret, PII veya serbest metin
  içermemelidir (yalnızca sabit şablon + kapalı enum değeri).
- Human-visible failure signal, yeni bir MCP çağrısı başlatmamış
  ve audit zincirini yeniden tetiklememiş olmalıdır.

**Evidence:**

- `Read` tool'un yürütülmediğine dair kanıt (tool çıktısı yok, deny
  gözlemi veya log kaydı).
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
- `mcp_server` ve `mcp_tool` değerleri, gerçek MCP server adı değil;
  built-in tool için tanımlanmış canonical etiket içermelidir.

**Evidence:**

- Spike sırasında network çağrısı yapılmadığına dair log veya gözlem.
- MCP server bağlantısı kurulmadığını gösteren doğrulama notu.
- Geçici dosyaların ve artifact'ların incelenmesi sonucu gerçek
  credential veya endpoint içermediğinin kaydı.

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

**Failure Condition:**

- İnsan maintainer karar kaydı oluşturmamışsa.
- Kayıt, gerçek MCP bağlantısının otomatik olarak yetkilendirildiğini
  ima ediyorsa.
- Kayıt, spike'ın neyi kanıtlamadığını belirtmiyorsa.
- No-Go kapılarının hâlâ açık olduğu kaydedilmemişse.
- Karar imzasız, anonim veya makine tarafından otomatik oluşturulmuşsa
  (insan maintainer atfı yoksa).

---

## Quality Gate Özeti

| Quality Gate                                                                              | Karşılayan AC  |
|-------------------------------------------------------------------------------------------|----------------|
| Canonical `.claude/settings.json` ve hook scriptleri değişmeden kalır                     | AC-001, AC-010 |
| Aktif hook listesi yalnızca `Read`/`PreToolUse` matcher'ını içerir                        | AC-002         |
| Gerçek `Read` çağrısında hook tetiklendiği local artifact ile kanıtlanır                  | AC-003         |
| Üretilen audit event tam olarak 15 alan taşır                                              | AC-004         |
| Artifact raw input, dosya içeriği, prompt, URL, token, PII veya serbest metin içermez     | AC-005         |
| `session_reference` ve `operation_reference` raw runtime identifier taşımaz               | AC-006         |
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
