---
name: requirement-grilling
description: Bir fikri REQ'e çevirmeden önce insanla tek tek soru sorarak belirsizlikleri kapatır; çıktısı net acceptance criteria, kapsam dışı listesi ve terim sözlüğü güncellemesidir. Ana oturum insanla birlikte çalıştırır.
agent: product-analyst
triggers:
  - Yeni bir fikir veya belirsiz bir istek REQ'e dönüştürülecekken
  - Acceptance criteria eksik veya yoruma açıkken
  - Tasarım fazında aynı soru ikinci kez tartışılmaya başladığında
---

# Skill: Requirement Grilling

Esin kaynağı: mattpocock/skills `grill-me` ve `grill-with-docs` (MIT).
DevFlow'a uyarlanmış, kendi ifadelerimizle.

## Amaç

Belirsizliği tasarım fazından önce, insanla birlikte kapatmak. ADR ve review
döngülerinin çoğu, requirement'ta cevaplanmamış bir sorunun tasarımda
tartışılmasından doğar. Bu skill o soruları baştan sorar.

Bu skill insanla etkileşim gerektirir. Alt ajan insanla konuşamaz; bu yüzden
ana oturum çalıştırır ve sonucu product-analyst'e girdi olarak verir.

## Prosedür

### 1. Önce kendin bul

Kod tabanından, mevcut REQ'lerden, contract'lardan veya
`docs/product/GLOSSARY.md`'den cevaplanabilecek bir şeyi insana sorma; bak
ve bulduğunu doğrulat.

### 2. Tek seferde tek soru

- Her turda tek soru sor. Soruyla birlikte önerdiğin cevabı ve gerekçesini
  ver; insan onaylar, düzeltir veya reddeder.
- Karar ağacında ilerle: önce kapsamı (ne var, ne yok), sonra davranışı
  (normal akış, hata durumları, yetki), en son kenar durumları.
- Yalnızca uygulamayı veya testi değiştirecek soruları sor. "Olsa güzel olur"
  ayrıntıları kapsam dışı listesine yaz, sorma.

### 3. Durma koşulu

Şu üçü netleşince dur:

1. Her acceptance criterion test edilebilir bir cümle (girdi, beklenen sonuç)
2. Kapsam dışı listesi yazılmış
3. ADR eşiği kontrol edilmiş: gerekiyor mu, gerekmiyor mu, neden

Genelde 5-12 soru yeterlidir. 15 soruyu geçtiysen REQ büyük demektir; iki
REQ'e bölmeyi öner.

### 4. Çıktı

- Requirement ve AC taslağı için product-analyst'e verilecek özet
  (karar listesi, AC'ler, kapsam dışı, açık sorular en fazla 3)
- `docs/product/GLOSSARY.md` için yeni veya netleşen terimler: terim, tek
  cümlelik tanım, kodda kullanılacak ad. Sözlük kısa tutulur; ajanlar uzun
  açıklama yerine bu terimleri kullanır.

## Sınırlar

- Mimari karar verme; yalnızca ADR eşiğinin sağlanıp sağlanmadığını kaydet.
- İnsanın vermediği bir kararı AC'ye yazma.
