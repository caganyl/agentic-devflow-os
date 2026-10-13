---
name: orchestrate-delivery
description: Ana oturumun çok rollü bir teslimatı (feature, bug, AI/RAG, dashboard, güvenlik, release, maliyet) baştan sona yönetmesi için tek orkestrasyon protokolü — run sınırı, plan ve task graph, tasarım fazı döngü kesicisi, subagent/agent team dispatch, kanıt kaydı ve merge tavsiyesi.
when_to_use: Bir REQ için teslimat başlatılırken, managed run (launch) içinde iş dağıtılırken, kesilmiş bir run'a devam edilirken veya birden fazla DevFlow rolü gerektiğinde. Tek rollü küçük işte gerekmez.
---

# Skill: Orchestrate Delivery

## Amaç

Ana oturum tek orkestratördür. `delivery-lead` yalnızca plan döner; alt
ajanları sen başlatır, CLI kayıt komutlarını sen çalıştırırsın. Bu protokol
Claude Code'un native subagent/agent team mekanizmasını yönlendirir; ayrı bir
API, SDK dispatcher veya dış orkestratör değildir.

CLI her zaman: `python3 "$DEVFLOW_OPERATIONS_SCRIPT" <komut> --target "$DEVFLOW_RUN_WORKTREE"`
(managed run dışında `python3 scripts/devflow_operations.py <komut> --target <yol>`).

## Prosedür

### 1. Run Sınırı ve Bağlama

- `DEVFLOW_RUN_WORKTREE` tanımlıysa kök ve branch'i doğrula
  (`git rev-parse --show-toplevel`, `git rev-parse --abbrev-ref HEAD` ↔
  `DEVFLOW_RUN_BRANCH`). Uyuşmazlıkta başlama, blocker'ı raporla.
- `status` ile run durumunu oku. Run REQ'e bağlı değilse (`req_id` yok)
  implementer'lar yazamaz: insana `docs/ownership/REQ-NNN.json` onayını ve
  `launch --req-id REQ-NNN` ile yeniden başlatmayı söyle; implementation
  dispatch etme.
- Run yoksa insan başlatır: `launch --target <proje> --objective "REQ-NNN: ..." --req-id REQ-NNN`
  (`--dry-run` ile önizleme, `--agent-teams` ile agent team modu).

### 2. Girdileri Doğrula

- REQ-ID ve acceptance criteria yoksa implementation yok; Product Analyst
  (belirsizse önce insanla `requirement-grilling`).
- Mimari profil yoksa/`draft` ise önce `project-onboarding` workflow'u.
- Manifest `approved` değilse implementation yok; insan adımı.

### 3. Plan ve Task Graph

- Küçük işte rolleri `.claude/rules/task-routing.md`'den kendin seç; çok
  rollü işte `delivery-lead`'den plan iste (task graph, roller, gate'ler,
  context pack taslağı, ADR gerekip gerekmediği).
- Task graph'ı CLI üretir:
  `generate-task-graph --delivery-type <tip> [--needs-adr]`.
  `--needs-adr` yalnızca `solution-architect.md`'deki ADR eşiği sağlanıyorsa
  verilir. Tipler: `new_feature`, `ai_rag`, `data_dashboard`,
  `bug_resolution`, `security_response`, `release_readiness`,
  `cost_optimization`, `new_product_discovery`, `backend_utility`
  (risk sinyali olmayan küçük, yerel backend işi).
- **Task graph değişmezdir.** Aktif bir run'da (task `planned` dışına
  çıkmış, delegation event'i veya kanıt kaydı var) `--force` exit 16 ile
  reddedilir. Farklı routing gerekiyorsa yeni run başlat; mevcut run'ı
  değiştirme. Eşik yokken ADR eklemek için run'ı yeniden oluşturma.
- Task durumunu `update-task-status --task-id <id> --status <durum>` ile
  ilerlet (`planned → ready → in_progress → completed → verified`).

### 4. Tasarım Fazı (döngü kesici, en fazla bir kez)

1. Eşik yoksa ADR yok; gerekirse kısa karar notu.
2. solution-architect tek ADR yazar (`.claude/templates/adr.md`).
3. adr-reviewer tur 1 → APPROVE / APPROVE_WITH_NOTES ise adım 5; BLOCK ise
   architect yalnızca BLOCKER'ları kapatır.
4. adr-reviewer tur 2 (son) → hâlâ BLOCK ise dur, BLOCKER listesini insana
   sun. Üçüncü tur yok (hook reddeder).
5. `Proposed` ADR ile contract adımına geç; contract-broker'ın yazdığı
   dosyayı `record-contract-evidence --evidence-path docs/contracts/<dosya>`
   ile kaydet — implementation bununla açılır. `Accepted` ve açık NOTES merge
   öncesi insan özetine girer.

Bu noktadan sonra tasarım dokümanlarına dönülmez. Herhangi bir blokajda
(insan kapısı, ownership/branch reddi) architect'i yeniden çağırma; blokajı
tek özetle insana sun ve dur.

### 5. Context Pack

Rol başına `project-context-synthesis` ile tek format
(`.claude/templates/context-pack.md`) kullanarak `.devflow/context/` altına
yaz. Alt ajana belge içeriği değil yol + 5-10 satır özet ver. Ham
NotebookLM/Obsidian içeriği, token, URL veya credential girmez.

### 6. Dispatch

Her görev mesajı: rol, görev, girdiler (yollar), üretilecek artefakt, gate.

- **Varsayılan: subagent**, sıralı veya bağımsız.
- **Agent team** yalnızca hepsi sağlanırsa: run `--agent-teams` ile
  başlatıldı (`execution_mode: agent_teams`), en az iki bağımsız araştırma/
  review/ayrık dosya alanı görevi var, aynı dosyaya eşzamanlı yazma yok.
  İlk paralel faz yalnızca analiz, contract review, test planı, security
  review veya ayrık alan görevleridir; implementation contract kaydını bekler.
- **Paralel write yasağı:** aynı veya iç içe `write_paths`'e iki eşzamanlı
  yazma görevi verilmez (ör. backend `src/` + frontend `src/` yasak;
  `src/api/` + `src/ui/` serbest).
- Sıra: implementation → QA → Security → Docs Writer → Integration/Release.
- Review döngüleri: ADR en fazla 2 tur; security, design, eval ve PR triage
  en fazla bir yeniden inceleme; sonrası insan kararı.
- Alt ajan sonucu en fazla 10 satır özet olarak alınır; `CONTEXT_REQUEST:`
  gelirse en fazla 2 tur ek bağlam ver.

### 7. Kanıt Kaydı

Ajanlar `.devflow/runs/` ve `.devflow/reports/` yazamaz; kayıtları sen
yaparsın:

| Ne zaman | Komut |
|---|---|
| Contract yazıldı | `record-contract-evidence --evidence-path docs/contracts/<dosya>` |
| Implementation/QA task'ı dosya üretti | `record-work-product-evidence --task-id <id> --evidence-path <değişen dosya>` |
| Testler | `record-qa-evidence --test-command "<tam suite komutu>"` (CLI çalıştırıp exit kodunu ölçer) |
| Security raporu (yalnızca `security_review_required=true` run'da) | `record-security-evidence --verdict pass\|blocked --max-severity <...> --evidence-path docs/quality/security-reports/<rapor>.md` |
| Son | `generate-run-report` → `.devflow/reports/RUN-NNN-report.json` ve `-scorecard.md` |

`security_review_required` ve uygulanabilirlik CLI tarafından deterministik
belirlenir; gerekmiyorsa security gate `not_applicable` sayılır.

### 8. Teslim

- integration-release `release-scorecard` ile tavsiye üretir.
- `prepare-delivery [--confirm-delivery]` yalnızca doğrulama raporu üretir;
  gerçek Git mutasyonu yapmaz.
- Commit, push, PR ve main merge insan adımıdır. Tüm gate'ler geçilmeden
  "merge ready" deme; insana `.devflow/reports/RUN-NNN-scorecard.md`'yi göster.

## Delegation Kanıtı Dürüstlüğü

- `--agent-teams` yalnızca konfigürasyondur; gerçek dispatch kanıtı değildir.
- SubagentStart/Stop event'i (`.devflow/delegation-events/`) yoksa
  "delegated" / "executed by role" iddiası yapılmaz;
  `delegation_evidence_status` `not_observed` veya `unavailable` kalır.
- Aynı run içinde yazılmış AC veya security checklist bağımsız onay gibi
  gösterilmez. Inline teslimat başarısızlık değildir ama delegation başarısı
  olarak raporlanmaz.

## Hata ve Recovery

- **Gate başarısız:** blocker'ı önceliklendir, bypass etme.
- **Ownership/branch reddi:** tasarım sorunu değildir; insan adımını raporla.
- **Oturum kesildi:** `status` → açık task'lar → `.devflow/context/` →
  kaldığın task'tan devam. Yarım iş tamamlanmadan delivery bitmiş sayılmaz.
- İnsan onayı gerektiren işlemler: `.claude/rules/autonomy-gates.md`.
