# Workflow: Cost Optimization

## Ne Zaman Çağrılır?

Cloud, AI/LLM veya infrastructure maliyetleri beklenenden yüksek olduğunda;
planlı maliyet iyileştirmesi yapılması gerektiğinde; ya da model/provider
değişikliği değerlendirildiğinde.

## Girdiler

- Maliyet raporu veya alert
- Etkilenen servis veya bileşen listesi
- Hedef maliyet azaltma yüzdesi veya bütçe kısıtı
- Mevcut latency ve quality baseline
- Context pack

## Kullanılacak Roller

1. **Delivery Lead** — maliyet/kalite trade-off kararlarını önceliklendirme
2. **Solution Architect** — mimari iyileştirme seçenekleri, ADR
3. **AI/Data Engineer** — LLM/embedding model seçimi, prompt optimizasyonu, caching
4. **Integration/Release** — iyileştirme sonrası benchmark ve scorecard

## Gerekli Skill'ler

- `orchestrate-delivery`
- `task-routing`
- `evalops-regression` — model değişikliği kalite etkisi
- `release-scorecard`

## Approval Gate'ler

- [ ] Mevcut baseline ölçülmüş (cost, latency, quality)
- [ ] Iyileştirme seçenekleri değerlendirilmiş
- [ ] ADR yazılmış (önemli mimari değişiklik ise)
- [ ] Yeni benchmark tamamlanmış
- [ ] Quality regression olmadığı doğrulanmış
- [ ] **İnsan onayı: model/provider değişikliği production'a alınmadan önce**

## Üretilecek Artefaktlar

- Maliyet analizi raporu
- ADR (mimari değişiklik ise)
- Benchmark karşılaştırma raporu
- Güncellenmiş handoff

## Completion Kriteri

- Hedef maliyet azaltma sağlanmış
- Quality ve latency baseline'dan gerileme yok
- Değişiklik belgelenmiş ve test edilmiş

## Handoff Formatı

```markdown
## Cost Optimization: [bileşen adı]
- Önceki maliyet: ...
- Sonraki maliyet: ...
- Uygulanan değişiklik: ...
- Quality etkisi: ...
- Latency etkisi: ...
```

## Failure / Recovery

- Quality bozuluyor: değişikliği geri al, daha küçük adımla dene
- Maliyet hedefi tutmuyor: Solution Architect ile alternatif mimari değerlendir
- Benchmark anlaşmazlığı: EvalOps Reviewer ile eval metodolojisini netleştir
