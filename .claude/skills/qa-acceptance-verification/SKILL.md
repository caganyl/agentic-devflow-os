---
name: qa-acceptance-verification
description: Requirement ve acceptance criteria üzerinden test coverage, regression ve eksik senaryo tespitini yapar.
when_to_use: Implementation tamamlandıktan sonra, QA sign-off öncesi veya test kapsamı değerlendirilirken.
---

# Skill: QA Acceptance Verification

## Amaç

Her acceptance criteria'nın testinin olduğunu, her testin çalıştığını
ve regression riskinin yönetildiğini doğrula.

## Prosedür

### 1. Acceptance Criteria Taraması

Requirement dosyasından (`docs/product/requirements/REQ-XXX.md`) tüm AC'leri
numaralarıyla çıkar (AC-1, AC-2, ...).

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

.NET (xUnit + `WebApplicationFactory`):

```csharp
public class CreateOrderTests(WebApplicationFactory<Program> factory)
    : IClassFixture<WebApplicationFactory<Program>>
{
    [Fact] // REQ-012 AC-1
    public async Task AC1_ValidOrder_Returns201()
    {
        var client = factory.CreateClient();
        var response = await client.PostAsJsonAsync("/orders", new { sku = "A1", qty = 1 });
        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
    }
}
```

React (Vitest + React Testing Library):

```tsx
it("AC-2: geçersiz miktarda hata mesajı gösterir", async () => {
  render(<OrderForm />);
  await userEvent.type(screen.getByRole("spinbutton", { name: /miktar/i }), "0");
  await userEvent.click(screen.getByRole("button", { name: /gönder/i }));
  expect(screen.getByRole("alert")).toHaveTextContent(/en az 1/i);
});
```

- Her test tek bir AC'yi test eder
- Test adı hangi AC'yi test ettiğini belirtir
- Bağımsız çalışır (diğer testlere bağımlı değil)
- Deterministic (her çalıştırmada aynı sonuç)

### 5. Regression Kontrolü

Dilim sırasında yalnızca değişen davranışı kapsayan odaklı testleri çalıştır;
sign-off'tan önce bir kez tüm suite'i çalıştır.

```
- [ ] Tüm suite sign-off öncesi bir kez çalıştırıldı ve geçiyor
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
