# DevFlow Mimarisi

Agentic DevFlow OS'un nasıl çalıştığının tek güncel anlatımı. Kurallar:
[`PROJECT_CONSTITUTION.md`](../PROJECT_CONSTITUTION.md); ownership ve merge
süreci: [`docs/ownership/README.md`](ownership/README.md); rol yetkileri:
[`docs/decisions/AGENT_CAPABILITY_MATRIX.md`](decisions/AGENT_CAPABILITY_MATRIX.md).
Eski çalışma modeli belgeleri `docs/archive/` altındadır ve güncel değildir.

## 1. Ne işe yarar

DevFlow, Claude Code üzerine kurulu bir teslimat sistemidir. İşi rollere
böler, her rolün neye dokunabileceğini araç çağrısı seviyesinde hook'larla
zorlar ve yapılan işi Git'teki kanıta bağlar. Ajan özeti kanıt değildir;
kanıt, CLI'ın ölçtüğü ve run state'e yazdığı kayıttır.

## 2. Topoloji

```
agentic-devflow-os/  (framework repo, DEVFLOW_HOME)
├── .claude/        agent, skill, rule, workflow, template; framework'ün kendi hook'ları
├── hooks/          plugin hook kaydı (hooks.json)
├── scripts/        operations CLI, guard, recorder, validator, mimari tarayıcı, bootstrap
├── bin/            claude-devflow, devflow-manifest
└── dist/           build çıktısı (gitignore)
    ├── devflow-plugin/          → Claude Code plugin'i
    └── codex-devflow-plugin/    → Codex Phase 1A paketi

hedef proje/        (iş yapılan repo)
├── CLAUDE.md       bootstrap'ın koyduğu TARGET_CLAUDE.md
├── .claude/rules/  bootstrap'ın kopyaladığı rule'lar
├── .devflow/       run durumu (bkz. §6)
└── docs/ …         requirement, contract, ADR, ownership, handoff
```

Framework repo hedef proje kodu, migration veya credential içermez. Hedef
projeye yalnızca plugin çıktısı ve bootstrap'ın kopyaladıkları gider.
Operations CLI, target olarak framework repo verilirse exit 2 ile reddeder.

## 3. Kurulum (tek yöntem)

```bash
~/Developer/agentic-devflow-os/bin/install   # komutları ~/.local/bin'e bağlar
cd <hedef-proje> && claude-devflow
```

Komutlar framework kökünü (`DEVFLOW_HOME`) kendi gerçek konumlarından bulur;
`DEVFLOW_HOME` yalnızca farklı bir checkout kullanmak için verilir.

`bin/claude-devflow` önce `scripts/devflow_bootstrap.sh`'i, sonra
`claude --plugin-dir "$DEVFLOW_HOME/dist/devflow-plugin"` çalıştırır. Düz
`claude` plugin'i yüklemez. Bootstrap her adımda idempotenttir:

| Adım | Davranış |
| --- | --- |
| Framework repo kontrolü | Framework repo içindeyse hiçbir şey yapmadan çıkar |
| Plugin | `dist/devflow-plugin` yoksa veya kaynaklardan eskiyse build eder |
| Git | Repo değilse `git init`; `req-NNN-*` branch'inde değilse `req-001-bootstrap` branch'ine geçer |
| Politika | `CLAUDE.md` yoksa `TARGET_CLAUDE.md`'yi koyar, rule'ları `.claude/rules/` altına kopyalar |
| İskelet | `docs/…`, `design/reviews`, `evals`, `backend`, `frontend`, `migrations`, `tests`, `ai` |
| Ownership | `REQ-001` iskelet requirement'ı ve yalnızca iskelet dizinlerini kapsayan `approved` `docs/ownership/REQ-001.json` |
| Workspace | `init-target` ile `.devflow/`; `.devflow/cache/` ve `.devflow/logs/` `.gitignore`'a |

Feature REQ'leri için `devflow-manifest <REQ-no>` yalnızca `draft` manifest
üretir; `approved` yapmak insan adımıdır.

## 4. Plugin içeriği

`scripts/build_devflow_plugin.py` şunları `dist/devflow-plugin/` altına
koyar: `agents/`, `skills/`, `templates/`, `workflows/`, `rules/`; script'ler
(`devflow_operations.py`, `devflow_target_guard.py`,
`devflow_delegation_recorder.py`, `validate_ownership_manifest.py`,
`devflow_arch_scan.py`, `devflow_bootstrap.sh`, `devflow_new_manifest.sh`);
`hooks/hooks.json` ve dört shell hook (`session-start.sh`, `protect-main.sh`,
`protect-sensitive-paths.sh`, `enforce-role-boundaries.sh`). Böylece hedef
projede framework repo'nun kendisine uyguladığı korumanın aynısı çalışır.
Plugin `settings.json`, MCP konfigürasyonu veya credential taşımaz.

Not: plugin subagent'larında `hooks`, `mcpServers` ve `permissionMode`
frontmatter alanları Claude Code tarafından yok sayılır; kısıtlar bu yüzden
`tools` listesi ve plugin hook'larıyla uygulanır.

## 5. Orkestrasyon modeli

- **Tek orkestratör ana oturumdur** (`orchestrate-delivery` skill'i).
  Görevleri o dağıtır, CLI kayıt komutlarını o çalıştırır.
- **`delivery-lead` planlayıcıdır:** task graph, minimum rol seti, gate'ler
  ve context pack taslağı döner. `Agent`, `Write` ve `Bash` aracı yoktur.
- **Roller ve sıra:** product-analyst → (ADR eşiği varsa solution-architect +
  adr-reviewer) → contract-broker → insan (manifest onayı) → implementer'lar
  → QA → Security → Docs Writer → Integration/Release → insan (commit, push,
  merge). Routing tablosu: `.claude/rules/task-routing.md`.
- **Tasarım fazı döngü kesicisi:** ADR yalnızca eşik sağlanırsa; bir branch'te
  en fazla bir yeni ADR; en fazla 2 review turu; Accepted ADR dondurulur;
  run içinde adr-reviewer APPROVE'u ve `record-contract-evidence` kaydı
  implementasyonu açar (anayasa §5a). Diğer review'lar en fazla bir yeniden
  inceleme alır. İnsan kapısı veya ownership blokajında architect yeniden
  çağrılmaz; tek özetle durulur.
- **Dispatch:** varsayılan subagent. Agent team yalnızca `launch --agent-teams`
  ile, bağımsız işler varken ve aynı dosyaya eşzamanlı yazma yokken. Aynı
  `write_paths`'e paralel yazma görevi verilmez.
- **Kademeli bağlam:** alt ajana yol + kısa özet verilir; eksikse
  `CONTEXT_REQUEST:` ile en fazla 3 kalem, en fazla 2 tur.

## 6. Hedef projede `.devflow/`

`init-target` ve `launch` (yalnızca run worktree'sinde) oluşturur:

```
.devflow/
├── project.json            proje meta verisi, run sayacı, current_run_id
├── policy.json             yasak git operasyonları, korumalı branch'ler
├── source-register.json    kaynak metadata'sı (ham içerik/token yok)
├── .gitignore              cache/, logs/, *.tmp
├── context/                context pack'ler (ana oturum yazar)
├── plans/                  plan notları (ana oturum yazar)
├── task-packets/           RUN-NNN-TASK-NNN.json (generate-task-graph yazar)
├── runs/                   RUN-NNN.json — imzalı run state; yalnızca CLI yazar
├── reports/                RUN-NNN-report.json, RUN-NNN-scorecard.md; yalnızca CLI yazar
├── delegation-events/      SubagentStart/Stop kaydı (recorder yazar)
├── cache/                  gitignore; state-signing.key
└── logs/                   gitignore
```

Task graph `runs/RUN-NNN.json` içindeki `tasks` alanı ve task packet'lerdir.
Target guard `.devflow/runs/` ve `.devflow/reports/` altına Write/Edit'i
reddeder; run state'teki REQ bağı bu yüzden ajan kontrolünde değildir.

## 7. Managed run

```bash
claude-devflow launch --objective "REQ-NNN: ..." --req-id REQ-NNN [--dry-run] [--agent-teams]
# = python3 scripts/devflow_operations.py launch --target "$PWD" ...
```

`launch`: çalışma ağacı temiz olmalı (exit 11) → çakışmasız run numarası →
`<hedef-üst>/.devflow-worktrees/<hedef-adı>/run-NNN` worktree'si ve
`devflow/run-run-NNN` branch'i (çakışmada exit 12) → worktree içinde
`init-target` + `create-run` (`--req-id` ile manifeste bağlanır) → plugin
build → `DEVFLOW_RUN_WORKTREE`, `DEVFLOW_RUN_BRANCH`,
`DEVFLOW_OPERATIONS_SCRIPT`, `DEVFLOW_ARCH_SCAN_SCRIPT` ile interaktif
`claude --plugin-dir` (agent teams yalnızca child env'de). Main checkout'a
dokunulmaz. `--req-id` yoksa implementer yazımı hook tarafından reddedilir.

Operations CLI komutları: `init-target`, `create-run`, `launch`, `status`,
`generate-task-graph`, `update-task-status`, `record-qa-evidence`,
`record-security-evidence`, `record-contract-evidence`,
`record-work-product-evidence`, `generate-run-report`, `prepare-delivery`.
`prepare-delivery` yalnızca doğrulama raporu üretir; gerçek Git mutasyonu
yapmaz. Çıkış kodları script docstring'indedir (ör. 2 framework repo, 7
korumalı branch, 9 gate geçilmedi, 16 aktif run'da `--force`, 21 ölçülen exit
kodu ile bildirilen test sayıları çelişiyor, 22 run state kilidi alınamadı).

Kanıt kuralları (CLI zorlar):

- **Görev sırası:** bir implementation task'ı, bağımlılıkları `completed`
  veya `verified` olmadan `in_progress`'e geçemez.
- **Work product:** kanıt dosyası boş olamaz ve run'ın `base_commit`'ine göre
  değişmiş (veya yeni) olmalıdır; commit edilmiş run işi de sayılır.
- **QA:** `--total/--passed/--failed` tutarlı olmalı (total>0,
  passed+failed=total, exit 0 yalnızca failed=0); `true`, `:`, `exit 0`,
  `echo …` gibi boş komutlar reddedilir.
- **Documentation task'ı (010, docs-writer):** kanıtı bir `README.md` veya
  `docs/handoffs/` altındaki dosyadır; release task'ı ona bağlıdır.
- Run state'e her yazım dosya kilidiyle yapılır (`DEVFLOW_STATE_LOCK_TIMEOUT`).

## 8. Hook'lar ve sınırlar

Framework repo'da `.claude/settings.json`, hedef projede plugin'in
`hooks/hooks.json` dosyası kaydeder. Guard'lar fail-closed çalışır: `jq` veya
`python3` yoksa, girdi bozuksa veya hook beklenmedik bir hatayla biterse çağrı
exit 2 ile reddedilir. Bash komut filtreleri "best effort"tur; asıl sınır izin
kuralları ve worktree izolasyonudur.

| Hook | Ne yapar |
|---|---|
| `devflow_target_guard.py` (plugin) | `git merge`, force push, branch silme, `git reset`, `git clean -f`, `git checkout -- .`, `git restore .`, `rm -rf`; `.env*`, secret/credential, MCP config, Claude ayarları ve hook dosyalarına yazma; `DEVFLOW_RUN_WORKTREE` dışına çıkma; `.devflow/runs|reports` yazımı |
| `protect-main.sh` | Oturum veya hedef dosyanın checkout'u `main`/`master` (ya da `DEVFLOW_PROTECTED_BRANCHES`) üzerindeyse yazımı; `git -C`/`--git-dir`/`cd` ile korumalı checkout'a giden Git mutasyonunu reddeder |
| `protect-sensitive-paths.sh` | `.env*`, `secrets/`, anahtar dosyaları, Claude ayarları ve hook script'lerine dokunmayı reddeder |
| `enforce-role-boundaries.sh` | Rol bazlı yazma yolları; implementer'lar için branch + onaylı manifest + `write_paths`; doküman rollerinde Bash yok; governed ajanlarda Git mutasyonu (`git add/commit/push/branch/...`), paket kurulumu, dosyaya yönlendirme, dış sisteme yazma ve saldırı aracı yasağı; ADR loop breaker (ana oturum dahil; branch başına en fazla 1 yeni ADR, dondurulmuş ADR yalnızca statüsüyle emekliye ayrılır); handoff/requirement 8000 karakter büyüme bütçesi; mimari profil ve docs-writer kapıları |
| `session-start.sh` | Repo, branch, main koruması, profil durumu ve son handoff'u bağlama ekler |
| `devflow_delegation_recorder.py` (plugin) | SubagentStart/Stop için içeriksiz kayıt; hata alsa da teslimatı bloklamaz |

Commit, push ve merge insan adımıdır: governed ajanlar için `git commit`
dahil Git mutasyonu hook tarafından reddedilir; ana oturumun komutları target
guard'dan geçer ama main merge, force push ve geçmiş silme yine reddedilir.

## 9. MCP, NotebookLM ve Obsidian

DevFlow plugin'i MCP sunucusu tanımlamaz ve bağlamaz; gerçek bir MCP
bağlantısı insan onayıdır. Politika
[ADR-009](architecture/adr/ADR-009-mcp-policy-simplified.md): Claude Code izin
kuralları ve isteğe bağlı `mcp__*` PreToolUse hook'u. NotebookLM ve Obsidian
bağlıysa yalnızca evidence/stratejik not özeti olarak kullanılır
(`notebooklm-grounded-retrieval`, `obsidian-project-context`); kaynak
sıralamasının en altındadır.

## 10. Bilinen sınırlar

- Guard bir sandbox değildir: yalnızca Claude Code araç çağrılarını kapsar;
  terminale doğrudan yazılan komutları ve alt süreçleri yakalamaz. Bu boşluğu
  CI ownership diff gate'i kapatır.
- Delegation kanıtı yaşam döngüsüdür, içerik değildir.
- Mimari tarayıcı sezgiseldir; çıktısı insan onayına kadar "gözlem"dir.
- Branch protection mevcut GitHub planında etkin değildir; insan merge
  kontrolü zorunludur (bkz. `docs/ownership/README.md`).
