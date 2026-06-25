# REQ Handoff Template

Bu şablon, `docs/handoffs/REQ-XXX.md` dosyası oluşturulurken kullanılır
(bkz. `docs/handoffs/README.md`). Her alan placeholder içerir; hiçbir alan
otomatik olarak "approved", "passed" veya "Go" varsayımıyla doldurulmamıştır.
Bu şablonu kullanan rol, her alanı gerçek kanıtla doldurmalı; kanıt yoksa
"Bilinmiyor" veya "Eksik" olarak işaretlemelidir.

---

## Requirement Kimliği ve Başlık

- **REQ-ID:** `<REQ-XXX>`
- **Başlık:** `<requirement başlığı>`
- **Requirement dosyası:** `<docs/product/requirements/REQ-XXX.md veya yol>`
- **Acceptance criteria dosyası:** `<yol>`

## Kaynak Branch / PR / Commit Bilgileri

- **Implementation branch:** `<req-XXX-kisa-aciklama>`
- **Ownership registry branch (varsa):** `<ownership-REQ-XXX-kisa-aciklama>`
- **PR numarası/linki:** `<#PR>`
- **Base SHA:** `<sha>`
- **Head SHA:** `<sha>`
- **Worktree:** `<worktree yolu veya "Bilinmiyor">`

## Kapsam Özeti

- **Bu PR'da yapılan:** `<özet>`
- **Bu PR'da yapılmayan / out-of-scope:** `<özet>`

## Acceptance Criteria Coverage

| Kriter | Karşılandı mı | Kanıt |
| --- | --- | --- |
| `<kriter 1>` | `<Evet/Hayır/Kısmen>` | `<test/log/ekran görüntüsü referansı>` |
| `<kriter 2>` | `<Evet/Hayır/Kısmen>` | `<...>` |

## Contract ve Mimari Etkiler

- **Etkilenen contract'lar:** `<docs/contracts/... veya "Yok">`
- **Contract değişikliği var mı:** `<Evet/Hayır>`
- **İlgili ADR'ler:** `<docs/architecture/adr/ADR-XXX veya "Yok">`
- **Yeni mimari karar gerekiyor mu:** `<Evet/Hayır — gerekiyorsa ayrı ADR sürecine yönlendirin>`

## Database / Migration Etkisi

- **Migration var mı:** `<Evet/Hayır>`
- **Migration dosyası/yolu:** `<yol veya "Yok">`
- **Rollback notu:** `<rollback adımı veya "Yok — migration yok">`
- **Production migration onayı:** `<Bekliyor / İnsan onayı alındı: kim, ne zaman>`

## Test Evidence

- **Çalıştırılan testler:** `<komut(lar)>`
- **Sonuç:** `<pass/fail özeti>`
- **Lint sonucu:** `<özet>`
- **Typecheck sonucu:** `<özet>`
- **UI state kontrolü (varsa):** loading / empty / error / permission /
  mobile → `<her biri için durum>`
- **AI/eval regression kontrolü (varsa):** `<özet veya "Uygulanamaz">`

## Security Bulguları

- **Security Red Team incelemesi yapıldı mı:** `<Evet/Hayır>`
- **Bulgular:** `<liste veya "Yok">`
- **Açık/kapalı durumları:** `<liste>`

## Accessibility / UI Review

- **Design Reviewer incelemesi yapıldı mı:** `<Evet/Hayır/Uygulanamaz>`
- **Bulgular:** `<liste veya "Yok">`

## AI / Model / Eval Etkisi

- **Bu REQ bir AI/model değişikliği içeriyor mu:** `<Evet/Hayır>`
- **Golden dataset / eval güncellemesi:** `<özet veya "Uygulanamaz">`
- **Latency/cost etkisi:** `<özet veya "Uygulanamaz">`

## Bilinen Riskler ve Açık İşler

- `<risk 1>`
- `<açık iş 1>`

## Rollback veya Recovery Notları

- **Rollback adımı:** `<adım veya "Tanımlanmadı">`
- **Recovery sorumlusu:** `<rol/insan>`

## İnsan Onay Gereksinimleri

- [ ] Ownership manifest approval (insan maintainer)
- [ ] Main merge (insan maintainer)
- [ ] Production deploy onayı (insan maintainer) — uygulanabilirse
- [ ] Production migration onayı (insan maintainer) — uygulanabilirse
- [ ] Secret/API key/cloud değişikliği onayı (insan maintainer) — uygulanabilirse

## Release Readiness Önerisi

> Aşağıdaki seçeneklerden birini işaretleyin. Bu öneri bir insan kararı
> değildir; nihai kararı insan maintainer verir.

- [ ] Go
- [ ] Conditional Go — koşul: `<koşulu yazın>`
- [ ] No-Go — gerekçe: `<gerekçeyi yazın>`

## Human Maintainer Kararı

- **Karar:** `<Bekliyor / Onaylandı / Reddedildi>`
- **Karar veren:** `<isim>`
- **Tarih:** `<tarih>`
- **Not:** `<varsa ek not>`

## Sonraki Adım / Owner

- **Sonraki adım:** `<özet>`
- **Owner:** `<rol veya isim>`
