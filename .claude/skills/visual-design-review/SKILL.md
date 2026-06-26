---
name: visual-design-review
description: UI/UX, tipografi, spacing, layout hiyerarşisi, responsive davranış, accessibility, interaction feedback ve "AI-generated generic UI" riskleri için review yapar.
agent: design-reviewer
triggers:
  - UI içeren her feature tamamlandığında
  - Merge öncesi design/a11y review gerektiğinde
  - Tasarım kararı tartışmalı olduğunda
---

# Skill: Visual Design Review

## Amaç

Kullanıcının ekranına bakan gözler olarak değerlendir. Teknik olarak çalışan
ama kullanılması zor veya görsel açıdan tutarsız arayüzleri tespit et.

## Prosedür

### 1. Bilgi Mimarisi ve Hiyerarşi

```
- [ ] Kullanıcı nereye bakması gerektiğini anlıyor mu?
- [ ] En önemli eylem veya bilgi görsel olarak öne çıkıyor mu?
- [ ] İçerik gruplaması mantıklı mı?
- [ ] Başlık hiyerarşisi (h1 → h2 → h3) tutarlı mı?
```

### 2. Tipografi ve Spacing

```
- [ ] Font boyutları okunabilir mi? (min 14px gövde metni)
- [ ] Line-height yeterli mi? (1.4-1.6 arası)
- [ ] Metin rengi kontrast oranı yeterli mi? (WCAG AA: 4.5:1 normal, 3:1 büyük metin)
- [ ] Spacing tutarlı mı? (tasarım token'larına uyuyor mu?)
- [ ] Margin ve padding tutarsızlığı var mı?
```

### 3. Responsive Davranış

```
- [ ] Mobile (320-480px) görünüm bozulmuyor mu?
- [ ] Tablet (768-1024px) düzgün mü?
- [ ] Desktop'ta gereksiz boşluk yok mu?
- [ ] Tablo ve grafik mobile'da okunabilir mi?
- [ ] Overflow sorunları var mı?
```

### 4. Accessibility (a11y)

```
- [ ] Tüm etkileşimli öğeler keyboard ile erişilebilir mi?
- [ ] Focus indicator görünür mü?
- [ ] Alt text resimler için var mı?
- [ ] ARIA label'lar anlamlı mı?
- [ ] Form alanları label ile eşleşiyor mu?
- [ ] Renk tek başına bilgi taşımıyor mu?
- [ ] Hata mesajları ekran okuyucuya açık mı?
```

### 5. Durum Yönetimi (State Coverage)

```
- [ ] Loading state tasarımı var mı ve uygun mu?
- [ ] Empty state tasarımı var mı ve bilgilendirici mi?
- [ ] Error state kullanıcıya ne yapacağını söylüyor mu?
- [ ] Success state feedback veriliyor mu?
- [ ] Permission denied state açıklayıcı mı?
```

### 6. Interaction Feedback

```
- [ ] Buton tıklanabilir olduğu görsel olarak anlaşılıyor mu?
- [ ] Hover ve active state'ler var mı?
- [ ] Disabled state görsel olarak farklı mı?
- [ ] Asenkron işlemlerde kullanıcı "bir şey oluyor" biliyor mu?
```

### 7. "AI-Generated Generic UI" Riski

LLM ile üretilen UI'larda özellikle şunlara dikkat et:
```
- [ ] Renk paleti ürünle tutarlı mı? (Şablondan kalan mavi-gri değil mi?)
- [ ] Component boyutları ve spacing stash değerleri mi yoksa keyfi mi?
- [ ] İkon seti tutarlı mı? (karışık icon library yok mu?)
- [ ] Buton stilleri uygulamada kullanılan sistemle örtüşüyor mu?
- [ ] Gereksiz veya içeriksiz placeholder metin kaldı mı?
```

## Bulgu Formatı

```markdown
### Design Finding: [başlık]

**Severity:** Blocker / Major / Minor / Suggestion
**Kategori:** a11y / Responsive / Tipografi / Spacing / State / Interaction / Tutarlılık
**Etkilenen bileşen:** [sayfa veya component adı]
**Açıklama:** [sorun ve neden önemli]
**Ekran görüntüsü/referans:** [varsa]
**Öneri:** [nasıl düzeltilmeli]
```

## Review Kararı

- **Blocker:** a11y ihlali, kritik responsive bozulma, state eksikliği — düzeltilmeden merge yapılmaz
- **Major:** Önemli tutarsızlık veya kullanılabilirlik sorunu — plan içinde takip et
- **Minor:** Küçük hizalama veya spacing — sonraki iterasyonda
- **Suggestion:** Fikir veya alternatif; zorunlu değil

## Kesin Sınırlar

- Uygulama kodu, CSS veya component değiştirme; yalnızca rapor üret
