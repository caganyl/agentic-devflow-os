# REQ-XXX — Handoff

<!-- Bütçe ~8.000 karakter (hook zorlar). Kanıtı olmayan alan "Eksik" yazılır;
     hiçbir alan "approved/passed/Go" varsayımıyla doldurulmaz. Ayrıntı yerine
     yol ver. Aynı içerik: framework repo'da docs/templates/REQ_HANDOFF_TEMPLATE.md. -->

## Kimlik

- REQ: `docs/product/requirements/REQ-XXX.md` · AC: `<yol veya "REQ içinde">`
- Branch / run: `<req-XXX-... | devflow/run-...>` · PR: `<#no | yok>`
- Durum: `<in-progress | ready-for-review | merged | blocked>`

## Kapsam

- Yapılan: `<1-3 madde>`
- Kapsam dışı: `<1-3 madde>`

## Kararlar ve Contract'lar

- ADR / karar notu: `<yol | yok>` (status: `<Proposed/Accepted>`)
- Contract: `<docs/contracts/... | exception>` · değişti mi: `<evet/hayır>`
- Karar sapmaları: `<uygulamada ADR'den sapma | yok>`

## AC Kapsamı

| AC | Karşılandı | Kanıt (test/rapor yolu) |
| --- | --- | --- |
| AC-1 | `<evet/hayır/kısmen>` | `<yol>` |

## Kanıt

- Test komutu ve sonucu: `<komut — geçen/toplam>` (`record-qa-evidence` kaydı: `<var/yok>`)
- Lint / typecheck / build: `<özet>`
- Security: `<rapor yolu, en yüksek severity | uygulanamaz>`
- UI durumları / design review: `<özet | uygulanamaz>`
- Eval (AI): `<scorecard yolu | uygulanamaz>`
- Migration ve rollback: `<migration yolu, rollback SQL yolu | yok>`

## Riskler ve Açık İşler

- `<risk veya açık iş>`

## İnsan Kararları

- [ ] Ownership manifest onayı
- [ ] Main merge
- [ ] Production deploy / migration / secret (uygulanabilirse)
- Release önerisi (insan kararı değildir): `<Go | Conditional Go: koşul | No-Go: gerekçe>`

## Sonraki Adım

- `<adım>` — owner: `<rol/insan>`
