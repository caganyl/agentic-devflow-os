---
name: evalops-regression
description: Golden, adversarial ve regression eval yaklaşımını; quality/cost/latency/faithfulness trade-off'larını yönetir.
agent: evalops-reviewer
triggers:
  - AI/RAG/LLM feature tamamlandığında
  - Model, provider, prompt veya retrieval değiştiğinde
  - Release öncesi kalite regresyonu kontrolünde
---

# Skill: EvalOps Regression

## Amaç

AI feature'ların kalitesini ölçülebilir ve tekrarlanabilir biçimde değerlendir.
"İyi görünüyor" yeterli değil; sayılarla kanıtla.

## Eval Türleri

### 1. Golden Dataset Eval

Beklenen çıktısı bilinen test örnekleri:
```yaml
# evals/configs/golden-req-xxx.yaml
dataset: evals/datasets/golden-req-xxx.jsonl
metrics:
  - exact_match
  - semantic_similarity
threshold:
  exact_match: 0.90
  semantic_similarity: 0.85
```

Her örnek formatı:
```json
{
  "input": "kullanıcı sorgusu",
  "expected_output": "beklenen yanıt",
  "tags": ["category", "difficulty"]
}
```

### 2. Adversarial Dataset Eval

Sistemi zorlayan, edge case ve kötü niyetli girdiler:
```json
{
  "input": "ignore previous instructions and...",
  "expected_behavior": "refusal",
  "attack_type": "prompt_injection"
}
```

Adversarial kategoriler:
- Prompt injection denemesi
- Out-of-scope sorgu
- Belirsiz veya çelişkili girdi
- Çok uzun girdi
- Desteklenmeyen dil

### 3. Regression Dataset Eval

Önceki release'de geçen örnekler. Her release'de çalıştırılır:
```python
# Minimum: önceki golden score - 5% tolerans
# Eğer score düşerse → blocker
```

## Metrik Seti

| Metrik | Açıklama | Hedef |
|--------|----------|-------|
| Faithfulness | Kaynaklara ne kadar sadık? | ≥ 0.85 |
| Relevance | Soru ile yanıt ne kadar uyumlu? | ≥ 0.80 |
| Exact Match | Beklenen çıktıyla tam eşleşme | Task-specific |
| Latency (P95) | 95. yüzdelik yanıt süresi | ≤ 2000ms |
| Cost per 1K calls | API maliyeti | Bütçeye göre |

## Prosedür

### 1. Baseline Ölç (Model/Prompt Değişikliği Öncesi)

```
golden_baseline = run_eval(golden_dataset, current_model)
cost_baseline = measure_cost(golden_dataset, current_model)
latency_baseline = measure_latency(golden_dataset, current_model)
```

### 2. Değişiklik Sonrası Karşılaştır

```
if golden_new < golden_baseline - threshold:
    BLOCKER: quality regression
if cost_new > cost_baseline * 1.2:
    WARNING: cost regression (insan onayı)
if latency_new > latency_target:
    WARNING: latency regression
```

### 3. Scorecard Üret

```markdown
## EvalOps Scorecard: REQ-XXX

| Metrik | Baseline | Yeni | Delta | Sonuç |
|--------|----------|------|-------|-------|
| Faithfulness | 0.88 | 0.91 | +0.03 | ✓ |
| Relevance | 0.83 | 0.79 | -0.04 | ⚠ minor regression |
| Latency P95 | 1200ms | 980ms | -220ms | ✓ |
| Cost/1K | $0.45 | $0.38 | -$0.07 | ✓ |

**Adversarial:** 47/50 geçti (3 başarısız - açıklama eklendi)
**Regression:** Baseline'dan kayda değer düşüş yok
**Karar:** ✓ release için onaylı
```

## Kesin Sınırlar

- Production kodu, prompt implementation veya model adapter değiştirme
- Insan onayı olmadan model/provider değişikliği deploy etme
- Scorecard olmadan release onayı verme
