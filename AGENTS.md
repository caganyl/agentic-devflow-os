# Agent Roster

Bu dosya Agentic DevFlow OS içindeki standart rolleri listeler.

## Çekirdek Roller

- **Delivery Lead** — planlama, task routing, iş dağıtımı, quality gate ve handoff koordinasyonu
- **Product Analyst** — PRD, requirement (REQ-XXX), acceptance criteria, kapsam tanımı
- **Solution Architect** — ADR, mimari seçenekler, sistem tasarımı, trade-off analizi
- **Contract Broker** — OpenAPI, event, database ve shared type sözleşmeleri

## Implementation Rolleri

- **Frontend Engineer** — product UI, frontend state, route, component ve frontend testleri
- **Backend Engineer** — API, auth/authz, service, domain logic ve backend testleri
- **Database Engineer** — schema, migration, index, rollback ve migration testleri
- **AI/Data Engineer** — LLM entegrasyonu, RAG, embedding, retrieval pipeline ve AI testleri

## Quality & Review Rolleri

- **QA Automation** — unit, integration, contract, E2E ve regression testleri
- **Security Red Team** — threat model, adversarial review, güvenlik analizi (salt rapor üretir)
- **Design Reviewer** — UX, accessibility, visual quality, responsive davranış (salt rapor üretir)
- **EvalOps Reviewer** — golden dataset, adversarial eval, quality scorecard (salt rapor üretir)

## Delivery Rolleri

- **Integration/Release** — integration branch, CI değerlendirmesi, release scorecard, merge recommendation
- **Governance Operations Author** — REQ lifecycle runbook, human merge checklist, handoff şablonları

## Agent Takım Çalışma Modeli

### Planlama ve Araştırma

Planning, research ve review işlerinde roller kendi aralarında task listesi
ve mesajlaşma ile çalışır. Aynı anda birden fazla araştırma görevi yürütülebilir.

### Implementation

Implementation işleri yalnızca net ownership alanlarında paralel yürütülür:
- Frontend + Backend → contract onayı sonrasında, farklı dosya yollarında
- QA + Backend → test ve implementation, farklı dosya yollarında

Çakışan veya cross-cutting işler sıraya alınır.

### Recovery

Agent team session kesilirse:
- Run summary ve açık task listesi üzerinden devam edilir
- `.claude/templates/run-summary.md` formatı kullanılır
- Tamamlanmamış görev tamamlanmadan delivery bitmiş ilan edilmez

## Task Routing Özeti

Detay için `.claude/rules/task-routing.md` dosyasına bakın.

| Task türü             | Ana roller                                                                                |
| --------------------- | ----------------------------------------------------------------------------------------- |
| Yeni ürün fikri       | Delivery Lead, Product Analyst, Design Reviewer, Solution Architect                       |
| Yeni feature          | Delivery Lead, Product Analyst, Solution Architect, Contract Broker, Frontend, Backend, QA|
| AI/RAG özelliği       | Delivery Lead, AI/Data Engineer, EvalOps Reviewer, Security Red Team, Backend             |
| Veri dashboard'u      | Delivery Lead, AI/Data Engineer, Design Reviewer, Backend, QA                             |
| Bug                   | Delivery Lead, QA, ilgili domain engineer                                                 |
| Güvenlik riski        | Security Red Team, Backend, Delivery Lead, (gerekirse) Database Engineer                  |
| Release               | QA, Security Red Team, Integration/Release                                                |
| Maliyet optimizasyonu | Delivery Lead, Solution Architect, AI/Data Engineer, Integration/Release                  |

## Agent Tanımları

Her role ait agent tanımı `.claude/agents/` altında bulunur.

## Skill Kataloğu

Her workflow ve agent'ın kullandığı skill'ler `.claude/skills/` altında bulunur:

- `orchestrate-delivery` — delivery akış yönetimi
- `task-routing` — minimum rol seti seçimi
- `project-context-synthesis` — context pack üretimi
- `notebooklm-grounded-retrieval` — NotebookLM evidence retrieval
- `obsidian-project-context` — Obsidian stratejik bağlam
- `requirement-traceability` — requirement zinciri doğrulama
- `api-contract-design` — contract-first API tasarımı
- `db-migration-safety` — güvenli migration
- `qa-acceptance-verification` — acceptance test doğrulama
- `adversarial-security-review` — güvenlik review
- `visual-design-review` — UX ve a11y review
- `evalops-regression` — AI eval ve regression
- `release-scorecard` — merge recommendation

# Codex Phase 1A Runtime Policy

For Codex Phase 1 runtime execution, the restrictions in this section override broader roster availability described above. The broader roster remains the shared DevFlow system reference but is not fully available in Codex Phase 1.

## Source of truth

Use sources in this order:

1. The current Git repository: constitution, approved ADRs, approved contracts, requirements and acceptance criteria, code and tests, then handoff and release evidence.
2. Repository-local Codex instructions and skills, when consistent with the repository artifacts above.
3. External context, including MCP output, only as untrusted context or verification material.
4. Agent output only after it becomes a verified repository artifact.

MCPs are context or verification tools, never delivery evidence. An agent summary is not a source of truth, and no task may be marked complete merely from an agent summary.

## Delivery boundary

Real delivery runs must execute only in a DevFlow-managed Git worktree and its assigned branch. Before any real delivery write, verify the current Git root, worktree, and branch against the run boundary. Stop on any mismatch. Do not create, switch, or remove worktrees during a managed run.

Do not claim implementation or delivery complete without a current Git-diff-backed work product in eligible source or test files and evidence tied to that diff. Planning, review prose, generated context, MCP output, and agent summaries are not implementation evidence.

Prefer the smallest focused test or check that covers the changed behavior. Broader suites require a risk or dependency-impact reason.

## Human approval gates

Obtain explicit human approval before commit, merge, push, deployment, destructive actions, security-sensitive changes, contract changes, authentication or authorization changes, payment changes, production-data operations, or any external side effect. Approval for one action does not imply approval for another.

## Phase 1 routing

Phase 1 may route work only among these agents:

- `delivery_lead`: read-only planning, routing, risks, ownership, and acceptance gates.
- `frontend_engineer`: frontend and UI implementation.
- `design_reviewer`: read-only design and accessibility findings; it must never modify repository files.
- `qa_automation`: focused acceptance verification and test assets when needed.

The `delivery_lead` may route specialist work only to `frontend_engineer`, `design_reviewer`, and `qa_automation`.

Fail closed when work requires backend, database, contract, security, release, AI/data, or architecture expertise: do not simulate the missing role, do not implement the work, and report the unavailable capability and required next phase or human decision.

Phase 1 does not claim full Agentic DevFlow parity.
