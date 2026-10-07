---
name: architecture-intake
description: Sıfırdan başlayan (greenfield) bir projede mimariyi insanla tek tek soru sorarak belirler ve brownfield projelerle aynı formatta onaylı mimari profil üretir. Ana oturum insanla birlikte çalıştırır.
agent: solution-architect
triggers:
  - Mimari tarayıcı project_state empty döndüğünde
  - Yeni bir servis veya frontend uygulaması sıfırdan kurulacakken
---

# Skill: Architecture Intake (Greenfield)

## Amaç

Boş bir projede ajanların kafasına göre yapı kurmasını önlemek. Mimari
kararlar insanla birlikte, her soruda bir öneriyle alınır ve sonuç mevcut
projelerdekiyle aynı profil formatına yazılır. Böylece backend ve frontend
ajanları greenfield ve brownfield projede aynı şekilde çalışır.

Alt ajan insanla konuşamaz; bu skill'i ana oturum çalıştırır.

## Prosedür

### 1. Tek seferde tek soru, her soruda öneri

Her soruda seçenekleri, önerini ve tek cümlelik gerekçesini ver. İnsan
onaylar veya değiştirir. Ekip standardı veya şirket kuralı varsa önce onu sor.

**Backend (.NET)**
1. Proje boyutu ve ekip: tek servis mi, modüler monolit mi?
2. Katman stili: Clean Architecture (Domain / Application / Infrastructure /
   Api) mı, vertical slice mı? Küçük, CRUD ağırlıklı servis için vertical
   slice; karmaşık domain kuralı için Clean Architecture öner.
3. API stili: controller mı, minimal API mi?
4. Veri erişimi: EF Core mu, Dapper mı, ikisi birden mi? Repository katmanı
   olacak mı (EF Core ile çoğu zaman gereksiz)?
5. CQRS/mediator kullanılacak mı? Kullanılmayacaksa application service.
6. Doğrulama ve hata modeli: FluentValidation + ProblemDetails; Result tipi mi,
   exception mı?
7. Test: xUnit/NUnit, Testcontainers, mimari test (NetArchTest).

**Frontend**
1. Next.js (App Router) mı, Vite + React SPA mı? SEO/SSR gerekiyorsa Next.
2. Klasör stili: feature-based mi, Feature-Sliced Design mı?
3. Sunucu verisi: server component + fetch, React Query, SWR?
4. İstemci state: gerek var mı, varsa Zustand / Redux Toolkit?
5. UI kütüphanesi ve stil: Tailwind + shadcn/ui, MUI, kurumsal tasarım sistemi?
6. Form ve şema: react-hook-form + zod?
7. Test: Vitest + Testing Library, Playwright.

**Ortak**
- Kod, yorum ve adlandırma dili (ör. İngilizce kod + Türkçe yorum)
- API sözleşmesi: OpenAPI'den istemci üretilecek mi?

### 2. Durma koşulu

Yukarıdaki başlıkların hepsi için bir karar var veya "şimdilik gerek yok"
denmiş. 15 soruyu geçme; kalanlar varsayılan önerinle kaydedilir ve
"varsayılan" diye işaretlenir.

### 3. Çıktı

- `docs/architecture/profile/ARCHITECTURE_PROFILE.md` ve
  `architecture-profile.json`, şablonlardan, kararlarla doldurulmuş.
  İnsan son kez okuyup `Status: confirmed` yapar.
- Geri alınması pahalı kararlar (katman stili, veri erişimi) ADR eşiğini
  sağlıyorsa tek bir kuruluş ADR'si.
- İlk implementation görevi olarak iskelet: çözüm/proje yapısı, mimari test
  projesi, lint sınır kuralları. Bu görev backend/frontend engineer'a gider;
  paket kurulumu ve `dotnet new` gibi iskelet komutlarını ana oturum çalıştırır.
