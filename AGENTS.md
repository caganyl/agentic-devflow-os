# Agent Roster

Bu dosya Agentic DevFlow OS içindeki standart rolleri listeler.

## Çekirdek Roller

- **Delivery Lead** — plan, task routing, risk ve quality gate önerisi (dağıtmaz; orkestratör ana oturumdur)
- **Product Analyst** — PRD, requirement (REQ-XXX), acceptance criteria, kapsam tanımı
- **Solution Architect** — ADR (yalnızca eşik sağlanırsa), karar notu, trade-off analizi
- **Contract Broker** — OpenAPI, event, database ve shared type sözleşmeleri
- **ADR Reviewer** — bir ADR'ye tek turda VERDICT (en fazla 2 tur, sonrası insan kararı)
- **Architecture Analyst** — mevcut projeyi tarar, insan onayına giden mimari profil taslağını yazar

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

- **Integration/Release** — kanıt toplama, release scorecard, PR review triage, merge tavsiyesi
- **Governance Operations Author** — ownership & merge rehberi, handoff şablonu, operasyon prosedürleri
- **Docs Writer** — klasör README'leri, kök README'nin otomatik blokları, yalnızca yorum değişiklikleri ve handoff

## Çalışma Modeli

- Orkestratör ana oturumdur; Delivery Lead yalnızca plan döner.
- Implementation yalnızca ayrık ownership yollarında paralel yürür
  (Frontend + Backend contract kaydından sonra); çakışan işler sıraya alınır.
- Sıra: implementation → QA → Security → Docs Writer → Integration/Release → insan.
- Oturum kesilirse run durumu ve açık task listesi üzerinden devam edilir.

## Task Routing Özeti

Codex `.claude/rules/` okumaz; tablonun kaynağı `.claude/rules/task-routing.md`,
burada kısa kopyası durur.

| Task türü             | Ana roller |
| --------------------- | ---------- |
| Yeni ürün fikri       | Delivery Lead, Product Analyst, Design Reviewer, Solution Architect (fizibilite notu) |
| Yeni feature          | Delivery Lead, Product Analyst, Contract Broker, Frontend, Backend, QA, Security, Docs Writer, Integration/Release (ADR eşiği varsa + Solution Architect, ADR Reviewer) |
| AI/RAG özelliği       | Delivery Lead, AI/Data Engineer, EvalOps Reviewer, Security Red Team, Backend |
| Veri dashboard'u      | Delivery Lead, AI/Data Engineer, Design Reviewer, Backend, QA |
| Bug                   | Delivery Lead, QA, ilgili domain engineer |
| Güvenlik riski        | Security Red Team, Backend, Delivery Lead, (gerekirse) Database Engineer |
| Release               | QA, Security Red Team, Integration/Release |
| Maliyet optimizasyonu | Delivery Lead, Solution Architect, AI/Data Engineer, Integration/Release |
| Projeye katılım / yeni proje | Architecture Analyst, Docs Writer; greenfield'da Solution Architect, Backend, Frontend |
| Dokümantasyon         | Docs Writer |

## Tanımlar

Agent'lar `.claude/agents/`, skill'ler `.claude/skills/`, workflow'lar
`.claude/workflows/` altındadır. Katalog ve sistem anlatımı: `README.md`,
`docs/ARCHITECTURE.md`.

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

While working, run the smallest focused test or check that covers the changed behavior; run the full suite once before declaring the task done.

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
