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
