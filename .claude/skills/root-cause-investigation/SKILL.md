---
name: root-cause-investigation
description: Bug çözümünde kök neden kanıtlanmadan fix yazılmamasını sağlar. Repro, hipotez günlüğü ve en fazla üç hipotezlik bir sınır kullanır.
agent: qa-automation
triggers:
  - bug-resolution workflow'u başladığında
  - Bir test beklenmedik şekilde başarısız olduğunda ve sebep açık olmadığında
  - Aynı hata ikinci kez "düzeltildi" denip geri geldiğinde
---

# Skill: Root Cause Investigation

Esin kaynağı: garrytan/gstack `/investigate` ve mattpocock/skills
`diagnosing-bugs` fikirleri. DevFlow'a uyarlanmış, kendi ifadelerimizle.

## Amaç

Belirtiyi değil sebebi düzeltmek ve deneme-yanılma ile token yakmayı
durdurmak. Kural basit: kök neden kanıtlanmadan fix yazılmaz.

## Prosedür

### 1. Repro

QA önce hatayı yeniden üreten ve başarısız olan bir test yazar
(`bug_resolution` görev grafiğindeki repro adımı). Repro yoksa fix yok.
Repro üretilemiyorsa bunu raporla ve dur; tahminle kod değiştirme.

### 2. Hipotez günlüğü

`.devflow/context/` altında görev için kısa bir günlük tut:

```text
H1: <iddia> — kanıt için yapılacak gözlem — sonuç: doğrulandı/çürüdü
H2: ...
```

Her hipotez tek bir gözlemle test edilir: bir log satırı, bir breakpoint
yerine geçen hedefli test, bir sorgu çıktısı. Kodu "deneme amaçlı"
değiştirip sonuca bakmak hipotez testi değildir.

### 3. Sınır

En fazla 3 hipotez. Üçü de çürürse dur ve insana şunu raporla: repro testi,
denenen hipotezler, elenen olasılıklar, bir sonraki en olası alan. Dördüncü
tahmine geçme.

### 4. Fix

Kök neden doğrulanınca:

- Fix yalnızca kök nedene dokunur. Komşu kodu "fırsat bu fırsat" diye
  düzenleme.
- Repro testi geçer, ilgili regression suite temiz kalır.
- Handoff'a tek paragraf: kök neden, neden daha önce yakalanmadı, eklenen test.
