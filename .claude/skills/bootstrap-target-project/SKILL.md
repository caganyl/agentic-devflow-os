---
name: bootstrap-target-project
description: Target project .devflow/ yapısını doğrular ve framework / target repo ayrımını korur.
agent: delivery-lead
triggers:
  - Yeni bir target project'e DevFlow uygulanmadan önce
  - .devflow/ workspace'in doğru yapıda olup olmadığı kontrol edilmesi gerektiğinde
  - Framework repo ile target repo ayrımı sorgulandığında
---

# Skill: Bootstrap Target Project

## Amaç

Target project repository'sinde `.devflow/` çalışma alanını kurmak, doğrulamak ve
framework repo ile target repo arasındaki sınırı korumak.

## Prosedür

### 1. Ön Kontrol

Başlamadan önce şunları doğrula:

- Target path bir Git repository mi? (`git rev-parse --git-dir`)
- Target path framework repo ile aynı değil mi?
- Framework repo içinde bir alt dizin değil mi?

Herhangi biri başarısız olursa işlemi durdur ve kullanıcıya açıkla.

### 2. .devflow/ Yapısını Kur

**Önemli:** `init-target` yalnızca korumalı olmayan branch üzerinde çalışır.
`main` veya `master` üzerindeyken exit code 7 ile reddeder.

Önerilen akış: Doğrudan `launch` kullan — otomatik run worktree ve branch oluşturur,
`.devflow/` yalnızca yeni run worktree içinde başlatılır, main checkout değişmez.

```bash
# Önerilen: launch ile tam otomatik başlatma
python3 scripts/devflow_operations.py launch \
  --target PATH \
  --dry-run  # Önce planı görmek için

python3 scripts/devflow_operations.py launch \
  --target PATH \
  --objective "REQ-XXX: kısa açıklama"
```

Manuel `init-target` yalnızca feature branch üzerinde kullanılır:

```bash
python3 scripts/devflow_operations.py init-target --target PATH
```

Bu komut şu yapıyı oluşturur:

```text
.devflow/
├── project.json         ← proje meta verisi, run sayacı
├── policy.json          ← teslim politikası ve yasaklı operasyonlar
├── source-register.json ← kayıt edilmiş kaynaklar
├── context/             ← context pack'ler
├── plans/               ← delivery planları
├── task-packets/        ← görev paketleri
├── runs/                ← run state dosyaları
├── reports/             ← scorecard ve raporlar
├── cache/               ← gitignore'lanmış
└── logs/                ← gitignore'lanmış
```

### 3. Source Register'ı Doldur

`source-register.json` şu source tiplerini destekler:

| Tip | İzin verilen alanlar | Yasak alanlar |
|-----|----------------------|---------------|
| `local_docs` | id, label, path, relevance, confidence, notes | token, credential, password, secret |
| `notebooklm` | id, label, freshness, access_mode, relevance, notes | token, url, credential, notebook_content, raw_content |
| `obsidian` | id, label, relevance, notes | token, credential, password, vault_path (tüm vault) |
| `git_repository` | id, label, path, relevance, confidence, notes | token, credential, password |

NotebookLM için yalnız opaque label ve freshness kaydedilir — ham içerik, URL veya token kesinlikle saklanmaz.

Obsidian için yalnızca seçilmiş note referansları kaydedilir — tüm vault otomatik bağlanmaz.

### 4. Policy Doğrulama

`policy.json` şu kısıtları içermelidir:

- `forbidden_git_operations`: merge, force push, branch silme, reset, clean
- `protected_branches`: main, master
- `require_confirm_delivery: true`
- `dry_run_by_default: true`

### 5. Gitignore Kontrolü

Target project'in `.gitignore` dosyasında şunlar olduğunu kontrol et:
- `.devflow/cache/`
- `.devflow/logs/`

`.devflow/.gitignore` dosyasının da oluşturulduğunu doğrula.

### 6. Framework / Target Ayrımı Sınırları

- Framework repo (`~/Developer/agentic-devflow-os`) yalnızca DevFlow kontrol düzlemini taşır.
- Target project kendi kaynak kodunu ve `.devflow/` çalışma alanını taşır.
- Framework repo içinde target project artefaktı üretme.
- Target project içinde framework repo'ya doğrudan referans verme.
- Plugin output (`dist/devflow-plugin/`) üzerinden çalış.

## Hata Durumları

- **Git repo değil:** `init-target` exit code 3 ile reddeder — kullanıcıya `git init` öner.
- **Framework repo:** Exit code 2 ile reddeder — farklı bir dizin seç.
- **Korumalı branch (main/master):** Exit code 7 ile reddeder — `launch` kullan veya feature branch oluştur.
- **Zaten başlatılmış:** `--force` olmadan mevcut state korunur.
- **Yasak alan:** `validate_source_register_entry` exit code 10 ile durdurur.
- **Kirli çalışma ağacı (launch):** Exit code 11 — commit veya stash yap.
