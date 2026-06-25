# REQ-002 — Local Hook Audit Runtime Spike

## Requirement Metadata

| Alan               | Değer                                                                                      |
|--------------------|--------------------------------------------------------------------------------------------|
| **Requirement ID** | REQ-002                                                                                    |
| **Status**         | Proposed                                                                                   |
| **Title**          | Local Hook Audit Runtime Spike                                                             |
| **Date**           | 2026-06-26                                                                                 |
| **Author**         | Product Analyst                                                                            |
| **Branch**         | product-req-002-local-hook-audit-runtime                                                   |
| **AC Reference**   | `docs/product/acceptance-criteria/AC-REQ-002-local-hook-audit-runtime-spike.md`           |

---

> **Durum notu:** Bu requirement `Proposed` statüsündedir. İnsan maintainer
> acceptance kararı olmadan runtime spike uygulanamaz. Bu requirement gerçek
> MCP bağlantısını, production audit sink'i veya credential kullanımını
> onaylamaz.

---

## Problem

REQ-001, audit lifecycle karar modelini offline sentetik testlerle doğruladı.

Ancak REQ-001, Claude Code'un gerçek runtime'ında command hook'un
tetiklendiğini, JSON input'un stdin üzerinden geldiğini, local audit
writer'ın gerçek lifecycle event'ini işleyebildiğini veya audit writer
unavailable durumunda gerçek `PreToolUse` denial davranışını kanıtlamaz.

Bu boşluk şu açık soruları yanıtsız bırakmaktadır:

- Claude Code'un command hook yapılandırması gerçek bir `PreToolUse`
  event'ini tetikliyor mu?
- Hook script, Claude Code'un ürettiği JSON payload'ı stdin üzerinden
  gerçekten alıyor mu?
- Yerel ve geçici bir audit writer bu JSON'u okuyup ADR-006 ve MCP Audit
  Event Contract'a uygun bir event üretebiliyor mu?
- Audit writer başarısız olduğunda hook gerçekten fail-closed davranıyor
  mu ve `PreToolUse` deny alıyor mu?

Bu dört soru REQ-001 sentetik test paketiyle yanıtlanamaz; yalnızca gerçek
Claude Code runtime'ında disposable local bir test ortamında
kanıtlanabilir.

ADR-006 §10 "Capability validation yaklaşımı", iki ayrı katmanı açıkça
tanımlar: (1) gerçek bağlantı olmadan sentetik hook payload testi
(REQ-001 ile kapatıldı) ve (2) gerçek bağlantı sonrası environment-specific
smoke test. REQ-002 bu iki katman arasında köprü kuran bir ara adımdır:
gerçek MCP bağlamadan, yalnızca built-in tool kullanarak Claude Code
runtime'ının hook mekanizmasını yerel ortamda doğrular.

---

## Objective

Gerçek MCP server bağlamadan, yalnızca built-in ve güvenli bir Claude Code
tool event'i kullanarak disposable local workspace içinde gerçek command
hook lifecycle davranışını doğrulamak.

İlk doğrulama aracı olarak yalnızca built-in `Read` tool kullanılacaktır.

Bu spike'ın hedefi yalnızca şu iki ölçülebilir runtime kanıtını üretmektir:

1. **Controlled successful path:** Claude Code command hook, built-in `Read`
   çağrısında tetiklenir; yerel audit writer ADR-006/MCP Audit Event Contract
   şemasına uygun event üretir; `Read` tool normal akışa devam eder.
2. **Controlled failure path:** Audit writer unavailable olduğunda hook
   fail-closed davranır; `PreToolUse` deny üretir; `Read` tool çalışmaz;
   dış dispatch gerçekleşmez.

Bu spike hiçbir gerçek MCP bağlantısı, dış dispatch, credential veya
production audit sink gerektirmez.

---

## User / Stakeholder

| Taraf                  | Gereksinim                                                                                                                          |
|------------------------|-------------------------------------------------------------------------------------------------------------------------------------|
| **Human Maintainer**   | Gerçek Claude Code runtime'ında command hook lifecycle'ının kanıtlanması; ADR-006 §10 iki katmanlı capability validation'ın ilk gerçek adımı için yerel evidence görmek. |
| **Security Red Team**  | Fail-closed davranışın (audit writer unavailable → deny) gerçek runtime'da doğrulanması; raw veri sızıntısının olmaması.           |
| **Solution Architect** | ADR-006'nın sentetik → gerçek hook lifecycle doğrulama zincirinin yerel ayak izini ortaya koymak.                                  |
| **Delivery Lead**      | "Gerçek runtime kanıtı yok" boşluğunun kapatılması; sonraki gerçek MCP connection kararı için gerekli bir öncülün elde edilmesi.  |

---

## Scope

REQ-002 aşağıdaki dar davranışları kapsar:

### 1. Disposable Local Workspace ve Temporary Configuration

Disposable local test workspace içinde, yalnızca local ve geçici bir Claude
Code hook configuration hazırlanır. Bu configuration:

- Repository'nin canonical `.claude/settings.json` dosyasını değiştirmez.
- Commit edilmez; spike tamamlandığında silinir.
- Yalnızca test süresi boyunca aktif olan geçici bir yapılandırmadır.

### 2. Yalnızca Read Matcher ile Hook

Test configuration yalnızca built-in `Read` tool için `PreToolUse` matcher
kullanır. Hiçbir MCP server matcher'ı, credential gerektiren matcher,
external tool matcher veya production hook davranışını etkileyecek başka bir
matcher eklenmez.

### 3. Stdin Üzerinden JSON Payload

Command hook, Claude Code'dan gelen runtime JSON payload'ını stdin üzerinden
alır. Hook'un stdin'den okuyabildiği ve yapılandırılmış JSON'u işleyebildiği
gerçek runtime kanıtıyla doğrulanır.

### 4. Yalnızca Güvenli Metadata İşleme

Hook yalnızca gerekli güvenli metadata'yı işler; raw tool input, dosya
içeriği, prompt, URL, token, header, secret, PII, exception metni veya
reason persist etmez.

### 5. 15 Alanlık Kapalı Şema ile Audit Event Üretimi

Local audit event, ADR-006 ve MCP Audit Event Contract içindeki tam 15
alanlık closed schema ile üretilir. 15 alan dışında hiçbir alan persist
edilmez.

### 6. Privacy-Preserving Runtime Referanslar

`session_reference` ve `operation_reference` alanlarına ait session veya
operation runtime kimlikleri raw biçimde persist edilmez; yalnızca test-only
privacy-preserving referanslar kullanılır.

### 7. Controlled Successful Path

Audit writer event'i yazabildiğinde built-in `Read` tool normal permission
akışına devam eder; gereksiz deny alınmaz.

### 8. Controlled Failure Path

Audit writer unavailable veya write acknowledgement başarısız olduğunda hook
fail-closed davranır:

- `PreToolUse` tool kullanımını deny eder.
- Dış dispatch, MCP çağrısı veya network çağrısı gerçekleşmez.

### 9. Cleanup

Test tamamlandığında local configuration, temporary hook script ve local
audit artefact'lar temizlenir. Spike'ın geçici olduğu ve hiçbir kalıcı
değişiklik bırakmadığı kanıtlanır.

### 10. Evidence Kaydı

Evidence yalnızca sentetik/local runtime spike başarısını veya başarısızlığını
kaydeder. Gerçek dosya içeriği, prompt, session verisi veya kullanıcı verisi
kaydedilmez.

---

## Out of Scope

Aşağıdakiler bu requirement'ın açıkça **kapsam dışındadır**:

- Gerçek MCP server kurulumu veya bağlantısı (NotebookLM, Obsidian,
  Playwright, GitHub MCP, Context7 veya başka herhangi bir MCP)
- NotebookLM, Obsidian, Playwright, GitHub veya Context7 MCP kullanımı
- `.claude/settings.json` içine kalıcı veya commit edilebilir hook eklenmesi
- Production hook implementation
- Repository içine production audit sink veya audit writer eklenmesi
- Append-only veya kanıtlanabilir tamper-evident production storage seçimi
- Credential, token, API key, endpoint veya secret eklenmesi
- Network, cloud, staging veya production erişimi
- MCP capability validation
- Environment-specific MCP smoke test
- Audit sink vendor veya transport seçimi
- Gerçek kullanıcı verisi veya gerçek dosya içeriği işleme
- `operation_reference` somut üretim algoritmasının seçimi (ADR-006 Open
  Questions)
- `session_reference` somut üretim algoritmasının seçimi
- Human-visible failure signal'inin storage/location mekanizması seçimi
- `failure_category` taksonomisinin genişletilmesi
- Mevcut `.claude/hooks/enforce-role-boundaries.sh` hook'unun değiştirilmesi
- CI diff gate veya ownership enforcement zincirinin değiştirilmesi

---

## Acceptance Criteria

Tüm ayrıntılı kabul kriterleri ayrı bir dosyada tanımlanmıştır:

`docs/product/acceptance-criteria/AC-REQ-002-local-hook-audit-runtime-spike.md`

Özet (tam tanım AC dosyasındadır):

| AC ID  | Konu                                                                                              |
|--------|---------------------------------------------------------------------------------------------------|
| AC-001 | Disposable local workspace ve temporary configuration oluşturma sınırları                         |
| AC-002 | `/hooks` veya eşdeğer runtime doğrulamasıyla yalnızca `Read` matcher'lı hook'un görünmesi        |
| AC-003 | Gerçek built-in `Read` çağrısında hook'un çalıştığına dair local evidence                        |
| AC-004 | Üretilen audit event'in tam olarak 15 alan taşıması                                               |
| AC-005 | Raw input, dosya içeriği, URL, prompt, token, PII, file path, reason veya exception text sızıntısının olmaması |
| AC-006 | Raw runtime reference'ların persist edilmemesi                                                    |
| AC-007 | Audit writer başarılı olduğunda tool call'ın gereksiz deny almaması                               |
| AC-008 | Audit writer unavailable olduğunda `PreToolUse` deny/fail-closed davranışı                        |
| AC-009 | Network, MCP server, credential ve external dependency olmadan çalışma                            |
| AC-010 | Cleanup kanıtı; temporary settings, script ve audit artefact'ların kaldırılması                   |
| AC-011 | İnsan maintainer evidence incelemesi ve açık karar kaydı                                          |

---

## Non-Functional Requirements

| Gereksinim        | Açıklama                                                                                                                                         |
|-------------------|--------------------------------------------------------------------------------------------------------------------------------------------------|
| **İzolasyon**     | Spike disposable bir local workspace içinde yürütülür; repository'nin canonical dosyalarını değiştirmez.                                         |
| **Güvenlik**      | Üretilen local audit artifact gerçek dosya içeriği, prompt, PII, token veya credential taşımaz.                                                 |
| **Geçicilik**     | Hook configuration, script ve audit artifact spike sonunda silinir; kalıcı değişiklik bırakılmaz.                                               |
| **Dar Kapsam**    | Yalnızca built-in `Read` tool ile test edilir; MCP server, dış araç veya network gerektiren hiçbir test senaryosu dahil edilmez.                 |
| **Evidence Kalitesi** | Üretilen evidence yalnızca local runtime başarısını veya başarısızlığını kaydeder; gerçek kullanıcı verisi veya session içeriği içermez.   |

---

## Dependencies

| Bağımlılık                            | Durum      | Referans                                                                                                     |
|---------------------------------------|------------|--------------------------------------------------------------------------------------------------------------|
| ADR-005 Accepted                      | Tamamlandı | `docs/architecture/adr/ADR-005-mcp-tooling-control-plane.md`                                                |
| ADR-006 Accepted                      | Tamamlandı | `docs/architecture/adr/ADR-006-mcp-audit-logging-and-runtime-enforcement.md`                                |
| REQ-001 / AC-011 Completed            | Tamamlandı | `docs/product/requirements/REQ-001-mcp-hook-lifecycle-synthetic-validation.md`                              |
| REQ-001 Handoff                       | Tamamlandı | `docs/handoffs/REQ-001.md`                                                                                   |
| MCP Audit Event Contract              | Tamamlandı | `docs/decisions/MCP_AUDIT_EVENT_CONTRACT.md`                                                                 |
| MCP Connection Preconditions kaydı    | Tamamlandı | `docs/quality/security-reports/SEC-ADR-005-MCP-CONNECTION-PRECONDITIONS.md`                                 |

---

## Risks

| Risk                                                                                   | Olasılık | Etki   | Açıklama                                                                                                                                                                                                       |
|----------------------------------------------------------------------------------------|----------|--------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Claude Code command hook'unun `PreToolUse`'u doğru biçimde tetiklemediği veya stdin payload'ını beklenen formatta iletmediği ortaya çıkabilir | Orta | Yüksek | Bu spike'ın birincil araştırma sorusudur; eğer hook tetiklenmiyorsa bu bulgu ADR-006 §10'un gerçek bağlantı öncesi kapatılması gereken bir gap olduğunu kanıtlar ve ayrı bir tasarım adımı gerektirir. |
| Geçici hook config'in canonical repository dosyalarını beklenmedik biçimde etkilemesi  | Düşük    | Yüksek | Spike yalnızca disposable workspace içinde çalışmalıdır; canonical `.claude/settings.json` ve mevcut hook script bu spike kapsamında değiştirilmez. Bu durum AC-001 ve AC-010 kapsamında doğrulanır.          |
| Audit writer script'in beklenmedik biçimde raw dosya içeriği veya prompt'u local artifact'a persist etmesi | Orta | Yüksek | AC-005 bu riski doğrudan ele alır; artifact içeriğinin insan maintainer tarafından incelenmesi zorunludur (AC-011). |
| Cleanup adımının eksik kalması ve geçici yapılandırmanın repository'de kalıcı hale gelmesi | Düşük | Orta | AC-010 cleanup kanıtını zorunlu kılar; cleanup tamamlanmadan AC-010 geçemez.                                                                                                                                  |
| Spike sonucunun gerçek MCP bağlantısı için "No-Go kapıları kapatıldı" olarak yanlış yorumlanması | Orta | Yüksek | Human gate ifadesi bu dokümanın "Human Approval Gates" bölümünde ve AC-011'de açıkça yer almaktadır; bu risk açıkça bildirilmiş ve sınırlandırılmıştır. |

---

## Human Approval Gates

Bu requirement'ın implementation'a geçmesi için aşağıdaki insan onay
noktaları zorunludur:

1. **REQ-002 acceptance:** Bu requirement ve AC dosyası insan maintainer
   tarafından gözden geçirilmeden spike başlamaz.
2. **Evidence incelemesi:** Spike tamamlandıktan sonra, insan maintainer
   local evidence artifact'ı incelemeli ve açık bir karar kaydı
   oluşturmalıdır (AC-011).

**REQ-002'nin tamamlanması, gerçek MCP bağlantısı veya production audit
enforcement için otomatik izin vermez. Gerçek MCP bağlantısı; append-only
veya kanıtlanabilir tamper-evident audit sink, out-of-band/non-recursive
writer, durable write acknowledgment, MCP bazlı capability validation,
environment-specific MCP smoke test, credential storage onayı ve MCP bazlı
human maintainer onayı gerektirir.**

Bu onay kapıları `SEC-ADR-005-MCP-CONNECTION-PRECONDITIONS.md`'deki
"Bağlantı Öncesi Zorunlu Kapılar" listesinde detaylı biçimde
tanımlanmıştır.

---

## Implementation Handoff Notu

Bu requirement yalnızca ölçülebilir runtime davranış kanıtını tanımlar.
Implementation'a başlanmadan önce:

- Ownership manifest hazırlanmalıdır (Delivery Lead / insan maintainer).
- Spike yalnızca onaylı, disposable workspace içinde çalıştırılmalıdır.
- Hook script ve temporary config, spike tamamlandığında silinmelidir
  (AC-010).
- Handoff güncellemesi Delivery Lead veya insan maintainer tarafından
  planlanmalıdır; Product Analyst bu güncellemeyi yapmaz.

---

## NotebookLM Evidence References

Bu requirement yalnızca repository içi Git-tracked dokümanlara dayanır.
NotebookLM ve Obsidian bu requirement'ın yazımında kaynak olarak
**kullanılmamıştır**.

Canonical referanslar:

- `docs/architecture/adr/ADR-005-mcp-tooling-control-plane.md` (Accepted)
- `docs/architecture/adr/ADR-006-mcp-audit-logging-and-runtime-enforcement.md`
  (Accepted)
- `docs/decisions/MCP_AUDIT_EVENT_CONTRACT.md`
- `docs/quality/security-reports/SEC-ADR-005-MCP-CONNECTION-PRECONDITIONS.md`
- `docs/handoffs/REQ-001.md`
- `docs/product/requirements/REQ-001-mcp-hook-lifecycle-synthetic-validation.md`
- `PROJECT_CONSTITUTION.md` (source of truth hiyerarşisi, §2, §3, §6)
- `CLAUDE.md` (security rules)
- `AGENTS.md` (rol listesi)

---

## Open Questions

1. **Claude Code command hook'unun `PreToolUse` event'ini stdin üzerinden
   iletip iletmediği:** Bu spike'ın birincil araştırma sorusudur; yanıt
   henüz doğrulanmamıştır. Hook payload'ı formatı (JSON structure,
   encoding, field names) implementation öncesi açık kalmaktadır.

2. **Disposable workspace yapılandırmasının tam izolasyon sınırları:**
   Geçici hook config'in tam olarak nasıl (hangi dosya, hangi path,
   nasıl izole) oluşturulacağı ve cleanup'ın eksiksiz sağlanacağı
   implementation tasarımı gerektirir; bu REQ yalnızca davranış sınırlarını
   tanımlar.

3. **Fail-closed enforcement mekanizması:** Audit writer başarısız
   olduğunda hook'un `PreToolUse` deny'ı nasıl sinyalleyeceği (exit code,
   stdout payload, vb.) Claude Code hook runtime dokümantasyonuna bağlıdır;
   bu detay implementation adımında netleştirilmelidir.

4. **Privacy-preserving reference üretim yöntemi:** `session_reference`
   ve `operation_reference` alanlarının test-only privacy-preserving
   biçimde nasıl üretileceği (local sayaç, sabit prefix, vb.) bu REQ
   kapsamında seçilmez; implementation sırasında belirlenir.

5. **Local artifact formatı:** Üretilen local audit event'inin hangi
   formatta (JSON satırı, dosya) ve nerede (geçici dosya yolu)
   saklanacağı implementation kararıdır; bu REQ yalnızca 15 alanlık
   kapalı şema zorunluluğunu ve yasak veri sınırlarını tanımlar.
