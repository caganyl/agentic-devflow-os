---
name: release-scorecard
description: PR kapsamı, CI, test, security review, known limitations, rollback ihtiyacı ve merge recommendation üretir.
when_to_use: Bir run'ın QA, security ve dokümantasyon adımları bittiğinde, release-readiness workflow'unda veya merge tavsiyesi istendiğinde.
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

Her satır kayıtlı bir kanıta bağlanır (yol veya komut çıktısı); kanıt yoksa
"Eksik" yazılır.

### 2. CI ve Test Kanıtı

```
- [ ] Run state'te qa_evidence kayıtlı, source=executed (record-qa-evidence --test-command), qa_passed=true
- [ ] Lint / typecheck / build: stack-verification sonucu handoff'ta
- [ ] PR Quality ve Ownership Diff Gate son commit için yeşil (PR varsa)
- [ ] Her AC için en az bir test var (handoff AC tablosu)
```

### 3. Karar ve Contract Kanıtı

```
- [ ] adr_required=true ise ADR reviewer APPROVE dosyası var (docs/architecture/adr/reviews/)
- [ ] new_feature run'ında contract kanıtı kayıtlı (record-contract-evidence)
- [ ] Contract değişikliği varsa contract'ta versiyon/status güncel
- [ ] Açık PR review yorumları triage edildi (docs/release/pr-reviews/)
```

### 4. Security Review

```
- [ ] security_review_required=false ise "not applicable"; true ise security_evidence kayıtlı
- [ ] Security Red Team raporu docs/quality/security-reports/ altında
- [ ] Critical blocker yok
- [ ] High blocker yok (veya kabul edildi ve belgelendi)
- [ ] Bilinen Medium ve Low'lar listelendi
```

### 5. QA ve Work-Product Kanıtı

```
- [ ] approval_gates.tests_passing ve qa_sign_off = true
- [ ] Implementation ve QA task'ları için work-product kanıtı kayıtlı
- [ ] generate-run-report çıktısı: technical_readiness ve merge_recommendation
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
- [ ] Commit/push ve PR (insan)
- [ ] Main merge (insan)
- [ ] (AI feature ise) Model deployment onayı
- [ ] (DB migration ise) Production migration onayı

**Blocker'lar:** [varsa liste]

**Merge sonrası izleme:** [monitor edilecek metrikler]
```

## Karar Kriterleri

- **MERGE READY:** Tüm checkbox'lar kanıtla işaretli, blocker yok, known limitations yazılmış (karar yine insanındır)
- **BLOCKED:** Herhangi bir Critical/High blocker, test başarısızlığı veya CI hatası var

## Kesin Sınırlar

- Git push, main merge, production deploy veya production migration yapma
- Blocker varken "merge ready" kararı verme
