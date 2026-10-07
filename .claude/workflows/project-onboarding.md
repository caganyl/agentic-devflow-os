# Workflow: Project Onboarding

## Ne Zaman Çağrılır?

- Biri mevcut bir projeye sonradan katıldığında ve mimariyi öğrenmek istediğinde
- DevFlow bir projede ilk kez kullanılacakken
- Sıfırdan bir .NET servisi veya Next.js/React uygulaması kurulacakken
- Implementer ajan "mimari profil yok" blocker'ı raporladığında

## Girdiler

- Target repo (tam checkout)
- Varsa ekip/şirket mimari standartları
- Greenfield ise ürün bağlamı (ne inşa ediliyor, kaç kişilik ekip)

## Kullanılacak Roller

**Mevcut proje (brownfield):**
1. **Architecture Analyst** — tarayıcıyı çalıştırır, örnek dosyalardan kalıpları çıkarır, profil taslağı yazar
2. **İnsan** — açık soruları cevaplar, profili `confirmed` yapar
3. **Docs Writer** — katman/feature klasör README'leri ve kök README'nin otomatik blokları (yorum eklemez)
4. **Backend / Frontend Engineer** (opsiyonel) — onaylı kuralları mimari teste çevirir

**Yeni proje (greenfield):**
1. **Ana oturum + insan** — `architecture-intake` ile kararlar
2. **Solution Architect** — ADR eşiği sağlanıyorsa tek kuruluş ADR'si
3. **Backend / Frontend Engineer** — iskelet, mimari test projesi, lint sınır kuralları
4. **Docs Writer** — README'ler

## Gerekli Skill'ler

- `architecture-discovery` — brownfield tarama ve profil taslağı
- `architecture-intake` — greenfield mimari kararları (insanla)
- `documentation-sync` — README'ler
- `stack-verification` — profil kontrolünün doğrulama sırasına eklenmesi

## Approval Gate'ler

- [ ] Profil taslağı insan tarafından okundu, açık sorular cevaplandı
- [ ] **İnsan onayı:** `Status: confirmed` (yalnızca insan yazabilir)
- [ ] Profil kontrolü (`devflow_arch_scan.py --check`) temiz veya bilinen sapmalar listelenmiş

## Üretilecek Artefaktlar

- `docs/architecture/profile/ARCHITECTURE_PROFILE.md`
- `docs/architecture/profile/architecture-profile.json`
- Katman/feature klasörlerinde `README.md`
- Kök README'de `devflow:auto` blokları
- (Greenfield) iskelet ve mimari test projesi

## Completion Kriteri

- Profil `confirmed`
- Implementer ajanlar yeni görevlerde profili ve referans dosyaları kullanıyor
- Profil kontrolü stack-verification'ın parçası

## Handoff Formatı

Bkz. `.claude/templates/handoff.md`. Handoff'a profilin özeti değil, yolu ve
bilinen sapmalar listesi yazılır.

## Failure / Recovery

- Tarayıcı katman çıkaramadı (`unknown`): insan profilde `layer_by_project` ile elle eşler
- Profil kontrolü çok sayıda mevcut ihlal veriyor: ihlaller "bilinen sapma" olarak
  listelenir, kural hedef durumu tanımlar; sapmaları kapatmak ayrı REQ'lerdir
- Greenfield'da insan karar vermek istemiyor: varsayılan öneriler "varsayılan"
  işaretiyle yazılır, profil yine de insan tarafından onaylanır
