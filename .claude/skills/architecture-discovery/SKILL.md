---
name: architecture-discovery
description: Mevcut (brownfield) bir .NET ve/veya Next.js/React projesinin mimarisini deterministik tarayıcı ve birkaç örnek dosyayla çıkarır, insan onayına giden mimari profil taslağını üretir ve onaylı kuralların sürekli kontrolünü kurar.
agent: architecture-analyst
triggers:
  - Projeye sonradan katılan biri projeyi tanımak istediğinde
  - Bir projede DevFlow ilk kez kullanılacakken
  - Implementer ajan "mimari profil yok" blocker'ı raporladığında
---

# Skill: Architecture Discovery

## Amaç

Bir projenin fiilen nasıl kurulduğunu (katmanlar, referans yönü, API stili,
veri erişimi, frontend yapısı) kanıtla çıkarmak ve bunu iki işe yarar hale
getirmek: yeni katılan kişi için okunur bir özet, ajanlar için uyulacak ve
kontrol edilebilir kurallar.

## Prosedür

### 1. Tara (deterministik)

```bash
python3 "$DEVFLOW_ARCH_SCAN_SCRIPT" --root . --compact   # özet
python3 "$DEVFLOW_ARCH_SCAN_SCRIPT" --root .             # örnek dosyalar dahil
```

Tarayıcı dosya yazmaz. Çıkardıkları: .sln/.csproj referans grafiği, katman
tahmini, paketler (MediatR, EF Core, Dapper, FluentValidation, mapping,
mimari test paketleri), API stili (controller / minimal API), build
ayarları; frontend için framework (Next/Vite/CRA), router (app/pages),
klasör stili (feature-based / FSD / type-based), state, veri çekme, UI,
form, doğrulama, test ve lint kütüphaneleri, import alias'ları.

### 2. Örneklerden kalıp çıkar

Tarayıcının `samples` listesindeki dosyaları oku. Her katman için şunları not et:

- Adlandırma (ör. `CreateOrderCommand` + `CreateOrderHandler`, `OrdersController`)
- Bir endpoint'in uçtan uca yolu: endpoint → handler/service → repository/DbContext
- Doğrulama nerede, hata nasıl dönülüyor (exception, Result tipi, ProblemDetails)
- DI kaydı nerede (`DependencyInjection.cs`, `Program.cs`)
- Frontend: veri çekme nerede (server component, React Query hook, servis
  katmanı), bileşen klasör düzeni, form + şema kalıbı

Her kalıp için bir **referans dosya** seç: ajanlar yeni kod yazarken bu
dosyayı aynalar. Emin olamadığın kalıp için Grep ile 2-3 ek örneğe bak;
tüm kaynak ağacını okuma.

### 3. Profili yaz

Şablonlar: `.claude/templates/architecture-profile.md` ve
`.claude/templates/architecture-profile.json`. Hedef:
`docs/architecture/profile/`. Status `draft`.

- **Gözlem** (tarayıcıdan, kanıt yolu ile) ve **çıkarım** (senin yorumun,
  güven düzeyi ile) ayrı yazılır.
- Mevcut ihlaller (ör. Domain → Infrastructure referansı) "bilinen sapma"
  olarak listelenir; kural olarak değil.
- JSON'daki `rules` yalnızca tarayıcının kontrol edebildiği kuralları içerir
  (proje referans yönü, frontend feature sınırı). Diğer kalıplar Markdown'da
  "konvansiyon" olarak kalır.

### 4. İnsan onayı

İnsana en fazla 7 soru sor (ana oturum üzerinden). İnsan profili düzeltir ve
`Status: confirmed` yapar. Onaylı profil ajanlar için dondurulur.

### 5. Kuralı kalıcı yap

Onaydan sonra:

- `stack-verification` her çalıştırmada
  `python3 "$DEVFLOW_ARCH_SCAN_SCRIPT" --root . --check docs/architecture/profile/architecture-profile.json`
  çalıştırır; ihlal varsa görev bitmez.
- Kalıcı koruma için kuralların mimari teste çevrilmesi önerilir
  (NetArchTest/ArchUnitNET, `eslint-plugin-boundaries`). Bu bir implementation
  görevidir; backend/frontend engineer'a atanır.
- docs-writer, profilden kök README'nin mimari özet bloğunu ve katman
  klasörlerinin README'lerini üretir.
