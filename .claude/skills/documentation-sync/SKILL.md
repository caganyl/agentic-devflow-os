---
name: documentation-sync
description: Klasör README'lerini yazar, kök README'nin otomatik bloklarını mimari profile ve gerçek komutlara göre günceller ve değişen dosyalara yalnızca değerli yorumlar ekler. docs-writer ajanı uygular.
agent: docs-writer
triggers:
  - Bir REQ'in implementation ve QA'i bittiğinde, release öncesi
  - Mimari profil onaylandıktan sonra (onboarding)
  - Kök README'deki komutlar veya klasör haritası eskidiğinde
---

# Skill: Documentation Sync

## Amaç

Dokümanı kodla aynı anda güncel tutmak, ama gürültü üretmeden. Yeni katılan
biri bir klasörü açtığında ne işe yaradığını ve kuralını görür; kod
okuyucusu yalnızca kodun anlatamadığı "neden"i yorumda bulur.

## Prosedür

### 1. Kapsamı belirle

- Varsayılan: bu branch'te değişen dosyalar ve bunların klasörleri
  (`git diff --name-only <base>`).
- Onboarding: mimari profildeki katman/feature klasörleri; yorum eklenmez,
  yalnızca README yazılır.
- Açık yol listesi verilmediyse tüm repoya yorum ekleme. Bir çalıştırmada en
  fazla 30 kaynak dosyası.

### 2. Klasör README'si

Yalnızca anlamlı sınırı olan klasörlere yaz: proje kökü (.csproj klasörü),
katman, feature/modül, paylaşılan kütüphane. Her alt klasöre README açma.

```markdown
# <Klasör adı>

<Bir cümle: bu klasör ne için var.>

## İçerik
- `<alt klasör veya dosya kalıbı>` — <ne bulunur>

## Kurallar
- <profilden gelen kural, ör. "Infrastructure'a referans vermez">
- <adlandırma, ör. "Her komut için <Ad>Command + <Ad>Handler">

## Giriş noktaları
- <ör. DependencyInjection.cs, index.ts>

## Buraya konmaz
- <ör. EF Core sorguları — Infrastructure'da>
```

En fazla 40 satır. Profilde olmayan bir kuralı uydurma.

### 3. Kök README'nin otomatik blokları

Kök README'de şu işaretler yoksa bir kez ekle, sonra yalnızca içlerini güncelle:

```markdown
<!-- devflow:auto:architecture:start -->
...mimari profilin 5-10 satırlık özeti...
<!-- devflow:auto:architecture:end -->

<!-- devflow:auto:commands:start -->
...build/test/lint komutları (stack-verification'daki gerçek komutlar)...
<!-- devflow:auto:commands:end -->

<!-- devflow:auto:folders:start -->
...klasör haritası, her satırda klasör README'sine link...
<!-- devflow:auto:folders:end -->
```

İşaretlerin dışındaki metne dokunma. Komutları uydurma; projede gerçekten
çalışan komutları yaz (csproj, package.json script'leri).

### 4. Yorumlar

| Ne | Nerede | Örnek |
|---|---|---|
| XML doc | .NET public tip/üye | `/// <summary>Siparişi onaylar; stok yetersizse OutOfStock döner.</summary>` |
| TSDoc | Export edilen fonksiyon, hook, bileşen | `/** Sepeti sunucuyla eşitler; çevrimdışıyken kuyruğa alır. */` |
| "Neden" yorumu | Açık olmayan iş kuralı, kısıt, bilinçli takas | `// Neden: ödeme sağlayıcısı 30 sn sonra idempotency anahtarını unutuyor` |

Yazma: kodu tekrar eden yorum (`// i'yi artır`), değişiklik günlüğü yorumu,
TODO yağmuru, yorum satırına alınmış kod. Mevcut yanlış veya eski bir yorumu
düzeltebilirsin; bu da yalnızca yorum değişikliğidir.

### 5. Sınırlar

Hook şunu zorlar: docs-writer kaynak dosyada yalnızca yorum değiştirebilir.
Kodda sorun görürsen düzeltme, rapora yaz. Çıktının sonunda değişen dosya
listesini ve "rapor edilen kod sorunları" bölümünü ver.
