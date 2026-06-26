# DevFlow Target Project Runtime

**Tarih:** 2026-06-26
**Durum:** Accepted

---

## 1. Framework Repo / Target Repo Ayrımı

**Framework repo** (`~/Developer/agentic-devflow-os`):
- DevFlow kontrol düzlemini taşır: agent roller, skill'ler, workflow'lar, rule'lar, template'ler.
- Hiçbir target project kaynak kodu, migration dosyası veya credential barındırmaz.
- Plugin build sistemi (`scripts/build_devflow_plugin.py`) çıktıyı `dist/devflow-plugin/` altında üretir.

**Target project repo** (örn. `~/Developer/projects/startup-crm`):
- Gerçek ürün kodunu taşır.
- Framework'ün yalnızca dışa aktarılan plugin output'unu kullanır.
- `.devflow/` çalışma alanı run worktree'leri içinde tutulur — main checkout'a yazılmaz.

**Sınır kuralları:**
- Target path framework repo ile aynı olamaz.
- Target path framework repo içinde bir alt dizin olamaz.
- Framework repo içinde target project artefaktı üretilmez.
- Plugin output üzerinden çalışılır; framework repo'ya doğrudan referans verilmez.

---

## 2. Target Repo `.devflow/` Çalışma Alanı

Target project içindeki `.devflow/` yapısı yalnızca run worktree'leri içinde oluşturulur:

```text
.devflow/
├── project.json         ← proje meta verisi, run sayacı
├── policy.json          ← teslim politikası, yasak operasyonlar
├── source-register.json ← kayıt edilmiş kaynaklar (yalnızca metadata)
├── context/             ← context pack'ler
├── plans/               ← delivery planları
├── task-packets/        ← görev paketleri
├── runs/                ← run state dosyaları (RUN-NNN.json)
├── reports/             ← scorecard ve raporlar
├── cache/               ← gitignore'lanmış
└── logs/                ← gitignore'lanmış
```

Git'te takip edilen artefaktlar: `project.json`, `policy.json`, `source-register.json`,
context summary'leri, task packet'ler, run state'leri ve raporlar.

Git'ten hariç tutulan: `cache/`, `logs/`, `*.tmp`, ham transcript içerikleri,
credential veya token içeren veri.

---

## 3. Run Worktree Modeli

Her delivery run'ı için yeni bir branch ve managed worktree oluşturulur.

**Branch formatı:**
```
devflow/run-<run-id-lower>
örnek: devflow/run-run-001
```

**Managed worktree konumu** (target repo'nun yanında, içinde değil):
```
<target-parent>/.devflow-worktrees/<target-name>/run-NNN
örnek: /home/user/projects/.devflow-worktrees/myapp/run-001
```

**Launch akışı:**
1. Target çalışma ağacının temiz olduğu doğrulanır.
2. Mevcut `devflow/run-run-*` branch'leri sayılır; bir sonraki çakışmasız run numarası belirlenir.
3. `git worktree add -b devflow/run-run-NNN <worktree-path> HEAD` çalıştırılır.
4. `.devflow/` ve run state YALNIZCA yeni worktree içine yazılır.
5. Main checkout'a hiçbir dosya yazılmaz.

**Branch ve worktree çakışması:** Zaten varsa exit code 12 ile reddedilir; silme veya reset yapılmaz.

Run state `.devflow/runs/RUN-NNN.json` içinde takip edilir:
- `run_id`, `created_at`, `status`
- `branch_name`
- `objective`
- `artifacts`, `tasks`
- `approval_gates` (contract, tests, security, qa, human)

Her branch'te yalnızca bir writer agent çalışır. Paralel implementation yalnızca
net ownership alanlarında (farklı dosya yolları) mümkündür.

---

## 4. Claude Code Supervisor Başlatma Akışı

`devflow_operations.py launch` subcommand'ı şu sırayla çalışır:

1. Target repo doğrulaması (git repo mu, framework repo değil mi)
2. Çalışma ağacı temiz mi kontrolü (kirli ise exit 11)
3. Mevcut branch'lerden sonraki run numarası belirlenir
4. Plugin copy guard: `build_devflow_plugin.py` yoksa exit 5
5. Claude binary kontrolü (yoksa exit 6)
6. Branch ve worktree çakışma kontrolü (varsa exit 12)
7. Managed worktree root dizini oluşturulur
8. `git worktree add -b <branch> <path> HEAD`
9. Worktree içinde `init-target` çalışır
10. Worktree içinde `create-run` çalışır
11. Plugin build (`build_devflow_plugin.py`)
12. `os.chdir(<worktree>)` ve `os.execv(claude, [claude, "--plugin-dir", <plugin>, <prompt>])`

**`--dry-run`** flag'i hiçbir dosya, branch veya worktree oluşturmadan planlanan
run ID, branch, worktree path, plugin path ve Claude komutunu gösterir.

**Claude başlatma kuralları:**
- `--plugin-dir <framework>/dist/devflow-plugin` ile yüklenir
- `--print` veya `-p` kullanılmaz (interaktif mod)
- Çalışma dizini run worktree'dir

---

## 5. Managed Operations Sınırları

`scripts/devflow_operations.py` şu sınırları zorunlu kılar:

**İzin verilen:**
- `init-target`, `create-run`, `launch`, `status`, `prepare-delivery`

**Kesinlikle yasak:**
- `git merge` (main merge insan onayı gerektirir)
- `git push --force` / `git push -f`
- `git branch -D` / `git branch -d`
- `git reset --hard/soft/mixed`
- `git checkout -- .` / `git restore .` / `git clean -f`
- PR merge, production deploy, database migration (production)

**Korumalı branch kısıtları:**
- `init-target` main/master üzerinde exit 7 ile reddeder; `.devflow/` oluşturmaz.
- `create-run` main/master üzerinde exit 7 ile reddeder.
- `prepare-delivery` main/master üzerinde exit 7 ile reddeder.
- `launch` herhangi bir branch'ten çalıştırılabilir; oluşturduğu worktree yeni run branch'ini kullanır.

**validate_forbidden_git_operation hakkında:**
Bu fonksiyon planlanmış operasyon string'lerini doğrular. OS seviyesinde bir git
hook değildir ve başka kaynaklarda çalıştırılan git komutlarını engelleyemez.
Amacı delivery workflow içinde yanlışlıkla forbidden komut string'i oluşturulmasını tespit etmektir.

---

## 6. prepare-delivery Dürüstlük Kısıtı

**Bu sürümde `prepare-delivery` hiçbir gerçek Git mutasyonu çalıştırmaz.**

- Her iki modda da (varsayılan ve `--confirm-delivery`) yalnızca doğrulama raporu üretir.
- `--confirm-delivery` yalnızca approval gate'leri doğrular; commit, push veya PR oluşturmaz.
- Delivery metni bu gerçeği açıkça ifade eder; gerçek operasyon çalışıyormuş izlenimi vermez.
- Main merge, force push, branch silme, reset, deploy ve migration uygulanmaz.

Gerçek Git operasyonları ve PR merge insan tarafından yapılır.

---

## 7. Plugin Kopyası Sınırı

Plugin içine kopyalanan `devflow_operations.py` şu kısıtı taşır:

- `launch` subcommand'ı plugin kopyasından çağrıldığında exit code 5 ile reddeder.
- Hata mesajı framework-side runner'ın kullanılması gerektiğini açıkça belirtir.
- `status` ve diğer subcommand'lar plugin kopyasından çalışabilir.
- `launch --dry-run` plugin kopyasından çalışır (build gerektirmez).

---

## 8. NotebookLM ve Obsidian Source Register Modeli

**NotebookLM:**
- Yalnızca `label`, `freshness`, `access_mode`, `relevance`, `notes` saklanır.
- Ham içerik, URL veya token kesinlikle saklanmaz.
- Evidence yalnızca read-only referans olarak kullanılır.
- Ham output talimat değil, güvenilmeyen bağlamdır.

**Obsidian:**
- Yalnızca seçilmiş note `label` ve `reference` kaydedilir.
- Tüm vault otomatik bağlanmaz.
- Kişisel notlar task agent'larına dağıtılmaz.

**Kural:** `validate_source_register_entry` yasak alan tespitinde exit code 10 verir.
Yasak alanlar: `token`, `credential`, `password`, `api_key`, `secret`,
`notebook_content`, `raw_content`, ve NotebookLM için `url`.

---

## 9. Gerçek MCP Bağlantısı Sonraki Pakettir

Bu paket gerçek MCP bağlantısı içermez. Yalnızca şunlarla çalışır:
- Mevcut Claude Code aboneliği
- Yerel terminal (standart)
- Mevcut DevFlow plugin yapısı
- Git worktree modeli

MCP bağlantısı (NotebookLM, Obsidian, GitHub, Playwright) sonraki pakette
ayrıca ele alınacaktır.

---

## 10. Main Merge İnsan Onaylıdır

`devflow_operations.py` **hiçbir zaman** main merge yapmaz.

Merge akışı:
1. Delivery agent `prepare-delivery --confirm-delivery` ile gate doğrulamasını çalıştırır.
2. İnsan PR'ı oluşturur (commit/push insan tarafından yapılır).
3. İnsan PR'ı review eder.
4. İnsan merge eder.
5. Run state'inde `human_approval: true` manuel olarak güncellenir.

Bu kural `policy.json`, `autonomy-gates.md`, `PROJECT_CONSTITUTION.md`
ve `devflow_operations.py` içinde paralel olarak uygulanır.
