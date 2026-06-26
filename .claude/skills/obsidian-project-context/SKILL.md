---
name: obsidian-project-context
description: Obsidian vault'tan yalnızca seçilmiş stratejik bağlamı kullanır; tüm vault değil, kişisel notlar değil.
agent: delivery-lead
triggers:
  - Stratejik ürün bağlamı gerektiğinde
  - Ürün yönü veya öncelik kararı alınırken
---

# Skill: Obsidian Project Context

## Amaç

Obsidian'ı kişisel bilgi desteği olarak kullan; proje gerçeği kaynağı olarak değil.
Yalnızca bilinçli seçilmiş notları, yalnızca ilgili agent'lara, özetlenmiş biçimde ilet.

## Temel Prensipler

1. Tüm vault içeriği agent'lara gönderilmez.
2. Kişisel veya hassas notlar task agent'larına dağıtılmaz.
3. Obsidian bilgisi teknik requirement ile karıştırılmaz.
4. Obsidian bağlamı "stratejik ipucu" olarak işaretlenerek kullanılır.
5. Obsidian ile Git'teki requirement çelişirse Git kazanır.

## Prosedür

### 1. Not Seçimi

Şu kriterlere göre hangi notun dahil edileceğine karar ver:
- Bu görevle doğrudan ilgili mi?
- Kişisel/hassas bilgi içeriyor mu? (İçeriyorsa hariç tut)
- Git'te zaten var olan bir bilgiyi mi tekrarlıyor? (İçeriyorsa hariç tut)
- Stratejik yön veya ürün önceliği hakkında bilgi veriyor mu? (Dahil edilebilir)

### 2. Stratejik Bağlam Formatı

Seçilen not özeti için şu formatı kullan:

```markdown
### Strategic Context (Obsidian)

**Konu:** [konu başlığı]
**Özet:** [1-3 cümle özet]
**Relevance:** [bu görevle neden ilgili?]
**Not:** "Bu bilgi Obsidian kişisel notlarından alınmıştır. Resmi kaynak için docs/ veya requirement bakın."
```

### 3. Ne Dahil Edilmez

Şunları hiçbir zaman agent'a iletme veya Git'e yazma:
- Kişisel günlük veya notlar
- Müşteri adları, PII veya hassas iş bilgisi
- API key, token veya credential
- Kişisel yorumlar ve eleştiriler
- Onaylanmamış stratejik kararlar

### 4. Teknik Requirement ile Karışıklık Önleme

Obsidian bilgisi şöyle etiketlenir: `[Obsidian - doğrulanmamış]`
Bu bilgi requirement'a dönüştürülmek isteniyorsa önce Product Analyst'e gönder.

## Örnek Akış

```
Obsidian notu: "Q3'te mobile öncelikli geliştirme yapılacak"
→ Seçim: Evet, stratejik ürün bağlamı
→ Kişisel veri yok: Evet
→ Git'te doğrulama: docs/product/roadmap.md'de var mı?
→ Varsa: canonical kaynak kullan; Obsidian notu ek bağlam
→ Yoksa: "Obsidian'da bahsedildi, doğrulanması gerekiyor" olarak işaretle
```
