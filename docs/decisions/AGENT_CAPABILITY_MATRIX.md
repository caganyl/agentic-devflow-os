# Agent Capability Matrix

Bu dosya, Agentic DevFlow OS içindeki rollerin hangi tür değişiklikleri yapabileceğini tanımlar.

| Agent | Doküman yazabilir | Uygulama kodu yazabilir | Test yazabilir | Review / reject | Branch / worktree |
|---|---:|---:|---:|---:|---:|
| Delivery Lead | Evet | Hayır | Hayır | Süreç kontrolü | Hayır |
| Product Analyst | Evet | Hayır | Hayır | Scope önerisi | Hayır |
| Solution Architect | Evet | Hayır | Hayır | Mimari öneri | Hayır |
| Contract Broker | Evet | Hayır | Contract test önerisi | Contract uyumu | Contract branch |
| Frontend Engineer | Evet | Frontend alanı | Frontend testleri | Hayır | Frontend branch |
| Backend Engineer | Evet | Backend alanı | API/unit testleri | Hayır | Backend branch |
| Database Engineer | Evet | Schema/migration | Migration testleri | Veri bütünlüğü | Database branch |
| AI/Data Engineer | Evet | AI/data alanı | Eval ve data testleri | Hayır | AI/Data branch |
| QA Automation | Evet | Test kodu ile sınırlı | Evet | Test sonucu | QA branch |
| Security Red Team | Rapor | Hayır | Proof-of-concept test | Evet | Read-only |
| Design Reviewer | Rapor | Hayır | Hayır | UX/a11y önerisi | Read-only |
| EvalOps Reviewer | Rapor | Eval kodu ile sınırlı | Evet | AI kalite sonucu | Eval branch |
| Integration / Release | Release dokümanı | Integration çözümü | CI doğrulama | Go/No-Go önerisi | integration/REQ-ID |

## Evrensel Kurallar

- Hiçbir agent `main` branch'e doğrudan yazamaz.
- Hiçbir agent kendi implementasyonunu tek başına approve edemez.
- Security Red Team bulguyu üretir; fix ilgili implementer tarafından yapılır.
- Integration Agent branch'leri birleştirir fakat `main` merge yapmaz.
- Production deploy, production migration ve secret işlemleri yalnızca insan onayıyla yapılır.
- Her non-trivial değişiklik REQ-ID, test kanıtı ve handoff ile bağlanır.
