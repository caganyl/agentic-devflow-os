---
name: task-routing
description: Bir task veya REQ için gereksiz rol çağırmadan minimum DevFlow rol setini, workflow'u ve paralel/sıralı grupları seçer; kararı kısa bir routing notu olarak belgeler.
when_to_use: Yeni bir task veya REQ geldiğinde, plan güncellenirken, kapsam değiştiğinde veya hangi ajanın çağrılacağı belirsizken.
---

# Skill: Task Routing

## Amaç

Her task için doğru minimum rol setini belirle. Routing tablosu ve karar
ağacının tek kaynağı `.claude/rules/task-routing.md`'dir; burada kopyası
tutulmaz, dosyayı oku.

## Prosedür

### 1. Workflow'u Seç

- Yeni ürün fikri → `new-product-discovery`
- Onaylı REQ ile yeni feature → `feature-delivery`
- AI/LLM/RAG bileşeni → `ai-rag-delivery`
- Dashboard veya veri görselleştirme → `data-dashboard-delivery`
- Bug → `bug-resolution`
- Güvenlik riski veya incident → `security-response`
- Release hazırlığı → `release-readiness`
- Maliyet optimizasyonu → `cost-optimization`
- Projeye katılım / onaylı mimari profil yok → `project-onboarding`
- Yalnızca README veya yorum → Docs Writer, workflow gerekmez

### 2. Temel Rol Setini Al ve Risk Faktörlerini Uygula

Temel seti `.claude/rules/task-routing.md` tablosundan al, karar ağacını
uygula. Ek roller:

| Faktör | Eklenen Rol |
|--------|-------------|
| ADR eşiği sağlanıyor | Solution Architect + ADR Reviewer |
| Yeni dış sistem entegrasyonu veya yüksek güvenlik riski | Security Red Team |
| AI/ML bileşen | EvalOps Reviewer |
| Database schema değişikliği | Database Engineer |
| UI değişikliği | Design Reviewer |
| Kod veya klasör yapısı değişti | Docs Writer (QA ve Security sonrası) |
| Merge öncesi kanıt/scorecard | Integration/Release |

### 3. Paralel Çalışma Kontrolü

Aynı dosya yoluna dokunacak iki role paralel atama yapma. Contract kaydı
olmadan Frontend + Backend'e paralel atama yapma.

### 4. Routing Kararını Belgele

```markdown
## Task Routing Kararı: [görev adı]
- Workflow: [ad] · delivery type: [tip]
- Roller: [liste] · eklenen/çıkarılan ve gerekçe: [liste]
- Paralel gruplar: [...] · sıralı bağımlılıklar: [A → B → C]
```

Daha az rol daha hızlıdır ama risk kaçırabilir; daha fazla rol koordinasyon
maliyetidir. Seçim bilinçli yapılır ve gerekçesi bu notta belgelenir.
