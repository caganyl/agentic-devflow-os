# MCP Audit Event Contract

Bu doküman, `docs/architecture/adr/ADR-006-mcp-audit-logging-and-runtime-
enforcement.md` kapsamında tanımlanan MCP audit logging modelinin event
contract'ıdır. Bu doküman **teknik olmayan ama uygulanabilir** bir
sözleşmedir: bir implementasyon ekibi bu alanları doğrudan bir şemaya
dönüştürebilir, fakat bu doküman kendisi bir kod, config veya gerçek MCP
bağlantısı değildir.

Bu contract şu an **teknik olarak enforce edilmemektedir**. Hiçbir audit
logger, hook veya MCP server bu contract'ı bu doküman kapsamında
implemente etmemiştir. Bu contract, ADR-006'nın "Open Questions"
bölümünde belirtilen teknik tasarım kararları netleşene kadar bir
**referans sözleşmedir**.

**Bu contract'ın sınırı (Security Red Team review remediation):** Bu
contract yalnızca **event payload şemasını** tanımlar; aşağıdaki konular
bu contract'ın kapsamı dışındadır ve ADR-006'nın ilgili bölümlerine
aittir:

- Bu 15 alanlık event payload, audit storage/sink'in **integrity,
  durability veya tamper-evidence** mekanizmasını belirlemez. Bu garanti
  audit sink katmanının zorunlu sorumluluğudur (bkz. ADR-006 "12. Audit
  Integrity, Durability and Tamper Evidence İlkesi"). Bu contract'a, bu
  garantiyi sağlamaya çalışan ham tool input/output veya secret taşıyan
  ek "integrity alanları" **eklenmez**.
- Audit writer'ın out-of-band ve non-recursive olması gerekliliği (bkz.
  ADR-006 "13. Out-of-Band ve Non-Recursive Audit Writer İlkesi") bu
  payload şemasının bir parçası değildir; bu, audit yazma mekanizmasının
  bir tasarım kısıtıdır.
- Dispatch'ten önceki durable write acknowledgment gereksinimi (bkz.
  ADR-006 "15. TOCTOU Kapanışı") bu contract'ın alan listesinde
  modellenmez; bu, lifecycle sıralamasına ait bir kısıttır.

## Amaç

- MCP tool çağrılarının (denenen, izin verilen, reddedilen, başarılı,
  başarısız) insan tarafından gözden geçirilebilir, secret/PII
  içermeyen bir audit trail'i ile kayıt altına alınmasını tanımlamak.
- Audit kaydının **action authority** olmadığını ve yalnızca görünürlük
  sağladığını açıkça sınırlamak.
- Hangi alanların zorunlu, hangi alanların yasak olduğunu net biçimde
  belirlemek.

## Kapsam Dışı Alanlar

Bu contract aşağıdakileri **kapsamaz**:

- Gerçek bir MCP server kurulumu, bağlantısı veya konfigürasyonu.
- Credential, token veya API key saklama mekanizması.
- Git diff path authority denetimi (bkz. ADR-004, `scripts/
  validate_ownership_diff.py`).
- Claude'un `Edit`/`Write`/`Bash` araç çağrıları için dosya sistemi
  ownership enforcement (bkz. ADR-001, ADR-003,
  `.claude/hooks/enforce-role-boundaries.sh`).
- Audit storage vendor seçimi, retention süresi veya review sıklığı
  kararı (bkz. ADR-006 "Storage, retention ve review modeli" — bu
  kararlar insan maintainer onayı gerektirir ve bu contract'ta
  verilmemiştir).
- Prompt injection pattern detection veya content sanitization
  mekanizması (ADR-005 "Open Questions" kapsamında ayrı bir takip
  kalemidir).

## Event Türleri

`PermissionRequest → PreToolUse → gerçek MCP çağrısı` sıralaması evrensel
ve her çağrıda zorunlu bir zincir **değildir**. `PreToolUse` her aday
çağrı için zorunlu temel kontrol noktasıdır; `PermissionRequest` ise
yalnızca bir permission dialog gösterilecekse ortaya çıkan **koşullu**
bir event'tir. İzin reddi yolunda tool hiç çalışmadığından
`PostToolUse`/`PostToolUseFailure` üretilmez; bunun yerine açık bir
`PermissionDenied` denial outcome'u (bkz. `outcome: denied`) kullanılır.

| Event türü | Ne zaman üretilir | Zorunlu mu |
|---|---|---|
| `PreToolUse` | Her aday MCP tool çağrısı için temel pre-execution kontrol noktası; policy evaluation ve gerçek bağlantı aşamasındaki fail-closed kararın ana noktası | Evet — her aday çağrı için |
| `PermissionRequest` | Yalnızca Claude Code kullanıcıya/konfigürasyona bir permission dialog gösterecekse | Koşullu — her çağrıda zorunlu değil; tetiklendiğinde audit açısından görünür olmalı |
| `PermissionDenied` (veya eşdeğer açık denial outcome) | İzin reddedildiğinde ve aksiyon hiç yürütülmediğinde | Evet — `PermissionRequest` reddedildiğinde zorunlu; aksiyon yürütülmeden önce tamamlanmış olmalı |
| `PostToolUse` | MCP tool çağrısı başarıyla tamamlandığında (yalnızca gerçek execution başladıktan sonra) | Evet — gerçek execution başarıyla tamamlandığında |
| `PostToolUseFailure` | Gerçek tool execution başladıktan sonra hata/exception oluştuğunda | Evet — gerçek execution hata ile sonuçlandığında |

Her gerçekleşen MCP tool çağrısı niyeti, yukarıdaki event türlerinden en
az birini üretmelidir. Hiçbir çağrı niyeti audit'siz, sessizce
ilerlememelidir (bkz. ADR-006 "Fail-closed yaklaşımı"). "`PermissionRequest`
her zaman olur" veya "`PostToolUseFailure` izin reddini kapsar" biçiminde
hiçbir yanlış çıkarım bu contract'tan türetilemez: izin reddi ile gerçek
execution sonrası hata, ayrı ve birbirine indirgenemeyen iki audit
yoludur.

## Kapalı Payload Modeli (Closed Schema)

Bu event contract, tam olarak **15** zorunlu alandan oluşan **kapalı**
(closed) bir payload modelidir. Bu, şu anlama gelir:

- Aşağıdaki tabloda tanımlı 15 alan dışında **hiçbir alan** audit event
  payload'ına eklenemez.
- `note`, `notes`, `message`, `error_message`, `details`, `description`,
  `context`, `metadata`, `debug`, serbest metin yorum alanı, raw runtime
  identity, raw tool input/output, prompt, URL, header, dosya yolu,
  exception metni veya kullanıcı kontrollü herhangi bir serbest metin
  alanı bu payload'da **kesinlikle bulunmaz** ve eklenemez.
- **Audit event schema'sında serbest metin not alanı yoktur. Böyle bir
  alan eklenemez. Redaction, yasak veriyi kabul etmek için bir istisna
  değildir; yasak verinin event payload'a hiç girmemesidir.**
- Bu kapalı model, ADR-006'nın "8. Secret / PII minimization" bölümüyle
  aynı anlamda tanımlıdır; iki doküman arasında çelişki olması durumunda
  her ikisi de güncellenmelidir.

## Zorunlu Alanlar ve Tanımları

Aşağıdaki tablo **15** zorunlu alanı tanımlar (önceki sürümde 14 alan
vardı; `operation_reference` eklenmesiyle toplam 15'e çıkmıştır). Bu 15
alan, yukarıdaki "Kapalı Payload Modeli" bölümünde tanımlandığı gibi
**kapalı bir liste**dir; bu listeye yeni alan eklenmesi ayrı bir
`schema_version` artışı ve ADR güncellemesi gerektirir.

| Alan | Tanım |
|---|---|
| `schema_version` | Bu event contract'ının sürüm numarası. Contract değiştiğinde artar. |
| `event_id` | Bu audit kaydına ait benzersiz tanımlayıcı (örnek: UUID). Tekil olmalı, tekrar kullanılmamalı. |
| `timestamp` | Event'in oluştuğu an, UTC, ISO-8601 biçiminde. |
| `session_reference` | Ham kullanıcı/oturum kimliği değil; privacy-preserving, **oturum seviyesinde** bir korelasyon referansı (örnek: tek yönlü hash). Bu alan kişiyi veya gerçek oturum içeriğini doğrudan ifşa etmemelidir. |
| `operation_reference` | Aynı MCP çağrısına ait `PreToolUse`, koşullu `PermissionRequest`/`PermissionDenied`, `PostToolUse` ya da `PostToolUseFailure` event'lerini ilişkilendirmek için kullanılan, **çağrı (per-call) seviyesinde**, privacy-preserving, tek yönlü/local olarak üretilen bir korelasyon referansı. Raw `tool_use_id`, transcript path, prompt, kullanıcı kimliği veya tool input taşımaz. Aynı session içindeki paralel tool çağrılarını ayırt etmeyi sağlar; `session_reference`'tan farklı bir granülaritededir. **Zorunlu kısıt:** privacy-preserving olmanın yanında **collision-resistant** olmalıdır; aynı retention penceresinde iki farklı MCP operasyonu için tekrar kullanılamaz ve paralel çağrıların lifecycle event'leri yanlışlıkla aynı operation altında birleşmemelidir (bkz. ADR-006 "16. `operation_reference` Collision-Resistance İlkesi"). Somut üretim yöntemi bu contract'ta seçilmez (bkz. ADR-006 "Open Questions"). |
| `agent_type` | Çağrıyı yapan custom agent rolü (örnek: `solution-architect`, `backend-engineer`). `AGENTS.md`'de tanımlı rol adlarından biri olmalıdır. |
| `event_phase` | Bu kaydın hangi lifecycle event'ine ait olduğu. Yukarıdaki "Event Türleri" tablosundaki değerlerden biri. |
| `mcp_server` | Çağrılan MCP sunucusunun **canonical sınıf/etiket** adı (örnek: `notebooklm`, `obsidian`, `github-mcp`). Gerçek endpoint, host adı veya bağlantı dizesi değildir. Runtime event'inden gelen ham string **hiçbir zaman doğrudan güvenilir kabul edilmez**; bu alana yalnızca local allowlist/map üzerinden üretilen canonical bir etiket yazılabilir. Sınıflandırılamayan/allowlist dışı bir değer için bu alana **sabit sentinel** `"unclassified"` yazılır — ham runtime string'i hiçbir koşulda bu alana yazılmaz (bkz. "Tool Identity Sınıflandırması"). |
| `mcp_tool` | Çağrılan MCP tool'unun canonical adı/etiketi (örnek: `search_sources`, `read_note`). Aynı şekilde **doğrudan güvenilir kabul edilmez**; sınıflandırılamayan/allowlist dışı bir değer için bu alana sabit sentinel `"unclassified"` yazılır; ham runtime string'i hiçbir koşulda bu alana yazılmaz. |
| `action_class` | Aksiyonun sınıfı; yalnızca aşağıdaki "İzinli Değerler" enum listesinden bir değer. Serbest metin veya kullanıcı kontrollü değer kabul edilmez. Ham aksiyon parametrelerini içermez. |
| `environment_scope` | Aksiyonun hedef ortam sınıfı; yalnızca aşağıdaki enum listesinden bir değer. Serbest metin kabul edilmez. Gerçek URL veya hostname değildir. |
| `policy_decision` | Capability matrix/policy katmanının kararı; yalnızca aşağıdaki enum listesinden bir değer. `mcp_server`/`mcp_tool` `"unclassified"` olduğunda bu alan zorunlu olarak `"deny"` olmalıdır. |
| `outcome` | Çağrının nihai sonucu; yalnızca aşağıdaki enum listesinden bir değer. |
| `failure_category` | Yalnızca `outcome` `failure` veya `blocked` olduğunda zorunlu; yalnızca aşağıdaki tanımlı enum kümesinden bir değer (serbest metin kabul edilmez). `mcp_server`/`mcp_tool` `"unclassified"` olduğunda bu alan zorunlu olarak `"unclassified_tool_identity"` olmalıdır. |
| `audit_record_version` | Bu tekil kaydın iç sürüm/format numarası (şema güncellemesi olmadan kaydın kendi revize edilme durumunu izlemek için). |

## Alanların İzinli Değerleri / Normatif Enum'lar

Aşağıdaki enum listeleri **normatiftir**: `action_class`,
`environment_scope`, `policy_decision`, `outcome` ve `failure_category`
alanları yalnızca burada tanımlı değerlerden oluşur; serbest metin veya
kullanıcı kontrollü değer bu alanlara **hiçbir koşulda kabul edilmez**
(bkz. ADR-006 "14. Unknown Tool Identity ve Sentinel Model").

- `event_phase`: `PreToolUse` \| `PermissionRequest` \| `PermissionDenied`
  \| `PostToolUse` \| `PostToolUseFailure` (`PermissionRequest` koşulludur;
  `PermissionDenied` yalnızca izin reddi yolunda üretilir ve
  `PostToolUse`/`PostToolUseFailure`'ın yerine geçer, onlarla birlikte
  üretilmez)
- `action_class`: `read` \| `write` \| `evidence_retrieval` \|
  `permission_check` \| `other`
- `environment_scope`: `localhost` \| `preview` \| `staging` \|
  `production` \| `n/a`
- `policy_decision`: `allow` \| `deny` \| `not_evaluated`
- `outcome`: `success` \| `failure` \| `denied` \| `blocked`
- `failure_category`: `policy_violation` \| `capability_mismatch` \|
  `unclassified_tool_identity` \| `tool_error` \| `audit_unavailable` \|
  `unknown`

Bu enum kümesi kapalıdır: bir audit logger, burada tanımlı olmayan bir
değeri bu alanlara **yazamaz**. Bu liste ilk teknik tasarım iterasyonunda
genişletilebilir (bkz. ADR-006 "Open Questions" — `failure_category`
taksonomisinin genişletilmesi); bu genişletme ayrı bir teknik karar
gerektirir ve bu contract'ın `schema_version`'ını artırmalıdır. Liste
genişletilse bile, alan her zaman **tanımlı bir enum üyesi** olmalıdır;
serbest metin asla kabul edilmez.

## Canonical `mcp_server` / `mcp_tool` Etiket Formatı

`mcp_server` ve `mcp_tool` alanları, runtime'dan gelen ham string'in
doğrudan kopyası **değildir**; bu alanlara yazılabilecek canonical
etiketler şu kısıtlara tabidir (bkz. ADR-006 "14. Unknown Tool Identity ve
Sentinel Model"):

- Yalnızca lowercase ASCII güvenli karakter kümesi: önerilen format
  `^[a-z0-9][a-z0-9._-]{0,63}$`.
- En fazla 64 karakter.
- Sınıflandırılamayan veya `MCP_AGENT_CAPABILITY_MATRIX.md` dışı bir
  değer için bu alanlara **yalnızca** sabit sentinel `"unclassified"`
  yazılabilir; ham runtime string'i bu alanlara hiçbir koşulda
  yazılamaz.

## Tool Identity Sınıflandırması

`mcp_server` ve `mcp_tool` alanları, gerçek bir MCP runtime event'inden
geldikleri için **doğrudan güvenilir kabul edilmez**:

- Runtime event içindeki tool kimliği, gerçek bağlantı aşamasından önce
  **strict format validation** ile sınıflandırılmalıdır.
- Sınıflandırma sonucunda MCP server, MCP tool veya
  `MCP_AGENT_CAPABILITY_MATRIX.md` eşleşmesi kesin biçimde
  çıkarılamıyorsa, gerçek bağlantı aşamasında audit kaydı **zorunlu olarak
  sabit sentinel değerlerle** üretilir:
  - `mcp_server: "unclassified"`
  - `mcp_tool: "unclassified"`
  - `policy_decision: "deny"`
  - `failure_category: "unclassified_tool_identity"`
- Belirsiz, tanınmayan veya capability matrix dışı kalan bir tool
  identity, gerçek bağlantı için tek başına fail-closed sebebidir.
- **Ham runtime string'i hiçbir koşulda persist edilmez:** sınıflandırma
  başarısız olduğunda, runtime'dan gelen orijinal `mcp_server`/`mcp_tool`
  string'i — denial yolu dahil — hiçbir audit alanına, human-visible
  failure signal'e veya serbest metin alana yazılamaz. Audit kaydı
  yalnızca yukarıdaki sabit sentinel değerleri taşır (bkz. ADR-006 "14.
  Unknown Tool Identity ve Sentinel Model").
- Canonical `mcp_server`/`mcp_tool` etiketleri yalnızca local
  allowlist/map üzerinden üretilir; bu etiketler lowercase ASCII güvenli
  karakter kümesiyle sınırlıdır (en fazla 64 karakter, önerilen format
  `^[a-z0-9][a-z0-9._-]{0,63}$` — bkz. "Canonical `mcp_server` /
  `mcp_tool` Etiket Formatı").
- Bu sınıflandırma varsayımı önce sentetik hook payload testiyle, daha
  sonra MCP bazlı environment-specific smoke test ile doğrulanmalıdır
  (bkz. ADR-006 "10. Capability validation yaklaşımı").
- Raw tool input, raw tool output, prompt, URL, header, token, secret
  veya dosya içeriği, bu sınıflandırma adımında dahi audit event'ine
  dahil edilmez. Audit payload içinde error message, raw identity, URL,
  prompt, header, dosya yolu veya başka bir açıklama/serbest metin alanı
  bulunmaz.

## Concurrency ve Ordering

- Aynı session içinde paralel MCP çağrıları olabilir; `timestamp` alanı
  tek başına **total ordering kanıtı değildir**.
- Bir çağrının lifecycle bütünlüğü (`PreToolUse` → koşullu
  `PermissionRequest`/`PermissionDenied` → `PostToolUse`/
  `PostToolUseFailure`) `operation_reference` üzerinden değerlendirilir,
  timestamp sıralamasına dayanılmaz.
- Batch-level event'ler (birden çok çağrıyı tek kayıtta özetleme) bu
  contract'ın ana audit kaynağı **değildir**; gerekirse gelecekte ayrı
  bir genişletme olarak ele alınır.
- Her operation için izin/ret/başarı/failure sonucu, `operation_reference`
  üzerinden audit kanıtında ayırt edilebilir olmalıdır.

## Audit Unavailable Davranışı

- Gerçek MCP bağlantısı aşamasında, dış çağrı başlamadan **önce** audit
  logger kullanılabilir değilse veya audit event yazımı doğrulanamazsa,
  dış MCP çağrısı **başlatılmaz**; çağrı `deny` edilir.
- **"Availability ping" yeterli değildir:** gerçek gate, dispatch'ten önce
  minimal `PreToolUse` event'inin **durable write acknowledgment**'ının
  alınmasıdır — yalnızca sink'in erişilebilir olduğunun kontrolü değil,
  o spesifik event'in sink'in integrity/durability modeline uygun
  biçimde yazıldığının doğrulanmasıdır (bkz. ADR-006 "15. TOCTOU
  Kapanışı: Durable Write Acknowledgment Önce, Dispatch Sonra"). Bu
  acknowledgment alınmadan dış MCP çağrısı dispatch edilmez.
- Bu durumda insan incelemesi için secret/PII içermeyen, human-visible
  bir failure signal üretilmesi gereklidir (örnek:
  `failure_category: audit_unavailable`). Bu signal **yeni bir MCP
  çağrısı başlatmaz** ve audit zincirini yeniden tetiklemez (bkz. ADR-006
  "13. Out-of-Band ve Non-Recursive Audit Writer İlkesi").
- Bu signal'in storage/location mekanizması bu contract'ta seçilmez;
  ayrı bir teknik karar olarak ADR-006 "Open Questions" altında kalır.
- Audit logging arızası hiçbir koşulda sessiz `allow` veya dış çağrının
  audit'siz devamı sonucunu doğurmaz.

### Human-Visible Failure Signal — Audit Event Payload'ından Ayrımı

`failure_category: audit_unavailable` (veya başka bir `failure_category`
değeri) ile birlikte üretilmesi gereken human-visible failure signal, bu
contract'ın 15 alanlık audit event payload'ından **tamamen ayrı bir
kavramdır**. Bu ayrım ADR-006 "6a. Human-Visible Failure Signal — Kapalı
Tanım" ile aynı anlamda, bağlayıcı biçimde burada da tekrarlanır:

- Human-visible failure signal, bu contract'ta tanımlı 15 alanlık audit
  event payload'ının **ek bir alanı değildir** ve bu şemaya yeni bir alan
  olarak eklenemez.
- Bu signal **out-of-band ve non-recursive** bir bildirimdir; audit event
  yazma yolunun veya audit sink'in kendisi üzerinden taşınmaz.
- Bu signal **yalnızca locally controlled sabit şablonlar** ve bu
  contract'ta tanımlı **kapalı `failure_category` enum değerleri**
  üzerinden üretilebilir; serbest metin üretimi yoktur.
- Bu signal **raw tool identity, raw error/exception metni, prompt, URL,
  token, secret, PII, kullanıcı verisi veya serbest metin taşımaz**.
- Bu signal'in üretilmesi veya görüntülenmesi **yeni bir MCP çağrısı
  başlatmaz**.
- Bu signal, **human approval veya capability validation kanıtının
  yerine geçmez**; bu kanıtlar ayrı ve açık biçimde insan maintainer
  tarafından sağlanmalıdır (bkz. ADR-005 "İnsan Onay Kapıları", ADR-006
  "10. Capability validation yaklaşımı").

Bu signal'in **nerede/nasıl gösterileceği** (storage, location, vendor)
açık kalır (bkz. yukarıdaki madde); ancak yukarıdaki altı kısıt (içerik
modeli) açık bir soru değildir.

## Yasak Alanlar

Aşağıdaki alan veya veri sınıfları **hiçbir audit kaydında bulunmaz**:

- Ham tool input (gönderilen tam parametre/payload).
- Ham tool output (MCP'den dönen tam yanıt).
- Prompt içeriği (sistem prompt'u, kullanıcı mesajı, agent talimatı).
- URL query değeri veya tam URL (yalnızda `environment_scope` gibi geniş
  sınıflandırma tutulabilir).
- `Authorization` header, token, API key, secret veya credential.
- Kişisel veri (PII): ad, e-posta, telefon, adres, müşteri kaydı.
- Dosya içeriği (okunan veya yazılan dosyanın gerçek içeriği).
- Serbest metin not alanı veya buna eşdeğer herhangi bir alan — `note`,
  `notes`, `message`, `error_message`, `details`, `description`,
  `context`, `metadata`, `debug` dahil, ancak bunlarla sınırlı olmaksızın.
  **Audit event schema'sında serbest metin not alanı yoktur. Böyle bir
  alan eklenemez. Redaction, yasak veriyi kabul etmek için bir istisna
  değildir; yasak verinin event payload'a hiç girmemesidir.**
- Error message, raw/ham tool identity string'i, dosya yolu veya başka
  bir açıklama/serbest metin alanı (bkz. "Tool Identity Sınıflandırması").
- Audit storage/sink integrity, durability veya tamper-evidence
  mekanizmasını belirlemeye/taşımaya yönelik herhangi bir ek alan; bu
  garanti audit sink katmanının sorumluluğudur, event payload'ın değil
  (bkz. ADR-006 "12. Audit Integrity, Durability and Tamper Evidence
  İlkesi").

## Secret/PII Redaction İlkeleri

- Audit kaydı, yukarıdaki "Zorunlu Alanlar" listesinin dışına **hiçbir
  ek serbest metin alanı eklemez**. Bu bir azaltma stratejisi değil,
  kapalı şema kuralının kendisidir: audit event schema'sında serbest
  metin not alanı yoktur, böyle bir alan eklenemez ve redaction yasak
  veriyi kabul etmek için bir istisna değildir — yasak veri event
  payload'a hiç girmez.
- `mcp_server` ve `mcp_tool` alanları **sınıf/etiket** taşır, gerçek
  bağlantı dizesi, endpoint veya credential parçası taşımaz.
- `session_reference`, doğrudan kullanıcı kimliğine geri dönüştürülebilir
  ham bir değer olmamalıdır; tek yönlü/privacy-preserving bir korelasyon
  referansı olmalıdır.
- Bir audit logger, kayıt oluşturmadan önce yukarıdaki "Yasak Alanlar"
  listesinden herhangi birini tespit ederse, bu veriyi audit kaydına
  **eklemek yerine** kaydı `failure_category: audit_unavailable` ile
  işaretlemeli ve ADR-006'nın fail-closed ilkesine göre ilerlemelidir.
- Tool output içinde geçen herhangi bir talimat, emir veya yönlendirme
  (ADR-005 "Untrusted MCP Output" ilkesiyle tutarlı olarak) audit
  kaydına **hiçbir biçimde dahil edilmez**; bu içerik audit trail'in bir
  parçası değildir ve agent için eylem emri oluşturmaz.

## Event Örneği

Aşağıdaki örnek tamamen **sentetiktir**. Sahte sunucu adı, sahte tool adı
kullanır; gerçek URL, token, kullanıcı, müşteri veya secret içermez; ham
input/output taşımaz.

```json
{
  "schema_version": "1.0.0",
  "event_id": "9b1c2e3a-synthetic-example-0001",
  "timestamp": "2026-06-25T10:15:00Z",
  "session_reference": "corr-ref-sample-0001",
  "operation_reference": "op-ref-sample-0001-a",
  "agent_type": "solution-architect",
  "event_phase": "PostToolUse",
  "mcp_server": "example-notes-mcp",
  "mcp_tool": "search_sources",
  "action_class": "evidence_retrieval",
  "environment_scope": "n/a",
  "policy_decision": "allow",
  "outcome": "success",
  "failure_category": null,
  "audit_record_version": 1
}
```

Policy/capability uyumsuzluğu nedeniyle `PreToolUse` aşamasında reddedilen
bir çağrı örneği (yine tamamen sentetik):

```json
{
  "schema_version": "1.0.0",
  "event_id": "9b1c2e3a-synthetic-example-0002",
  "timestamp": "2026-06-25T10:16:30Z",
  "session_reference": "corr-ref-sample-0002",
  "operation_reference": "op-ref-sample-0002-a",
  "agent_type": "frontend-engineer",
  "event_phase": "PreToolUse",
  "mcp_server": "example-browser-mcp",
  "mcp_tool": "navigate_page",
  "action_class": "write",
  "environment_scope": "production",
  "policy_decision": "deny",
  "outcome": "denied",
  "failure_category": "capability_mismatch",
  "audit_record_version": 1
}
```

Kullanıcı/konfigürasyon tarafından izin reddedilen, dolayısıyla aksiyon
hiç yürütülmeyen bir `PermissionDenied` örneği (yine tamamen sentetik;
`PostToolUse`/`PostToolUseFailure` bu dalda **üretilmez**, aynı
`operation_reference` ile yalnızca `PreToolUse` ve `PermissionDenied`
kayıtları ilişkilendirilir):

```json
{
  "schema_version": "1.0.0",
  "event_id": "9b1c2e3a-synthetic-example-0003",
  "timestamp": "2026-06-25T10:17:10Z",
  "session_reference": "corr-ref-sample-0003",
  "operation_reference": "op-ref-sample-0003-a",
  "agent_type": "qa-automation",
  "event_phase": "PermissionDenied",
  "mcp_server": "example-browser-mcp",
  "mcp_tool": "submit_form",
  "action_class": "write",
  "environment_scope": "staging",
  "policy_decision": "deny",
  "outcome": "denied",
  "failure_category": "policy_violation",
  "audit_record_version": 1
}
```

Sınıflandırılamayan/allowlist dışı bir tool identity nedeniyle reddedilen
bir çağrı örneği (yine tamamen sentetik; ham runtime string'i hiçbir
alana yazılmaz, yalnızca sabit sentinel değerler kullanılır):

```json
{
  "schema_version": "1.0.0",
  "event_id": "9b1c2e3a-synthetic-example-0004",
  "timestamp": "2026-06-25T10:18:45Z",
  "session_reference": "corr-ref-sample-0004",
  "operation_reference": "op-ref-sample-0004-a",
  "agent_type": "backend-engineer",
  "event_phase": "PreToolUse",
  "mcp_server": "unclassified",
  "mcp_tool": "unclassified",
  "action_class": "other",
  "environment_scope": "n/a",
  "policy_decision": "deny",
  "outcome": "blocked",
  "failure_category": "unclassified_tool_identity",
  "audit_record_version": 1
}
```

## Ek Kurallar

- **Tool output içindeki talimatlar audit kaydına dahil edilmez.** Bir
  MCP tool'unun döndürdüğü içerikte geçen herhangi bir emir, yönlendirme
  veya "ignore previous instructions" benzeri ifade, audit kaydının
  hiçbir alanına kopyalanmaz ve agent için eylem emri oluşturmaz (ADR-005
  ile tutarlı).
- **Audit kaydı action authority değildir.** Bir aksiyonun audit
  kaydına yazılmış olması, o aksiyonun politika açısından yetkili
  olduğu anlamına gelmez. Yetkilendirme kararı `policy_decision` alanına
  yansır, ancak nihai yetki capability matrix ve runtime enforcement
  katmanındadır; audit kaydı sadece bu kararın bir izini tutar.
- **Audit kaydı capability validation kanıtına referans olabilir, fakat
  tek başına human approval değildir.** Bir MCP'nin gerçek bağlantıya
  geçmesi için gereken human approval (ADR-005, SEC-ADR-005), audit
  kayıtlarının varlığından bağımsız, ayrı ve açık bir insan maintainer
  kararı gerektirir. Audit kaydı bu kararın yerine geçmez; en fazla
  capability validation/smoke test sürecinin bir kanıtı olarak
  referans gösterilebilir.
- **Bu event contract, gerçek MCP connection veya credential saklama
  config'i değildir.** Bu doküman hiçbir MCP server adı, endpoint, token
  veya gerçek bağlantı bilgisi içermez ve içermeyecektir.
- **Audit yazımı out-of-band ve non-recursive olmalıdır.** Bu contract'ı
  implemente eden bir audit writer, kendi gözlemlediği MCP tool-call
  lifecycle'ını (aynı `PreToolUse`/`PostToolUse` zincirini) yeniden
  tetikleyerek kayıt yazamaz; audit sink işlemleri recursive bir
  audit/enforcement döngüsü oluşturmamalıdır (bkz. ADR-006 "13.
  Out-of-Band ve Non-Recursive Audit Writer İlkesi"). Bu, event
  payload'ın bir alanı değil, audit writer implementasyonunun bağlayıcı
  bir kısıtıdır.
- **Bu payload integrity/durability garantisi vermez.** 15 alanlık bu
  event payload, audit storage/sink'in append-only veya tamper-evident
  olup olmadığını belirlemez; bu garanti audit sink katmanının zorunlu
  sorumluluğudur ve gerçek bağlantı öncesi insan tarafından ayrıca
  doğrulanmalıdır (bkz. ADR-006 "12. Audit Integrity, Durability and
  Tamper Evidence İlkesi").

## İlgili Dokümanlar

- `docs/architecture/adr/ADR-006-mcp-audit-logging-and-runtime-
  enforcement.md`
- `docs/architecture/adr/ADR-005-mcp-tooling-control-plane.md`
- `docs/decisions/MCP_AGENT_CAPABILITY_MATRIX.md`
- `docs/quality/security-reports/SEC-ADR-005-MCP-CONNECTION-
  PRECONDITIONS.md`
- PROJECT_CONSTITUTION.md (source of truth hiyerarşisi, security policy)
- CLAUDE.md (security rules)
