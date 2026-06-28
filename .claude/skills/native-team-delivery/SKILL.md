---
name: native-team-delivery
description: Delivery Lead için native Claude Code agent team dispatch protokolü ve task graph yönetimi. Run state'e göre subagent veya agent team seçer; güvenli paralel dispatch kurallarını uygular.
agent: delivery-lead
triggers:
  - launch --agent-teams ile başlatılmış bir run'da dispatch kararı gerektiğinde
  - Task graph oluşturulacağında
  - Paralel vs sıralı dispatch kararı verilecekken
  - native-team-delivery protokolü uygulanacağında
---

# Skill: Native Team Delivery

## Amaç

Delivery Lead'i run state'e dayalı olarak doğru dispatch modunu seçmeye,
task graph oluşturmaya ve Claude Code'un native subagent/agent team
kapasitesini güvenli biçimde kullanmaya yönlendir.

**Önemli:** Bu protokol Claude Code'un native agent team/subagent davranışını
yönlendirir. Ayrı bir API, SDK dispatcher veya external orchestrator değildir.

## Prosedür

### 1. Run State ve Politikayı Oku

```
.devflow/runs/RUN-NNN.json  →  execution_mode, requested_agent_teams
.devflow/policy.json         →  forbidden_git_operations, protected_branches
.devflow/source-register.json →  kullanılabilir kaynaklar
```

Kontrol listesi:
- `execution_mode` nedir? (`subagents` / `agent_teams`)
- `requested_agent_teams` true mu?
- `task_graph_status` ne durumda? (`not_started` / `in_progress` / `ready_for_delivery`)
- `context_pack_status` ne durumda?

### 2. Requirement ve Acceptance Criteria Doğrulaması

**Requirement (REQ-ID) ve acceptance criteria tanımlı değilse:**
- Implementation dispatch yapılmaz.
- Görev discovery veya analysis olarak kalır.
- Product Analyst devreye alınır.

```
REQ-ID eksikse → discovery/analysis task olarak işaretle, implementation dispatch etme
AC tanımlı değilse → implementation dispatch etme
```

### 3. Context Pack Oluştur

Context pack'i `.devflow/context/RUN-NNN-context-pack.md` konumuna yaz.

İzin verilen kaynaklar:
- Target repo canonical docs (`docs/`, `src/`, `.devflow/`)
- `.devflow/source-register.json` metadata (yalnızca label, freshness, relevance)
- Run objective ve acceptance criteria

**Kesinlikle dahil etme:**
- Ham NotebookLM/Obsidian içeriği
- Token, URL veya credential
- Framework repo'ya ait dosyalar

Context pack şablonu:
```markdown
# Context Pack: RUN-NNN

## Run Objective
[bir paragraf]

## Relevant Requirements
- REQ-ID: [özet]
  AC: [ilgili acceptance criteria listesi]

## Source Register Summary
- [kaynak label] — [freshness] — [relevance]

## Known Risks
- [risk]: [etki] — [azaltma]

## Out of Scope
- [kapsam dışı]
```

Context pack oluşturulunca run state'i güncelle:
`.devflow/runs/RUN-NNN.json` → `context_pack_status: "ready"`

### 4. Task Graph Oluştur

Task graph'ı `.devflow/plans/RUN-NNN-task-graph.md` konumuna yaz.
Aynı zamanda `.devflow/runs/RUN-NNN.json` içindeki `tasks` alanını güncelle.

Her task için zorunlu alanlar:

```json
{
  "task_id": "T-001",
  "title": "kısa görev başlığı",
  "owner_agent": "backend-engineer",
  "status": "pending",
  "depends_on": [],
  "owned_paths": ["src/api/", "tests/api/"],
  "required_artifacts": ["docs/contracts/api-v1.yaml"],
  "approval_gate": "contract_approved"
}
```

Task graph şablonu:

```markdown
# Task Graph: RUN-NNN

| task_id | title | owner_agent | depends_on | owned_paths | approval_gate |
|---------|-------|-------------|------------|-------------|---------------|
| T-001 | Contract üret | contract-broker | — | docs/contracts/ | contract_approved |
| T-002 | Backend impl | backend-engineer | T-001 | src/api/ | tests_passing |
| T-003 | Frontend impl | frontend-engineer | T-001 | src/ui/ | tests_passing |
| T-004 | Test yaz | qa-automation | T-002, T-003 | tests/ | qa_sign_off |
| T-005 | Security review | security-red-team | T-002, T-003 | — | security_review_complete |
```

**Task Graph Immutability — Kritik Kural:**

Task graph bir kez oluşturulup run'a bağlandıktan sonra, run aktif ise
`generate-task-graph --force` **kesinlikle kullanılmaz.** Aktif run, şu koşullardan birinin
geçerli olduğu run demektir:
- Herhangi bir task `"planned"` dışında bir statüde ise
- `.devflow/delegation-events/` altında event dosyası varsa
- Run state'te QA kanıtı (`qa_evidence`) kayıtlıysa
- Run'a artefakt bağlanmışsa

`--force` bu korumaları aşamaz; aktif run'da çağrılırsa exit code 16 ile reddedilir
ve run state dosyası değiştirilmez.

Farklı delivery routing gerekiyorsa mevcut run'ı değiştirme; yeni run başlat:
```bash
python3 scripts/devflow_operations.py create-run --target . --objective "..."
python3 scripts/devflow_operations.py generate-task-graph --target . --delivery-type ...
```

### 5. Dispatch Modu Seç

#### Agent Team Kullanma Koşulları (tümü sağlanmalı)

1. `execution_mode == "agent_teams"` (launch --agent-teams ile başlatıldı)
2. En az iki **bağımsız** araştırma, review veya ayrık dosya alanı görevi var
3. Aynı dosyaya eşzamanlı yazma planlanmıyor

Bu koşullardan herhangi biri sağlanmıyorsa → **subagent kullan.**

#### Paralel Write Yasağı

```
KURAL: Aynı owned_path'e eşzamanlı iki write task oluşturulamaz.

ÖRNEK — İZİN VERİLEMEZ:
  T-002 (backend-engineer) → owned_paths: ["src/"]
  T-003 (frontend-engineer) → owned_paths: ["src/"]  ← çakışma!

ÖRNEK — İZİN VERİLİR:
  T-002 (backend-engineer) → owned_paths: ["src/api/"]
  T-003 (frontend-engineer) → owned_paths: ["src/ui/"]  ← ayrık alan ✓
```

#### Team Mode İlk Paralel Faz Sınırlaması

Agent teams aktifken ilk paralel faz **yalnızca** şu işleri kapsayabilir:
- Analysis (requirement analizi, context synthesis)
- Contract review
- Test plan hazırlığı
- Security review (implementation sonrası)
- Bağımsız ayrık dosya alanlarına ayrılmış görevler

Implementation görevleri için contract onayı beklenir.

#### Dispatch Karar Tablosu

| Koşul | Dispatch Modu |
|-------|---------------|
| execution_mode = subagents | Sıralı / bağımsız custom subagent |
| execution_mode = agent_teams, bağımsız işler var, path çakışması yok | Agent team (paralel faz) |
| execution_mode = agent_teams, ancak işler sıralıysa | Custom subagent (sıralı) |
| Aynı path'e paralel write planlandı | Kesinlikle yasak |

### 6. QA ve Security Gate

```
Implementation → QA (qa-automation) → Security Review (security-red-team)
                                   ↓
                         task_graph_status: "ready_for_delivery"
```

QA tamamlanmadan delivery bitmiş sayılmaz.  Security gate için üç kavram ayrı tutulur:

| Alan | Anlamı |
|------|--------|
| `security_review_required` | Delivery type + objective sinyallerine göre belirlenir; generate-task-graph yazır |
| `security_review_status` | `not_applicable` \| `pending` \| `completed` |
| `security_gate_satisfied` | `required=false` → `true`; `required=true` + evidence → `true`; aksi → `false` |

**Kural:**
- `required=false` (low-risk, sinyalsiz `backend_utility` vb.) → `security_review_status: not_applicable`, `security_gate_satisfied: true`. Security Red Team çağrılmaz; scorecard'da "not applicable" yazar.
- `required=true` → security evidence olmadan `security_gate_satisfied: false`; `technical_readiness: not_ready`.

Applicability kararı `determine_security_applicability(delivery_type, objective)` fonksiyonuyla deterministik olarak üretilir. LLM yorumuna bırakılmaz.

### 7. İnsan Onayı Gerektiren İşlemler

Aşağıdaki işlemler **hiçbir koşulda** agent tarafından yapılamaz:

| İşlem | Neden |
|-------|-------|
| `git merge` / `git push --force` | Geçmiş yok eder |
| `git branch -d` / `git branch -D` | Başkasının çalışmasını silebilir |
| `git reset --hard` / `--soft` / `--mixed` | Geri alınamaz |
| `git clean -f`, `git checkout -- .`, `git restore .` | Uncommitted kayıp |
| `rm -rf` | Kalıcı silme |
| Production deploy | İnsan kararı gerektirir |
| Database migration (production) | Rollback riski |
| Credential veya secret değişikliği | Güvenlik sınırı |
| External MCP bağlantısı kurma | İnsan onayı gerektirir |
| Main branch merge | PR review + insan onayı |

### 8. Sonuç Artefaktları — Zorunlu Finalization Adımı

Delivery tamamlandığında canonical run state ve scorecard **yalnızca** yetkili CLI
komutuyla üretilir. Doğrudan Write/Edit ile `.devflow/runs/` veya `.devflow/reports/`
altına yazma **yasaktır** ve target guard tarafından engellenir.

**Adım 1 — QA kanıtını authoritative olarak kaydet:**
```bash
python3 scripts/devflow_operations.py record-qa-evidence \
  --target . \
  --total <toplam test sayısı> \
  --passed <geçen> \
  --failed <başarısız> \
  --exit-code <runner exit kodu> \
  --evidence-path <göreli kanıt yolu>   # opsiyonel
```

Bu komut `approval_gates.tests_passing` ve `approval_gates.qa_sign_off` değerlerini
otomatik olarak günceller. Doğrudan Write/Edit ile bu alanları yazmak yasaktır.

- Exit code 0 ve failed = 0 ise: `tests_passing: true`, `qa_sign_off: true`
- Exit code ≠ 0 veya failed > 0 ise: `tests_passing: false`, `qa_sign_off: false`

**Adım 2 — Canonical raporu üret:**
```bash
python3 scripts/devflow_operations.py generate-run-report --target .
```

Bu komut:
- `.devflow/runs/RUN-NNN.json` içindeki `native_delegation_observed`, `observed_delegation_count`,
  `delegation_evidence_status` ve `updated_at` alanlarını hook event'lerinden projekte eder.
- `.devflow/reports/RUN-NNN-report.json` canonical JSON raporu üretir.
- `.devflow/reports/RUN-NNN-scorecard.md` canonical Markdown scorecard üretir.

Canonical status değerleri (serbest string yasak):
- `delegation_evidence_status`: yalnızca `"observed"` | `"not_observed"` | `"unavailable"`
- `status` / `merge_recommendation`: yalnızca `"awaiting_human_approval"` | `"ready_for_human_merge"` | `"not_ready"`

Delivery summary taslağı (opsiyonel, `.devflow/context/` altına yazılabilir):
```markdown
# Delivery Summary: RUN-NNN

## Tamamlanan Görevler
- [T-NNN] [başlık] — [owner_agent] ✓

## Üretilen Artefaktlar
- [path]: [açıklama]

## Açık Gate'ler
- [ ] [gate adı]: [bekleyen neden]

## Bekleyen İnsan Kararları
- [ ] [karar]: [gerekçe]

## Bilinen Sınırlamalar
- [sınırlama]
```

Finalization tamamlandıktan sonra human approval göndermek için insan kullanıcıya
`.devflow/reports/RUN-NNN-scorecard.md` göster.

## 9. Delegation Evidence Honesty

Native delegasyonu raporlarken şu kavramlar kesinlikle ayrı tutulur:

| Kavram | Açıklama |
|--------|----------|
| `requested_execution_mode` | `--agent-teams` ile yapılandırılan çalışma modu (konfigürasyon) |
| `agent_teams_requested` | `--agent-teams` bayrağının verilip verilmediği (konfigürasyon) |
| `native_delegation_observed` | Gerçek SubagentStart/SubagentStop hook event'inin kaydedilip kaydedilmediği (gözlem) |
| `delegation_evidence_status` | `unavailable` / `not_observed` / `observed` (hook evidence durumu) |

### Kurallar

1. **Native hook event olmadan "delegated", "executed by role", "agent teams active" iddiası yapılmaz.**
2. `--agent-teams` yalnızca konfigürasyon kanıtıdır; gerçek dispatch gözlemi değildir.
3. Delegation event yoksa `delegation_evidence_status: "not_observed"` veya `"unavailable"` kullanılır.
4. Bir task'ın work-product'ı QA tarafından doğrulanmış olabilir; ancak atanan rolün gerçek native session'da çalıştığı iddiası yalnızca native hook event varsa yapılır.
5. Aynı run içinde üretilen acceptance criteria, bağımsız kullanıcı onayı gibi gösterilmez.
6. Aynı run içinde yazılan security checklist, ayrı security-agent session kanıtı olmadan "security-red-team executed" olarak gösterilmez.

### Minimum Artefact Politikası

Küçük, düşük riskli, local objective'ler için gereksiz rol, görev ve belge üretilmez.

**Risk sinyal yoksa (pure-Python utility, local tool, no API/auth/external):**
- `backend_utility` delivery tipi kullanılır: planning + implementation + qa + release
- Frontend, API contract design, ADR, standalone security report üretilmez

**Risk sinyali varsa (API surface, auth, payment, external service, deployment, schema migration):**
- Uygun delivery tipi (`new_feature`, `security_response`, vb.) seçilir
- Gerekli ek görevler deterministik sinyal eşleşmesiyle eklenir; LLM yorumuna bırakılmaz

Risk sinyali tespiti için `detect_objective_risk_signals()` fonksiyonu kullanılır.

## Kısıtlar

- Context pack'te ham NotebookLM/Obsidian içeriği, token, URL veya credential bulunmaz.
- Aynı owned_path'e eşzamanlı paralel write task oluşturulamaz.
- Requirement ve AC olmadan implementation dispatch edilmez.
- Agent teams yalnızca bağımsız paralel işler için; sıralı iş akışında subagent kullan.
- Main merge, force push, deploy, migration, credential değişikliği insan onayı olmadan yapılmaz.
- Bu protokol native Claude Code agent team/subagent mekanizmasını yönlendirir;
  ayrı bir API/SDK dispatcher değildir.
- Gerçek native dispatch olmayan yerde sahte delegation summary üretilmez.
- Inline delivery, başarısızlık değildir; ancak "delegation success" olarak raporlanamaz.
