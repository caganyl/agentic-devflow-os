---
name: task-routing
description: Task türü, risk, bağımlılık ve ownership üzerinden minimum agent setini seçer.
agent: delivery-lead
triggers:
  - Her yeni task veya REQ-ID geldiğinde
  - Mevcut plan güncellendiğinde
  - Scope değiştiğinde
---

# Skill: Task Routing

## Amaç

Her task için gereksiz rol çağırmadan doğru minimum agent setini belirle.

## Prosedür

### 1. Task Türünü Belirle

Şu soruları sor:
- Yeni ürün fikri mi? → `new-product-discovery` workflow
- Onaylı REQ ile yeni feature mi? → `feature-delivery` workflow
- AI/LLM/RAG bileşen var mı? → `ai-rag-delivery` workflow
- Veri görselleştirme veya dashboard mı? → `data-dashboard-delivery` workflow
- Bir bug düzeltmesi mi? → `bug-resolution` workflow
- Güvenlik riski veya incident mi? → `security-response` workflow
- Release hazırlığı mı? → `release-readiness` workflow
- Maliyet optimizasyonu mu? → `cost-optimization` workflow

### 2. Temel Rol Setini Al

`.claude/rules/task-routing.md` tablosundan task türüne uygun temel seti al.

### 3. Risk Faktörlerini Uygula

Her faktör için ilgili rolü ekle:

| Faktör | Eklenen Rol |
|--------|-------------|
| Mimari karar gerekiyor | Solution Architect |
| Yeni external sistem entegrasyonu | Security Red Team |
| AI/ML bileşen | EvalOps Reviewer |
| Database schema değişikliği | Database Engineer |
| UI içeriyor | Design Reviewer (varsa) |
| Production deploy gerekiyor | Integration/Release |
| Yüksek güvenlik riski | Security Red Team (zorunlu) |

### 4. Paralel Çalışma Kontrolü

Her iki role aynı dosya yoluna dokunacaksa paralel atama yapma.
Contract onayı olmadan Frontend + Backend'e paralel atama yapma.

### 5. Routing Kararını Belgele

```markdown
## Task Routing Kararı: [görev adı]

- Task türü: [tür]
- Temel roller: [liste]
- Eklenen roller ve gerekçe: [liste]
- Çıkarılan roller ve gerekçe: [liste]
- Paralel gruplar: [Frontend+Backend, QA+Implementation vb.]
- Sıralı bağımlılıklar: [A → B → C]
```

## Notlar

- Daha az rol = daha hızlı teslimat, ama gözden kaçan risk
- Daha fazla rol = daha kapsamlı coverage, ama koordinasyon maliyeti
- Delivery Lead her ikisi arasında bilinçli seçim yapar ve belgelenr
