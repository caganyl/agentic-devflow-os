# Workflow: Release Readiness

## Ne Zaman Çağrılır?

Bir feature veya feature seti production'a alınmadan önce release hazırlık
değerlendirmesi yapılması gerektiğinde.

## Girdiler

- Kapsama girecek REQ-ID listesi
- Integration branch durumu
- CI sonuçları
- Açık bilinen sorunlar veya riskler
- Oncall ve rollback planı

## Kullanılacak Roller

1. **Integration/Release** — scorecard üretimi, CI değerlendirmesi
2. **QA Automation** — test coverage son kontrolü, regression
3. **Security Red Team** — son güvenlik taraması
4. **Delivery Lead** — merge recommendation kararı

## Gerekli Skill'ler

- `release-scorecard` — tam scorecard üretimi
- `stack-verification` — son build/test/bağımlılık sırası
- `pr-review-triage` — açık PR yorumlarının sınıflanması (yanıtları insan gönderir)
- Dinamik pentest (opsiyonel, periyodik): insan staging ortamında DAST aracı
  (ör. strix) çalıştırır; ajanlar çalıştıramaz (hook reddeder). Rapor
  `docs/quality/security-reports/` altına konur ve Security Red Team
  bulguları severity'ye göre sınıflar.
- `qa-acceptance-verification` — son test durumu
- `adversarial-security-review` — son güvenlik taraması

## Approval Gate'ler

- [ ] Tüm hedeflenen REQ-ID'ler tamamlanmış
- [ ] CI yeşil (lint, typecheck, test suite)
- [ ] Security review tamamlanmış
- [ ] QA sign-off verilmiş
- [ ] Rollback planı hazır
- [ ] Known limitations belgelenmiş
- [ ] **İnsan onayı: main merge ve production deploy**

## Üretilecek Artefaktlar

- Release scorecard (`.claude/templates/merge-recommendation.md` formatında)
- Known limitations listesi
- Rollback talimatı

## Completion Kriteri

- Scorecard "merge ready" durumunda
- Tüm blocker'lar kapatılmış
- İnsan onayı alınmış

## Handoff Formatı

```markdown
## Release: v[versiyon veya REQ listesi]
- Kapsam: [REQ-ID listesi]
- CI: geçti/başarısız
- Security: temiz/açık sorun
- QA: sign-off alındı
- Rollback: [talimat özeti]
- Merge kararı: ready / blocked
```

## Failure / Recovery

- CI başarısız: blocker sorunu ilgili engineer'a ilet
- Security blocker: Security Red Team ile remediation
- QA başarısız: QA Automation ile root cause
- İnsan onayı gelmezse: bekle, devam etme
