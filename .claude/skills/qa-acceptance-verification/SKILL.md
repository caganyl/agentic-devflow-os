---
name: qa-acceptance-verification
description: Requirement ve acceptance criteria üzerinden test coverage, regression ve eksik senaryo tespitini yapar.
agent: qa-automation
triggers:
  - Implementation tamamlandıktan sonra
  - Release öncesi QA gate'inde
  - Test coverage değerlendirilirken
---

# Skill: QA Acceptance Verification

## Amaç

Her acceptance criteria'nın testinin olduğunu, her testin çalıştığını
ve regression riskinin yönetildiğini doğrula.

## Prosedür

### 1. Acceptance Criteria Taraması

Requirement dosyasından tüm AC'leri çıkar:
```python
# AC-01: [açıklama]
# AC-02: [açıklama]
# ...
```

### 2. Test Coverage Matrisi Oluştur

```markdown
| AC ID | Test Var mı? | Test Tipi | Sonuç | Not |
|-------|-------------|-----------|-------|-----|
| AC-01 | Evet | unit | geçiyor | - |
| AC-02 | Hayır | - | eksik | QA görevi oluştur |
| AC-03 | Evet | integration | başarısız | blocker |
```

### 3. Eksik Test Tespiti

AC başına şu senaryoları kontrol et:
- **Happy path:** Normal akış çalışıyor mu?
- **Edge case:** Sınır değerleri test edildi mi?
- **Error path:** Hata senaryoları test edildi mi?
- **Permission:** Yetkisiz erişim reddediliyor mu?
- **Regression:** Eski feature'lar hala çalışıyor mu?

### 4. Test Yazma Standartları

```python
def test_ac01_user_can_create_resource():
    """AC-01: Kullanıcı geçerli veriyle kaynak oluşturabilmeli."""
    # Arrange
    ...
    # Act
    ...
    # Assert
    ...
```

- Her test tek bir AC'yi test eder
- Test adı hangi AC'yi test ettiğini belirtir
- Bağımsız çalışır (diğer testlere bağımlı değil)
- Deterministic (her çalıştırmada aynı sonuç)

### 5. Regression Kontrolü

```
- [ ] Tüm mevcut testler hala geçiyor
- [ ] Değiştirilen kodun etkilediği alan tarandı
- [ ] Integration test suite çalıştırıldı
- [ ] E2E testler kritik akışları kapsıyor
```

### 6. QA Sign-off Kararı

Şu koşulların hepsinde sign-off ver:
- Tüm AC'ler için test var ve geçiyor
- Regression test suite temiz
- Kritik hata senaryoları test edilmiş
- Eksik test kalmamış (veya açıkça belgelenmiş ve kabul edilmiş)

Koşullar sağlanmazsa: blocker listesi ile birlikte "sign-off verilmedi" raporu yaz.

## Notlar

- Mock kullanımında dikkatli ol — production davranışından sapabilir
- Flaky test = güvenilmez test; düzelt veya kaldır
- Coverage yüzde sayısı değil, AC coverage önemlidir
