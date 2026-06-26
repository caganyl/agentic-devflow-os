# REQ-003 — Local Canonical MCP Audit Runtime Foundation

## Requirement Metadata

| Alan               | Değer                                                                                         |
|--------------------|-----------------------------------------------------------------------------------------------|
| **Requirement ID** | REQ-003                                                                                       |
| **Status**         | Approved                                                                                      |
| **Title**          | Local Canonical MCP Audit Runtime Foundation                                                  |
| **Date**           | 2026-06-26                                                                                    |
| **Approval Date**  | 2026-06-26                                                                                    |
| **Author**         | Backend Engineer / QA Automation                                                              |
| **Branch**         | req-003-local-audit-runtime                                                                   |
| **AC Reference**   | `docs/product/acceptance-criteria/AC-REQ-003-local-canonical-mcp-audit-runtime-foundation.md` |

---

> **Durum notu:** Bu requirement `Approved` statüsündedir. Human maintainer bu
> exact scope için onay vermiştir: gerçek MCP bağlantısı olmadan, canonical MCP
> audit runtime'ın local deneysel foundation'ını oluştur.
>
> Bu requirement:
> - Gerçek MCP bağlantısı **yapmaz**.
> - `SEC-ADR-005-MCP-CONNECTION-PRECONDITIONS.md`'deki No-Go kapılarından
>   **hiçbirini kapatmaz**.
> - SQLite transaction acknowledgment yalnızca **application-level** durable
>   acknowledgment yaklaşımıdır; fiziksel storage garantisi iddia etmez.
> - Integrity chain ve append-only schema kontrolleri **tamper-proof değildir**
>   (external anchoring olmadan).
> - Gerçek MCP capability validation ayrıca yapılmalıdır.

---

## Problem

ADR-007, canonical MCP audit runtime için altı adlandırılmış bileşeni ve yaşam
döngüsü sırasını tanımlamıştır. Bu mimari bugüne kadar yalnızca sentetik
(test-only, offline, deterministik) bir harness ile doğrulanmıştır (REQ-001).
Gerçek MCP bağlantısından önce kullanılacak, ADR-007 bileşen sınırlarını
uygulayan ve contract uyumunu SQLite üzerinde doğrulayan bir local Python
foundation yoktur.

Bu boşluk şu soruları yanıtsız bırakmaktadır:

- ADR-007'nin altı bileşeni (Canonicalizer, Policy Gate, Event Builder, Audit
  Sink, Out-of-Band Writer + Durable Acknowledgment Gate, Failure Signal)
  arasındaki sorumluluk sınırları gerçek modül koduna nasıl yansır?
- SQLite ile application-level durable write acknowledgment pre-dispatch
  gate olarak çalışabilir mi?
- Append-only schema trigger'ları ile hash-chain integrity, local ortamda
  uygulanabilir mi?
- Pre-dispatch audit failure, dispatch'i operasyonel olarak engelliyor mu ve
  "persisted record var" iddiası üretmiyor mu?
- Post-dispatch audit write failure, dispatch'i retroaktif olarak iptal etmiyor
  mu ve audit-integrity incident üretiliyor mu?

REQ-003 bu soruları local experimental foundation ile yanıtlar. Bu çalışma
bir product feature değil; gerçek MCP bağlantısından önce kullanılacak
implementation foundation'dır.

---

## Scope

### Kapsam içi

- `src/mcp_audit_runtime/` Python modülü: altı ADR-007 bileşeninin local
  uygulaması.
- `tests/mcp_audit_runtime/` test paketi: sekiz kritik senaryo.
- Gerçek MCP dispatch yerine `simulated_dispatch` local callback.
- Python standard library dışında dependency yok.
- Mevcut tüm testlerin geçmeye devam etmesi.

### Kapsam dışı

- Gerçek MCP server bağlantısı veya herhangi bir dış servis bağlantısı.
- Network çağrısı, token, API key, credential, secret.
- `.claude/`, `.github/`, hook veya persistent config değişikliği.
- Mevcut ADR, contract veya security precondition dosyalarının değiştirilmesi.
- Git commit, push, PR veya branch işlemi.
- Tamper-proof audit (external anchoring olmadan mümkün değil).
- Gerçek MCP capability validation.

---

## Bileşenler

### 1. Identity Canonicalizer (`src/mcp_audit_runtime/canonicalizer.py`)

Ham `(raw_server, raw_tool)` çiftini local allowlist üzerinden canonical
etikete çevirir. Tanınmayan identity için yalnızca `mcp_server: "unclassified"`,
`mcp_tool: "unclassified"` sabit sentinel döner. Ham string hiçbir
log/event/failure-signal içine yazılmaz. Built-in araçlar bu bileşenden
geçmez.

### 2. Policy and Capability Gate (`src/mcp_audit_runtime/policy_gate.py`)

Canonical kimliği agent identity, tool capability ve environment boundary
koşullarıyla değerlendirerek `allow` veya `deny` kararı ve uygun
`failure_category` üretir. Bu modül audit sink'e doğrudan yazmaz.

### 3. Canonical Event Builder (`src/mcp_audit_runtime/event_builder.py`)

`MCP_AUDIT_EVENT_CONTRACT.md` kapalı 15 alanlı şeması ile tam ve geçerli
bir audit event dict üretir. Yeni alan eklenmez. Raw input/output, prompt,
URL, path, token, secret, header, exception text veya serbest metin kabul
etmez. Contract enum'ları dışına çıkmaz.

### 4. SQLite Local Audit Sink (`src/mcp_audit_runtime/sqlite_sink.py`)

Database path runtime parametresi olarak verilir. `PRAGMA synchronous=FULL`
kullanır. Normal application-level UPDATE/DELETE işlemlerini engelleyen schema
trigger'ları içerir. Event sırası için SHA-256 hash-chain uygular.

> **Kısıt:** Bu yapı external anchoring olmadan tamper-proof değildir.

### 5. Out-of-Band Writer + Durable Acknowledgment (`src/mcp_audit_runtime/writer.py`)

MCP kullanmaz, recursive çağrı üretmez. Başarılı synchronous SQLite transaction
commit, local application-level durable acknowledgment olarak ele alınır. Writer
hatasında dispatch başlamaz. Failure signal üretir (kapalı `failure_category`
enum, serbest metin yok, raw identity yok).

### 6. Lifecycle Orchestrator (`src/mcp_audit_runtime/orchestrator.py`)

`simulated_dispatch` local callback kullanır. Pre-dispatch akışı: identity
canonicalization → policy decision → PreToolUse event build → durable write
acknowledgment → yalnızca allow + ack ise dispatch. Pre-dispatch audit failure
durumunda dispatch başlamaz ve persisted canonical event varmış gibi iddia
edilmez.

---

## Güvenlik Sınırı

Bu requirement'ın tamamlanması `SEC-ADR-005-MCP-CONNECTION-PRECONDITIONS.md`
içindeki herhangi bir No-Go kapısını kapatmaz. Gerçek MCP bağlantısı için
tüm zorunlu kapılar açık kalmaya devam eder.

---

## İlgili Dokümanlar

| Doküman | Konum |
|---|---|
| ADR-005 | `docs/architecture/adr/ADR-005-mcp-tooling-control-plane.md` |
| ADR-006 | `docs/architecture/adr/ADR-006-mcp-audit-logging-and-runtime-enforcement.md` |
| ADR-007 | `docs/architecture/adr/ADR-007-canonical-mcp-audit-runtime-architecture.md` |
| Audit Event Contract | `docs/decisions/MCP_AUDIT_EVENT_CONTRACT.md` |
| Agent Capability Matrix | `docs/decisions/MCP_AGENT_CAPABILITY_MATRIX.md` |
| Security Preconditions | `docs/quality/security-reports/SEC-ADR-005-MCP-CONNECTION-PRECONDITIONS.md` |
| REQ-001 Handoff | `docs/handoffs/REQ-001.md` |
| REQ-002 Handoff | `docs/handoffs/REQ-002.md` |
