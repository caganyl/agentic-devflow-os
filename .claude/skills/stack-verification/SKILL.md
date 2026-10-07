---
name: stack-verification
description: Bir görevi "bitti" demeden önce .NET ve Next.js/React projelerinde sabit sırayla build, format, tip, test, mimari, bağımlılık ve UI dedektörü kontrollerini çalıştırır; bağlama yalnızca hataları taşır ve sonucu record-qa-evidence ile kaydettirir.
agent: qa-automation
triggers:
  - Implementer görevini tamamlamadan önce
  - QA sign-off öncesi
  - PR review düzeltmelerinden sonra
---

# Skill: Stack Verification

Esin kaynağı: affaan-m/everything-claude-code `verification-loop` fikri;
UI adımı için pbakaus/impeccable deterministik dedektörü (Apache-2.0).
DevFlow'a ve .NET/Next.js yığınına uyarlanmıştır.

## Amaç

Tek, öngörülebilir bir doğrulama sırası: ilk kırılan adımda dur, yalnızca
hatayı bağlama al, düzelt, aynı adımdan devam et. Uzun log'lar bağlamı
doldurmaz.

## Prosedür

### Kurallar

- Sırayı değiştirme; ilk başarısız adımda dur.
- Çıktıyı filtrele: yalnızca hata/başarısız satırları ve özet satırını al.
  `2>&1 | tail -40` veya `grep -E "error|Failed|FAIL"` kullan. Dosyaya
  yönlendirme (`>`, `tee`) hook tarafından reddedilir.
- Paket indiren komut yok: `npx --no-install` kullan. Eksik araç bir
  blocker'dır; kurulumu ana oturum/insan yapar.

### 0. Mimari profil kontrolü (profil varsa)

```bash
python3 "$DEVFLOW_ARCH_SCAN_SCRIPT" --root . --check docs/architecture/profile/architecture-profile.json
```

`ok: false` ise dur: yeni bir yasak proje referansı veya feature sınırı
ihlali var. `known_deviations` altındakiler görevi düşürmez.

### .NET

1. Build: `dotnet build --nologo -warnaserror 2>&1 | tail -40`
2. Format: `dotnet format --verify-no-changes 2>&1 | tail -20`
3. Test (mimari testler dahil, NetArchTest/ArchUnitNET):
   `dotnet test --nologo --no-build 2>&1 | grep -E "Failed|error|Passed!|Failed!" | tail -40`
4. Bağımlılık: `dotnet list package --vulnerable --include-transitive 2>&1 | tail -30`

### Next.js / React

1. Tip: `npx --no-install tsc --noEmit 2>&1 | tail -40`
2. Lint: `npx --no-install eslint . --max-warnings=0 2>&1 | tail -40`
3. Test: projenin test script'i (Vitest/Jest), yalnızca başarısızlar
4. Build: `npx --no-install next build 2>&1 | tail -40`
5. Bağımlılık: `npm audit --audit-level=high 2>&1 | tail -30`
6. UI dedektörü (yalnızca UI dosyası değiştiyse ve `impeccable` sabit
   sürümlü devDependency olarak kuruluysa):
   `npx --no-install impeccable detect --fast --json <değişen klasörler>`
   Bulgular blocker değildir; design-reviewer'a girdi olur. Projenin kendi
   tasarım sistemiyle çelişen kurallar ekip kararıyla kapatılır.

### Sonuç ve kanıt

Tüm adımlar geçtiyse sayıları ana oturuma bildir; kanıt kaydını yetkili CLI
yapar:

```bash
python3 "$DEVFLOW_OPERATIONS_SCRIPT" record-qa-evidence --target "$DEVFLOW_RUN_WORKTREE" \
  --total <n> --passed <n> --failed 0 --exit-code 0
```

Bir adımda üç düzeltme denemesinden sonra hâlâ kırmızıysa dur ve
`root-cause-investigation` skill'ine geç veya blocker olarak raporla.

### CI karşılığı

Aynı sıra CI'da da çalışmalı; ajanın yerel sonucu CI'ın yerini almaz.
Impeccable dedektörü için CI adımı örneği (sürümü sabitle):

```yaml
- name: UI anti-pattern detector
  run: npx --no-install impeccable detect --fast --json src/
```
