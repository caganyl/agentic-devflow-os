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

QA tamamlanmadan ve gerekiyorsa security review yapılmadan:
- `task_graph_status` → `"ready_for_delivery"` yapılamaz
- `qa_sign_off: true` ve `security_review_complete: true` gate'leri beklenir

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

### 8. Sonuç Artefaktları

Delivery tamamlandığında şunları üret:

```
.devflow/reports/RUN-NNN-delivery-summary.md
.devflow/runs/RUN-NNN.json  (güncellendi)
```

Delivery summary şablonu:
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

Run state son güncellemesi:
```json
{
  "status": "awaiting_human_approval",
  "task_graph_status": "ready_for_delivery"
}
```

## Kısıtlar

- Context pack'te ham NotebookLM/Obsidian içeriği, token, URL veya credential bulunmaz.
- Aynı owned_path'e eşzamanlı paralel write task oluşturulamaz.
- Requirement ve AC olmadan implementation dispatch edilmez.
- Agent teams yalnızca bağımsız paralel işler için; sıralı iş akışında subagent kullan.
- Main merge, force push, deploy, migration, credential değişikliği insan onayı olmadan yapılmaz.
- Bu protokol native Claude Code agent team/subagent mekanizmasını yönlendirir;
  ayrı bir API/SDK dispatcher değildir.
