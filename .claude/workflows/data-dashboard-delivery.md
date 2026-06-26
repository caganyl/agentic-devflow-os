# Workflow: Data Dashboard Delivery

## Ne Zaman Çağrılır?

Veri görselleştirme, analitik dashboard, raporlama veya BI bileşeni
geliştirildiğinde. Hem veri pipeline hem de UI katmanı içerir.

## Girdiler

- REQ-ID ve acceptance criteria
- Veri kaynakları ve schema bilgisi
- Metrik ve KPI tanımları
- Görselleştirme gereksinimleri (grafik tipi, filtreleme, drill-down)
- Context pack

## Kullanılacak Roller

1. **Delivery Lead** — plan, data pipeline ve UI bağımlılıkları
2. **AI/Data Engineer** — veri pipeline, aggregation, query optimizasyonu
3. **Design Reviewer** — dashboard layout, bilgi hiyerarşisi, erişilebilirlik
4. **Backend Engineer** — veri API'si ve servis katmanı
5. **QA Automation** — veri doğruluk testleri ve UI regression

## Gerekli Skill'ler

- `orchestrate-delivery`
- `task-routing`
- `visual-design-review` — dashboard UX kalitesi
- `qa-acceptance-verification`
- `release-scorecard`

## Approval Gate'ler

- [ ] Metrik ve KPI tanımları onaylanmış
- [ ] Veri kaynakları erişimi doğrulanmış
- [ ] API contract hazır
- [ ] Design review tamamlanmış
- [ ] Veri doğruluk testleri geçiyor
- [ ] **İnsan onayı: main merge**

## Üretilecek Artefaktlar

- Dashboard implementation kodu
- Veri pipeline veya query kodu
- API contract
- Veri doğruluk test suite
- Güncellenmiş handoff

## Completion Kriteri

- Tüm metrikler doğru hesaplanıyor (test ile kanıtlanmış)
- Dashboard responsive ve erişilebilir
- Veri kaynağı değiştiğinde grafik günceleniyor
- Performance hedefleri karşılanmış

## Handoff Formatı

```markdown
## Dashboard: [dashboard adı]
- REQ-ID: REQ-XXX
- Veri kaynakları: ...
- Metrikler: ...
- Bilinen veri kalitesi sınırlamaları
- Refresh stratejisi
```

## Failure / Recovery

- Veri kalitesi sorunu: AI/Data Engineer root cause analizi
- Performance sorunu: Backend Engineer + index/query optimizasyonu
- UX beklenti uyumsuzluğu: Design Reviewer ile re-review
