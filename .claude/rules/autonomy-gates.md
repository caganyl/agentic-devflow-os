# Autonomy Gates

Hangi işlemlerin otomatik, hangilerinin insan onaylı olduğunu tanımlar.

## Otomatik (insan onayı gerektirmez)

- Kod okuma, grep, glob, dosya keşfi; requirement analizi, risk analizi,
  task graph ve context pack üretimi
- Taslak üretimi: requirement, ADR, contract, test, handoff (PR açmadan)
- Feature branch'te kod ve test yazma; local test, lint ve typecheck
- Security, design, EvalOps ve release scorecard raporu üretimi

## İnsan Onayı Gerektirir

- **Git ve deployment:** main merge, production deployment, force push,
  branch silme. Commit ve push da insan adımıdır (governed ajanlar için hook
  reddeder).
- **Veritabanı ve altyapı:** production migration, cloud resource
  oluşturma/silme, production altyapı değişikliği, rollback kararı
- **Güvenlik ve kimlik:** secret/API key, permission/role değişikliği,
  external service entegrasyonu başlatma
- **Dış sistemler:** gerçek MCP bağlantısı, external API'ye write, ödeme,
  e-posta/Slack/bildirim gönderme, PR yorumu yazma veya thread çözme
- **Geri döndürülemez:** veri silme veya toplu güncelleme, log/audit trail
  temizleme, production'da destructive operasyon

## Approval Gate Süreci

Bir işlem insan onayı gerektirdiğinde ajan durur; yapılacak işlemi, etkisini
ve varsa daha güvenli alternatifi tek özetle sunar. Onay beklenirken aynı
işlem yeniden denenmez ve tasarım dokümanlarına geri dönülmez.

## Recovery

Oturum kesilirse `status` çıktısı ve açık task listesi üzerinden devam
edilir; yarım kalan iş tamamlanmadan delivery bitmiş ilan edilmez.
