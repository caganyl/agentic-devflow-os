---
name: tdd-vertical-slice
description: Implementer ve QA rolleri için kırmızı-yeşil döngüsü. Testler yalnızca contract ve acceptance criteria'dan çıkan public seam'lerde, her seferinde tek dilim olarak yazılır.
agent: backend-engineer
triggers:
  - Onaylı manifestli bir REQ için implementation başlarken
  - Bug fix için repro testi yazılırken
  - QA bir acceptance criterion'u teste çevirirken
---

# Skill: TDD — Dikey Dilim

Esin kaynağı: mattpocock/skills `tdd` (MIT). DevFlow'a uyarlanmış, kendi ifadelerimizle.

## Amaç

Ajanın hem çalışan kod hem de refactor'dan sağ çıkan testler üretmesi.
Testler davranışı public sınırdan doğrular; iç yapıya bağlanmaz.

## Prosedür

### 1. Seam'leri baştan belirle

Seam, davranışı dışarıdan gözlemlediğin public sınırdır: bir HTTP endpoint,
bir application service metodu, bir React bileşeninin kullanıcıya görünen
davranışı. Seam listesi icat edilmez, şuradan çıkar:

- Onaylı contract (endpoint, event, tablo)
- Görevin acceptance criteria maddeleri

Task packet'te seam listesi yoksa önce listeyi yaz (en fazla 5 seam) ve
Delivery Lead'e raporla. Listede olmayan seam'e test yazma.

### 2. Döngü: bir seam, bir test, bir minimal implementation

1. **Kırmızı:** Tek bir davranış için başarısız olan testi yaz. Testi çalıştır,
   gerçekten doğru sebeple başarısız olduğunu gör.
2. **Yeşil:** Yalnızca bu testi geçirecek kadar kod yaz. Gelecek testleri
   öngörme, spekülatif özellik ekleme.
3. Sonraki davranışa geç. Her test bir öncekinden öğrendiğine göre şekillenir.

Refactor bu döngünün parçası değildir; review aşamasında yapılır.

### 3. Kaçınılacak kalıplar

- **Implementation'a bağlı test:** İç collaborator'ları mock'lamak, private
  metot test etmek, davranışı arayüz yerine yan kanaldan (doğrudan DB
  sorgusu gibi) doğrulamak. İşareti: davranış değişmediği halde refactor'da
  kırılır.
- **Totolojik test:** Beklenen değeri kodun hesapladığı yolla yeniden hesaplamak.
  Beklenen değer bağımsız bir kaynaktan gelir: AC'deki örnek, elle bulunmuş
  bir değer, contract'taki örnek yanıt.
- **Yatay dilimleme:** Önce tüm testleri, sonra tüm kodu yazmak. Hayali
  davranışı test eder ve yapıyı erkenden dondurur.
- **Testi geçirmek için assertion'ı gevşetmek.** Test yanlışsa bunu raporla;
  sessizce değiştirme.

### 4. Yığına özgü notlar

- **.NET:** xUnit/NUnit. API seam'i için `WebApplicationFactory` ile
  integration testi; DB gerekiyorsa Testcontainers. Domain kuralları için
  application service seviyesinde unit test.
- **Next.js/React:** Vitest veya Jest + React Testing Library; kullanıcıya
  görünen davranışı rol/etiket ile sorgula. Uçtan uca akış için Playwright.

### 5. Kanıt

Her dilim sonunda yalnızca ilgili test projesini çalıştır; tüm suite'i
dilim sonunda değil, görev sonunda `stack-verification` ile çalıştır.
Test çıktısını bağlama taşırken yalnızca başarısız satırları al.
