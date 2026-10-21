# WCAG 2.2 Erişilebilirlik Denetimi (referans)

Esin kaynağı: msitarzewski/agency-agents `testing-accessibility-auditor` (MIT).
DevFlow'a uyarlandı, kendi ifadelerimizle.

`visual-design-review` §4 bu dosyayı kullanır. Değişiklik yeni veya değişen
etkileşimli bileşen içeriyorsa (form, modal, menü, sekme, tablo, tarih
seçici) tamamı uygulanır; yalnızca metin/stil değişikliğinde §1 ve §2 yeter.

## 1. Bulgu kuralları

- Her a11y bulgusu bir WCAG 2.2 başarı kriterine numara ve adla bağlanır
  (ör. `2.4.7 Focus Visible`, `1.4.3 Contrast (Minimum)`). Kriteri olmayan
  gözlem bulgu değil, öneridir.
- Otomatik tarayıcı temiz diye "erişilebilir" deme. Odak sırası, okuma
  sırası, ARIA'nın yanlış kullanımı ve bilişsel engeller otomatik bulunmaz.
- Özel bileşenler (sekme, modal, carousel, tarih seçici, combobox) aksi
  gösterilene kadar şüphelidir; klavyeyle tek tek denenir.
- Önce semantik HTML: `<button>`, `<label>`, `<table>` varken `div` + ARIA
  kuran kod bulgudur.
- Dekoratif görselde dolu `alt` da, etiketsiz etkileşimli öğe de hatadır.

## 2. Önem skalası ve DevFlow karşılığı

| WCAG önemi | Anlamı | `visual-design-review` kararı |
|---|---|---|
| Critical | Bazı kullanıcılar için akış tamamen kapanır (klavye tuzağı, etiketsiz zorunlu alan, odaklanamayan ana buton) | Blocker |
| Serious | Ciddi engel; geçici çözümle aşılır (görünmeyen odak, modal kapanınca odağın kaybolması) | Blocker |
| Moderate | Zorlaştırır ama akış tamamlanır (zayıf hata metni, eksik tablo başlığı ilişkisi) | Major |
| Minor | Kullanılabilirliği düşüren küçük kusur | Minor |

## 3. Klavye kontrol listesi

Genel:

```
- [ ] Her etkileşimli öğeye Tab ile ulaşılıyor; sıra görsel düzeni izliyor
- [ ] Hiçbir yerde klavye tuzağı yok (Tab ile her zaman çıkılabiliyor)
- [ ] Her etkileşimli öğede odak göstergesi görünüyor
- [ ] Sayfada "içeriğe atla" bağlantısı var ve çalışıyor
- [ ] Escape modal, açılır menü ve katmanları kapatıyor
- [ ] Modal/katman kapanınca odak onu açan öğeye dönüyor
```

Bileşene göre:

```
Sekmeler  - [ ] Ok tuşları sekmeler arasında, Home/End ilk/son sekmeye gider
          - [ ] Seçili sekme aria-selected ile belirtilir
Menüler   - [ ] Ok tuşları gezinir, Enter/Space seçer, Escape kapatıp odağı geri verir
Modal     - [ ] Açılınca odak modalın içine gelir, Tab modal dışına kaçmaz
Tablolar  - [ ] Başlıklar scope/headers ile hücrelere bağlı; caption veya aria-label var
          - [ ] Sıralanabilir kolonlar klavyeyle çalışır
Formlar   - [ ] Hata mesajı alana bağlı (aria-describedby) ve ekran okuyucuya duyurulur
Carousel  - [ ] Durdurma kontrolü var ve klavyeyle erişilir
```

## 4. Otomatik tarama (opsiyonel)

`design-reviewer`'ın Bash yetkisi yoktur. Hedef projede `@axe-core/cli`
sabit sürümlü devDependency ise tarama `qa-automation` veya ana oturum
tarafından çalıştırılır; sonuç rapora kanıt olarak eklenir:

```bash
npx --no-install axe <url> --tags wcag2a,wcag2aa,wcag21a,wcag21aa,wcag22aa
```

Her kapsam içi URL ve durum (boş, hata, yükleniyor) ayrı taranır. Paket
kurulu değilse kurulmaz (yeni bağımlılık insan onayı ister); rapora
"otomatik tarama yapılmadı" yazılır.

## 5. Rapor özeti

Rapor sonunda kapsam ve sonuç açıkça yazılır:

- **Denetlenen:** sayfalar, durumlar, kullanılan araçlar
- **Denetlenmeyen:** sayfalar, durumlar, ekran okuyucu kombinasyonları
- **WCAG AA durumu:** kapsamdaki bir A/AA kriteri başarısızsa "uymuyor";
  gerekli testler eksikse "belirlenemedi"; ancak tüm akış denetlendiyse "uyuyor"
