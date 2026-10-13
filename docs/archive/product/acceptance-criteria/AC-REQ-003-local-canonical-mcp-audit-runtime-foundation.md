# AC-REQ-003 — Acceptance Criteria: Local Canonical MCP Audit Runtime Foundation

## Metadata

| Alan               | Değer                                                                                          |
|--------------------|------------------------------------------------------------------------------------------------|
| **REQ ID**         | REQ-003                                                                                        |
| **AC Dokümanı**    | AC-REQ-003                                                                                     |
| **Status**         | Approved                                                                                       |
| **Date**           | 2026-06-26                                                                                     |
| **Approval Date**  | 2026-06-26                                                                                     |
| **REQ Referansı**  | `docs/product/requirements/REQ-003-local-canonical-mcp-audit-runtime-foundation.md`            |

---

> **Önemli:** Bu AC dokümanı yalnızca local deneysel foundation'ın davranışını
> tanımlar. Gerçek MCP bağlantısı, production hook implementasyonu, credential
> veya production audit altyapısı bu kriterlerin kapsamı dışındadır.

---

## AC-001 — Canonical Allow Lifecycle

**Başlık:** Canonical allow yolunda PreToolUse yazılır, dispatch çalışır,
PostToolUse success yazılır.

**Given:** Allowlist'te tanımlı bir `(raw_server, raw_tool)` çifti, izinli
bir `agent_type` ve geçerli bir `environment_scope`.

**When:** `run_lifecycle()` çağrılır; `simulated_dispatch` callback başarıyla
tamamlanır.

**Then:**
- `dispatch_attempted = True`
- `pre_event_written = True`
- `post_event_written = True`
- PreToolUse event: `policy_decision="allow"`, `outcome="success"`, `failure_category=null`
- PostToolUse event: `event_phase="PostToolUse"`, `policy_decision="allow"`,
  `outcome="success"`, `failure_category=null`
- Her iki event de SQLite sink'te kayıtlıdır.
- `failure_signal = None`, `audit_integrity_incident = False`

---

## AC-002 — Unclassified Identity → Blocked

**Başlık:** Tanınmayan identity için PreToolUse `blocked` kaydı yazılır,
dispatch çalışmaz.

**Given:** Allowlist'te bulunmayan bir `(raw_server, raw_tool)` çifti.

**When:** `run_lifecycle()` çağrılır.

**Then:**
- `dispatch_attempted = False`
- `pre_event_written = True`
- PreToolUse event: `mcp_server="unclassified"`, `mcp_tool="unclassified"`,
  `policy_decision="deny"`, `outcome="blocked"`,
  `failure_category="unclassified_tool_identity"`
- Ham `raw_server` ve `raw_tool` stringleri event payload'ının hiçbir alanında
  bulunmaz.
- `failure_signal = None` (çünkü PreToolUse başarıyla yazıldı).

---

## AC-003 — Capability/Policy Mismatch → Denied

**Başlık:** Capability veya policy uyuşmazlığında PreToolUse `denied` kaydı
yazılır, dispatch çalışmaz.

**Given:** Allowlist'te tanımlı bir `(raw_server, raw_tool)` çifti; ancak
`agent_type` bu tool için izinli değil.

**When:** `run_lifecycle()` çağrılır.

**Then:**
- `dispatch_attempted = False`
- `pre_event_written = True`
- PreToolUse event: canonical `mcp_server` ve `mcp_tool` değerleri (sentinel
  değil), `policy_decision="deny"`, `outcome="denied"`,
  `failure_category="capability_mismatch"`
- `failure_signal = None` (çünkü PreToolUse başarıyla yazıldı).

---

## AC-004 — Pre-Dispatch Writer Failure → No Dispatch

**Başlık:** Pre-dispatch writer başarısız olduğunda dispatch çalışmaz ve
persisted record varmış gibi iddia edilmez.

**Given:** Herhangi bir geçerli lifecycle girdisi; ancak audit sink'in
`write_event()` metodu başarısız döner (False).

**When:** `run_lifecycle()` çağrılır.

**Then:**
- `dispatch_attempted = False`
- `pre_event_written = False`
- `failure_signal` is not None; `failure_category` kapalı enum değeri taşır.
- `audit_integrity_incident = False`
- `failure_signal` raw identity, exception text veya serbest metin içermez.

---

## AC-005 — Tool Execution Failure → PostToolUseFailure + tool_error

**Başlık:** Tool execution başarısız olduğunda PostToolUseFailure event yazılır.

**Given:** Canonical allow; ancak `simulated_dispatch` callback exception fırlatır.

**When:** `run_lifecycle()` çağrılır.

**Then:**
- `dispatch_attempted = True`
- `post_event_written = True`
- PostToolUseFailure event: `event_phase="PostToolUseFailure"`,
  `policy_decision="allow"`, `outcome="failure"`, `failure_category="tool_error"`
- Exception metni event payload'ının hiçbir alanında bulunmaz.
- `audit_integrity_incident = False`

---

## AC-006 — Post-Dispatch Writer Failure → No Rollback, Incident

**Başlık:** Post-dispatch audit write başarısız olduğunda execution geri
alınmaz; audit integrity incident üretilir.

**Given:** Canonical allow, dispatch başarılı; ancak PostToolUse event yazımı
başarısız.

**When:** `run_lifecycle()` çağrılır.

**Then:**
- `dispatch_attempted = True`
- `pre_event_written = True`
- `post_event_written = False`
- `audit_integrity_incident = True`
- `failure_signal` is not None (audit-integrity incident sinyali).
- Dispatch geri alınmaz, cancel edilmez.
- Yeni simulated dispatch başlatılmaz.

---

## AC-007 — Forbidden Raw Fields Not Present

**Başlık:** Event payload'ında yasak raw alanlar bulunmaz.

**Given:** Herhangi bir lifecycle çalıştırması (allow, denied, blocked, failure).

**When:** Üretilen event dict'ler incelenir.

**Then:**
- Hiçbir event dict 15 alandan fazla field içermez.
- `note`, `notes`, `message`, `error_message`, `details`, `description`,
  `context`, `metadata`, `debug`, `raw_input`, `raw_output`, `prompt`, `url`,
  `header`, `file_path`, `exception`, `reason`, `token`, `credential`,
  `api_key`, `secret`, `pii`, `tool_input`, `tool_output` gibi yasak alan
  adları hiçbir event'te bulunmaz.
- Event field değerleri bilinen synthetic forbidden marker değerleri içermez
  (raw payload, raw identity, exception text, URL, token, PII).

---

## AC-008 — SQLite Schema Trigger Blocks UPDATE/DELETE

**Başlık:** SQLite schema trigger'ları application-level UPDATE ve DELETE
işlemlerini engeller.

**Given:** En az bir event yazılmış bir SQLite audit database.

**When:** Doğrudan sqlite3 bağlantısı üzerinden UPDATE ve DELETE denemeleri yapılır.

**Then:**
- UPDATE denemesi bir sqlite3 exception ile başarısız olur.
- DELETE denemesi bir sqlite3 exception ile başarısız olur.
- Exception mesajı "audit_events: updates are not permitted" veya
  "audit_events: deletes are not permitted" içerir.

---

## Genel Kısıtlar

Tüm AC'ler için geçerli:

- Testler yalnızca Python standard library kullanır.
- Testlerde yalnızca geçici dizin (`tempfile.mkdtemp`) kullanılır; repo
  içine database dosyası yazılmaz.
- Gerçek MCP bağlantısı, network çağrısı, token, credential veya dış servis
  kullanılmaz.
- Bu AC'lerin karşılanması `SEC-ADR-005-MCP-CONNECTION-PRECONDITIONS.md`
  içindeki hiçbir No-Go kapısını kapatmaz.
