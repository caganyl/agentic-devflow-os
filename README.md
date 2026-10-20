# Agentic DevFlow OS

Claude Code üzerine kurulmuş, rol tabanlı, kanıta dayalı ve güvenlik odaklı bir yazılım teslimat
işletim sistemi. Bir AI ajanına "şunu yap" demek yerine **kimin neye dokunabileceğini önceden
tanımlar ve bu kuralları araç çağrısı seviyesinde hook'larla zorlar.** Bu repo framework'ün
kendisidir; iş yapılan proje ayrı bir "hedef proje" reposudur.

> Güncel ölçek (2026-10-13): **17** agent rolü · **25** skill (2'si eski adlar için
> yönlendirme) · **9** workflow · **6** rule · **16** şablon · **4** framework hook'u +
> **2** plugin hook script'i · **12** script · **6** aktif ADR (+3 arşivde).
> Sistem anlatımı: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) ·
> Kurallar: [`PROJECT_CONSTITUTION.md`](PROJECT_CONSTITUTION.md) ·
> Ownership ve merge: [`docs/ownership/README.md`](docs/ownership/README.md)

<a id="hizli-basla"></a>
## ⏱️ 5 dakikada başla

```bash
# 1. Framework repo'yu klonla ve komutları kur (~/.local/bin'e symlink;
#    gerekirse ~/.zshrc'ye tek bir PATH bloğu ekler). Sonra yeni terminal aç.
git clone https://github.com/caganyl/agentic-devflow-os.git ~/Developer/agentic-devflow-os
~/Developer/agentic-devflow-os/bin/install
claude-devflow doctor                           # git, python3, jq, claude ve PATH kontrolü

# 2. Hedef projede oturum aç: bootstrap (plugin build, branch, CLAUDE.md,
#    rule'lar, docs iskeleti, REQ-001 manifesti, .devflow/) + claude --plugin-dir
cd ~/Developer/projects/benim-projem
claude-devflow

# 3. Oturumda: dolu projede "projeyi tanı" (architecture-analyst profil taslağı
#    yazar, sen confirmed yaparsın); boş projede architecture-intake.
#    Sonra fikrini anlat: requirement → (gerekirse ADR) → contract.

# 4. Yeni REQ için draft manifest üret, gözden geçir, "approved" yap
devflow-manifest 002

# 5. Onaylı manifeste bağlı managed run başlat (önce --dry-run ile bak)
claude-devflow launch --objective "REQ-002: kısa açıklama" --req-id REQ-002

# 6. (İsteğe bağlı) Ayrı bir terminalde ekibi canlı ofis olarak izle
claude-devflow office            # örnek run için: claude-devflow office --demo
```

Gereken: Python 3.9+, Bash, `jq`, Git ve Claude Code CLI (bkz. [Bağımlılıklar](#bagimliliklar)).

## İçindekiler

0. [5 dakikada başla](#hizli-basla)
1. [Mimari Konum](#mimari-konum)
2. [Nasıl Çalışır — Teslimat Akışı](#teslimat-akisi)
3. [Projeye Katılım ve Mimari Profil](#mimari-profil)
4. [Tasarım Fazı ve Döngü Kesici](#tasarim-fazi)
5. [Klasör Yapısı](#klasor-yapisi)
6. [Agent Kataloğu](#agent-katalogu)
7. [Hook Kataloğu — Kuralların Zorlandığı Yer](#hook-katalogu)
8. [Skill, Workflow ve Rule Kataloğu](#skill-workflow-rule)
9. [Operations Runner](#operations-runner)
10. [Ownership Manifest ve CI Kapısı](#ownership)
11. [Kurulum ve Hızlı Başlangıç](#kurulum)
12. [Testler](#testler)
13. [Bağımlılıklar](#bagimliliklar)
14. [Kurallar ve Dikkat Edilecekler](#kurallar)
15. [Bilinen Sınırlar](#bilinen-sinirlar)

<a id="mimari-konum"></a>
## 📐 Mimari Konum

```
 ┌───────────────────────────────────────────────────────────────┐
 │ İnsan maintainer                                              │
 │ onay kapıları: manifest "approved" · ADR "Accepted" · profil  │
 │ "confirmed" · main merge · production · secret · PR yanıtları  │
 └──────────────────────────────┬────────────────────────────────┘
                                │ bin/claude-devflow (bootstrap + launch)
 ┌──────────────────────────────▼────────────────────────────────┐
 │ agentic-devflow-os  (framework repo)      ◄── Siz buradasınız │
 │ .claude/  agents · skills · rules · workflows · hooks · şablon │
 │ scripts/  guard · recorder · operations runner · arch scanner  │
 │ docs/     anayasa · ADR · ownership · mimari anlatım           │
 └──────────────────────────────┬────────────────────────────────┘
                                │ scripts/build_devflow_plugin.py
                                ▼ dist/devflow-plugin/  (gitignore'da)
 ┌───────────────────────────────────────────────────────────────┐
 │ Claude Code oturumu  (claude --plugin-dir dist/devflow-plugin)│
 │ PreToolUse: target guard → protect-main → protect-sensitive → │
 │             enforce-role-boundaries                            │
 │ SubagentStart/Stop: delegation recorder                        │
 └──────────────────────────────┬────────────────────────────────┘
                                │ yazma yalnızca rol izni + ownership manifesti ile
 ┌──────────────────────────────▼────────────────────────────────┐
 │ Hedef proje repo   (.devflow/ durum, docs/, mimari profil,    │
 │                     kaynak kod)                                │
 └──────────────────────────────┬────────────────────────────────┘
                                │ pull request
 ┌──────────────────────────────▼────────────────────────────────┐
 │ GitHub Actions: Ownership Governance (PR Quality + Diff Gate)  │
 └───────────────────────────────────────────────────────────────┘
```

Framework repo ile hedef proje arasındaki sınır sistemin en önemli sınırıdır: hedef projeye
yalnızca plugin çıktısı (`dist/devflow-plugin/`) gider, hedef projede yalnızca `.devflow/`
çalışma alanı açılır. Operations runner, hedef olarak framework repo verilirse çıkış kodu `2`
ile reddeder. Ayrıntı: [`.claude/rules/target-project-boundaries.md`](.claude/rules/target-project-boundaries.md).

<a id="teslimat-akisi"></a>
## 🔄 Nasıl Çalışır — Teslimat Akışı

Yeni bir feature için standart akış ([`.claude/workflows/feature-delivery.md`](.claude/workflows/feature-delivery.md)).
Ön koşul: hedef projenin onaylı bir mimari profili vardır (bkz. [sonraki bölüm](#mimari-profil)).

```
 ana oturum           tek orkestratör (orchestrate-delivery); delivery-lead'den plan alır
 delivery-lead        plan, task graph, minimum rol seti (dağıtmaz; yazma/Bash yok)
      │
 [AC belirsiz mi?] ── evet ─► ana oturum + insan: requirement-grilling
      │
 product-analyst      docs/product/…  REQ-NNN + acceptance criteria + GLOSSARY.md
      │
 [ADR eşiği var mı?] ─ hayır ─► docs/decisions/REQ-NNN-<konu>.md (≤10 satır karar notu)
      │ evet
 solution-architect   docs/architecture/adr/ADR-NNN  (Status: Proposed)
 adr-reviewer         docs/architecture/adr/reviews/ADR-NNN-review-<tur>.md  (≤ 2 tur)
      │
 contract-broker      docs/contracts/…  (frontend+backend paralel gidecekse zorunlu)
      │
 İNSAN                docs/ownership/REQ-NNN.json  status: approved   ◄── tek tasarım onayı
      │
 implementer'lar      backend / frontend / database / ai-data / qa
                      tdd-vertical-slice → stack-verification; yalnızca write_paths altına
      │
 review rolleri       qa-automation → security-red-team (+ design-reviewer · evalops-reviewer)
                      fix sonrası en fazla bir yeniden inceleme, sonrası insan
      │
 docs-writer          değişen klasörlerin README'leri, yalnızca yorum değişiklikleri, handoff
      │
 integration-release  kanıt, release scorecard, pr-review-triage, merge tavsiyesi
      │
 İNSAN                commit/push, PR yanıtları, main merge
```

Temel ilkeler:

- **Requirement olmadan davranış icat edilmez.** Her ürün davranışı bir `REQ-NNN` kimliği ve
  test edilebilir acceptance criteria taşır.
- **Contract-first paralellik.** Frontend ve backend, onaylı contract olmadan paralel başlamaz.
- **Minimum rol seti.** Her task'te tüm roller çağrılmaz; task türüne göre seçim
  [`.claude/rules/task-routing.md`](.claude/rules/task-routing.md) tablosundan yapılır.
- **Kademeli bağlam.** Alt ajana önce dar bir paket verilir; eksik kalırsa sonucunun başında
  `CONTEXT_REQUEST:` ile en fazla 3 yol + bölüm ister, en fazla 2 tur.
- **Kanıt zinciri.** Evidence → requirement → AC → task → test → handoff. Bir ajanın özeti
  kanıt değildir; ancak Git artefaktına dönüşüp doğrulanırsa resmi sayılır.
- **Gerçeğin kaynağı sıralaması:** Anayasa → onaylı ADR → onaylı contract → requirement →
  kod ve testler → handoff → NotebookLM → Obsidian. Son ikisi kanıt katmanıdır, mimari
  gerçeği değiştiremez ([`.claude/rules/source-of-truth.md`](.claude/rules/source-of-truth.md)).

<a id="mimari-profil"></a>
## 🧱 Projeye Katılım ve Mimari Profil

Implementer ajanların mevcut mimariyi bozmadan kod yazabilmesi için her hedef projede onaylı
bir **mimari profil** bulunur: `docs/architecture/profile/ARCHITECTURE_PROFILE.md` (okunur
özet, konvansiyonlar, referans dosyalar) ve `architecture-profile.json` (tarayıcının kontrol
ettiği kurallar). Akış [`.claude/workflows/project-onboarding.md`](.claude/workflows/project-onboarding.md):

| Durum | Ne olur |
|---|---|
| Dolu proje (brownfield) | `architecture-analyst`, [`scripts/devflow_arch_scan.py`](scripts/devflow_arch_scan.py) ile .NET (.sln/.csproj referans grafiği, katman, paketler, API stili) ve Next.js/React (router, klasör stili, state, veri çekme, alias'lar) yapısını tarar, örnek dosyalardan kalıp çıkarır ve `draft` profil yazar |
| Boş proje (greenfield) | Ana oturum insanla `architecture-intake` yapar: her soruda öneriyle tek tek karar alınır, aynı profil formatına yazılır |
| İnsan onayı | Açık sorular (en fazla 7) cevaplanır, insan `Status: confirmed` yazar; onaylı profil ajanlar için dondurulur |
| Sürekli kontrol | `stack-verification` her görevde `devflow_arch_scan.py --check` çalıştırır; yeni yasak referans veya feature sınırı ihlali görevi bitirmez, `known_deviations` düşürmez |

Profil yoksa veya `draft` ise implementer'lar dolu projede yazmaya başlamaz, blocker raporlar.
Tarayıcı salt okunurdur, yalnızca standart kütüphane kullanır ve dosya yazmaz.

<a id="tasarim-fazi"></a>
## 🧭 Tasarım Fazı ve Döngü Kesici

Managed run'lar eskiden ADR taslağı ↔ review arasında sonsuz döngüye girebiliyordu; ayrıca
`devflow/run-*` branch'lerinde implementer yazımı her zaman reddedildiği için run tasarım
işine geri itiliyordu. Tasarım fazı artık deterministik bir çıkış koşuluyla biter:

| Kural | Nerede zorlanır |
|---|---|
| ADR yalnızca eşik sağlanırsa yazılır: yeni dış bağımlılık/servis, context'ler arası veri modeli/migration, auth/güvenlik sınırı, geriye uyumsuz public contract, geri alınması pahalı karar; `new_feature` task graph'ında ADR task'ı yalnızca `--needs-adr` ile | `solution-architect.md`, `task-routing.md` |
| Bir ADR için en fazla **2** review turu; sonrası insan kararı (`DEVFLOW_ADR_MAX_REVIEW_ROUNDS`) | hook: ADR loop breaker |
| Bir branch'te en fazla **1** yeni ADR (`DEVFLOW_ADR_MAX_NEW_PER_BRANCH`); `adr/` alt klasörlerinde (`reviews/` hariç) ve `docs/decisions/` altında ADR dosyası açılamaz | hook |
| Security, design, eval ve PR triage review'ları en fazla bir yeniden inceleme alır; sonrası insan | `CLAUDE.md`, ajan prompt'ları |
| Review dosyaları yalnızca `adr-reviewer` tarafından, `ADR-NNN-review-<tur>.md` adıyla, sırayla ve bir `VERDICT:` satırıyla yazılır; sonradan değiştirilemez | hook |
| `Accepted` / `Superseded` / `Rejected` ADR dondurulur; yalnızca status satırı Superseded/Deprecated/Withdrawn yapılarak emekliye ayrılabilir; sapmalar handoff/PR'a veya yeni ADR'ye yazılır | hook |
| ADR boyut bütçesi ~12.000 karakter (`DEVFLOW_ADR_MAX_CHARS`); küçülten düzenlemeler her zaman serbest | hook |
| Managed run, `launch --req-id REQ-NNN` ile onaylı bir manifeste bağlanırsa implementer'lar `devflow/run-*` branch'inde yazabilir | hook + `validate_ownership_manifest.py --managed-run` |
| Ownership/branch reddi tasarım sorunu değildir; architect yeniden çağrılmaz, blocker tek özetle insana raporlanır | `CLAUDE.md`, `agent-common.md`, `orchestrate-delivery` |

`adr-reviewer` verdict'leri: `APPROVE`, `APPROVE_WITH_NOTES` (tasarım biter, notlar handoff'a),
`BLOCK` (yalnızca anayasa ihlali, onaylı contract/REQ ile çelişki veya azaltılmamış geri
döndürülemez risk). Üslup ve "daha iyi olabilir" türü bulgular BLOCK sebebi değildir.

<a id="klasor-yapisi"></a>
## 📁 Klasör Yapısı

```
agentic-devflow-os/
├── PROJECT_CONSTITUTION.md     # anayasa: kaynak sıralaması, insan onay kapıları, branch/güvenlik politikası
├── CLAUDE.md                   # bu repoda çalışan Claude oturumları için talimatlar + kodlama ilkeleri
├── AGENTS.md                   # rol listesi + Codex Phase 1A runtime politikası
├── bin/                        # install, claude-devflow, devflow-manifest
├── .claude/
│   ├── agents/                 # 17 rol tanımı (frontmatter: model, maxTurns, tools, skills)
│   ├── skills/                 # 25 skill — ajanlara iş yapma yöntemini öğretir
│   ├── workflows/              # 9 teslimat reçetesi (feature, bug, release, security, onboarding…)
│   ├── rules/                  # ortak ajan kuralları, autonomy gates, kaynak hiyerarşisi; path'e bağlı routing/context/sınır kuralları
│   ├── templates/              # ADR, requirement, handoff, context pack, mimari profil, TARGET_CLAUDE…
│   ├── hooks/                  # session-start, protect-main, protect-sensitive-paths, enforce-role-boundaries
│   └── settings.json           # framework repo'nun kendi hook kaydı ve izin listeleri
├── hooks/hooks.json            # plugin hook kaydı (hedef projelerde devreye girer)
├── scripts/                    # build, operations CLI, guard'lar, recorder, validator'lar, tarayıcı, bootstrap
├── docs/
│   ├── ARCHITECTURE.md         # sistemin tek güncel anlatımı
│   ├── architecture/adr/       # ADR-001…004, 008, 009 + reviews/ (adr-reviewer kayıtları)
│   ├── architecture/profile/   # hedef projede onaylı mimari profilin yeri (burada yalnızca README)
│   ├── decisions/              # agent capability matrisi; ADR eşiği sağlanmayan kısa karar notları
│   ├── ownership/              # schema.json, TEMPLATE.json, REQ manifestleri, README (ownership & merge)
│   ├── product/                # requirements, acceptance-criteria, prd, user-stories
│   ├── contracts/              # openapi, events, database, shared-types
│   ├── quality/                # security raporları, a11y, test kanıtı
│   ├── handoffs/               # REQ handoff'ları (şablon: docs/templates/REQ_HANDOFF_TEMPLATE.md)
│   ├── templates/              # handoff şablonu
│   ├── archive/                # güncel olmayan belgeler (MCP audit zinciri, eski çalışma modeli)
│   └── ai/, release/
├── .codex/, .agents/           # Codex Phase 1A: 4 ajan, 3 skill, hook kaydı
├── tests/                      # unittest modülleri
├── evals/, design/             # AI eval veri setleri; tasarım referansları (design-reviewer raporları hedefte design/reviews/)
└── .github/workflows/ownership-governance.yml   # PR kalite + ownership diff kapısı
```

<a id="agent-katalogu"></a>
## 🤖 Agent Kataloğu

Araç kısıtları frontmatter'da tanımlıdır; yazma yolları
[`enforce-role-boundaries.sh`](.claude/hooks/enforce-role-boundaries.sh) tarafından zorlanır.
Tam matris: [`docs/decisions/AGENT_CAPABILITY_MATRIX.md`](docs/decisions/AGENT_CAPABILITY_MATRIX.md).
Ortak kurallar her rol için [`.claude/rules/agent-common.md`](.claude/rules/agent-common.md); her rol kendi
skill'lerini `skills:` frontmatter'ıyla önceden yükler.

| Rol | Model | Sorumluluk | Yazabildiği yer | Bash |
|---|---|---|---|---|
| `delivery-lead` | sonnet | Plan, task graph, rol seçimi, quality gate önerisi; dağıtmaz (orkestratör ana oturumdur) | Hiçbir yer | Yok |
| `product-analyst` | sonnet | REQ, user story, acceptance criteria, terim sözlüğü | `docs/product`, `docs/decisions` | Yok |
| `solution-architect` | opus | Mimari alternatifler, trade-off, ADR (yalnızca eşik sağlanırsa) | `docs/architecture`, `docs/decisions` (ADR loop breaker ile) | Yok |
| `adr-reviewer` | sonnet | Bir ADR'ye tek turda VERDICT; ADR'yi yeniden yazmaz | `docs/architecture/adr/reviews` | Yok |
| `architecture-analyst` | sonnet | Mevcut projeyi tarar, `draft` mimari profil yazar | Yalnızca iki profil dosyası | Yalnızca tarayıcı + mutasyonsuz inceleme |
| `contract-broker` | sonnet | OpenAPI / event / DB / shared type contract | `docs/contracts` | Yok |
| `frontend-engineer` | sonnet | UI, route, state, a11y, frontend testleri; profili aynalar | Onaylı manifestteki `write_paths` | Sınırlı |
| `backend-engineer` | sonnet | API, auth/authz, domain logic, backend testleri; profili aynalar | Onaylı manifestteki `write_paths` | Sınırlı |
| `database-engineer` | sonnet | Schema, migration taslağı, rollback; production migration çalıştırmaz | Onaylı manifestteki `write_paths` | Sınırlı |
| `ai-data-engineer` | sonnet | LLM/RAG, embedding, retrieval, AI feature testleri | Onaylı manifestteki `write_paths` | Sınırlı |
| `qa-automation` | sonnet | Unit/integration/contract/E2E/regression, repro testleri | Onaylı manifestteki `write_paths` | Sınırlı |
| `docs-writer` | sonnet | Klasör README'leri, kök README'nin `devflow:auto` blokları, yorumlar, handoff | `README.md` dosyaları, `docs/handoffs`; kaynak dosyada yalnızca yorum | Yalnızca mutasyonsuz inceleme |
| `security-red-team` | opus | Threat model, adversarial review; yalnızca rapor | `docs/quality/security-reports` | Yalnızca mutasyonsuz tarama |
| `design-reviewer` | sonnet | UX, a11y, responsive, durum ekranları review'u | `design/reviews` (hedefte bootstrap açar), `docs/quality/accessibility` | Yok |
| `evalops-reviewer` | sonnet | Adversarial/regression eval, scorecard | `evals/…`, `docs/ai/evals`, `docs/ai/model-decisions` | Sınırlı |
| `integration-release` | haiku | Kayıtlı kanıttan release scorecard, PR review triage, merge tavsiyesi; push/merge yapmaz | `docs/release`, `docs/handoffs` | Sınırlı |
| `governance-operations-author` | sonnet | Ownership & merge rehberi, handoff şablonu, operasyon prosedürleri | `docs/operations`, `docs/templates`, `docs/ownership/README.md` | Yok |

Model ataması bilinçlidir ve hiçbir rol `inherit` kullanmaz: seyrek çağrılan ve hata maliyeti
yüksek roller Opus, kod ve yargı gerektiren roller Sonnet, büyük ölçüde CLI verisi derleyen
`integration-release` Haiku kullanır (gerekçe: capability matrisi, "Model Ataması").

"Sınırlı" Bash: Git mutasyonu, yıkıcı dosya işlemi, bağımlılık kurulumu, merge, deploy,
migration, izin değişikliği, dosyaya yönlendirme (`>`, `>>`, `<`), dış sisteme yazma
(`gh pr|issue comment/review/create/edit…`, yazma amaçlı `gh api`, `agent-reviews
--reply/--resolve/--watch`) ve aktif saldırı araçları (`strix`) reddedilir. `2>&1`, `>&2` ve
`/dev/null` yönlendirmeleri dosya yazımı sayılmaz; PR yorumlarını okumak serbesttir.

<a id="hook-katalogu"></a>
## 🛡️ Hook Kataloğu — Kuralların Zorlandığı Yer

Hook'lar iki yerde kayıtlıdır: framework repo'nun kendisi için
[`.claude/settings.json`](.claude/settings.json), hedef projeler için plugin'in
[`hooks/hooks.json`](hooks/hooks.json) dosyası. Tüm guard hook'ları **fail-closed** çalışır:
`jq` veya `python3` bulunamazsa işlem reddedilir.

| Hook | Olay | Ne yapar |
|---|---|---|
| `devflow_target_guard.py` (yalnızca plugin) | PreToolUse Bash/Write/Edit | `git merge`, force push, branch silme, `git reset`, `git clean -f` ve yıkıcı silme komutlarını, `.env` ve korumalı config yazımını reddeder; `DEVFLOW_RUN_WORKTREE` tanımlıysa worktree dışına çıkışı engeller |
| `protect-main.sh` | PreToolUse Bash/Write/Edit | Oturum `main` üzerindeyse tüm Bash/Write/Edit çağrılarını reddeder; kullanıcıdan `claude --worktree <ad>` ile izole oturum açmasını ister |
| `protect-sensitive-paths.sh` | PreToolUse Bash/Write/Edit | `.env*`, `secrets/`, `credentials.json`, `*.pem`/`*.key`/`*.p12`/`*.pfx`, Claude ayarları ve hook script'lerine dokunmayı reddeder |
| `enforce-role-boundaries.sh` | PreToolUse Bash/Write/Edit | Rol bazlı yazma yolları; implementer'lar için manifest yetkilendirmesi; doküman rollerine Bash yasağı; ADR loop breaker; mimari profil kapısı (`confirmed` yalnızca insan, onaylı profil dondurulur); docs-writer kapısı (kaynak dosyada yalnızca yorum değiştiren Edit); dış sisteme yazma ve aktif saldırı aracı yasağı |
| `session-start.sh` | SessionStart | Repo, branch, çalışma ağacı durumu, main koruması, mimari profil durumu ve en güncel handoff'u bağlama ekler; plugin oturumlarında `DEVFLOW_ARCH_SCAN_SCRIPT` yolunu tanımlar |
| `devflow_delegation_recorder.py` (yalnızca plugin) | SubagentStart/Stop | `.devflow/delegation-events/` altına içeriksiz yaşam döngüsü kaydı yazar; hata alsa bile teslimatı bloklamaz |
| `devflow_office_recorder.py` (yalnızca plugin, async) | SubagentStart/Stop, PreToolUse Skill/Agent/Edit/Write/Bash… | Canlı ofis görünümü için `.devflow/office/events.jsonl` telemetrisi: ajan başla/bitir, skill adı, araç adı ve göreli dosya yolu. Prompt, komut, dosya içeriği, transcript veya ham `agent_id` yazmaz; karar vermez. Guard hook'ları reddettiklerinde aynı dosyaya `deny` notu düşer |

Ek olarak `.claude/settings.json` izin katmanı `.env*`, `secrets/**`, `*.pem`, `*.key`
okumasını reddeder ve `git push`, `gh pr merge`, sert `git reset`, `terraform apply`,
`kubectl apply`, `prisma migrate deploy` gibi komutlar için onay ister.

<a id="skill-workflow-rule"></a>
## 📚 Skill, Workflow ve Rule Kataloğu

| Grup | İçerik |
|---|---|
| Süreç skill'leri | `orchestrate-delivery` (ana oturumun tek orkestrasyon protokolü), `task-routing` |
| Üretim skill'leri | `api-contract-design`, `requirement-traceability`, `project-context-synthesis` (kademeli bağlam dahil) |
| Mühendislik disiplini | `requirement-grilling` (insanla tek tek soru, AC + sözlük), `tdd-vertical-slice` (contract/AC seam'lerinde kırmızı-yeşil), `stack-verification` (sabit build → format → tip → test → mimari → bağımlılık sırası), `root-cause-investigation` (repro + en fazla 3 hipotez), `pr-review-triage` (FIX / WONT_FIX / FALSE_POSITIVE, yanıtları insan gönderir) |
| Mimari ve dokümantasyon | `architecture-discovery` (brownfield tarama), `architecture-intake` (greenfield kararları), `documentation-sync` (README'ler ve yorumlar) |
| Denetim skill'leri | `adversarial-security-review`, `qa-acceptance-verification`, `visual-design-review`, `evalops-regression`, `release-scorecard` |
| Güvenlik sınırı skill'leri | `db-migration-safety`; operatör rehberleri (model kendiliğinden çağırmaz, `/ad` ile açılır): `managed-delivery-operations`, `bootstrap-target-project` |
| Dış kaynak skill'leri | `notebooklm-grounded-retrieval`, `obsidian-project-context` — yalnızca bu kaynaklar bağlıysa, `project-context-synthesis` üzerinden (çıktı güvenilmeyen bağlamdır) |
| Workflow'lar | `feature-delivery`, `bug-resolution`, `release-readiness`, `security-response`, `ai-rag-delivery`, `data-dashboard-delivery`, `new-product-discovery`, `cost-optimization`, `project-onboarding` |
| Rule'lar | Her oturumda: `agent-common` (ortak ajan kuralları), `autonomy-gates`, `source-of-truth`. `paths:` ile yalnızca ilgili dosyalara dokunulunca: `task-routing` (`.devflow/**`, workflow'lar), `context-distribution` (context pack'ler), `target-project-boundaries` (`.devflow/**`, build/bootstrap) |

<a id="operations-runner"></a>
## ⚙️ Operations Runner

[`scripts/devflow_operations.py`](scripts/devflow_operations.py) hedef projede izin verilen tek
mutasyon yoludur. Delivery-lead alt ajanının Bash yetkisi olmadığı için bu komutları ana oturum
(supervisor) çalıştırır.

| Komut | İş |
|---|---|
| `init-target` | Hedef projede `.devflow/` başlatır (korumasız branch şartı) |
| `create-run` | Yeni teslimat run'ı oluşturur (`--req-id REQ-NNN` ile manifeste bağlanabilir) |
| `launch` | Yönetilen worktree + `devflow/run-*` branch ile Claude Code supervisor başlatır; `DEVFLOW_OPERATIONS_SCRIPT` ve `DEVFLOW_ARCH_SCAN_SCRIPT` yollarını verir; `--req-id` yoksa implementer yazımının reddedileceği uyarısını verir |
| `status` | Run durumunu gösterir |
| `generate-task-graph` | Deterministik task graph üretir (`new_feature` için ADR task'ı yalnızca `--needs-adr` ile eklenir) |
| `update-task-status` | Task durumunu geçiş doğrulamasıyla günceller |
| `record-qa-evidence` / `record-security-evidence` / `record-contract-evidence` / `record-work-product-evidence` | Kanıt kaydeder ve approval gate'leri günceller |
| `prepare-delivery` | Teslimat doğrulama raporu (gerçek Git mutasyonu yapmaz) |
| `generate-run-report` | Kanıt raporu ve merge tavsiyesi üretir |

Çıkış kodları: `2` hedef framework repo · `3` git repo değil · `7` korumalı branch ·
`8` yasak git operasyonu · `9` approval gate geçilmedi · `11` çalışma ağacı temiz değil.

Hedef projedeki `.devflow/` alanı: `project.json`, `policy.json`, `source-register.json`,
`context/`, `plans/`, `task-packets/`, `runs/`, `reports/`, `delegation-events/` ve gitignore'daki
`cache/`, `logs/` (ayrıntı: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §6). Ajanlar
`.devflow/runs/` ve `.devflow/reports/` altına yazamaz; bu yüzden run state'teki REQ bağı ajan
kontrolünde değildir.

<a id="ownership"></a>
## 🔐 Ownership Manifest ve CI Kapısı

Implementer bir dosyaya ancak şu koşulların **hepsi** sağlanırsa yazabilir
(ADR-002, ADR-003, ADR-008):

1. Branch `req-NNN-kisa-aciklama` biçiminde **veya** `launch --req-id REQ-NNN` ile başlatılmış
   aktif managed run branch'i (`devflow/run-*`, `DEVFLOW_RUN_BRANCH` ile eşleşmeli),
2. `docs/ownership/REQ-NNN.json` mevcut ve `status: approved` (onay insan adımıdır),
3. Ajan manifestte owner olarak tanımlı,
4. Hedef yol o ajanın `write_paths` alanı altında.

Manifest şeması: [`docs/ownership/schema.json`](docs/ownership/schema.json), şablon:
[`docs/ownership/TEMPLATE.json`](docs/ownership/TEMPLATE.json), süreç:
[`docs/ownership/README.md`](docs/ownership/README.md).

[`ownership-governance.yml`](.github/workflows/ownership-governance.yml) her PR'da iki iş
çalıştırır (ADR-004):

- **PR Quality** — hook sözdizimi (`bash -n`), Python derleme, tüm unittest'ler ve
  `git diff --check` (boşluk hatası).
- **Ownership Diff Gate** — `pull_request_target` ile **güvenilir base kodundan**
  `validate_ownership_diff.py` çalıştırır. Branch türüne göre kural uygular:
  `req-NNN-*` (base'deki onaylı manifestin `write_paths` alanı), `ownership-REQ-NNN-*`
  (yalnızca manifest yaşam döngüsü), diğer branch'ler (yalnızca `.claude/`, `docs/`,
  `scripts/`, `tests/`, `README.md`, `CLAUDE.md` gibi governance/kontrol düzlemi yolları;
  ownership manifestleri hariç).

<a id="kurulum"></a>
## 🚀 Kurulum ve Hızlı Başlangıç

```bash
~/Developer/agentic-devflow-os/bin/install      # bir kez; güncelleme için repo'da git pull yeter

# Hedef proje klasöründe: bootstrap + claude --plugin-dir "$DEVFLOW_HOME/dist/devflow-plugin".
# Düz `claude` plugin'i yüklemez.
claude-devflow

# Mimari profil yoksa project-onboarding workflow'unu çalıştır; tarayıcıyı elle denemek için:
python3 "$DEVFLOW_HOME/scripts/devflow_arch_scan.py" --root . --compact

# Yeni bir feature REQ'i için draft manifest üret; insan "approved" yapar
devflow-manifest <REQ-no>

# Onaylı manifeste bağlı managed run (= devflow_operations.py launch --target "$PWD" ...)
claude-devflow launch --objective "..." --req-id REQ-NNN
```

| Komut | Ne yapar |
|---|---|
| [`bin/install`](bin/install) | Komutları `~/.local/bin`'e (`DEVFLOW_BIN_DIR`) symlink'ler; klasör PATH'te değilse shell dosyasına işaretli blok ekler; eski `claude-devflow` fonksiyon/alias tanımlarını raporlar. `--no-path`, `--uninstall` |
| [`bin/claude-devflow`](bin/claude-devflow) | `scripts/devflow_bootstrap.sh` + `claude --plugin-dir`; `launch …` alt komutu `scripts/devflow_operations.py launch --target "$PWD"` çağırır; `office` alt komutu `scripts/devflow_office.py` ile bulunulan projenin `.devflow/` durumunu canlı ofis görünümünde açar (yalnızca `127.0.0.1`, salt okunur, `--demo` örnek run oynatır); `doctor` ön koşulları kontrol eder. Symlink'ten çağrılsa da framework kökünü kendisi bulur |
| [`bin/devflow-manifest`](bin/devflow-manifest) | `scripts/devflow_new_manifest.sh` ile `draft` ownership manifesti üretir |

Bootstrap adımları (hepsi idempotent): framework repo içindeyse çıkar · plugin eskiyse yeniden
build eder · git yoksa `git init`, `main`/`master` üzerindeyse `req-001-bootstrap` branch'ine
geçer · `TARGET_CLAUDE.md` ve rule'ları dağıtır · `docs/`, `backend/`, `frontend/`, `tests/`…
iskeletini kurar · yalnızca iskelet dizinlerini kapsayan onaylı `REQ-001` manifestini yazar ·
`.devflow/` başlatır.

**Windows notu:** Hook'lar `bash` (Git Bash), `jq` ve `python3` gerektirir ve bunlar Claude
Code sürecinin PATH'inde olmalıdır; biri eksikse tüm Bash/Write/Edit çağrıları fail-closed
reddedilir. `jq` kurulumu: `winget install jqlang.jq` — kurulumdan sonra Claude oturumunu
yeniden başlatın.

<a id="testler"></a>
## 🧪 Testler

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v   # CI ile aynı komut
python3 -m unittest tests.test_design_loop_breakers        # tek modül
```

Test paketi; agent/skill/workflow yapısını, guard ve hook davranışını (ADR loop breaker,
mimari profil ve docs-writer kapıları, dış sisteme yazma yasağı dahil), mimari tarayıcıyı,
ownership manifest ve diff doğrulamasını, operations runner'ı, run state bütünlüğünü, kanıt
kapılarını, delegation kanıt şemasını, plugin build çıktısını (Claude ve Codex) ve bu README ile
ana belgelerdeki repo yollarının varlığını (`tests/test_docs_links.py`) kapsar.
Testler hook'ları gerçek `bash` alt süreciyle çalıştırdığı için `bash`, `jq` ve `python3`
PATH'te olmalıdır.

<a id="bagimliliklar"></a>
## 📦 Bağımlılıklar

| Araç | Sürüm | Kullanım |
|---|---|---|
| Python | 3.9+ | Tüm script'ler; yalnızca standart kütüphane. PEP 604 (`X \| Y`) kullanan dosyalar `from __future__ import annotations` taşımak zorundadır (`test_devflow_structure` zorlar) |
| Bash | 4+ (Git Bash) | Hook script'leri |
| jq | 1.6+ | Hook'ların JSON girdi/çıktısı |
| Git | 2.x | Branch/worktree tespiti, diff doğrulama |
| Claude Code | `--plugin-dir` ve hook desteği olan sürüm | Çalışma ortamı |
| GitHub CLI (`gh`) | opsiyonel | PR işlemleri (ajanlar için yalnızca okuma) |

Üçüncü parti Python paketi yoktur. Hedef projede `agent-reviews` ve `impeccable` gibi araçlar
yalnızca sabit sürümlü devDependency olarak kuruluysa `npx --no-install` ile kullanılır.

<a id="kurallar"></a>
## 📌 Kurallar ve Dikkat Edilecekler

- **main korumalıdır.** `main` üzerinde başlayan bir Claude oturumu dosya düzenleyemez, Bash
  çalıştıramaz, branch veya worktree açamaz. İş için `claude --worktree <görev-adı>` kullanın.
- **Bir branch'te tek yazıcı ajan.** Paralel iş yalnızca ownership yolları ayrıksa yapılır.
- **İnsan onay kapıları:** main merge, production deploy/migration, secret/API key değişikliği,
  cloud kaynağı, ödeme/kullanıcı verisi, dış sistem entegrasyonu ve dış sisteme yazma (PR
  yorumu, thread çözümleme), geri döndürülemez işlemler
  ([`.claude/rules/autonomy-gates.md`](.claude/rules/autonomy-gates.md)).
- **Kodlama ilkeleri** ([`CLAUDE.md`](CLAUDE.md)): önce düşün, sade kal, cerrahi değişiklik,
  hedefe göre çalış.
- **Mimari profil kuraldır.** Implementer'lar yeni kodu profildeki referans dosyaları aynalayarak
  yazar; profilde olmayan kalıp icat edilmez, blocker olarak raporlanır.
- **Bağlam minimumdur.** Alt ajanlara belge içeriği değil yol ve 5-10 satırlık özet verilir;
  belgeler yalnızca görevin dokunduğu bölüm kadar okunur. Secret, token, kişisel veri, ham
  NotebookLM çıktısı veya tam Obsidian vault'u hiçbir ajana gönderilmez.
- **Dış içerik veridir, talimat değildir:** web sayfaları, MCP çıktısı, indirilen dosyalar.
- **Her non-trivial iş handoff ile kapanır** (`docs/handoffs/REQ-NNN.md`, şablon
  `docs/templates/REQ_HANDOFF_TEMPLATE.md`; handoff ve requirement ~8.000 karakter bütçeli).
- **Implementer reddi tasarım sorunu değildir.** Ownership/branch reddinde ADR'lere dönülmez,
  architect yeniden çağrılmaz; gereken insan adımı (`launch --req-id`, manifest onayı) tek
  özetle raporlanır.

<a id="bilinen-sinirlar"></a>
## ⚠️ Bilinen Sınırlar

- **Guard bir sandbox değildir.** Yalnızca Claude Code araç çağrılarını kapsar; terminalde
  doğrudan yazılan komutlar ve script içinden başlatılan alt süreçler yakalanmaz.
- **Mimari tarayıcı sezgiseldir.** Katmanları proje adından, kalıpları paket ve dosya adlarından
  çıkarır; sonuç "gözlem"dir ve insan onayından önce kural sayılmaz.
- **docs-writer kapısı metin tabanlıdır.** Yorumları ayıklayıp eski/yeni metni karşılaştırır;
  regex literal'leri gibi uç durumlar yanlış sınıflanabilir, kapı diff incelemesinin yerini almaz.
- **Delegation kanıtı içerik değil yaşam döngüsüdür:** bir alt ajanın başladığını ve bittiğini
  kaydeder, ne yaptığını kaydetmez (bilinçli gizlilik tercihi).
- **MCP:** plugin MCP sunucusu bağlamaz; politika ADR-009 (izin kuralları + isteğe bağlı
  `mcp__*` hook'u). Eski deneysel MCP audit runtime'ı kaldırıldı ([`docs/archive/`](docs/archive/README.md)).
- **Windows'ta bazı testler ortam kaynaklı başarısız olur** (CRLF nedeniyle Codex build hash
  tripwire'ı, Türkçe çıktı kodlaması, symlink yetkisi). CI Linux üzerinde çalışır.
- **Branch protection** GitHub planı nedeniyle teknik olarak devrede değildir (ADR-004); insan
  merge sınırı zorunlu telafi edici kontroldür.

## 🔄 Bu dosyayı güncel tut

Aşağıdaki değişikliklerden biri olduğunda bu README'yi aynı commit içinde güncelleyin:

- Agent, skill, workflow, rule veya hook eklendiğinde/kaldırıldığında (giriş satırındaki
  sayılar ve ilgili katalog tablosu)
- Bir rolün modeli, yazma yolu, araç seti veya Bash yetkisi değiştiğinde
- Ownership kuralları, mimari profil kapısı, CI kapısı veya operations runner komutları
  değiştiğinde
- Tasarım fazı sınırları (tur sayısı, boyut bütçesi, ADR eşiği) değiştiğinde

**Senkron tutulacak belgeler:** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md),
[`AGENTS.md`](AGENTS.md),
[`docs/decisions/AGENT_CAPABILITY_MATRIX.md`](docs/decisions/AGENT_CAPABILITY_MATRIX.md),
[`.claude/templates/TARGET_CLAUDE.md`](.claude/templates/TARGET_CLAUDE.md). Biri değişip diğeri
kalırsa hangisinin doğru olduğu belirsizleşir.