# REQ-001 — MCP Hook Lifecycle Synthetic Validation

## Requirement Metadata

| Alan              | Değer                                                                             |
|-------------------|-----------------------------------------------------------------------------------|
| **Requirement ID**| REQ-001                                                                           |
| **Status**        | Proposed                                                                          |
| **Title**         | MCP Hook Lifecycle Synthetic Validation                                           |
| **Date**          | 2026-06-25                                                                        |
| **Author**        | Product Analyst                                                                   |
| **Branch**        | product-req-001-mcp-hook-lifecycle-validation                                     |
| **AC Reference**  | `docs/product/acceptance-criteria/AC-REQ-001-mcp-hook-lifecycle-synthetic-validation.md` |

---

> **Durum notu:** Bu requirement `Proposed` statüsündedir.
> Bu requirement gerçek MCP bağlantısı, hook config veya production
> kullanımını onaylamaz. İnsan acceptance kararı olmadan implementation
> başlamaz.

---

## Problem

ADR-005 ve ADR-006, MCP (Model Context Protocol) entegrasyonları için
sırasıyla bir politika ve kontrol düzlemi ile bir audit logging ve runtime
enforcement modeli kabul etti. Her iki ADR de "gerçek bağlantı öncesi
sentetik hook payload testi" önkoşulunu açıkça zorunlu kapı olarak belirledi
(ADR-006 §10 "Capability validation yaklaşımı").

Bununla birlikte şu boşluk mevcuttur: ADR-005 ve ADR-006 tasarım
kararlarını kayıt altına alır; ancak bu kararların gerçek bir MCP
bağlanmadan önce test edilebilir, doğrulanabilir ve kalıcı biçimde kanıtlanmış
davranışa dönüştüğü **çalışan bir test paketi yoktur**. Aşağıdaki kritik
sorular yanıtsız kalmaktadır:

- Sentetik bir `PreToolUse` payload'ında known/allowlist MCP tool identity
  doğru biçimde sınıflandırılabiliyor mu?
- Unknown veya allowlist-dışı bir tool identity, ham runtime string persist
  edilmeden sentinel değerler (`"unclassified"` + `deny` +
  `"unclassified_tool_identity"`) ile reddediliyor mu?
- `PermissionDenied` audit yolu, `PostToolUseFailure` ile karıştırılmadan
  ayrı bir lifecycle dalı olarak doğrulanabiliyor mu?
- Audit event payload'ı kapalı 15 alanlık şemaya sıkı sıkıya uyuyor mu?
  Yasak veri sızıyor mu?
- Paralel çağrılarda `operation_reference` çakışmıyor mu (collision-resistant)?
- Parser failure, malformed payload, capability mismatch ve audit unavailable
  gibi hata senaryoları gerçekten `deny`/`blocked` sonucu üretiyor mu?

Bu boşluk, gerçek MCP bağlantısının açılmasının önünde yapısal bir risk
oluşturur: ADR'ler "tasarlandı" demekte, ancak tasarımın davranış seviyesinde
doğrulandığını kanıtlayan hiçbir somut test evidence'ı yoktur.

---

## Objective

ADR-005 ve ADR-006 ile kabul edilen MCP güvenlik ve audit modelinin,
gerçek MCP bağlanmadan önce **sentetik payload'lar ve tamamen offline
testler** ile kalıcı biçimde doğrulanmasını sağlamak.

Bu requirement'ın hedefi çalışan bir **sentetik validation test paketi**
üretmektir: gerçek bir MCP server, credential, endpoint veya network
erişimi gerektirmeyen; deterministik ve tekrarlanabilir; her kritik
lifecycle dalını ve güvenlik kısıtını kanıtlayan bir test koleksiyonu.

Bu test paketinin başarıyla tamamlanması, ADR-006 §10'un "Sentetik hook
payload testi (bağlantı öncesi)" katmanını kapatır ve gerçek bağlantı için
gerekli olan capability validation'ın **ilk zorunlu kapısını** oluşturur.

---

## User / Stakeholder

| Taraf                   | Gereksinim                                                                                          |
|-------------------------|-----------------------------------------------------------------------------------------------------|
| **Human Maintainer**    | Gerçek MCP bağlantısından önce audit/enforcement modelinin kanıtlanmış biçimde çalıştığını görmek. |
| **Security Red Team**   | ADR-006'nın beş bağlayıcı security gate'inin (§12–§16) sentetik testle doğrulanması.             |
| **Solution Architect**  | ADR-005 ve ADR-006 tasarım kararlarının test edilebilir davranışa dönüştürüldüğünü görmek.         |
| **QA Automation**       | Deterministik, tekrarlanabilir test paketi ile implementation doğrulaması yapabilmek.               |
| **Delivery Lead**       | Gerçek bağlantı kararından önce kanıtlanmış bir "sentetik validation" milestone'una sahip olmak.   |

---

## Scope — In Scope

Aşağıdaki test davranışları bu requirement'ın kapsamındadır:

### 1. Known Tool Identity Sınıflandırması

Sentetik bir `PreToolUse` payload'ı ile `MCP_AGENT_CAPABILITY_MATRIX.md`
allowlist'inde tanımlı bir MCP tool identity, strict format validation
süreci üzerinden doğru canonical etiketle sınıflandırılabilmelidir.
Sınıflandırma, local allowlist/map üzerinden üretilen canonical etiketlerle
yapılır; ham runtime string doğrudan güvenilir kabul edilmez.

### 2. Unknown / Allowlist-Dışı Tool Identity → Sentinel Model

`MCP_AGENT_CAPABILITY_MATRIX.md` dışında kalan veya format validation'ı
geçemeyen bir tool identity için audit event aşağıdaki **sabit sentinel
değerlerle** üretilmelidir (ADR-006 §14, `MCP_AUDIT_EVENT_CONTRACT.md`
"Tool Identity Sınıflandırması"):

- `mcp_server: "unclassified"`
- `mcp_tool: "unclassified"`
- `policy_decision: "deny"`
- `failure_category: "unclassified_tool_identity"`

Ham runtime string'i (orijinal unknown değer) hiçbir audit alanına, denial
yoluna veya serbest metin alana yazılmamalıdır.

### 3. PermissionDenied Lifecycle Yolu Ayrımı

`PermissionDenied`, `PostToolUseFailure`'dan ayrı bir lifecycle dalıdır:

- `PermissionDenied` yolunda tool hiç çalışmaz; `PostToolUse` veya
  `PostToolUseFailure` event'i **üretilmez**.
- `PostToolUseFailure`, yalnızca gerçek tool execution başladıktan sonra
  hata oluştuğunda üretilir; bu, izin reddinin bir formu değildir.
- Bu iki dal ayrı sentetik test senaryolarıyla doğrulanmalıdır; birbirine
  indirgenemezler.

### 4. 15 Alanlık Kapalı Şema Doğrulaması

Audit event payload'ı tam olarak `MCP_AUDIT_EVENT_CONTRACT.md`'de tanımlı
15 zorunlu alandan oluşan kapalı (closed) şemayı içermelidir:

`schema_version`, `event_id`, `timestamp`, `session_reference`,
`operation_reference`, `agent_type`, `event_phase`, `mcp_server`,
`mcp_tool`, `action_class`, `environment_scope`, `policy_decision`,
`outcome`, `failure_category`, `audit_record_version`.

15 alan dışında hiçbir alan bu payload'da bulunmamalıdır.

### 5. Yasak Veri Dışlanması

Audit event payload'larına şu veriler hiçbir biçimde sızmamalıdır:

- Ham tool input veya output
- Prompt içeriği (sistem prompt'u, kullanıcı mesajı, agent talimatı)
- URL (query değeri veya tam URL)
- `Authorization` header, token, API key, secret veya credential
- Kişisel veri (PII): ad, e-posta, telefon, müşteri kaydı
- Dosya yolu veya dosya içeriği
- Error message veya exception metni
- Serbest metin not alanı (`note`, `notes`, `message`, `error_message`,
  `details`, `description`, `context`, `metadata`, `debug` veya eşdeğeri)

Redaction bu kısıtı karşılamak için geçerli bir mekanizma değildir;
yasak veri payload'a hiç girmemelidir.

### 6. operation_reference Collision-Resistance Doğrulaması

Aynı oturum içinde paralel yürütülen iki sentetik MCP operasyonu,
farklı ve çakışmayan `operation_reference` değerlerine sahip olmalıdır
(ADR-006 §16). Bu, iki eşzamanlı sentetik çağrının lifecycle event'lerinin
(örn. `PreToolUse`, `PostToolUse`) yanlışlıkla aynı operasyon altında
birleşmediğini doğrular.

### 7. Sentetik Hata Senaryoları → Deny/Blocked

Aşağıdaki sentetik hata koşullarının her biri `deny` veya `blocked`
sonucuyla eşleşmelidir:

- **Parser failure:** Malformed/geçersiz `PreToolUse` payload.
- **Malformed payload:** Eksik zorunlu alanlar veya geçersiz format.
- **Capability mismatch:** Agent/tool/environment üçlüsünün
  `MCP_AGENT_CAPABILITY_MATRIX.md` ile uyumsuzluğu.
- **Audit unavailable:** Audit sink kullanılamaz veya durable write
  acknowledgment alınamaz.

Her hata koşulu dış MCP çağrısını başlatmamalıdır.

### 8. Offline ve Deterministik Yürütme

Test paketi:

- Herhangi bir network erişimi olmadan tamamen çalışmalıdır.
- Aynı fixture'larla çalıştırıldığında her seferinde aynı sonucu
  üretmelidir (deterministik).
- Her test sonucu açık PASS/FAIL assertion içermelidir.

### 9. Gerçek MCP Bağımlılığı Olmadan Yürütme

Test paketi şunlardan hiçbirini gerektirmemelidir:

- Gerçek MCP server bağlantısı
- Gerçek credential, API key, token veya endpoint
- Network çağrısı
- `.claude/hooks/` implementasyonu
- `.claude/settings.json` konfigürasyonu
- Claude Code hook runtime'ı (gerçek hook sistemi)

Test fixture'ları yalnızca sentetik değerler içermelidir.

---

## Out of Scope

Aşağıdakiler bu requirement'ın açıkça **kapsam dışındadır**:

- Gerçek MCP server kurulumu veya bağlantısı (NotebookLM, Obsidian,
  Playwright, GitHub MCP, Context7 veya başka herhangi bir MCP)
- `.claude/hooks/` dosyasının implementasyonu
- `.claude/settings.json` değişikliği
- Token, API key, endpoint veya credential eklenmesi
- Audit sink/vendor/transport seçimi ve implementasyonu
- Gerçek audit logging altyapısının kurulumu
- Append-only / tamper-evident storage mekanizması seçimi (ADR-006 §12)
- Out-of-band / non-recursive audit writer implementasyonu (ADR-006 §13)
- Production, staging veya cloud ortamına erişim
- Gerçek browser side-effect, ödeme, webhook, kullanıcı silme veya
  başka dış sistem işlemi
- NotebookLM, Obsidian, Playwright, GitHub MCP veya Context7 MCP
  kullanımı (gerçek bağlantı anlamında)
- Human-visible failure signal'inin storage/location mekanizması seçimi
- `session_reference` ve `operation_reference` alanlarının somut üretim
  algoritmalarının seçimi

---

## Acceptance Criteria

Tüm ayrıntılı kabul kriterleri ayrı bir dosyada tanımlanmıştır:

`docs/product/acceptance-criteria/AC-REQ-001-mcp-hook-lifecycle-synthetic-validation.md`

Özet (tam tanım AC dosyasındadır):

| AC ID  | Konu                                                              |
|--------|-------------------------------------------------------------------|
| AC-001 | Known tool identity sınıflandırması                               |
| AC-002 | Unknown/allowlist-dışı tool identity → sentinel model             |
| AC-003 | PermissionDenied ve PostToolUseFailure lifecycle yolu ayrımı      |
| AC-004 | 15 alanlık kapalı şema doğrulaması                                |
| AC-005 | Yasak veri dışlanması                                             |
| AC-006 | operation_reference collision-resistance (paralel operasyonlar)   |
| AC-007 | Sentetik hata senaryoları → deny/blocked                          |
| AC-008 | Offline ve deterministik yürütme                                  |
| AC-009 | Gerçek MCP bağımlılığı olmadan yürütme                            |
| AC-010 | Açık PASS/FAIL assertion                                          |
| AC-011 | Implementation tamamlanınca test evidence kaydı                   |

---

## Non-Functional Requirements

| Gereksinim         | Açıklama                                                                                                                                             |
|--------------------|------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Offline**        | Test paketi, network erişimi olmayan bir ortamda eksiksiz çalışmalıdır.                                                                              |
| **Determinism**    | Aynı fixture girdileriyle aynı sonuç üretilmelidir; flaky veya non-deterministic test kabul edilmez.                                                 |
| **Izolasyon**      | Her test senaryosu diğerinden bağımsız çalışmalıdır; paylaşılan global state bulunmamalıdır.                                                         |
| **Güvenlik**       | Test fixture'ları, çıktıları ve assertion'ları gerçek credential, PII veya sensitive veri içermemelidir.                                             |
| **Sürdürülebilirlik** | Test tanımları `MCP_AUDIT_EVENT_CONTRACT.md` schema değişikliklerinde güncellenebilir yapıda olmalıdır.                                           |
| **Kanıt kaydı**    | Test paketinin sonuçları insan maintainer tarafından incelenebilir biçimde saklanmalıdır (hangi mekanizmayla saklanacağı bu REQ kapsamında seçilmez). |

---

## Dependencies

Bu requirement'ın implement edilebilmesi için aşağıdakiler gereklidir:

| Bağımlılık                            | Durum     | Referans                                                         |
|---------------------------------------|-----------|------------------------------------------------------------------|
| ADR-005 Accepted                      | Tamamlandı | `docs/architecture/adr/ADR-005-mcp-tooling-control-plane.md`    |
| ADR-006 Accepted                      | Tamamlandı | `docs/architecture/adr/ADR-006-mcp-audit-logging-and-runtime-enforcement.md` |
| MCP Audit Event Contract              | Tamamlandı | `docs/decisions/MCP_AUDIT_EVENT_CONTRACT.md`                     |
| MCP Agent Capability Matrix           | Tamamlandı | `docs/decisions/MCP_AGENT_CAPABILITY_MATRIX.md`                  |
| MCP Connection Preconditions kaydı    | Tamamlandı | `docs/quality/security-reports/SEC-ADR-005-MCP-CONNECTION-PRECONDITIONS.md` |

---

## Risks

| Risk                                              | Olasılık | Etki  | Açıklama                                                                                                                                                 |
|---------------------------------------------------|----------|-------|----------------------------------------------------------------------------------------------------------------------------------------------------------|
| Sentetik test gerçek hook davranışını yansıtmaz  | Orta     | Yüksek | Sentetik test yalnızca logic/contract doğrular; Claude Code runtime'ının MCP tool-call'larını `PreToolUse`'da gerçekten gözlemleyip gözlemlemediğini kanıtlamaz. Bu, environment-specific smoke test (kapsam dışı) ile ayrıca kapatılmalıdır. |
| Fixture'ların gerçek veri içermesi riski         | Düşük    | Yüksek | Test fixture'larına yanlışlıkla gerçek credential, endpoint veya PII girmesi, bu test paketinin kendi başına güvenlik ihlali oluşturmasına yol açar.    |
| 15 alanlık şemanın yorumlanma farklılıkları      | Orta     | Orta  | Implementer, `failure_category: null` ve `failure_category` olmayan durumu eşdeğer saymayabilir; AC-004 ve AC-010 bunu açık assertion ile kapsamalıdır. |
| PermissionDenied / PostToolUseFailure karışıklığı | Orta    | Orta  | Bu iki lifecycle dalının implementation sırasında tek yola indirgenmesi riski; AC-003 bu riski test seviyesinde açık biçimde ele alır.                  |
| operation_reference üretim algoritması belirsizliği | Düşük | Orta  | Somut üretim algoritması (ADR-006 Open Questions) bu REQ kapsamında seçilmez; test sentetik `operation_reference` değerleri kullanır. Gerçek implementasyonda collision-resistance ayrıca doğrulanmalıdır. |

---

## Human Approval Gates

Bu requirement'ın kapsamına giren test paketinin implementation'a geçmesi
için aşağıdaki insan onay noktaları zorunludur:

1. **REQ-001 acceptance:** Bu requirement ve AC dosyası insan maintainer
   tarafından gözden geçirilmeden implementation başlamaz.
2. **Test paketinin sonuçlarının onaylanması:** Test paketi çalıştırıldıktan
   sonra, human maintainer test evidence kaydını (AC-011) incelemeli ve
   "sentetik validation tamamlandı" kararını açıkça kayıt altına almalıdır.

**Aşağıdaki karar bu requirement'ın tamamlanmasıyla otomatik olarak
verilmez ve ayrı insan onayı gerektirir:**

REQ-001'in tamamlanması, gerçek MCP bağlantısı veya audit hook
implementasyonu için otomatik izin vermez. Gerçek bağlantı; audit sink
seçimi, append-only/tamper-evident doğrulama, out-of-band/non-recursive
writer doğrulaması, capability validation, environment-specific smoke test,
credential storage onayı ve MCP bazlı human maintainer onayı gerektirir.

Bu onay kapıları `SEC-ADR-005-MCP-CONNECTION-PRECONDITIONS.md`'deki
"Bağlantı Öncesi Zorunlu Kapılar" listesinde detaylı biçimde
tanımlanmıştır.

---

## Implementation Handoff

Bu requirement'a ilişkin implementation handoff'u aşağıdaki bilgileri
içermelidir:

- Test paketinin nerede konumlandırıldığı (dosya yolu veya klasör).
- Her test senaryosunun hangi AC ID'sine karşılık geldiği.
- Test çalıştırma komutu ve beklenen çıktı özeti.
- AC-011 kapsamında: Test sonuç kanıtının nerede saklandığı.
- Kapsam dışı kalan gerçek bağlantı adımları için sonraki insan kararının
  ne olduğu.

Bu handoff güncellemesinin Delivery Lead veya insan maintainer tarafından
planlanması gerekir; Product Analyst bu güncellemeyi yapmaz.

---

## NotebookLM Evidence References

Bu requirement yalnızca repository içi Git-tracked dokümanlara dayanır.
NotebookLM ve Obsidian bu requirement'ın yazımında kaynak olarak
**kullanılmamıştır**.

Canonical referanslar:

- `docs/architecture/adr/ADR-005-mcp-tooling-control-plane.md` (Accepted)
- `docs/architecture/adr/ADR-006-mcp-audit-logging-and-runtime-enforcement.md` (Accepted)
- `docs/decisions/MCP_AUDIT_EVENT_CONTRACT.md`
- `docs/decisions/MCP_AGENT_CAPABILITY_MATRIX.md`
- `docs/quality/security-reports/SEC-ADR-005-MCP-CONNECTION-PRECONDITIONS.md`
- `PROJECT_CONSTITUTION.md` (source of truth hiyerarşisi, §2, §3, §6)
- `CLAUDE.md` (security rules)
- `AGENTS.md` (rol listesi)

---

## Open Questions

Aşağıdaki belirsizlikler bu requirement kapsamında çözülmemiştir ve insan
maintainer veya ilgili agent tarafından ayrıca ele alınmalıdır:

1. **`operation_reference` somut üretim algoritması:** Bu REQ, sentetik
   `operation_reference` değerlerini test fixture'larında manuel atar.
   Gerçek implementasyonda collision-resistant üretim algoritması (hash,
   salted token, monotonic sayaç vb.) ayrıca seçilmeli ve doğrulanmalıdır
   (ADR-006 §16 ve Open Questions).

2. **`session_reference` üretim yöntemi:** Benzer şekilde, gerçek
   `session_reference` üretim mekanizması (privacy-preserving tek yönlü
   hash veya eşdeğeri) bu REQ kapsamında seçilmez.

3. **Sentetik testin Claude Code runtime hook ile entegrasyonu:** Bu test
   paketi Claude Code'un gerçek `PreToolUse` hook mekanizmasını test etmez;
   yalnızca logic ve contract doğrular. Gerçek hook entegrasyonu
   environment-specific smoke test (kapsam dışı) ile kapatılmalıdır.
   Bu entegrasyonun nasıl ve ne zaman yapılacağı açık kalmaktadır.

4. **Test evidence kaydının formatı ve konumu:** AC-011, implementation
   tamamlanınca test evidence kaydı istenir; ancak bu kaydın hangi formatta
   ve nerede tutulacağı bu REQ kapsamında belirtilmez. Bu karar Delivery
   Lead veya insan maintainer tarafından yapılmalıdır.

5. **`failure_category` taksonomisinin genişletilmesi:** ADR-006 Open
   Questions, ilk gerçek MCP entegrasyonu tasarlanırken `failure_category`
   enum listesinin genişletilebileceğini belirtir. Test paketi, şu an
   `MCP_AUDIT_EVENT_CONTRACT.md`'deki kapalı enum listesine dayanır; bu
   liste değişirse testlerin güncellenmesi gerekir.
