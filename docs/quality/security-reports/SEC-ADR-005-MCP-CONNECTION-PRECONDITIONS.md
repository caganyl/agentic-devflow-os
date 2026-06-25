# SEC-ADR-005 — MCP Connection Preconditions

## Kayıt Bilgisi

- **Related ADR:** ADR-005 (`docs/architecture/adr/ADR-005-mcp-tooling-control-plane.md`)
- **Status:** Open / Pending Human Approval
- **Scope:** policy-level security follow-up
- **Oluşturulma tarihi:** 2026-06-25
- **Owner:** Human Maintainer
- **Prepared by:** Security Red Team

Bu kayıt bir release handoff veya REQ handoff'u **değildir**. Bu kayıt, bu
review sırasında bir REQ-ID, acceptance criteria veya implementation
contract'ı incelenmemiştir; kapsam tamamen ADR-005 policy dokümanı ve ona
referans veren governance dokümanlarıdır (bkz. "Açık Teknik Kararlar" ve
"Kapsam/Bilinen Kısıt" notları).

## Amaç ve Kapsam

Bu doküman, ADR-005 ("MCP Tooling Control Plane and External Tool Access
Model") altında planlanan **herhangi bir gerçek MCP bağlantısından önce**
yerine getirilmesi gereken güvenlik ön koşullarını ve insan onay noktalarını
canonical biçimde kayıt altına alır. Bu doküman:

- ADR-005'in status alanını değiştirmez (ADR-005, PR #13 kapsamında `Accepted`
  durumuna geçirilmiştir; acceptance date: 2026-06-25 — bu kabul yalnızca
  policy kararını kapsar; gerçek MCP bağlantısı için "Bağlantı Öncesi Zorunlu
  Kapılar" listesi değişmeden açık kalmaktadır).
- Hiçbir MCP'nin `Active`, `Configured`, `Connected` veya kullanıma hazır
  olduğunu iddia etmez.
- Hiçbir token, endpoint, API key, secret, vendor kurulumu veya komut
  eklemez.

**Bilinen kısıt:** Bu review sırasında repository'de gerçek bir MCP
kurulumu, konfigürasyonu veya bağlantısı bulunmamaktadır (ADR-005 ve
`MCP_AGENT_CAPABILITY_MATRIX.md`'nin kendisi de bunu doğrular: tüm satırlar
"Planned — policy only" veya "Planned — future state, not connected"
durumundadır). Bu nedenle bu inceleme bir kod/implementation review'u değil,
**policy-level adversarial review**'dur.

## Güvenlik Durumu Özeti

- **Policy-level review sonucu: Conditional Go.**
- **Gerçek MCP bağlantısı için: No-Go.**

Bu iki ifade birbiriyle çelişmez: ADR-005'in kendisi (read-only-by-default
ilkesi, canonical source of truth modelinin korunması, untrusted MCP output
ilkesi, trust boundary ayrımı, tool classification ve per-MCP modeller) bir
**politika** olarak kabul edilebilir niteliktedir ve bu nedenle policy
seviyesinde "Conditional Go" değerlendirmesi alır — koşul, aşağıdaki
"Bağlantı Öncesi Zorunlu Kapılar" bölümünün insan maintainer tarafından
tamamlanmasıdır. Ancak **policy kabul edilebilir olması, teknik bağlantıyı
otomatik olarak yetkilendirmez**: ADR-005'in kendi metni (Audit logging
ön koşulu, credential saklama ön koşulu, Security Follow-up bölümü) ve bu
doküman, gerçek bir MCP hesabına/ortamına/sunucusuna bağlanmadan önce
zorunlu, henüz kapatılmamış kapılar bulunduğunu açıkça belirtir. Bu kapılar
tamamlanmadan hiçbir gerçek MCP kullanımı açılmaz; bu nedenle gerçek
bağlantı için sonuç **No-Go**'dur.

## Bağlantı Öncesi Zorunlu Kapılar

- [x] ADR-005 insan maintainer tarafından kabul edildi (`Accepted` durumuna
      geçti).
- [ ] MCP output'larının untrusted data olduğu ve içindeki talimatların
      action authority olmadığı doğrulandı.
- [ ] Minimum audit logging tasarlandı ve çalışır biçimde doğrulandı.
- [ ] Audit log; agent identity, MCP/tool identity, operation type,
      timestamp, environment/target scope ve outcome kaydediyor.
- [ ] Audit log secret, credential veya hassas tool output saklamıyor.
- [ ] Audit log retention, storage ve human review mekanizması insan
      tarafından onaylandı.
- [ ] Her MCP için ayrı capability validation tamamlandı.
- [ ] Her MCP için environment-specific smoke test tamamlandı.
- [ ] Credential storage yöntemi insan maintainer tarafından onaylandı.
- [ ] Credential'ların Git, `.claude/`, `.github/`, docs, Obsidian veya
      NotebookLM kaynaklarında olmadığı doğrulandı.
- [ ] İlgili MCP için least-privilege ve read-only erişim doğrulandı.
- [ ] Human maintainer ilgili MCP bağlantısı için açık onay verdi.

## Araç Bazlı Ek Ön Koşullar

### NotebookLM / Obsidian / Context7 / resmi docs

- Tool output untrusted data kabul edilir.
- Imperative içerik, sahte approval veya tool yönlendirmesi action
  authority değildir.
- Canonical source of truth değildir.
- İleride prompt injection pattern detection / sanitization değerlendirmesi
  gerekir.

### Playwright

- Explicit host/URL allowlist insan tarafından onaylanmış olmalı.
- Staging gerçek müşteri verisi ve production credential içermediği
  doğrulanmadan kullanılamaz.
- Test account ve sentetik veri kullanılır.
- Email, webhook, ödeme, kullanıcı silme, kalıcı silme, dış sistem çağrısı
  ve diğer yan etkili browser işlemleri varsayılan olarak yasaktır.

### GitHub MCP

- Repository-scoped, least-privilege, read-only credential gerekir.
- Admin, organization, collaborator, secret, branch protection, workflow
  permission ve write scope yasaktır.
- PR, issue, comment, commit message, workflow log veya release note
  içinde secret/PII görülürse agent kopyalamaz, özetlemez, durur ve insan
  maintainer'a bildirir.

### Future observability / database / cloud MCP

- Bu araçlar için gerçek bağlantı bu follow-up kapsamı dışındadır.
- Ayrı ADR, ayrı security review ve insan onayı olmadan bağlanamaz.
- Production write erişimi varsayılan olarak yasaktır.

## Doğrulama Kanıtı Formatı

Her gerçek MCP capability validation'ında aşağıdaki kanıtların
kaydedilmesi gerekir. Bu bölüm bir **şablondur**; hiçbir alan bu doküman
kapsamında otomatik doldurulmamıştır:

- MCP adı:
- Kullanılan agent rolü:
- İzinli environment / target:
- Credential scope özeti:
- Smoke test özeti:
- Audit log referansı:
- Sonuç: Go / Conditional Go / No-Go
- Human maintainer kararı:
- Tarih:

## Açık Teknik Kararlar

Aşağıdaki kararlar ADR-005'in "Open Questions" bölümüyle tutarlıdır ve bu
doküman kapsamında **çözülmemiştir**; ilgili agent'a (Solution Architect /
Delivery Lead / insan maintainer) devredilmesi gerekir:

- Audit log storage location.
- Retention süresi.
- Human review sıklığı.
- MCP tool-call runtime enforcement yöntemi.
- Capability matrix'in teknik olarak nasıl doğrulanacağı.
- Prompt injection detection / content sanitization yaklaşımı.
- Gelecekteki write-capable MCP aksiyonları için approval modeli.

## Açık Yasaklar

- Bu kayıt tek başına MCP bağlantısı onayı **değildir**.
- Bu kayıt token/secret saklama yeri **değildir**.
- Bu kayıt production erişim izni **değildir**.
- Bu kayıt agent'a main merge, deploy, migration veya external side effect
  yetkisi **vermez**.

## Merge Decision

- **Severity:** High (policy enforcement gap — audit logging ve capability
  validation tamamlanmadan gerçek MCP bağlantısı açılma riski).
- **Evidence:** ADR-005 "İnsan Onay Kapıları" (Audit logging ön koşulu,
  Credential saklama ön koşulu), ADR-005 "Security Follow-up / Connection
  Preconditions" bölümü, `MCP_AGENT_CAPABILITY_MATRIX.md` "Implementation
  status" sütunu (tüm satırlar "Planned").
- **Attack path / reproduction:** ADR-005 kabul edilip (Accepted) ardından
  audit logging tasarımı, capability validation veya credential storage
  onayı tamamlanmadan bir agent/insan gerçek bir MCP hesabına bağlanırsa,
  bu aksiyon hiçbir teknik mekanizma tarafından (mevcut runtime hook veya
  CI diff gate MCP tool call'larını denetlemez) yakalanmaz; bu, ADR-005'in
  kendisinin de açıkça kabul ettiği bir kalan risktir.
- **Impacted area:** Governance / MCP control plane; gelecekteki tüm MCP
  entegrasyonları.
- **Remediation requirement:** Yukarıdaki "Bağlantı Öncesi Zorunlu
  Kapılar" listesinin tamamı, ilgili MCP'ye özgü olarak kapatılmadan
  hiçbir gerçek bağlantı açılmamalıdır. Audit logging tasarımı ayrı bir
  teknik paket/ADR gerektirir (bkz. "Next Action").
- **Merge decision:** Bu policy dokümanı (ADR-005 ve bu follow-up kaydı)
  için **Conditional Go** — insan maintainer kabulüne bağlı. Gerçek MCP
  bağlantısı için **No-Go** — yukarıdaki zorunlu kapılar tamamlanana kadar
  geçerlidir.

## Next Action

ADR-005 için insan maintainer acceptance kararı alınır; ardından audit
logging tasarımı ayrı bir ADR veya tasarım paketi olarak başlatılır.

Bu non-trivial inceleme sonunda ilgili `docs/handoffs/REQ-XXX.md`
dokümanının güncellenmesi gerektiği not edilir; bu görev kapsamında bir
REQ-ID/handoff dosyası mevcut olmadığından bu güncelleme bu kayıt
tarafından yapılmamıştır — Delivery Lead'e bildirilmesi gerekir.
