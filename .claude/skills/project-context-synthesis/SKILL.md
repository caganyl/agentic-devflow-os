---
name: project-context-synthesis
description: Bir alt ajana görev vermeden önce local repo, seçilmiş dokümanlar ve source register'dan kısa, kaynak referanslı bir context pack (300-500 kelime) üretir; kademeli bağlam (CONTEXT_REQUEST) kuralını uygular.
when_to_use: Alt ajana görev atanmadan önce, uzun süredir dokunulmamış bir REQ'e devam edilirken veya bir ajan CONTEXT_REQUEST döndüğünde. Context pack'i ana oturum yazar.
---

# Skill: Project Context Synthesis

## Amaç

İlgili ajana ihtiyacından fazla değil, tam ihtiyacı kadar bağlam ver. Context
pack'i ve source register'ı ana oturum yazar; `delivery-lead` yalnızca hangi
bağlamın gerektiğini planında önerir.

## Prosedür

### 1. Kaynakları Seç

Yalnızca ilgili olanlar:

```
- docs/product/requirements/REQ-XXX.md (yalnızca ilgili AC maddeleri)
- docs/architecture/adr/ (indeks + ilgili ADR'nin Status ve Decision bölümü)
- docs/contracts/ (yalnızca dokunulan endpoint/event/tablo)
- docs/handoffs/REQ-XXX.md (yalnızca son "Sonraki Adım")
- docs/architecture/profile/ARCHITECTURE_PROFILE.md (rolün bölümü)
- ilgili kaynak modül ve testler
```

Her kaynak için güven düzeyi: canonical / draft / stale. Stale kaynak
"doğrulanması gerekiyor" diye işaretlenir.

### 2. Dış Kaynaklar (yalnızca bağlıysa)

- NotebookLM bağlıysa `notebooklm-grounded-retrieval` skill'ini uygula:
  yalnızca evidence özeti (bulgu, kaynak, güven, "doğrulanması gerekiyor").
- Obsidian bağlıysa `obsidian-project-context` skill'ini uygula: yalnızca
  seçilmiş stratejik not özeti, tüm vault değil.
- Bağlı değillerse bu adımı atla; context pack bunlar olmadan tamdır.

### 3. Source Register

Kaynak metadata'sı `.devflow/source-register.json`'a yazılır (şablon:
`.claude/templates/source-register.yaml`). Ham içerik, URL, token veya
credential yazılmaz; yasak alanları CLI reddeder (exit 10).

### 4. Context Pack Üret

Tek format: `.claude/templates/context-pack.md`. Konum:
`.devflow/context/RUN-NNN-<rol>.md`. 300-500 kelime, kaynak yolu + bölüm,
kapsam dışı açıkça yazılır. Rol başına ne verileceği:
`.claude/rules/context-distribution.md`.

### 4b. Kademeli Bağlam

Esin kaynağı: affaan-m/everything-claude-code `iterative-retrieval` fikri.

1. İlk paket en dardır: görev özeti, ilgili AC, seam/contract yolları,
   `docs/product/GLOSSARY.md` terimleri, kapsam dışı.
2. Alt ajan eksik görürse sonucunun başına yazar (en fazla 3 kalem):
   ```text
   CONTEXT_REQUEST:
   - docs/contracts/openapi/REQ-012.yaml#/paths/~1orders/post
   - src/Orders/Application/CreateOrderHandler.cs (yalnızca Handle metodu)
   ```
3. Yalnızca istenen bölümleri ekleyip görevi yeniden ver.
4. En fazla 2 retrieval turu. Üçüncü istek görevin yanlış bölündüğünün
   işaretidir; görevi küçült veya insana sor.

### 4c. Yerel Kod Haritası (pilot, opsiyonel)

Büyük repolarda (özellikle .NET çözümleri) Graphify tabanlı yerel kod
haritası kullanılabilir (`agent-common.md` "Kod Haritası"). İnsan bir kez
`claude-devflow map` ile kurar; araç yalnızca yerel AST modunda çalışır,
içerik dış LLM'e gönderilmez.

- Context pack'e haritanın tamamı veya GRAPH_REPORT girmez. Göreve dokunan
  sembol için `affected` ve gerekirse `explain` çıktısının ilgili satırları
  girer, kaynak olarak `code-map` ve `confidence: draft` ile.
- `status` "eski" diyorsa context pack'e bunu yaz veya önce insandan
  `claude-devflow map` iste.
- Bir CONTEXT_REQUEST "X'i kim çağırıyor?" türündeyse dosya eklemeden önce
  `affected`/`path` ile cevapla; yalnızca gerçekten okunması gereken
  dosyaları ekle.

## Notlar

- Raw doküman yerine kaynak referanslı özet ver.
- Hassas veri (secret, kişisel not) context pack'e girmez.
