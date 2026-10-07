# Mimari Profil — <Proje adı>

Status: draft
<!-- draft | confirmed. confirmed yalnızca insan tarafından yazılır; onaylı profil ajanlar için dondurulur. -->
Kaynak: <architecture-discovery (tarama tarihi) | architecture-intake (karar tarihi)>

## 1. Özet
<5-10 satır: stil, katmanlar, temel kütüphaneler. Kök README'nin mimari bloğu buradan üretilir.>

## 2. Backend (.NET)

### Katmanlar ve referans yönü
| Proje | Katman | Referans verebileceği katmanlar |
|---|---|---|

### Konvansiyonlar
| Konu | Kural | Referans dosya | Güven |
|---|---|---|---|
| API stili | <controller / minimal API> | <yol> | <yüksek/orta/düşük> |
| Yeni endpoint akışı | <endpoint → handler → DbContext> | <yol> | |
| Adlandırma | <CreateXCommand + CreateXHandler> | <yol> | |
| Doğrulama | <FluentValidation, pipeline behavior> | <yol> | |
| Hata modeli | <ProblemDetails / Result> | <yol> | |
| Veri erişimi | <EF Core, repository yok> | <yol> | |
| DI kaydı | <DependencyInjection.cs> | <yol> | |
| Test | <xUnit + Testcontainers, test projesi adı> | <yol> | |

## 3. Frontend

| Konu | Kural | Referans dosya | Güven |
|---|---|---|---|
| Framework / router | <Next App Router / Vite SPA> | <yol> | |
| Klasör stili | <feature-based: src/features/<ad>/index.ts public API> | <yol> | |
| Sunucu verisi | <React Query hook'ları features/<ad>/api altında> | <yol> | |
| İstemci state | <Zustand, yalnızca UI state> | <yol> | |
| Bileşen | <UI kütüphanesi, dosya başına tek bileşen> | <yol> | |
| Form | <react-hook-form + zod> | <yol> | |
| Test | <Vitest + Testing Library, Playwright> | <yol> | |

## 4. Konvansiyonlar (ortak)
- Kod dili: <İngilizce>
- Yorum dili (`comment_language`): <Türkçe / İngilizce>
- Commit: <Conventional Commits>

## 5. Bilinen sapmalar
<Mevcut ihlaller; kural değil, borç. Örn: Shop.Domain → Shop.Infrastructure referansı (bkz. tarama).>

## 6. Açık sorular (en fazla 7)
