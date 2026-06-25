# ADR-006 — MCP Audit Logging and Runtime Enforcement Model

- **ADR-ID:** ADR-006
- **Status:** Accepted
- **Date:** 2026-06-25
- **Acceptance date:** 2026-06-25
- **Owner:** Human maintainer
- **Related controls:** PROJECT_CONSTITUTION.md, CLAUDE.md, AGENTS.md,
  ADR-001-role-based-hook-enforcement.md,
  ADR-003-ownership-runtime-enforcement.md,
  ADR-004-ownership-ci-diff-enforcement.md,
  ADR-005-mcp-tooling-control-plane.md,
  docs/decisions/AGENT_CAPABILITY_MATRIX.md,
  docs/decisions/MCP_AGENT_CAPABILITY_MATRIX.md,
  docs/quality/security-reports/SEC-ADR-005-MCP-CONNECTION-PRECONDITIONS.md,
  docs/decisions/MCP_AUDIT_EVENT_CONTRACT.md (yeni)

## Context

ADR-005, MCP (Model Context Protocol) entegrasyonları için bir politika ve
sınıflandırma modeli kabul etti: read-only-by-default, canonical source of
truth modelinin korunması, untrusted MCP output ilkesi ve agent/tool/
environment üçlü yetki modeli. ADR-005 kabul edilirken Security Red Team
**High** öncelikli bir audit logging ön koşulu tanımladı ve
`SEC-ADR-005-MCP-CONNECTION-PRECONDITIONS.md` kaydında bunu "Bağlantı
Öncesi Zorunlu Kapılar" listesine taşıdı.

Bu acceptance anında repository'de hiçbir MCP `Active`, `Configured` veya
`Connected` değildir; `MCP_AGENT_CAPABILITY_MATRIX.md`'deki tüm satırlar
"Planned — policy only" veya "Planned — future state, not connected"
durumundadır. ADR-005'in "Open Questions" bölümü açıkça şunu bıraktı: audit
log'ların nerede saklanacağı, ne kadar süreyle saklanacağı, hangi
mekanizmayla review edileceği ve MCP tool call'larının Claude Code
runtime'ında teknik olarak nasıl gözlemlenip engellenebileceği henüz
kararlaştırılmamıştır.

Mevcut enforcement zinciri şu üç ayrı güven sınırından oluşur ve hiçbiri
diğerinin yerini almaz:

1. **Runtime hook (ADR-001, ADR-003):**
   `.claude/hooks/enforce-role-boundaries.sh`, Claude'un `Edit`/`Write`/
   `Bash` araç çağrılarını agent kimliğine ve (implementer agent'lar için)
   approved ownership manifest'e göre denetler.
2. **CI diff gate (ADR-004):** `scripts/validate_ownership_diff.py`, bir
   PR'ın Git diff'indeki path'lerin base-approved manifest yetkisi
   içinde kalıp kalmadığını merge-time'da denetler.
3. **MCP tool/data access boundary (ADR-005):** hangi agent'ın hangi
   MCP'yi hangi ortamda ve hangi yan etki sınırıyla kullanabileceğini
   tanımlayan politika modeli; ancak bu model şu ana kadar hiçbir teknik
   audit veya enforcement mekanizmasına bağlanmamıştır.

Bu ADR, ADR-005'in bıraktığı "audit logging ve MCP runtime enforcement
nasıl tasarlanır" sorusuna yanıt verir.

## Problem

ADR-001 — ADR-004 zinciri, "bir agent hangi dosyaya yazabilir" sorusunu
teknik olarak çözer. ADR-005, "bir agent hangi dış sisteme bağlanabilir"
sorusuna politika seviyesinde cevap verir ancak şu teknik boşlukları
bırakır:

- MCP tool çağrılarının (varsa) hangi Claude Code lifecycle event'lerinden
  gözlemlenebileceği netleşmemiştir.
- Bir MCP çağrısının gerçekleştiğine dair insan tarafından incelenebilir,
  secret/PII içermeyen bir kayıt mekanizması yoktur.
- Agent/MCP/environment eşleşmesi `MCP_AGENT_CAPABILITY_MATRIX.md`'ye
  uymadığında bunu fail-closed biçimde durduracak bir runtime mekanizma
  tanımlı değildir.
- Audit logger'ın kendisi çalışmazsa veya yazamazsa, bunun gerçek MCP
  çağrısını durdurması gerektiği ADR-005'te ilke olarak var ama teknik
  tasarımı yoktur.
- Capability validation'ın hangi aşamalardan (bağlanmadan önce sentetik
  test, bağlandıktan sonra gerçek smoke test) geçmesi gerektiği
  belirsizdir.

Bu ADR yalnızca **teknik tasarım modelidir**. Hiçbir MCP server kurmaz,
bağlamaz, audit logger'ı implemente etmez ve gerçek bağlantıyı açmaz.

## Decision

Agentic DevFlow OS için bir **MCP Audit Logging and Runtime Enforcement
Model** tanımlanır. Bu model, gerçek bir MCP bağlantısı kurulmadan önce
sağlanması gereken teknik tasarımı kayıt altına alır; hiçbir bileşeni bu
ADR kapsamında implemente edilmez.

### 1. Audit'in kapsamı

Bu ADR'de tanımlanan audit logging mekanizması **yalnızca MCP tool
çağrıları içindir**. Bu mekanizma:

- Normal Git diff denetimi (ADR-004) **değildir** ve onun yerine geçmez.
- Dosya sistemi audit'i (ADR-001/ADR-003 runtime hook) **değildir** ve
  onun yerine geçmez.
- Claude'un `Edit`/`Write`/`Bash` araç çağrılarını kapsamaz; bu çağrılar
  zaten ADR-001/ADR-003/ADR-004 zincirinin kapsamındadır.

MCP audit logging, **dış araç çağrısı görünürlüğü, politika kontrolü ve
audit trail** sağlamak için ayrı, ek bir katmandır.

### 2. Hedef lifecycle event'leri

Önceki taslakta `PermissionRequest → PreToolUse → gerçek MCP çağrısı`
sıralaması evrensel ve her çağrıda zorunlu bir zincir gibi sunulmuştu. Bu
yanlıştır ve düzeltilmiştir: `PermissionRequest`, yalnızca kullanıcıya bir
permission dialog gösterilecekse ortaya çıkan **koşullu** bir event'tir;
her MCP çağrısında bulunması zorunlu değildir. Aşağıdaki model bunun
yerine geçer:

1. **`PreToolUse`** — her aday MCP tool çağrısı için temel pre-execution
   kontrol noktasıdır. Policy evaluation'ın ve gerçek bağlantı aşamasındaki
   fail-closed kararın ana noktası burasıdır. Bu event, `PermissionRequest`
   tetiklenip tetiklenmediğinden bağımsız olarak her aday çağrı için
   gözlemlenmesi beklenen zorunlu noktadır.
2. **`PermissionRequest`** — yalnızca Claude Code kullanıcıya/konfigürasyona
   bir permission dialog gösterecekse ortaya çıkan **koşullu** event'tir.
   Her MCP çağrısında bulunması zorunlu değildir; ancak insan veya
   permission policy kararı gerektiren yollarda audit açısından görünür
   olmalıdır.
3. **İzin reddi / çağrının yürütülmemesi** — tool hiç çalışmadığında
   `PostToolUse` veya `PostToolUseFailure` event'i beklenemez (bu event'ler
   yalnızca gerçek tool execution başladıktan sonra anlamlıdır). Bu nedenle
   audit modeline açık bir `PermissionDenied` (veya eşdeğer açık bir denial
   outcome) yolu eklenmiştir: reddedilen bir çağrının audit kaydı, aksiyon
   hiç yürütülmeden önce tamamlanmış olmalıdır. `PostToolUseFailure`,
   izin reddini **kapsamaz**; izin reddi ile gerçek execution sonrası hata
   ayrı, birbirine indirgenemeyen iki audit yoludur.
4. **Gerçek MCP çağrısı** — yalnızca policy approval, capability
   doğrulaması ve audit availability koşulları sağlandıktan **sonra**
   gerçekleşebilir.
5. **`PostToolUse`** — başarılı gerçek tool execution sonrası üretilir.
6. **`PostToolUseFailure`** — gerçek tool execution başladıktan sonra hata
   veya failure result oluşursa üretilir.

Bu modelde "`PermissionRequest` her zaman olur" veya "`PostToolUseFailure`
izin reddini kapsar" biçiminde herhangi bir yanlış çıkarıma yer
verilmemiştir. Bu altı adım, agent/tool/environment üçlü yetki modelinin
(ADR-005) runtime'da hangi noktalarda gözlemlenip kayıt altına alınacağını
tanımlar.

### 3. Audit logging ilkeleri

1. Her MCP tool çağrısı (denenen, izin verilen, reddedilen veya
   başarısız olan) en az bir audit kaydı üretmelidir.
2. Audit kaydı **ham veri taşımaz**: tool input, tool output, prompt
   içeriği, URL query değeri, Authorization header, token, API key,
   secret, PII, müşteri kaydı veya dosya içeriği audit kaydına dahil
   edilmez. Audit kaydı yalnızca "bu çağrı oldu, bu sınıftaydı, bu
   sonuçla bitti" bilgisini taşır — çağrının içeriğini değil.
3. Audit kaydı **action authority değildir**. Bir aksiyonun audit
   kaydına yazılmış olması, o aksiyonun yetkili olduğu anlamına gelmez;
   audit sadece görünürlük sağlar, yetkilendirme kararı policy
   (capability matrix) ve runtime enforcement katmanına aittir.
4. Audit kaydı, schema'sı sabit ve insan tarafından makine-okunabilir
   biçimde gözden geçirilebilir olmalıdır (bkz.
   `MCP_AUDIT_EVENT_CONTRACT.md`).

### 4. Minimum kayıt alanları

Her audit kaydı en az şu **15** alanı içermelidir (tam tanım ve enum
değerleri `MCP_AUDIT_EVENT_CONTRACT.md`'dedir):

- `schema_version`
- `event_id`
- `timestamp`
- `session_reference` (privacy-preserving correlation reference; ham
  oturum/kullanıcı kimliği değil)
- `operation_reference` (aynı MCP çağrısına ait `PreToolUse`, koşullu
  `PermissionRequest`/denial, `PostToolUse` ya da `PostToolUseFailure`
  event'lerini ilişkilendirmek için kullanılan, privacy-preserving,
  per-call korelasyon referansı; `session_reference`'tan farklıdır —
  `session_reference` oturum seviyesinde, `operation_reference` tekil
  çağrı seviyesindedir ve aynı session içindeki paralel tool çağrılarını
  ayırt etmeyi sağlar)
- `agent_type`
- `event_phase`
- `mcp_server`
- `mcp_tool`
- `action_class`
- `environment_scope`
- `policy_decision`
- `outcome`
- `failure_category` (varsa)
- `audit_record_version`

`operation_reference` raw `tool_use_id`, transcript path, prompt veya
kullanıcı kimliği taşımaz; bu alanın somut üretim yöntemi (hash, salted
token, local sayaç vb.) bu ADR'de seçilmez ve "Open Questions" altında
açık kalır.

**Collision-resistance zorunlu kısıtı (bağlanmadan önce kapatılması gereken
gate — bkz. "16. `operation_reference` Collision-Resistance İlkesi"):**
`operation_reference` yalnızca privacy-preserving olmakla yetinemez; aynı
zamanda **collision-resistant** olmalıdır. Aynı retention penceresi içinde
iki farklı MCP operasyonuna aynı `operation_reference` değeri **asla**
atanamaz; bu, paralel çağrıların lifecycle event'lerinin yanlışlıkla aynı
operation altında birleşmesini önlemek için bağlayıcı bir gerekliliktir.
Somut üretim algoritması (hash fonksiyonu, salt stratejisi, sayaç + namespace
vb.) bu ADR'de seçilmez; ancak yüksek entropi, uniqueness ve
collision-resistance, gerçek bağlantı öncesi capability validation'ın
zorunlu bir parçasıdır.

### 5. Runtime enforcement yaklaşımı

Agent rolü, MCP tool'u ve environment scope eşleşmesi
`MCP_AGENT_CAPABILITY_MATRIX.md`'deki "Allowed agents", "Default
permission" ve "Environment scope" sütunlarıyla uyumlu değilse, **gerçek
bağlantı aşamasında** bu eşleşme deny/fail-closed olarak ele alınmalıdır.
Bu, ADR-003'ün implementer agent'lar için kurduğu "branch + manifest +
owner + write_paths" dört koşullu fail-closed modeline benzer bir mantığı
MCP tarafına taşır:

1. **Agent identity** — çağrıyı yapan agent, ilgili MCP için capability
   matrix'te "Allowed agents" listesinde olmalı.
2. **Tool capability** — istenen aksiyon, o MCP için tanımlı "Default
   permission" ve "Explicitly prohibited actions" sınırları içinde olmalı.
3. **Environment boundary** — aksiyon, o MCP için tanımlı "Environment
   scope" içinde olmalı.

Bu üç koşuldan biri sağlanmazsa karar **deny** olmalıdır. Bu ADR bu üç
koşulun hangi teknik mekanizmayla (Claude Code hook noktası, MCP server
tarafı policy katmanı veya ikisinin birleşimi) bağlanacağını henüz
kesinleştirmez (bkz. "Open Questions"); bu ADR yalnızca **modeli** kayıt
altına alır.

**Tool identity sınıflandırması ve strict parsing (önkoşul):** Yukarıdaki
üç koşulun değerlendirilebilmesi için runtime event içindeki tool kimliği
(`mcp_server`, `mcp_tool`) öncelikle **strict format validation** ile
sınıflandırılmalıdır; bu alanlar runtime event'inden geldiği için doğrudan
güvenilir kabul edilmez. Şu ilkeler geçerlidir:

- Sınıflandırma sonucunda MCP server, MCP tool veya capability matrix
  eşleşmesi kesin biçimde çıkarılamıyorsa, gerçek bağlantı aşamasında
  `policy_decision=deny` uygulanır.
- Belirsiz, tanınmayan veya `MCP_AGENT_CAPABILITY_MATRIX.md` dışında kalan
  bir tool identity, gerçek bağlantı için tek başına fail-closed sebebidir
  — agent identity ve environment boundary koşulları sağlanmış olsa bile.
- Bu sınıflandırma varsayımı önce sentetik hook payload testiyle, daha
  sonra MCP bazlı environment-specific smoke test ile doğrulanmalıdır
  (bkz. "10. Capability validation yaklaşımı").
- Raw tool input, raw tool output, prompt, URL, header, token, secret veya
  dosya içeriği, bu sınıflandırma adımında dahi audit event'ine dahil
  edilmez; sınıflandırma yalnızca `mcp_server`/`mcp_tool` etiketleri ve
  capability matrix eşleşmesi üzerinden yapılır.

**Ham runtime string'inin asla persist edilmemesi (bkz. "14. Unknown Tool
Identity ve Sentinel Model" — bu, bağlanmadan önce kapatılması zorunlu bir
gate'dir):** Runtime'dan gelen ham `mcp_server`/`mcp_tool` string'i hiçbir
zaman doğrudan güvenilir bir audit alanı değildir ve audit kaydına, denial
yoluna veya human-visible failure signal'e **hiçbir biçimde** ham olarak
yazılamaz. Audit event'ine yalnızca local allowlist/map üzerinden üretilen
canonical, güvenli etiketler yazılabilir. Sınıflandırılamayan veya
allowlist dışı bir değer için audit kaydı şu sabit sentinel değerlerle
oluşturulur:

- `mcp_server: "unclassified"`
- `mcp_tool: "unclassified"`
- `policy_decision: "deny"`
- `failure_category: "unclassified_tool_identity"`

### 6. Fail-closed yaklaşımı

Audit logger çalışmıyorsa, audit kaydı yazılamıyorsa veya bir audit event
herhangi bir nedenle oluşturulamıyorsa, gerçek MCP çağrısı **default
olarak ilerlememelidir**. Bu, "audit yoksa aksiyon da yok" ilkesidir. Bu
ilke aşağıdaki şekilde daha uygulanabilir biçimde tanımlanır:

- Gerçek MCP bağlantısı aşamasında, dış çağrı başlamadan **önce** audit
  logger kullanılabilir olmalı ve audit event yazımı doğrulanabilmelidir.
  Audit logger kullanılabilir değilse veya audit event yazımı
  doğrulanamazsa, dış MCP çağrısı **başlatılmaz**.
- Bu durumda çağrı `deny` edilir ve insan incelemesi için, secret/PII
  içermeyen, **human-visible bir failure signal** üretilmesi gereklidir
  (örnek niteliğinde: `failure_category: audit_unavailable`).
- Bu signal'in nerede/nasıl saklanacağı veya gösterileceği (storage,
  location, vendor) bu ADR kapsamında seçilmez; bu karar "Open Questions"
  altında açık kalır.
- Audit logging arızası hiçbir koşulda sessiz `allow` veya dış çağrının
  audit'siz biçimde devam etmesi sonucunu doğurmaz; arıza durumunda tek
  geçerli sonuç deny + human-visible failure signal'dir.

**"Audit availability ping" yeterli değildir (bağlanmadan önce kapatılması
zorunlu gate — bkz. "15. TOCTOU Kapanışı: Durable Write Acknowledgment
Önce, Dispatch Sonra"):** Bu ADR'nin önceki taslağında "audit availability
doğrulanmadan dış çağrı başlamaz" ifadesi yalnızca bir erişilebilirlik
ping'i gibi yorumlanabilirdi. Bu yanlıştır ve düzeltilmiştir: gerçek gate,
dış çağrıdan önceki **minimal `PreToolUse` audit event'inin durable write
acknowledgment'ı**dır — yalnızca audit sink'in "çalışıyor" olması değil,
o spesifik event'in onun integrity/durability modeline uygun biçimde
yazıldığının doğrulanmasıdır. Bu sıralamanın tam adımları aşağıdaki "15.
TOCTOU Kapanışı" bölümünde ve "MCP Event Lifecycle Modeli" diyagramında
tanımlanır.

Bu ilke şu an **yalnızca bir tasarım kararıdır**; bu ADR kapsamı teknik
tasarımdır ve bu karar gerçek bağlantı aşamasında uygulanacaktır. Bu ADR
hiçbir audit logger implemente etmez, hiçbir gerçek MCP çağrısını
durdurmaz veya izin vermez.

#### 6a. Human-Visible Failure Signal — Kapalı Tanım

Yukarıdaki "human-visible failure signal" ifadesi, bu ADR ve
`MCP_AUDIT_EVENT_CONTRACT.md` boyunca **tek ve sabit** bir anlamla
kullanılır; bu sinyal ile audit event payload'ı arasındaki ayrım
bağlayıcıdır:

- **Audit event payload'ının ek bir alanı değildir.** Human-visible
  failure signal, `MCP_AUDIT_EVENT_CONTRACT.md`'de tanımlı 15 alanlık
  kapalı şemaya yeni bir alan eklemez ve bu şemanın bir parçası olarak
  modellenmez.
- **Out-of-band ve non-recursive bir bildirimdir.** Audit event yazma
  yolundan ayrı bir bildirim kanalıdır; audit sink'in kendisi veya onun
  yazma zinciri üzerinden taşınmaz.
- **Yalnızca locally controlled sabit şablonlar ve kapalı
  `failure_category` enum değerleri üzerinden üretilebilir.** Sinyal,
  serbest metin oluşturarak değil, önceden tanımlı, sabit, insan
  tarafından yazılmış şablon metinleri ve `MCP_AUDIT_EVENT_CONTRACT.md`'de
  tanımlı kapalı `failure_category` enum üyeleri üzerinden üretilir.
- **Raw tool identity, raw error/exception metni, prompt, URL, token,
  secret, PII, kullanıcı verisi veya serbest metin taşımaz.** Bu sinyal,
  runtime'dan gelen ham hata mesajını, ham tool kimliğini veya başka bir
  serbest metin içeriği hiçbir biçimde yansıtmaz; yalnızca sabit şablon +
  kapalı enum değeri taşır.
- **Yeni bir MCP çağrısı başlatmaz.** Sinyalin üretilmesi veya
  görüntülenmesi, doğrudan veya dolaylı olarak yeni bir MCP tool-call
  tetiklemez; bu, "13. Out-of-Band ve Non-Recursive Audit Writer İlkesi"
  ile tutarlıdır.
- **Human approval veya capability validation kanıtının yerine geçmez.**
  Bu sinyalin üretilmiş olması, herhangi bir insan onayı, capability
  validation veya smoke test kanıtı sağlamaz; bu kanıtlar ayrı ve açık
  biçimde, insan maintainer tarafından sağlanmalıdır (bkz. "10.
  Capability validation yaklaşımı", ADR-005 "İnsan Onay Kapıları").

Bu sinyalin **nerede/nasıl gösterileceği** (storage, location, vendor,
terminal çıktısı vb.) bu ADR kapsamında seçilmez; bu karar "Open
Questions" altında açık kalır. Ancak sinyalin **içerik modeli** (yukarıdaki
beş kısıt) açık bir soru değildir; bu, gerçek bağlantı öncesi kapatılması
gereken bağlayıcı bir tasarım kuralıdır ve `MCP_AUDIT_EVENT_CONTRACT.md`
ile aynı anlamda tanımlıdır.

### 7. Concurrency ve ordering

Aynı session içinde paralel MCP çağrıları olabilir; bu durum audit
modelinin tasarımında açıkça kabul edilir:

- `timestamp` alanı tek başına total ordering kanıtı **değildir**; paralel
  çağrılarda event'ler arasında kesin bir sıralama garantisi vermez.
- Lifecycle bütünlüğü (bir çağrının `PreToolUse`'dan `PostToolUse`/
  `PostToolUseFailure`/denial'a kadar olan zinciri) `operation_reference`
  üzerinden değerlendirilir, timestamp sıralamasına dayanılmaz.
- Batch-level event'ler (birden çok çağrıyı tek bir audit kaydında
  özetleyen yaklaşımlar) bu tasarımın ana audit kaynağı **değildir**;
  gerekirse bu, gelecekte ayrı bir genişletme olarak ele alınır.
- Her operation için izin/ret/başarı/failure sonucu, `operation_reference`
  üzerinden audit kanıtında ayırt edilebilir olmalıdır.

### 8. Secret / PII minimization

- Audit kayıtları canonical Git repository'ye, `.claude/`, `.github/`,
  dokümanlara, Obsidian'a veya NotebookLM kaynaklarına **secret-bearing
  data olarak yazılmaz**.
- Audit kayıtları, ADR-005'in "Untrusted MCP Output / Indirect Prompt
  Injection İlkesi" ile tutarlı olarak, tool output içindeki talimatları
  veya ham içeriği **taşımaz**; bu içerik audit trail'in bir parçası
  değildir.
- Audit kaydı yalnızca yapısal/sınıflandırma alanları (bkz. minimum kayıt
  alanları) taşır. **Audit event schema'sında serbest metin not alanı
  yoktur. Böyle bir alan eklenemez. Redaction, yasak veriyi kabul etmek
  için bir istisna değildir; yasak verinin event payload'a hiç
  girmemesidir.** `note`, `notes`, `message`, `error_message`, `details`,
  `description`, `context`, `metadata`, `debug` veya buna eşdeğer serbest
  metin alanları bu schema'ya **eklenemez** (tam kapalı alan listesi için
  bkz. `MCP_AUDIT_EVENT_CONTRACT.md`).

### 9. Storage, retention ve review modeli

Bu ADR **hiçbir vendor, logging platformu veya saklama teknolojisi
seçmez**. Bunun yerine, bir storage/retention/review kararı alınacağı
zaman uygulanması gereken karar kriterlerini tanımlar:

- **Erişim sınırı:** Audit storage, secret-bearing olmayan veriyi taşısa
  bile, insan maintainer onayı olmadan herkese açık veya geniş erişimli
  bir hedefe yazılmamalıdır.
- **Git-tracked olmama:** Audit kayıtları canonical Git repository'nin
  bir parçası olarak commit edilmez (PROJECT_CONSTITUTION.md §6 ile
  tutarlı); ayrı bir storage hedefi gerektirir.
- **Retention süresi:** Audit kayıtlarının ne kadar süre saklanacağı
  insan maintainer tarafından belirlenmeli ve dokümante edilmelidir; bu
  ADR bir süre önermez.
- **Review sıklığı/sahibi:** Audit kayıtlarının kim tarafından, hangi
  sıklıkla gözden geçirileceği insan maintainer tarafından
  belirlenmelidir.
- **Tersine mühendislik riski:** Storage hedefi seçilirken, secret/PII
  içermese bile agent davranış desenlerinin (hangi agent hangi MCP'yi ne
  sıklıkla kullanıyor) hassas olabileceği dikkate alınmalıdır.

Bu kriterlerin hangi vendor/platform ile karşılanacağı **insan maintainer
onayı gerektirir**; bu ADR bu seçimi yapmaz.

### 10. Capability validation yaklaşımı

Capability validation iki ayrı katmanda yürütülmelidir:

1. **Sentetik hook payload testi (bağlantı öncesi):** Gerçek bir MCP
   bağlanmadan önce, Claude Code hook event'lerinde MCP tool çağrılarının
   görünür olup olmadığı sentetik (gerçek olmayan, üretilmiş) input'larla
   doğrulanmalıdır. Bu, "MCP tool çağrıları hook'larda görünür" varsayımını
   gerçek veri kullanmadan test eder.
2. **Environment-specific smoke test (bağlantı sonrası):** MCP gerçekten
   bağlandıktan sonra, ilgili araç için ortam-spesifik (örnek: yalnızca
   test hesabı/sentetik veri ile) bir smoke test yürütülmeli ve audit
   kaydının gerçekten üretildiği doğrulanmalıdır.

Bu iki katman birbirinin yerine geçmez: sentetik test, gerçek bağlantı
riski olmadan hook görünürlüğünü doğrular; smoke test ise gerçek bağlantı
sonrası audit/enforcement zincirinin gerçekten çalıştığını doğrular.

### 11. Gerçek bağlantının otomatik açılmaması

**Bu ADR kabul edilse bile, hiçbir gerçek MCP bağlantısı otomatik olarak
açılmaz.** ADR-005'in "Security Follow-up / Connection Preconditions" ve
`SEC-ADR-005-MCP-CONNECTION-PRECONDITIONS.md`'deki "Bağlantı Öncesi
Zorunlu Kapılar" listesi bu ADR'nin kabulünden sonra da geçerliliğini
sürdürür. Bu ADR'nin kabulü yalnızca audit/enforcement **tasarımının**
kabul edildiği anlamına gelir; gerçek bağlantı için ayrıca:

- Audit logging mekanizmasının çalışır biçimde implemente edilmesi,
- Her MCP için capability validation ve environment-specific smoke
  test'in tamamlanması,
- Credential storage onayının insan maintainer tarafından verilmesi,
- Ayrı, açık bir insan maintainer onayının kaydedilmesi

gerekir.

### 12. Audit Integrity, Durability and Tamper Evidence İlkesi

Security Red Team'in ADR-006 review bulgusu (Bulgu 1) üzerine, bu ADR'ye
**açık ve bağlayıcı** bir audit integrity ilkesi eklenmiştir. Bu ilke,
"Open Questions" altında bırakılabilecek bir tercih değil, **gerçek MCP
bağlantısından önce kapatılması zorunlu bir gate**'tir:

- Gerçek MCP bağlantısından önce, audit storage/sink **append-only veya
  doğrulanabilir biçimde tamper-evident** olmalıdır.
- Bir audit kaydı yazıldıktan sonra, yetkisiz silme, değiştirme veya
  retroaktif eksiltmeye karşı **teknik bir kontrol** bulunmalıdır (örnek
  nitelikte mekanizma sınıfları: append-only storage, hash-chain, WORM
  storage — ancak bu ADR somut mekanizmayı seçmez, bkz. aşağıda).
- Retention süreci kapsamındaki **meşru** silme/yaşam döngüsü işlemleri
  (örnek: retention süresi dolduğunda planlı silme), bu tamper-evidence
  kontrolünün dışında, ayrı ve açık bir yetkilendirme adımı ve buna dair
  kanıt gerektirir. Meşru retention silme işlemi ile yetkisiz/sessiz
  silme/değiştirme aynı yetki düzeyine sahip değildir.
- Audit storage integrity doğrulaması, "10. Capability validation
  yaklaşımı" bölümünde tanımlanan capability validation kanıtının
  **zorunlu bir parçasıdır**; integrity doğrulanmadan capability
  validation tamamlanmış sayılmaz.

**Bu ADR'nin seçmediği şey:** Hangi vendor, WORM storage, hash-chain veya
benzeri somut teknik mekanizmanın kullanılacağı bu ADR kapsamında
seçilmez; bu seçim "Open Questions" altında açık kalır (storage/vendor
kararı insan maintainer onayı gerektirir, bkz. "9. Storage, retention ve
review modeli").

**Bu ADR'nin seçtiği şey (bağlayıcı):** Seçilecek çözümün append-only veya
tamper-evident gereksinimini **nasıl sağladığı**, gerçek MCP bağlantısı
açılmadan önce **insan maintainer tarafından doğrulanmalıdır**. Bu
doğrulama yapılmadan capability validation tamamlanmış kabul edilmez ve
gerçek bağlantı açılamaz.

### 13. Out-of-Band ve Non-Recursive Audit Writer İlkesi

Security Red Team'in ADR-006 review bulgusu (Bulgu 2) üzerine, audit
writer'ın kendi gözlemlediği mekanizmayı kullanamayacağına dair **bağlayıcı**
bir ilke eklenmiştir:

- Audit logging mekanizması, gözlemlediği MCP tool-call lifecycle'ının
  **kendisini** audit yazımı için kullanamaz.
- Audit writer; bir MCP server çağrısı, MCP-benzeri bir tool call veya
  aynı `PreToolUse`/`PostToolUse` zincirini yeniden tetikleyecek herhangi
  bir mekanizma kullanarak audit kaydı yazamaz.
- Audit sink işlemleri (yazma, doğrulama, retry) için **recursive
  audit/enforcement döngüsü** oluşmamalıdır — audit yazma denemesinin
  kendisi yeni bir denetlenecek MCP tool-call üretmemelidir.
- Audit writer başarısız olduğunda yalnızca secret/PII içermeyen,
  human-visible bir failure signal üretilir (bkz. "6. Fail-closed
  yaklaşımı"); bu signal **yeni bir MCP çağrısı başlatmaz** ve audit
  zincirini tekrar tetiklemez.
- Somut sink/transport tekniği (örnek: local append-only dosya, ayrı bir
  out-of-band servis, harici logging pipeline) bu ADR'de seçilmez; ancak
  gerçek implementasyon öncesinde **re-entrancy olmadığının** sentetik
  test ve capability validation ile doğrulanması, bu ADR kapsamında
  **zorunlu teknik doğrulama** olarak kayıt altına alınır (bkz. "10.
  Capability validation yaklaşımı").

Bu ilke, "Open Questions" altında bırakılamaz; gerçek bağlantı öncesi
kapatılması gereken bir tasarım gate'idir.

### 14. Unknown Tool Identity ve Sentinel Model

Security Red Team'in ADR-006 review bulgusu (Bulgu 3) üzerine, "5. Runtime
enforcement yaklaşımı" bölümündeki tool identity sınıflandırması şu
**bağlayıcı** kurallarla netleştirilmiştir:

- Runtime'dan gelen `mcp_server` ve `mcp_tool` string'leri **hiçbir zaman**
  doğrudan güvenilir bir audit alanı değildir.
- Audit event'ine yalnızca **local allowlist/map** üzerinden üretilen
  canonical, güvenli etiketler yazılabilir.
- Sınıflandırılamayan veya allowlist dışı (`MCP_AGENT_CAPABILITY_MATRIX.md`
  dışı) bir değer için audit kaydı şu sabit sentinel değerlerle üretilir:
  - `mcp_server: "unclassified"`
  - `mcp_tool: "unclassified"`
  - `policy_decision: "deny"`
  - `failure_category: "unclassified_tool_identity"`
- Ham runtime string'i; denial yolu dahil, **hiçbir** audit kaydına,
  human-visible failure signal'e veya serbest metin alana yazılamaz.
- Canonical `mcp_server` ve `mcp_tool` etiketleri yalnızca lowercase ASCII
  güvenli karakter kümesiyle sınırlıdır:
  - En fazla 64 karakter.
  - Önerilen format: `^[a-z0-9][a-z0-9._-]{0,63}$`.
- `action_class`, `environment_scope`, `policy_decision`, `outcome` ve
  `failure_category` yalnızca tanımlı enum değerlerden oluşur; serbest
  metin veya kullanıcı kontrollü değer bu alanlara **kabul edilmez**.
- Audit payload içinde error message, raw identity, URL, prompt, header,
  dosya yolu veya başka bir açıklama/serbest metin alanı **bulunmaz**.

Bu kurallar `MCP_AUDIT_EVENT_CONTRACT.md` içinde normatif biçimde
tekrarlanmıştır; bu ADR ile contract arasında çelişki olması durumunda her
iki doküman da güncellenmelidir.

### 15. TOCTOU Kapanışı: Durable Write Acknowledgment Önce, Dispatch Sonra

Security Red Team'in ADR-006 review bulgusu (Bulgu 4) üzerine, audit
durable write ile gerçek MCP dispatch'i arasındaki time-of-check/
time-of-use (TOCTOU) riskini kapatan güvenli sıralama bağlayıcı biçimde
tanımlanmıştır. Gerçek bağlantı aşamasında bu sıralama şu şekilde
uygulanmalıdır:

1. `PreToolUse` tetiklenir.
2. Tool identity strict biçimde sınıflandırılır (bkz. "5. Runtime
   enforcement yaklaşımı", "14. Unknown Tool Identity ve Sentinel Model").
3. Role, tool ve environment capability policy değerlendirmesi yapılır
   (agent identity, tool capability, environment boundary — bkz. "5.").
4. Safe ve minimal `PreToolUse` audit event'i oluşturulur (yalnızca
   contract'ta tanımlı 15 alan; ham veri yok).
5. Audit sink, bu event'in durable/intended integrity modeline (bkz.
   "12. Audit Integrity, Durability and Tamper Evidence İlkesi") uygun
   biçimde yazıldığını **doğrular** (write acknowledgment).
6. Bu yazım onayı (acknowledgment) alınmadan, dış MCP çağrısı **dispatch
   edilmez**.
7. Yukarıdaki adımların herhangi birinde parser failure, identity
   mismatch, policy mismatch, timeout, malformed event, audit unavailable
   veya write acknowledgment failure oluşursa, çağrı **deny** edilir ve
   dış MCP çağrısı **başlatılmaz**.

"Audit availability ping" (yalnızca sink'in erişilebilir olduğunu kontrol
eden bir health-check) bu gate için **tek başına yeterli değildir**. Gerçek
gate, dispatch'ten önceki minimal `PreToolUse` audit event'inin **durable
write acknowledgment'ı**dır.

`PermissionDenied` akışı için de aynı model geçerlidir:

- Aksiyon yürütülmeden önce, denial kaydı — mümkünse — aynı güvenli/
  durable audit modeliyle tamamlanır.
- Audit sink tamamen unavailable ise dış MCP çağrısı zaten başlamaz;
  bu durumda yalnızca non-recursive, secret/PII içermeyen bir
  human-visible failure signal üretilebilir (bkz. "13. Out-of-Band ve
  Non-Recursive Audit Writer İlkesi").

Bu sıralama, "MCP Event Lifecycle Modeli" diyagramına da yansıtılmıştır
(bkz. ilgili bölüm).

### 16. `operation_reference` Collision-Resistance İlkesi

Security Red Team'in ADR-006 review bulgusu (Bulgu 5) üzerine,
`operation_reference` alanı için şu **bağlayıcı** ilkeler eklenmiştir:

- `operation_reference`, privacy-preserving olmanın yanında **collision-
  resistant** olmalıdır.
- Aynı retention penceresinde iki farklı MCP operasyonu için **tekrar
  kullanılamaz**.
- Paralel çağrıların lifecycle event'leri, `operation_reference` çakışması
  nedeniyle yanlışlıkla aynı operation altında **birleşmemelidir**.
- Üretim yöntemi (hash, salted token, namespaced sayaç vb.) bu ADR'de
  seçilmez; ancak yüksek entropi, uniqueness ve collision-resistance,
  gerçek bağlantı öncesi **teknik bir gerekliliktir**, isteğe bağlı bir
  iyileştirme değildir.
- Sentetik test ve gerçek MCP capability validation aşamasında, paralel
  çağrı/lifecycle correlation senaryosu (iki eşzamanlı çağrının
  `operation_reference` değerlerinin çakışmadığı) **doğrulanmalıdır**.

## Trust Boundaries

Üç ayrı güven sınırı vardır ve bu ADR bunlardan hiçbirini birleştirmez
veya birinin yerine geçirmez:

| Sınır | Kapsam | Sorumlu mekanizma |
|---|---|---|
| Runtime hook | Claude tool çağrısı (`Edit`/`Write`/`Bash`) ve agent/path sınırları | `.claude/hooks/enforce-role-boundaries.sh` (ADR-001, ADR-003) |
| CI diff gate | Git diff path authority | `scripts/validate_ownership_diff.py` (ADR-004) |
| MCP audit/enforcement | Dış araç çağrısı görünürlüğü, politika kontrolü ve audit trail | Bu ADR'nin tanımladığı, henüz implemente edilmemiş model |

Bu üç sınır birbirini **tamamlar**. Bir MCP politika ihlali, runtime hook
veya CI diff gate tarafından otomatik yakalanmaz; bu ihlali yakalayacak
mekanizma bu ADR'nin tanımladığı MCP audit/enforcement katmanıdır.

## MCP Event Lifecycle Modeli

`PermissionRequest`, her çağrıda zorunlu olmayan **koşullu** bir dal
olarak modellenmiştir; `PreToolUse` her aday çağrı için zorunlu temel
kontrol noktasıdır. İzin reddi, gerçek execution hiç başlamadığı için
`PostToolUseFailure` ile karıştırılmaz; ayrı bir `PermissionDenied` denial
yolu vardır.

```
[Agent MCP tool çağrısı niyeti]
        │
        ▼
   PreToolUse  (her aday çağrı için zorunlu pre-execution kontrol noktası)
        │
        ▼
   [1. Tool identity strict sınıflandırma — bkz. "14. Unknown Tool Identity
       ve Sentinel Model"]
        │
        ├──(belirsiz/allowlist dışı)──► mcp_server=unclassified,
        │                               mcp_tool=unclassified,
        │                               policy_decision=deny,
        │                               failure_category=unclassified_tool_identity
        │                               [dış MCP çağrısı dispatch edilmez]
        │
        ▼ (sınıflandırma kesinse)
   [2. Agent/tool/environment capability policy değerlendirmesi — bkz. "5."]
        │
        ├──(policy/capability uyumsuz)──► audit: event_phase=PreToolUse,
        │                                 outcome=blocked, policy_decision=deny
        │                                 [dış MCP çağrısı dispatch edilmez]
        │
        ▼ (policy/capability uyumlu)
   [3. Safe/minimal PreToolUse audit event oluşturulur (15 alan, ham veri yok)]
        │
        ▼
   [4. Audit sink durable write acknowledgment'ı doğrulanır — bkz. "15. TOCTOU
       Kapanışı"; bu adım yalnızca bir "availability ping" değildir]
        │
        ├──(write acknowledgment alınamaz / parser failure / timeout /
        │    malformed event / audit unavailable)──► audit (mümkünse):
        │                                             failure_category=audit_unavailable,
        │                                             policy_decision=deny,
        │                                             outcome=blocked
        │                                             + non-recursive,
        │                                               secret/PII içermeyen
        │                                               human-visible failure
        │                                               signal
        │                                             [dış MCP çağrısı
        │                                              dispatch edilmez]
        │
        ▼ (write acknowledgment alındı)
        ├──(yalnızca permission dialog gerekiyorsa, koşullu)──►
        │        PermissionRequest
        │              │
        │              ├──(reddedilirse)──► [durable write acknowledgment'lı]
        │              │                    audit: event_phase=PermissionRequest,
        │              │                    outcome=denied (PermissionDenied),
        │              │                    policy_decision=deny
        │              │                    [aksiyon hiç yürütülmez;
        │              │                     PostToolUse/PostToolUseFailure
        │              │                     beklenmez; dış MCP çağrısı
        │              │                     dispatch edilmez]
        │              │ (izin verilirse)
        │              ▼
        └──(permission dialog gerekmiyor + policy/capability uyumlu)──┐
                                                                       ▼
                                       [5. Audit write acknowledgment onaylı —
                                           dış MCP çağrısı ancak şimdi dispatch
                                           edilebilir]
                                                       │
                                                       ▼
                                       [MCP tool gerçekten çalışır]
                                                       │
                                          ┌────────────┴────────────┐
                                          ▼                         ▼
                                     PostToolUse              PostToolUseFailure
                                     (başarı)                  (hata/exception)
                                          │                         │
                                          ▼                         ▼
                          audit: outcome=success      audit: outcome=failure,
                                                        failure_category=...
```

Audit writer bu diyagramdaki hiçbir adımda kendi gözlemlediği MCP
tool-call lifecycle'ını (PreToolUse/PostToolUse zincirini) yeniden
tetikleyerek yazma işlemi yapamaz; audit yazımı **out-of-band ve
non-recursive** olmalıdır (bkz. "13. Out-of-Band ve Non-Recursive Audit
Writer İlkesi"). Audit sink'e yazılan her event, `operation_reference`
üzerinden ilişkilendirilir; bu referans collision-resistant olmalıdır
(bkz. "16. `operation_reference` Collision-Resistance İlkesi").

Her dal `operation_reference` ile ilişkilendirilen bir audit kaydı ile
sonuçlanmalıdır. Hiçbir dal sessizce audit'siz ilerlememelidir (bkz.
"Fail-closed yaklaşımı"). "`PermissionRequest` her zaman olur" veya
"`PostToolUseFailure` izin reddini kapsar" çıkarımları bu modelde
geçersizdir.

## Alternatives Considered

1. **Audit logging'i dosya sistemi audit'i (ADR-001/ADR-003 hook) ile
   birleştirmek**
   - Reddedildi. Dosya sistemi audit'i `Edit`/`Write`/`Bash` çağrılarını
     kapsar; MCP tool çağrıları farklı bir lifecycle event ailesinde
     (varsa) gözlemlenir ve farklı bir veri sınıfı (dış sistem yan etkisi)
     taşır. İki audit modelini birleştirmek, ADR-005'in zaten net
     biçimde ayırdığı trust boundary'leri karıştırma riski taşır.

2. **Audit kaydına ham tool input/output'u kısmen dahil etmek
   (örnek: ilk N karakter)**
   - Reddedildi. Kısmi ham veri dahi secret/PII sızıntısı riski taşır;
     "minimum alan, sınıflandırma odaklı" modelin amacını zayıflatır.
     Audit kaydı bir forensic ham veri arşivi değil, bir görünürlük/
     sınıflandırma trail'idir.

3. **Storage/retention/review için bu ADR kapsamında bir vendor seçmek**
   - Reddedildi. Vendor seçimi insan maintainer onayı gerektiren bir
     altyapı kararıdır ve bu ADR'nin "yalnızca audit logging ve runtime
     enforcement mimarisi tasarla" kapsamının dışındadır. Bu ADR yalnızca
     karar kriterlerini tanımlar.

4. **Capability validation'ı tek katmanda (yalnızca smoke test) tutmak**
   - Reddedildi. Gerçek bağlantı olmadan hook görünürlüğünü doğrulayacak
     bir sentetik test katmanı olmadan, "MCP tool çağrıları hook'larda
     görünür" varsayımı doğrulanmamış kalır ve ilk gerçek bağlantı
     denemesi kanıtsız bir varsayıma dayanır.

5. **Fail-closed davranışını bu ADR kapsamında hemen teknik olarak
   implemente etmek**
   - Reddedildi (görev kapsamı dışı). Bu ADR yalnızca mimari tasarımdır;
     uygulama hook'u, MCP config veya kod değişikliği bu görevin açık
     yazım sınırları dışındadır. Fail-closed davranışı yalnızca gerçek
     bağlantı aşamasında uygulanacak şekilde not edilmiştir.

## Consequences

- ADR-005'in audit logging ön koşulu için somut bir teknik tasarım
  modeli oluşur; ancak bu ADR hiçbir audit mekanizmasını çalışır hale
  getirmez.
- `MCP_AUDIT_EVENT_CONTRACT.md`, audit kaydının alanlarını ve
  redaction ilkelerini insan tarafından okunabilir biçimde tanımlar;
  ancak bu contract şu an **teknik olarak enforce edilmemektedir**.
- Gerçek MCP bağlantısı bu ADR'nin kabulüyle **otomatik olarak
  açılmaz**; ADR-005 ve `SEC-ADR-005-MCP-CONNECTION-PRECONDITIONS.md`'deki
  No-Go kararı değişmeden geçerlidir.
- Audit/enforcement mekanizmasının hangi teknik bileşenle (Claude Code
  hook noktası, MCP server tarafı policy katmanı vb.) bağlanacağı henüz
  belirlenmemiştir; bu açık kalan bir takip kalemidir (bkz. "Open
  Questions").
- Mevcut runtime hook (ADR-001/ADR-003) ve CI diff gate (ADR-004)
  değişmeden kalır; bu ADR onların kapsamını küçültmez veya yerini
  almaz.
- `operation_reference` alanı eklendiği için minimum zorunlu alan sayısı
  14'ten **15**'e çıkmıştır; lifecycle bütünlüğü artık timestamp
  sıralamasına değil bu alana dayanır.
- Tool identity (`mcp_server`/`mcp_tool`) artık doğrudan güvenilir kabul
  edilmez; strict classification başarısız olursa gerçek bağlantı
  aşamasında fail-closed deny uygulanır.
- Security Red Team'in ADR-006 review bulguları üzerine beş yeni bağlayıcı
  gate eklenmiştir (bkz. "12."–"16."): audit integrity/tamper-evidence,
  out-of-band/non-recursive audit writer, unclassified tool identity
  sentinel modeli, durable write acknowledgment öncesi dispatch yasağı ve
  `operation_reference` collision-resistance. Bu beş gate, gerçek MCP
  bağlantısı için "Bağlantı Öncesi Zorunlu Kapılar"
  (`SEC-ADR-005-MCP-CONNECTION-PRECONDITIONS.md`) listesine ek, **ADR-006
  kapsamlı** zorunlu ön koşullardır; bu liste insan maintainer tarafından
  gerçek bağlantı öncesi ayrıca doğrulanmalıdır.

## Implementation Impact

- Bu ADR hiçbir uygulama kodu, hook, test, MCP server kurulumu, MCP
  config, token, API key, endpoint, workflow veya
  `.claude/settings.json` değişikliği içermez.
- Yeni dosyalar: `docs/architecture/adr/ADR-006-mcp-audit-logging-and-
  runtime-enforcement.md`, `docs/decisions/MCP_AUDIT_EVENT_CONTRACT.md`.
- Var olan hiçbir dosya bu paket kapsamında değiştirilmemiştir.
- Bu ADR'nin teknik tasarımının gerçek bir audit logger'a ve runtime
  enforcement koduna dönüştürülmesi, ayrı bir implementation görevi
  (ilgili implementer agent + REQ-ID + ownership manifest) gerektirir;
  bu görev bu ADR kapsamında üstlenilmemiştir.
- Bu ADR'nin kabulünden sonra ilgili handoff dokümanının (varsa) bu
  kararı yansıtacak şekilde güncellenmesi gerektiği not edilir; bu
  güncelleme bu görev kapsamı dışındadır ve Delivery Lead/insan
  maintainer tarafından planlanmalıdır.

## Open Questions

Security Red Team review'u (ADR-006 review) sonrasında şu netleştirme
yapılmıştır: aşağıdaki ilkeler **Open Question değildir** ve gerçek
bağlantı öncesi kapatılması zorunlu bağlayıcı gate'lerdir (bkz. ilgili
bölümler):

- Tamper-evidence / append-only audit storage gereksinimi (bkz. "12.").
- Out-of-band ve non-recursive audit writer kısıtı (bkz. "13.").
- Ham/unclassified tool identity'nin hiçbir audit alanına persist
  edilmemesi ve sabit sentinel model (bkz. "14.").
- Durable `PreToolUse` write acknowledgment alınmadan dış MCP çağrısının
  dispatch edilmemesi (bkz. "15.").
- `operation_reference` için collision-resistance gerekliliği (bkz. "16.").

Aşağıdaki konular ise gerçekten açık kalmıştır — bunlar **somut teknik
seçim/implementasyon** kararlarıdır, yukarıdaki ilkelerin kendisi değil:

- MCP tool çağrılarının Claude Code runtime'ında hangi somut hook
  noktasından (varsa) teknik olarak gözlemlenip durdurulabileceği henüz
  doğrulanmamıştır; bu netleşmeden bu ADR'nin runtime enforcement
  bölümü mimari bir model olarak kalır, henüz teknik bir enforcement
  değildir.
- Audit log storage/retention/review için hangi vendor veya mekanizmanın
  seçileceği insan maintainer onayı gerektirir; bu ADR bu seçimi yapmaz.
- Hangi append-only veya tamper-evident storage mekanizmasının (vendor,
  WORM storage, hash-chain veya benzeri) seçileceği açık kalır; ancak bu
  mekanizmanın **var olması gerektiği** (bkz. "12.") açık değildir — bu
  yalnızca hangi teknik aracın seçileceği sorusudur.
- Audit sink transport tekniği (somut protokol/araç) açık kalır; ancak
  bu transport'un out-of-band ve non-recursive olması gerektiği (bkz.
  "13.") açık değildir.
- Tool identity classifier'ın implementasyon algoritması (allowlist/map'in
  somut veri yapısı, güncelleme süreci) açık kalır; ancak unclassified
  durumda hangi sentinel değerlerin yazılacağı (bkz. "14.") açık değildir.
- Runtime hook'un somut hangi teknik noktada enforcement yapacağı açık
  kalır; ancak dispatch'ten önce durable write acknowledgment'ın zorunlu
  olduğu (bkz. "15.") açık değildir.
- `session_reference` alanının nasıl privacy-preserving biçimde
  üretileceği (örnek: hash, salted token) ayrı bir teknik tasarım
  gerektirir.
- `operation_reference` alanının somut üretim yöntemi (hash, salted
  token, local monotonic sayaç, in-memory correlation map vb.) bu ADR'de
  seçilmemiştir; bu teknik karar ayrı bir tasarım adımı gerektirir.
  Kesinleşen kısıtlar: (a) tek yönlü, local olarak üretilen veya eşdeğer
  privacy-preserving bir mekanizma olmalı ve raw `tool_use_id`,
  transcript path, prompt veya kullanıcı kimliği taşımamalı, (b) seçilen
  yöntem collision-resistant olmalı ve aynı retention penceresinde iki
  farklı operasyona aynı değeri atamamalı (bkz. "16. `operation_reference`
  Collision-Resistance İlkesi" — bu kısıtın kendisi açık değildir, yalnızca
  hangi algoritmanın bunu sağlayacağı açıktır).
- Tool identity strict format validation/sınıflandırma kuralının (hangi
  pattern'lerin "tanınmış MCP server/tool" sayılacağı, capability matrix
  eşleştirme algoritması) tam tanımı ayrı bir teknik tasarım gerektirir;
  bu ADR yalnızca "belirsizse deny" ilkesini kayıt altına alır.
- Sentetik hook payload testinin kim tarafından, hangi araçla
  yürütüleceği henüz belirlenmemiştir.
- Capability matrix uyumsuzluğu tespit edildiğinde üretilecek
  `failure_category` taksonomisinin tam listesi, ilk gerçek MCP
  entegrasyonu tasarlanırken netleştirilmelidir.
- Audit logger'ın kendisinin başarısız olduğu durumda (yazma hatası,
  servis erişilemez vb.) Claude Code tarafında bunu nasıl algılayıp
  çağrıyı durduracağı teknik bir tasarım gerektirir; bu ADR yalnızca
  "audit yoksa aksiyon yok" ilkesini kayıt altına alır.
- Audit unavailable durumunda üretilecek **human-visible failure
  signal**'in storage/location mekanizması (örnek: local dosya, terminal
  çıktısı, ayrı bir uyarı kanalı) vendor seçmeden ayrı bir teknik tasarım
  gerektirir; bu ADR yalnızca bu signal'in var olması gerektiğini kayıt
  altına alır. Bu signal'in **içerik modeli** (audit event payload'ının
  ayrı bir alanı olmaması, out-of-band/non-recursive olması, yalnızca
  sabit şablon + kapalı `failure_category` enum üzerinden üretilmesi, raw
  veri taşımaması, yeni bir MCP çağrısı başlatmaması ve human
  approval/capability validation kanıtının yerine geçmemesi — bkz. "6a.
  Human-Visible Failure Signal — Kapalı Tanım") açık bir soru
  **değildir**; yalnızca storage/location seçimi açık kalır.

## Evidence

- PROJECT_CONSTITUTION.md (source of truth hiyerarşisi, security policy)
- CLAUDE.md (security rules)
- ADR-001-role-based-hook-enforcement.md
- ADR-003-ownership-runtime-enforcement.md
- ADR-004-ownership-ci-diff-enforcement.md
- ADR-005-mcp-tooling-control-plane.md
- docs/decisions/AGENT_CAPABILITY_MATRIX.md
- docs/decisions/MCP_AGENT_CAPABILITY_MATRIX.md
- docs/quality/security-reports/SEC-ADR-005-MCP-CONNECTION-PRECONDITIONS.md
- Security Red Team'in ADR-006 review bulguları (Bulgu 1–5: audit
  integrity/tamper-evidence, out-of-band/non-recursive audit writer,
  unclassified tool identity, TOCTOU/durable write acknowledgment,
  `operation_reference` collision-resistance) — bu review ayrı bir
  dosyalanmış security-report olarak henüz mevcut değildir; bulgular bu
  ADR'nin "12."–"16." bölümlerine doğrudan remediation olarak işlenmiştir.

NotebookLM ve Obsidian bu ADR'nin yazımında **kaynak olarak
kullanılmamıştır**; bu ADR yalnızca repository içi Git-tracked
dokümanlara dayanır.

## Acceptance Evidence

Bu bölüm, ADR-006'nın **politika ve mimari tasarım kararının** human
maintainer tarafından kabul edilmesine ilişkin doğrulanmış kanıtları
kayıt altına alır. Bu kabul yalnızca audit logging ve runtime enforcement
**mimari ve güvenlik tasarımını** kapsar; hiçbir gerçek MCP bağlantısını,
credential'ı, hook implementasyonunu, audit sink seçimini, vendor kararını
veya write-capable erişimi yetkilendirmez.

- ADR-006 ve `MCP_AUDIT_EVENT_CONTRACT.md`, PR #16 ile merge edildi.
- Security Red Team ilk review'unda beş tasarım bulgusu belirledi:
  - Bulgu 1: Audit integrity / tamper evidence gereksinimi.
  - Bulgu 2: Out-of-band ve non-recursive audit writer zorunluluğu.
  - Bulgu 3: Unknown tool identity için `unclassified` + deny modeli.
  - Bulgu 4: Durable write acknowledgment / TOCTOU kapanışı.
  - Bulgu 5: `operation_reference` collision-resistance zorunluluğu.
- Bu beş bulgu ADR-006 ve `MCP_AUDIT_EVENT_CONTRACT.md` içinde bağlayıcı
  policy gate'lere dönüştürüldü (bkz. "12."–"16." bölümleri ve
  "Consequences").
- Security Red Team ikinci geçişte `GO` sonucu verdi.
- İkinci review ayrıca closed-schema data minimization (15 alanlık kapalı
  şema, serbest metin alanının yasaklılığı) ve human-visible failure
  signal ayrımının (audit event payload'ından bağımsız, out-of-band
  kavram) doğru biçimde tanımlandığını doğruladı.
- Bu acceptance anında repository'de hiçbir MCP `Active`, `Configured`
  veya `Connected` değildir; `MCP_AGENT_CAPABILITY_MATRIX.md`'deki tüm
  satırlar "Planned" durumundadır.
- Gerçek MCP bağlantısı; hook implementasyonu, audit sink seçimi,
  sentetik hook payload doğrulaması, MCP bazlı capability validation,
  environment-specific smoke test ve insan onayı olmadan **No-Go**'dur.

## Approval

- **Required approver:** Human maintainer
- **Approval status:** Accepted
- **Acceptance date:** 2026-06-25
- **Evidence references:**
  - PR #16
  - Security Red Team first-pass review
  - Security Red Team second-pass review
- **Approval scope note:** Bu ADR yalnızca audit logging ve runtime
  enforcement **mimari tasarımını** kapsar. Bu ADR'nin onaylanması
  hiçbir gerçek MCP bağlantısını, credential'ı, audit logger
  implementasyonunu veya write-capable erişimi yetkilendirmez. Gerçek
  bağlantı, ADR-005 ve `SEC-ADR-005-MCP-CONNECTION-PRECONDITIONS.md`'deki
  "Bağlantı Öncesi Zorunlu Kapılar" tamamlanmadan ve ayrı bir insan
  maintainer onayı kaydedilmeden açılmaz.
- Bu kararın production altyapısı, audit veri modeli ve geri
  döndürülemez teknik karar içerme potansiyeli nedeniyle, herhangi bir
  implementasyon başlamadan önce insan maintainer onayı zorunludur.
- **Security Red Team gate'leri (insan doğrulaması zorunlu):** Gerçek MCP
  bağlantısı açılmadan önce, insan maintainer aşağıdaki beş gate'in
  karşılandığını ayrıca doğrulamalıdır (bkz. "12."–"16."): (1) seçilen
  audit storage/sink'in append-only veya tamper-evident olduğu kanıtı,
  (2) audit writer'ın out-of-band ve non-recursive olduğunun sentetik
  testle doğrulanması, (3) unclassified tool identity sentinel modelinin
  (`unclassified`/`deny`/`unclassified_tool_identity`) gerçekten
  uygulandığı, (4) dispatch'ten önce durable `PreToolUse` write
  acknowledgment'ın zorunlu olduğu, (5) `operation_reference` üretim
  yönteminin collision-resistant olduğu. Bu beş gate'in herhangi biri
  doğrulanmadan gerçek MCP bağlantısı açılmamalıdır.
