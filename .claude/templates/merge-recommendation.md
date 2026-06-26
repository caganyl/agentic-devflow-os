# Merge Recommendation

## Meta

- **REQ-ID(ler):** REQ-[NNN], REQ-[NNN]
- **Branch:** [branch adı]
- **Tarih:** YYYY-MM-DD
- **Hazırlayan:** integration-release

---

## Karar

> **[MERGE READY / BLOCKED]**

---

## Kapsam Özeti

- Hedeflenen REQ-ID'ler: [liste]
- Tamamlanan: [liste]
- Ertelenen: [liste]

## Kalite Kanıtı

| Alan | Durum | Not |
|------|-------|-----|
| CI (lint, typecheck) | ✓ / ✗ | |
| Unit testler | ✓ / ✗ | X/X geçiyor |
| Integration testler | ✓ / ✗ | X/X geçiyor |
| E2E testler | ✓ / ✗ / yok | |
| Security review | ✓ / ✗ | blocker yok |
| QA sign-off | ✓ / ✗ | |
| EvalOps scorecard | ✓ / ✗ / yok | AI feature varsa |

## Blocker'lar

_[Blocker yok / Blocker listesi]_

| Blocker | Severity | Sahip | Durum |
|---------|----------|-------|-------|
| [blocker] | Critical/High | [rol] | açık / kapalı |

## Known Limitations

- [sınırlama 1]: [neden kabul edildi, sonraki plan]
- [sınırlama 2]: ...

## Rollback Planı

- **Yöntem:** [git revert PR / feature flag / DB rollback]
- **Tahmini süre:** [X dakika]
- **Veri kaybı riski:** yok / düşük / orta / yüksek
- **Talimat:** [komut veya link]

## İnsan Onayı İçin Gereken Aksiyonlar

- [ ] Engineering lead PR'ı onaylar
- [ ] (AI feature ise) Model deployment onayı
- [ ] (DB migration ise) Production migration onayı
- [ ] Main merge

## Merge Sonrası İzleme

- [metrik 1] — [nasıl izlenecek]
- [metrik 2] — [nasıl izlenecek]
