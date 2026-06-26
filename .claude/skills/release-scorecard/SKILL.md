---
name: release-scorecard
description: PR kapsamı, CI, test, security review, known limitations, rollback ihtiyacı ve merge recommendation üretir.
agent: integration-release
triggers:
  - Feature delivery tamamlandığında
  - Release readiness workflow'unda
  - Merge recommendation gerektiğinde
---

# Skill: Release Scorecard

## Amaç

Tüm kalite kanıtlarını bir araya getir ve net bir merge kararı üret.
"Sanırım hazır" değil, kanıtlanmış hazırlık.

## Prosedür

### 1. Kapsam Doğrulama

```markdown
## Kapsam

- Hedeflenen REQ-ID'ler: [liste]
- Tamamlanan REQ-ID'ler: [liste]
- Tamamlanmayan (sonraki release): [liste]
- Kapsam dışı kalan işler: [liste]
```

### 2. CI Kontrol

```
- [ ] Lint: temiz
- [ ] Type check: temiz
- [ ] Unit test suite: geçiyor (X/X)
- [ ] Integration test suite: geçiyor (X/X)
- [ ] E2E testler: geçiyor (X/X) [varsa]
- [ ] Coverage hedefi karşılandı
```

### 3. Code Review

```
- [ ] Tüm PR'lar peer review aldı
- [ ] Kimse kendi PR'ını tek başına onaylamadı
- [ ] ADR gerektiren değişiklikler belgelendi
- [ ] Contract değişikliği varsa versiyonlama yapıldı
```

### 4. Security Review

```
- [ ] Security Red Team review tamamlandı
- [ ] Critical blocker yok
- [ ] High blocker yok (veya kabul edildi ve belgelendi)
- [ ] Bilinen Medium ve Low'lar listelendi
```

### 5. QA Verification

```
- [ ] Tüm AC'ler için test geçiyor
- [ ] Regression suite temiz
- [ ] QA sign-off verildi
```

### 6. Known Limitations

```markdown
## Known Limitations

- [sınırlama 1]: [neden kabul edildi, sonraki release planı]
- [sınırlama 2]: ...
```

### 7. Rollback Planı

```markdown
## Rollback

- Yöntem: [git revert / feature flag / DB rollback]
- Tahmini süre: [X dakika]
- Veri kaybı riski: [yok / düşük / orta / yüksek]
- Rollback talimatı: [link veya komut]
```

### 8. Merge Recommendation Üret

```markdown
## Merge Recommendation

**Karar:** ✓ MERGE READY / ⛔ BLOCKED

**Gerekçe:** [1-3 cümle]

**Onay için gereken insan aksiyonu:**
- [ ] Engineering lead onayı
- [ ] (AI feature ise) Model deployment onayı
- [ ] (DB migration ise) DBA onayı

**Blocker'lar:** [varsa liste]

**Merge sonrası izleme:** [monitor edilecek metrikler]
```

## Karar Kriterleri

- **MERGE READY:** Tüm checkbox'lar işaretli, blocker yok, known limitations kabul edilmiş
- **BLOCKED:** Herhangi bir Critical/High blocker, test başarısızlığı veya CI hatası var

## Kesin Sınırlar

- Git push, main merge, production deploy veya production migration yapma
- Blocker varken "merge ready" kararı verme
