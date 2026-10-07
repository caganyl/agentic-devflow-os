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

### 4b. Kademeli Bağlam (Iterative Retrieval)

Esin kaynağı: affaan-m/everything-claude-code `iterative-retrieval` fikri.

Context pack'i "her şey olsun" diye şişirme. Önce en dar paketi ver; alt ajan
eksik görürse ister:

1. İlk paket: görev özeti, ilgili AC maddeleri, seam/contract yolları,
   `docs/product/GLOSSARY.md` terimleri, kapsam dışı. 300-500 kelime.
2. Alt ajan eksik bağlam görürse işi durdurmadan sonucunun başına şu bloğu
   koyar (en fazla 3 kalem, her biri yol + bölüm):
   ```text
   CONTEXT_REQUEST:
   - docs/contracts/openapi/orders.yaml#/paths/~1orders/post
   - src/Orders/Application/CreateOrderHandler.cs (yalnızca Handle metodu)
   ```
3. Orkestratör yalnızca istenen bölümleri ekleyip görevi yeniden verir.
4. En fazla 2 retrieval turu. Üçüncü istek, görev tanımının yanlış
   bölündüğünün işaretidir; görevi küçült veya insana sor.

### 4c. Yerel Kod Haritası (pilot, opsiyonel)

Büyük repolarda (özellikle .NET çözümleri) keşif için yerel bir kod
haritası aracı (ör. Graphify) pilot olarak denenebilir. Koşullar:

- Yalnızca yerel AST/kod modu kullanılır; doküman veya kaynak kod içeriği
  onaysız bir dış LLM sağlayıcısına gönderilmez.
- Harita çıktısı canonical kaynak değildir; source register'da
  `confidence: draft` olarak kaydedilir.
- Context pack'e haritanın tamamı değil, ilgili modülün özeti girer.
- Pilotun ölçütü: aynı görevde keşif için okunan dosya sayısı ve token.

### 5. Dağıtım Kararı

`.claude/rules/context-distribution.md` kurallarına göre hangi agent'a
ne kadar bağlam verileceğine karar ver.

## Notlar

- Raw doküman yerine kaynak referanslı özet ver
- Hassas veri (secret, kişisel not) context pack'e ekleme
- Eski (stale) kaynak varsa "doğrulanması gerekiyor" işareti koy
