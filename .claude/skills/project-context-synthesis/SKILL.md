---
name: project-context-synthesis
description: Local repo, seçilmiş dokümanlar ve source register üzerinden kısa ve kaynak referanslı context pack üretir.
agent: delivery-lead
triggers:
  - Yeni bir task başlatılmadan önce
  - Uzun süredir çalışılmamış bir REQ'e devam edilirken
  - Agent'a görev atanmadan önce
---

# Skill: Project Context Synthesis

## Amaç

İlgili agent'a ihtiyacından fazla değil, tam ihtiyacı kadar bağlam ver.

## Prosedür

### 1. Kaynak Listesini Oluştur

Şu kaynakları kontrol et (hepsini değil, ilgili olanları):

```
- docs/product/requirements/REQ-XXX.md
- docs/architecture/adr/
- docs/contracts/
- docs/handoffs/REQ-XXX.md
- src/ (ilgili modül)
- tests/ (ilgili test)
```

Her kaynak için not al:
- Son değişiklik tarihi
- İlgililik derecesi (high/medium/low)
- Güven seviyesi (canonical/draft/stale)

### 2. Source Register'ı Güncelle

`.claude/templates/source-register.yaml` formatında kayıt tut:

```yaml
sources:
  - id: req-xxx
    path: docs/product/requirements/REQ-XXX.md
    type: requirement
    relevance: high
    confidence: canonical
    last_verified: "YYYY-MM-DD"
  - id: contract-api
    path: docs/contracts/api-v1.yaml
    type: contract
    relevance: high
    confidence: approved
    last_verified: "YYYY-MM-DD"
```

### 3. Evidence Summary Ekle (NotebookLM kullanılıyorsa)

```markdown
### Evidence from NotebookLM
- Finding: [bulgu]
  Source: [doküman adı]
  Confidence: high/medium/low
  Note: "doğrulanması gerekiyor — canonical değil"
```

### 4. Context Pack Üret

`.claude/templates/context-pack.md` formatında üret:
- 300-500 kelimeyi geçme
- Kaynak referansı içer
- Kapsam dışı olanları açıkça belirt

### 5. Dağıtım Kararı

`.claude/rules/context-distribution.md` kurallarına göre hangi agent'a
ne kadar bağlam verileceğine karar ver.

## Notlar

- Raw doküman yerine kaynak referanslı özet ver
- Hassas veri (secret, kişisel not) context pack'e ekleme
- Eski (stale) kaynak varsa "doğrulanması gerekiyor" işareti koy
