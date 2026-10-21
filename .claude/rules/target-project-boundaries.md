---
paths:
  - ".devflow/**"
  - "dist/**"
  - "scripts/build_devflow_plugin.py"
  - "scripts/devflow_bootstrap.sh"
  - "scripts/devflow_operations.py"
---

# Target Project Boundaries

Framework repo (bu repo, `DEVFLOW_HOME`) ile target project repo arasındaki
sınır. Ayrıntılı çalışma modeli: framework repo'da `docs/ARCHITECTURE.md`.

## Framework Repo

**İçerir:** agent, skill, workflow, rule ve template tanımları (`.claude/`),
plugin build sistemi (`scripts/build_devflow_plugin.py`), guard ve hook'lar,
governance dokümantasyonu (`docs/`).

**İçermez:** target project kaynak kodu, migration dosyası, credential veya
secret, gerçek external MCP bağlantısı.

## Target Project Repo

- Framework'ün yalnızca plugin çıktısı (`dist/devflow-plugin/`) kullanılır;
  framework repo dosyalarına doğrudan referans verilmez.
- Durum `.devflow/` altında tutulur: `project.json`, `policy.json`,
  `source-register.json`, `context/`, `plans/`, `task-packets/`, `runs/`,
  `reports/`, `delegation-events/`; `cache/` ve `logs/` gitignore'dadır.
- `.devflow/runs/` ve `.devflow/reports/` yalnızca operations CLI ile yazılır.
- `.devflow/` içinde secret, credential veya kişisel veri bulunmaz.

## Geçiş Sınırları

- Framework → target: yalnızca plugin çıktısı ve bootstrap'ın kopyaladığı
  `CLAUDE.md` şablonu ile rule'lar. Ponytail de framework'teki vendored
  plugin klasöründen `--plugin-dir` ile yüklenir; target'a dosya kopyalanmaz.
- Target → framework: geri bildirim ve governance güncellemesi (PR ile).
- Credential, API key veya secret hiçbir yönde geçmez.
- Operations runner, target olarak framework repo verilirse exit 2 ile reddeder.
