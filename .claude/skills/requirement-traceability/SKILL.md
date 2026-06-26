---
name: requirement-traceability
description: Evidence → requirement → acceptance criteria → task → test → handoff zincirini kurar ve doğrular.
agent: delivery-lead
triggers:
  - Yeni requirement oluşturulurken
  - Test coverage değerlendirilirken
  - Handoff hazırlanırken
  - Release öncesi traceability kontrolünde
---

# Skill: Requirement Traceability

## Amaç

Her requirement'ın kendi testine, her testin kendi görevine, her görevin
kendi handoff'una bağlanmasını sağla. Kopuk zincir = tamamlanmamış delivery.

## Traceability Zinciri

```
[Evidence/Research]
    ↓
[REQ-XXX: Requirement]
    ↓
[AC-01, AC-02... : Acceptance Criteria]
    ↓
[Task-1, Task-2... : Implementation Tasks]
    ↓
[test_xxx.py / spec_xxx.ts: Test Dosyaları]
    ↓
[docs/handoffs/REQ-XXX.md: Handoff]
```

## Prosedür

### 1. Traceability Matrisini Oluştur

```markdown
## Traceability Matrix: REQ-XXX

| AC ID | Açıklama | Test Dosyası | Test Adı | Durum |
|-------|----------|-------------|----------|-------|
| AC-01 | ... | tests/test_xxx.py | test_ac01_... | geçiyor |
| AC-02 | ... | tests/test_xxx.py | test_ac02_... | eksik |
```

### 2. Eksik Linkleri Bul

Her AC için kontrol et:
- Test dosyası var mı?
- Test adı AC'yi açıkça referans ediyor mu?
- Test bağımsız çalışıyor mu (mock bağımlılığı hatalı değil)?

### 3. Kopuk Zincir Durumları

- **AC var, test yok:** QA Automation'a görev oluştur
- **Test var, AC yok:** Product Analyst'e gönder, AC'yi netleştir
- **Test geçiyor ama hangi AC'yi kapsıyor belli değil:** Test adını ve docstring'i güncelle
- **Handoff güncellenmemiş:** Delivery Lead handoff'u güncelle

### 4. Release Traceability Kontrolü

Release öncesinde tüm REQ-ID'ler için:

```markdown
## Release Traceability Check

- [ ] Her REQ-ID için requirement dosyası var
- [ ] Her requirement için AC listesi var
- [ ] Her AC için en az bir test var
- [ ] Tüm ilgili testler geçiyor
- [ ] Her REQ-ID için handoff güncel
- [ ] Contract veya ADR değişikliği belgelenmiş
```

## Notlar

- Traceability matrisini `docs/handoffs/REQ-XXX.md` içine göm
- Eksik link = delivery tamamlanmamış; merge öneri yapma
