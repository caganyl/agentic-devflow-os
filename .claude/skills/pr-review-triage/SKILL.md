---
name: pr-review-triage
description: Açık bir PR'daki review bot ve insan yorumlarını okur, her birini düzelt/düzeltme/yanlış pozitif olarak sınıflar, düzeltmeleri implementer görevlerine çevirir ve insana yanıt planı bırakır. Yorum yazmaz, çözümlemez, commit/push yapmaz.
agent: integration-release
triggers:
  - PR açıldıktan sonra review bot'ları (Copilot, CodeRabbit, Bugbot, Claude Code Review) yorum bıraktığında
  - İnsan reviewer değişiklik istediğinde
---

# Skill: PR Review Triage

Esin kaynağı: pbakaus/agent-reviews (`resolve-agent-reviews` akışı).
DevFlow'a uyarlandı: dış sisteme yazma ve izleme döngüsü çıkarıldı.

## Amaç

Review bulgularını hızla kapatmak, ama DevFlow kurallarını bozmadan:
ajanlar commit/push yapmaz, GitHub'a yanıt yazmaz, thread çözümlemez. Bu
işlemler dış sisteme yazmadır ve insan onayı gerektirir (`autonomy-gates.md`).
Hook bu komutları governed ajanlar için reddeder.

## Prosedür

### 1. Yorumları oku (yalnızca okuma)

Proje `agent-reviews` paketini sabit sürümlü devDependency olarak içeriyorsa:

```bash
npx --no-install agent-reviews --unanswered --expanded
```

Yoksa GitHub CLI ile okuma:

```bash
gh pr view <PR> --comments
gh api repos/<owner>/<repo>/pulls/<PR>/comments
```

`--watch`, `--reply` ve `--resolve` kullanılmaz. Sürekli izleme döngüsü
token yakar; bir tur bittiğinde dur.

### 2. Sınıfla

Her yorum için tek karar:

| Karar | Ölçüt |
|---|---|
| FIX | Gerçek hata, güvenlik açığı, contract/AC ihlali veya ekibin REVIEW kurallarına göre "önemli" bulgu |
| WONT_FIX | Doğru gözlem ama bu REQ'in kapsamı dışında veya bilinçli bir karar (gerekçe tek cümle) |
| FALSE_POSITIVE | Bot kodu yanlış okumuş; kanıtı dosya:satır ile göster |

Üslup ve "nit" yorumları en fazla 5 tanesi FIX olabilir; gerisi WONT_FIX.

### 3. Düzeltmeleri dağıt

FIX maddelerini sahip olduğu yola göre implementer görevine çevir
(manifestteki `write_paths`). Aynı dosyaya iki rolü aynı anda atama.

### 4. İnsan için yanıt planı

`docs/release/pr-reviews/PR-<no>-round-<tur>.md` dosyasına yaz:

```text
PR: #<no>   Tur: <1|2>
| comment_id | karar | yanıt taslağı | ilgili görev/commit |
```

İnsan (veya insanın açık onayıyla ana oturum) düzeltmeleri commit eder,
push eder ve yanıtları gönderir.

### 5. Tur sınırı

En fazla 2 triage turu. İkinci turdan sonra gelen yeni bot yorumları ayrı bir
iş olarak insana raporlanır; otomatik üçüncü tur başlatılmaz.
