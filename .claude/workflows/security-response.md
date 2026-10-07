# Workflow: Security Response

## Ne Zaman Çağrılır?

Güvenlik açığı, threat model değişikliği, güvenlik audit bulgusu veya
güvenlik incident tespit edildiğinde. Hız ve gizlilik kritiktir.

## Girdiler

- Güvenlik bulgusunun tanımı
- Etkilenen bileşen veya veri alanı
- Severity seviyesi (Critical/High/Medium/Low)
- Saldırı vektörü veya proof-of-concept (varsa)
- Etkilenen kullanıcı/müşteri kapsamı

## Kullanılacak Roller

1. **Security Red Team** — tehdit analizi, severity tespiti, remediation planı
2. **Backend Engineer** — güvenlik patch implementasyonu
3. **Delivery Lead** — koordinasyon, insan escalation kararı
4. **Database Engineer** (veri sızıntısı veya SQL injection varsa)
5. **Integration/Release** (critical patch release ise)

## Gerekli Skill'ler

- `adversarial-security-review` — threat model ve remediation
- `root-cause-investigation` — açığın kök nedeni kanıtlanmadan patch yok
- Dinamik doğrulama: patch sonrası insan, staging'de DAST aracıyla (ör.
  strix) yeniden test eder; production'a karşı asla çalıştırılmaz.
- `db-migration-safety` (veri migration gerekiyorsa)
- `release-scorecard` (emergency release ise)

## Approval Gate'ler

- [ ] Severity değerlendirmesi tamamlanmış
- [ ] Etkilenen alan izole edilmiş
- [ ] Remediation planı hazırlanmış
- [ ] Fix implementasyonu tamamlanmış
- [ ] Security fix test edilmiş
- [ ] **İnsan onayı: tüm severity seviyeleri için patch deploy**
- [ ] Critical/High için: disclosure kararı insan tarafından alınır

## Üretilecek Artefaktlar

- Security review raporu (`.claude/rules/` veya handoff olarak)
- Patch kodu
- Güvenlik test senaryoları
- Incident report (kısa, hassas detay içermez)

## Completion Kriteri

- Güvenlik açığı kapatılmış ve test edilmiş
- Benzer açıklar için tarama yapılmış
- Incident timeline belgelenmiş
- Gerekirse kullanıcı bildirimi insan tarafından onaylanmış

## Handoff Formatı

```markdown
## Security Response: [açıklama - hassas detay gösterme]
- Severity: Critical/High/Medium/Low
- Etkilenen alan: ...
- Remediation özeti: ...
- Test edildi: evet/hayır
- Açık eylemler: ...
```

## Failure / Recovery

- Açık production'daysa: insan escalation → acil karar
- Fix regression yaratıyorsa: rollback → alternative approach
- Scope belirsizliği: Security Red Team ile sınır çiz, daha dar fix yap
- Gizlilik ihlali riski: insan onayı olmadan disclosure yapma
