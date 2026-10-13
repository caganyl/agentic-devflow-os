---
paths:
  - ".devflow/**"
  - ".claude/workflows/**"
---

# Task Routing Rules

Hangi task türünde hangi rollerin devreye gireceğinin tek kaynağı bu
dosyadır. Orkestratör ana oturumdur; `delivery-lead` yalnızca plan döner.

## Routing Tablosu

| Task türü             | Ana roller                                                                                 |
| --------------------- | ------------------------------------------------------------------------------------------ |
| Yeni ürün fikri       | Delivery Lead, Product Analyst, Design Reviewer, Solution Architect (fizibilite notu)      |
| Yeni feature          | Delivery Lead, Product Analyst, Contract Broker, Frontend, Backend, QA, Security, Docs Writer, Integration/Release (ADR eşiği varsa + Solution Architect, ADR Reviewer) |
| AI/RAG özelliği       | Delivery Lead, AI/Data Engineer, EvalOps Reviewer, Security Red Team, Backend Engineer     |
| Veri dashboard'u      | Delivery Lead, AI/Data Engineer, Design Reviewer, Backend Engineer, QA Automation         |
| Bug                   | Delivery Lead, QA Automation, ilgili domain engineer (Frontend/Backend/Database/AI)        |
| Güvenlik riski        | Security Red Team, Backend Engineer, Delivery Lead, gerekirse Database Engineer            |
| Release               | QA Automation, Security Red Team, Integration/Release                                      |
| Maliyet optimizasyonu | Delivery Lead, Solution Architect, AI/Data Engineer, Integration/Release                   |
| Projeye katılım / yeni proje kurulumu | Architecture Analyst, Docs Writer; greenfield'da Solution Architect, Backend, Frontend |
| Dokümantasyon (README, yorum) | Docs Writer                                                                     |

Teslimat sırası: implementation → QA → Security → Docs Writer →
Integration/Release → insan (merge).

## Minimum Rol Seçimi

Her task'te tüm roller çağrılmaz. Temel set tablodan gelir; şu faktörlere
göre rol eklenir veya çıkarılır:

1. **Bağımlılıklar** — hangi rol diğerinden önce gelir
2. **Risk seviyesi** — yüksek risk → daha fazla review rolü
3. **Ownership sınırları** — aynı dosya alanına paralel atama yapılmaz
4. **Mevcut artefaktlar** — contract kayıtlıysa Contract Broker atlanır

## Rol Seçimi Karar Ağacı

```
Task geldiğinde:
  1. Task türünü belirle (yukarıdaki tablo)
  1b. Implementation içeriyorsa onaylı mimari profil var mı?
     → Hayır, proje dolu: Architecture Analyst (project-onboarding workflow)
     → Hayır, proje boş: ana oturum insanla architecture-intake
  2. Requirement (REQ-ID) ve acceptance criteria var mı?
     → Hayır: Product Analyst (belirsizse önce ana oturum + insan: requirement-grilling)
  3. Mimari karar gerekiyor mu? (yalnızca şu durumlarda evet:
     yeni dış bağımlılık/servis, context'ler arası veri modeli/migration,
     auth/güvenlik sınırı, geriye uyumsuz public contract, geri alınması
     pahalı karar)
     → Evet: Solution Architect ADR yazar, adr-reviewer en fazla 2 turda karar verir
     → Hayır: ADR yok; gerekirse docs/decisions/ altına kısa karar notu
  4. Frontend + Backend paralel çalışacak mı? → Evet: önce Contract Broker
  5. AI/ML/LLM bileşen var mı? → Evet: EvalOps Reviewer
  6. Security-sensitive alan mı? → Evet: Security Red Team
  7. Kod veya klasör yapısı değişti mi? → Evet: Docs Writer (QA ve Security sonrası)
  8. Release hazırlığı mı? → Evet: Integration/Release
```

## Paralel Çalışma Kuralları

Paralel atama yalnızca ownership path'leri ayrık olduğunda yapılır.

**Paralel olabilir:**
- Frontend + Backend (contract kaydı sonrası, farklı dosya alanları)
- QA + Backend (test ve implementation, farklı dosya alanları)
- Design Reviewer + Implementation (review ve kod, farklı dosya alanları)

**Paralel olamaz:**
- Aynı modül veya dosyaya dokunacak iki implementation rolü
- Contract tanımlanmadan Frontend + Backend
- Security review tamamlanmadan release

## Approval Gate Noktaları

Her plan şu gate'leri belirtir:
- Contract kaydı (`record-contract-evidence`; frontend/backend paralel başlamadan önce)
- QA kabul kapısı (completion öncesi)
- Security review (release öncesi, risk sinyali varsa)
- İnsan onayı (main merge öncesi)
