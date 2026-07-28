# Sistem Genel Bakış

Bu belge Agentic DevFlow OS'un ne olduğunu, hangi parçalardan oluştuğunu ve
nasıl çalıştığını anlatır. Kurulum ve günlük kullanım için
[operations/REQ_LIFECYCLE_RUNBOOK.md](operations/REQ_LIFECYCLE_RUNBOOK.md),
kuralların tam metni için [PROJECT_CONSTITUTION.md](../PROJECT_CONSTITUTION.md).

## Ne işe yarar

DevFlow, Claude Code'un üzerine kurulmuş bir teslimat işletim sistemidir.
Yazılım geliştirmeyi rollere böler, her rolün neye dokunabileceğini kısıtlar ve
yapılan işi kanıta bağlar.

Temel fikir şudur: bir AI ajanına "şunu yap" demek yerine, **kimin ne
yapabileceğini önceden tanımlayıp kuralları çalışma anında zorlamak.** Kurallar
belge olarak yazılı değildir yalnızca; hook'lar aracılığıyla araç çağrısı
seviyesinde uygulanır.

## Topoloji

Tek bir kaynak repo, iki çalıştırılabilir paket üretir:

```
agentic-devflow-os/                    ← framework repo (kaynak)
├── .claude/                           agent, skill, rule, template tanımları
├── scripts/                           guard, recorder, operations runner, build
├── docs/                              governance, ADR, contract, runbook
└── dist/
    ├── devflow-plugin/                → Claude Code paketi
    └── codex-devflow-plugin/          → Codex paketi
```

`dist/` **gitignore'dadır**; build çıktısı commit edilmez, her makinede
`scripts/build_devflow_plugin.py` ile üretilir.

Claude Code'a bağlanması symlink ile yapılır:

```bash
python3 scripts/build_devflow_plugin.py
ln -sfn "$PWD/dist/devflow-plugin" ~/.claude/skills/devflow-plugin
```

### Framework repo ≠ hedef proje

Bu ayrım sistemin en önemli sınırıdır. DevFlow'un kendisi framework repo'da
yaşar. İş yaptığınız proje ayrı bir repodur ve orada yalnızca `.devflow/` adında
bir çalışma alanı açılır. Operations runner, hedef yolun framework repo olması
durumunda çıkış kodu 2 ile reddeder.

## Giriş noktası: `claude-devflow`

Sistem `claude-devflow` shell fonksiyonu ile açılır (`~/.zshrc`). Düz `claude`
plugin'i yüklemez; agent, skill ve hook'lar devreye girmez.

Fonksiyon önce `scripts/devflow_bootstrap.sh` çalıştırır, sonra
`claude --plugin-dir dist/devflow-plugin` ile oturumu başlatır. Bootstrap
bulunulan dizini şu hale getirir:

| Adım | Davranış |
| --- | --- |
| Framework repo kontrolü | Framework repo içindeyse hiçbir şey yapmadan çıkar |
| Plugin | `dist/` yoksa veya kaynaklardan eskiyse yeniden build eder |
| Git | Repo değilse `git init`, `main`/`master` üzerindeyse `req-001-bootstrap` branch'ine geçer |
| Politika | `CLAUDE.md` yoksa `templates/TARGET_CLAUDE.md`'den koyar, `rules/*.md` dosyalarını `.claude/rules/` altına dağıtır |
| İskelet | `docs/`, `design/reviews`, `evals`, `backend`, `frontend`, `migrations`, `tests`, `ai` |
| Ownership | `docs/product/REQ-001.md` + approved `docs/ownership/REQ-001.json` üretir ve validator ile doğrular |
| Workspace | `.devflow/` başlatır, cache/log yollarını `.gitignore`'a ekler |

Her adım idempotenttir; mevcut dosyanın üzerine yazmaz. Böylece aynı komut hem
boş klasörde hem devam eden projede güvenle çalışır.

REQ-001 manifesti bilinçli olarak `approved` üretilir: kapsamı yalnızca iskelet
dizinleridir, ürün davranışı tanımlamaz ve implementer agent'ların ilk anda
tamamen kilitli kalmasını önler. Feature REQ'leri bu istisnayı paylaşmaz —
`devflow-manifest <REQ-no>` yalnızca `draft` manifest üretir, `approved`'a
çevirmek insan adımıdır.

## Anayasa

Her şeyin dayandığı belge `PROJECT_CONSTITUTION.md`. Dört şey tanımlar:

**Gerçeğin kaynağı sıralaması.** Çelişki durumunda hangisinin kazanacağı
baştan yazılıdır: Anayasa → onaylı ADR → onaylı contract → requirement →
kod ve testler → handoff → NotebookLM → Obsidian. Son iki katman **kanıt
katmanıdır**; mimari gerçeği değiştiremezler.

**İnsan onay kapıları.** Ajan tarafından yapılamayacak işler: main'e merge,
production deploy, production migration, secret değişikliği, cloud kaynak
oluşturma/silme, ödeme ve kullanıcı verisi işlemleri, geri döndürülemez veri
operasyonları.

**Branch politikası.** main korumalıdır. Her feature kendi branch ve
worktree'sinde geliştirilir. Bir branch'te aynı anda tek yazıcı ajan çalışır.
Paralel frontend/backend çalışması ancak contract onaylandıktan sonra başlar.

**Güvenlik politikası.** Ajanların production erişimi yoktur. Secret'lar Git'e,
Obsidian'a veya NotebookLM'e yazılmaz. Dış doküman, web içeriği ve prompt'lar
güvenilmeyen veri kabul edilir.

## Agent'lar

14 rol tanımlıdır. Her birinin araç kısıtı vardır ve bu kısıt öneri değil,
teknik olarak dayatılır.

| Rol | Araçlar | Not |
|---|---|---|
| `delivery-lead` | Read, Grep, Glob, **Agent** | plan modu; yazma aracı yok |
| `backend-engineer` | Read, Grep, Glob, Write, Edit, Bash | |
| `frontend-engineer` | Read, Grep, Glob, Write, Edit, Bash | |
| `database-engineer` | Read, Grep, Glob, Write, Edit, Bash | production migration çalıştırmaz |
| `ai-data-engineer` | Read, Grep, Glob, Write, Edit, Bash | |
| `qa-automation` | Read, Grep, Glob, Write, Edit, Bash | |
| `security-red-team` | Read, Grep, Glob, Write, Edit, Bash | yalnızca rapor üretir |
| `evalops-reviewer` | Read, Grep, Glob, Write, Edit, Bash | |
| `integration-release` | Read, Grep, Glob, Write, Edit, Bash | push/merge/deploy yapmaz |
| `contract-broker` | Read, Grep, Glob, Write, Edit | Bash yok |
| `solution-architect` | Read, Grep, Glob, Write, Edit | Bash yok |
| `product-analyst` | Read, Grep, Glob, Write, Edit | Bash yok |
| `design-reviewer` | Read, Grep, Glob, Write, Edit | Bash yok |
| `governance-operations-author` | Read, Grep, Glob, Write, Edit | Bash yok |

İki tasarım kararı dikkat çeker:

**Delivery Lead tek orkestratördür ve hiç yazma aracı yoktur.** Başka ajan
çağırabilen tek rol odur, ama kendisi kod yazamaz. Planlayan ile uygulayanın
ayrılması bilinçlidir.

**Doküman üreten roller Bash alamaz.** Contract, ADR ve requirement üreten
roller komut çalıştırmaya ihtiyaç duymadığı için yetki de verilmemiştir.

Her rol tanımında ne yapmayacağı açıkça yazılıdır; hepsinde ortak olan madde
"main merge yapmaz"dır.

## Skill'ler

17 skill, ajanlara iş yapma yöntemini öğretir.

| Grup | Skill'ler |
|---|---|
| Süreç yönetimi | `orchestrate-delivery`, `autonomous-delivery-run`, `native-team-delivery`, `task-routing` |
| Üretim | `api-contract-design`, `requirement-traceability`, `project-context-synthesis` |
| Denetim | `adversarial-security-review`, `qa-acceptance-verification`, `visual-design-review`, `evalops-regression`, `release-scorecard` |
| Güvenlik sınırları | `managed-delivery-operations`, `db-migration-safety`, `bootstrap-target-project` |
| Dış kaynak | `notebooklm-grounded-retrieval`, `obsidian-project-context` |

Son gruptaki iki skill, dış kaynakların nasıl kullanılacağını kısıtlar:
NotebookLM'den gelen ham çıktı güvenilmeyen bağlamdır; Obsidian'dan tüm vault
değil yalnızca seçilmiş stratejik notlar kullanılır.

## Workflow'lar

Hangi işte hangi rollerin hangi sırayla devreye gireceğini tarif eden 8 reçete:

`feature-delivery`, `bug-resolution`, `release-readiness`, `security-response`,
`ai-rag-delivery`, `data-dashboard-delivery`, `new-product-discovery`,
`cost-optimization`.

## Hook'lar — kuralların uygulandığı yer

Buraya kadar anlatılanlar tanımdır. Hook'lar ise çalışma anında müdahale eden
kısımdır ve sistemin en kritik parçasıdır. `hooks/hooks.json` iki hook kaydeder.

### Target Guard

Her `Bash`, `Write` ve `Edit` çağrısından **önce** çalışır, tehlikeli olanı
çıkış kodu 2 ile reddeder ve gerekçeyi stderr'e yazar.

Engellenen Bash kalıpları:

- `git merge` (doğrudan ve `git -C <yol> merge` gibi global bayraklı biçimi)
- `git push` ile `--force`, `--force-with-lease` veya `-f`
- `git branch` ile `-d`, `-D` veya `--delete`
- `git reset --hard|--soft|--mixed`
- `git clean -f`, `git checkout -- .`, `git restore .`
- `rm -rf` ve tüm bayrak varyasyonları

Engellenen yazma yolları: `.env` ve türevleri, korumalı yapılandırma dosyaları.

`DEVFLOW_RUN_WORKTREE` ortam değişkeni tanımlıysa ek olarak sınır uygulaması
devreye girer: worktree dışına çözümlenen Write/Edit çağrıları ve `cd`,
`git -C`, `--work-tree` ile worktree dışına çıkan Bash çağrıları reddedilir.

`git merge-base`, `git merge-tree` ve `git merge-file` **salt okunur** plumbing
komutlarıdır ve geçerler. Kalıp `merge` sonrası `(?![-\w])` ile biter; sondaki
`\b` tireden önce de eşleştiği için bu komutlar eskiden yanlışlıkla
engelleniyordu.

### Delegation Recorder

`SubagentStart` ve `SubagentStop` olaylarında çalışır, hedef projedeki
`.devflow/delegation-events/` altına kayıt düşer.

Yazılan alanlar **tam olarak sekiz tanedir**: `schema_version`, `evidence_id`,
`timestamp`, `run_id`, `hook_event`, `lifecycle_state`, `agent_type`,
`evidence_source`.

Yazılmayanlar script'te tek tek sayılmıştır: oturum id'si, ajan id'si,
transcript yolu, prompt, girdi, çıktı, dosya içeriği, token, secret, kimlik
bilgisi, URL, mesaj, metin, log ve serbest metin taşıyan her alan. Kayıt tutulur
ama içerik sızmaz.

Recorder hata alsa bile `exit 0` döner; kanıt kaydı asla teslimatı bloklamaz.

## Operations runner

`scripts/devflow_operations.py`, izin verilen tek mutasyon yoludur. Alt
komutlar:

| Komut | İş |
|---|---|
| `init-target` | Hedef projede `.devflow/` başlat (korumasız branch şartı) |
| `create-run` | Yeni teslimat run'ı oluştur |
| `launch` | Yönetilen worktree + branch ile Claude Code başlat |
| `status` | Run durumunu göster |
| `generate-task-graph` | Teslimat tipine göre deterministik task graph üret |
| `update-task-status` | Task durumunu geçiş doğrulamasıyla güncelle |
| `record-qa-evidence` | QA sonuçlarını kaydet, approval gate'leri güncelle |
| `record-security-evidence` | Security review kanıtı kaydet |
| `record-contract-evidence` | Contract kanıtı kaydet (yalnızca new_feature) |
| `record-work-product-evidence` | İş ürünü kanıtı kaydet (aktif worktree değişikliği olmalı) |
| `prepare-delivery` | Teslimat doğrulama raporu (gerçek Git mutasyonu yok) |
| `generate-run-report` | Kanıt raporu ve merge tavsiyesi üret |

Çıkış kodları anlamlıdır ve otomasyonda ayırt edilebilir: `2` hedef framework
repo, `3` git repo değil, `7` korumalı branch, `8` yasak git operasyonu,
`9` approval gate geçilmedi, `11` çalışma ağacı temiz değil.

### Hedef projedeki `.devflow/`

```
.devflow/
├── project.json            proje meta verisi, run sayacı
├── policy.json             teslimat politikası, yasaklı operasyonlar
├── source-register.json    kayıtlı kaynaklar
├── context/                context pack'ler
├── plans/                  teslimat planları
├── task-packets/           görev paketleri
├── runs/                   run durum dosyaları
├── reports/                scorecard ve raporlar
└── delegation-events/      hook kanıtları
```

`source-register.json` kaynak tipine göre hangi alanların yasak olduğunu
tanımlar; örneğin NotebookLM kaynağına token, URL veya ham içerik yazılamaz.

## MCP katmanı

Sisteme bağlı MCP sunucuları (Claude Code oturumuna aittir, DevFlow'a özel
değildir): `context7` (kütüphane dokümanı), `playwright` (tarayıcı
otomasyonu), `obsidian` (yerel not hafızası), `notebooklm-mcp` (araştırma
kanıtı).

DevFlow'un katkısı bunları kısıtlamaktır: NotebookLM ve Obsidian, gerçeğin
kaynağı sıralamasının en altındadır ve çıktıları güvenilmeyen kabul edilir.

`src/mcp_audit_runtime` ayrı bir çalışmadır: MCP çağrılarını denetim altına
almak için temel atan, **deneysel** bir altyapıdır (REQ-003, ADR-007). Gerçek
MCP bağlantısı kurmaz, simüle edilmiş dispatch kullanır ve hiçbir güvenlik
kapısını kapatmaz. Üretim özelliği değildir.

## Gereksinimler

**Python 3.9+.** macOS'un `/usr/bin/python3` olarak dağıttığı sürüm 3.9'dur ve
tüm script'ler orada çalışacak şekilde tutulur. Modern `X | Y` annotation
sözdizimi kullanan script'ler `from __future__ import annotations` içermek
zorundadır; aksi halde annotation import anında değerlendirilir ve script
argparse'a bile ulaşamadan `TypeError` ile düşer.

Bu kural `tests/test_devflow_structure.py` içindeki
`ScriptPythonCompatibilityTest` tarafından zorlanır: `scripts/` altındaki her
dosya AST ile taranır, PEP 604 union kullanıp future import taşımayan bir dosya
testi düşürür.

Üçüncü parti bağımlılık yoktur; guard, recorder ve operations runner yalnızca
standart kütüphane kullanır.

## Bilinen sınırlar

**Target Guard bir kum havuzu değildir.** Yalnızca Claude Code'un araç
çağrılarını (`Bash`, `Write`, `Edit`) kapsar. Kullanıcının terminale doğrudan
yazdığı komutlar, script içinden başlatılan alt süreçler ve araç çağrısı
üzerinden geçmeyen hiçbir şey yakalanmaz. Bu bir **derinlemesine savunma
katmanıdır**, işletim sistemi seviyesi izolasyon değildir.

**Delegation kanıtı yaşam döngüsüdür, içerik değildir.** Kayıtlar bir alt
ajanın başladığını ve bittiğini söyler; ne yaptığını söylemez. Bu bilinçli bir
gizlilik tercihidir.

**mcp_audit_runtime üretimde değildir.** Yukarıda açıklandığı gibi deneysel
aşamadadır.

## Testler

```bash
python3 -m pytest tests/ -q
```

Test paketi agent tanımlarını, skill yapısını, workflow kapsamını, guard
davranışını, delegation kanıtı şemasını, ownership manifest doğrulamasını ve
plugin build çıktısını kapsar.
