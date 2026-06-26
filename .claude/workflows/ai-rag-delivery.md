# Workflow: AI/RAG Feature Delivery

## Ne Zaman Çağrılır?

LLM, RAG, embedding, retrieval pipeline, AI agent veya ML bileşen içeren
bir feature geliştirildiğinde. Standard feature delivery'den farklı olarak
eval ve regression adımları zorunludur.

## Girdiler

- REQ-ID ve acceptance criteria
- AI/ML ile ilgili kısıtlamalar (model, provider, cost bütçesi, latency hedefi)
- Golden dataset veya eval konfigürasyon taslağı
- Varsa mevcut benchmark sonuçları
- Context pack

## Kullanılacak Roller

1. **Delivery Lead** — plan, risk analizi, eval gate noktalarını belirleme
2. **AI/Data Engineer** — LLM entegrasyonu, RAG pipeline, embedding, prompt engineering
3. **Backend Engineer** — AI feature backend API ve servis katmanı
4. **EvalOps Reviewer** — golden dataset, adversarial eval, quality scorecard
5. **Security Red Team** — prompt injection, data leakage, model güvenlik riskleri
6. **Integration/Release** — release scorecard ve merge recommendation

## Gerekli Skill'ler

- `orchestrate-delivery`
- `task-routing`
- `evalops-regression` — eval ve regression yönetimi
- `adversarial-security-review` — prompt injection ve AI-specific riskler
- `release-scorecard`

## Approval Gate'ler

- [ ] Eval konfigürasyonu onaylanmış
- [ ] Golden dataset hazır ve review edilmiş
- [ ] Quality threshold'lar tanımlanmış (faithfulness, relevance, latency, cost)
- [ ] Adversarial eval tamamlanmış
- [ ] Security review (özellikle prompt injection) tamamlanmış
- [ ] EvalOps Reviewer sign-off verilmiş
- [ ] **İnsan onayı: main merge ve production model değişikliği**

## Üretilecek Artefaktlar

- AI feature implementation kodu
- Eval konfigürasyonu (`evals/configs/`)
- Quality scorecard (`evals/scorecards/`)
- Adversarial test sonuçları (`evals/results/`)
- Güncellenmiş handoff

## Completion Kriteri

- Golden dataset eval geçiyor (tanımlı threshold)
- Adversarial eval kabul edilebilir sınırda
- Cost ve latency hedefleri karşılandı
- Prompt injection ve data leakage riskleri giderildi

## Handoff Formatı

```markdown
## AI Feature: [feature adı]
- REQ-ID: REQ-XXX
- Model/Provider: ...
- Eval sonuçları özeti: quality / cost / latency
- Bilinen sınırlamalar
- Regression risk alanları
```

## Failure / Recovery

- Eval threshold aşılıyor: AI/Data Engineer ile prompt/retrieval iyileştirme
- Latency/cost hedefi tutmayan: Solution Architect ile model/provider değerlendirme
- Prompt injection: Security Red Team severity tespiti → blocker kararı
- Session kesilmesi: eval config ve açık sonuçlar üzerinden devam
