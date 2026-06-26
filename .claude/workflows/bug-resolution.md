# Workflow: Bug Resolution

## Ne Zaman Çağrılır?

Bir bug raporu, production incident veya regression tespit edildiğinde.
Hız kritiktir; ancak scope kontrolü ve test garantisi şarttır.

## Girdiler

- Bug tanımı ve repro adımları
- Etkilenen REQ-ID veya feature alanı
- Severity ve öncelik (P0/P1/P2/P3)
- Hata log'ları veya stack trace (varsa)
- Etkilenen kullanıcı veya sistem bilgisi

## Kullanılacak Roller

Severity'ye göre minimum set:

**P0/P1 (Production critical):**
1. **Delivery Lead** — kriz koordinasyonu, rol ataması
2. **QA Automation** — bug reproduksiyon ve test yazma
3. İlgili domain engineer (Frontend/Backend/Database/AI)
4. **Security Red Team** (güvenlik açığı ise)

**P2/P3 (Non-critical):**
1. **Delivery Lead** — önceliklendirme
2. QA Automation — test
3. İlgili domain engineer

## Gerekli Skill'ler

- `task-routing` — ilgili domain engineer seçimi
- `qa-acceptance-verification` — regression test coverage
- `adversarial-security-review` (güvenlik bug'ı ise)

## Approval Gate'ler

- [ ] Bug repro testi yazılmış ve başarısız oluyor (bug kanıtlanmış)
- [ ] Fix yazılmış
- [ ] Repro testi geçiyor
- [ ] Regression test suite temiz
- [ ] P0/P1 için: **İnsan onayı — production deploy**

## Üretilecek Artefaktlar

- Bug fix kodu
- Regression test
- Bug fix handoff notu (kısa)
- P0/P1 için: incident report (kısa)

## Completion Kriteri

- Repro testi geçiyor
- Mevcut test suite kırılmıyor
- Root cause belgelenmiş
- Benzer bug'lar için önleyici test eklenmiş

## Handoff Formatı

```markdown
## Bug Fix: [bug adı]
- REQ-ID veya etkilenen area: ...
- Root cause: ...
- Fix özeti: ...
- Eklenen test: ...
- Benzer risk alanları: ...
```

## Failure / Recovery

- Fix başka şeyi kırıyor: rollback, daha küçük fix
- Root cause belirsiz: daha fazla log ve investigation
- Güvenlik açığı: Security Red Team → CVE değerlendirmesi → insan onayı
