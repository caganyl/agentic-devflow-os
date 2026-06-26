# DevFlow: Native Team Runtime & Target Safety Envelope

**Date:** 2026-06-26
**Status:** Accepted
**Replaces:** (yeni karar — mevcut kararları genişletir)
**Related:** DEVFLOW_TARGET_PROJECT_RUNTIME.md, DEVFLOW_AUTONOMOUS_DELIVERY_MODEL.md

---

## Özet

Bu belge Agentic DevFlow OS'a eklenen iki yeni kapasiteyi tanımlar:

1. **Native Team Runtime** — `launch --agent-teams` bayrağı ile Claude Code'un
   deneysel agent teams özelliğinin per-run, opt-in olarak etkinleştirilmesi.

2. **Target Safety Envelope** — Plugin kaynaklı deterministic hook'ların (`devflow_target_guard.py`)
   target oturumuna taşınması ve Claude Code tool çağrılarının korunması.

---

## Bölüm 1 — Native Team Runtime

### 1.1 Agent Teams: Opsiyonel, Per-Run, Deneysel

- Agent teams varsayılan olarak **kapalıdır**. Varsayılan dispatch modu `subagents`'tır.
- Etkinleştirmek için: `launch --agent-teams`
- Bu bayrak yalnızca spawned Claude process environment'ını etkiler.
  Kullanıcının shell environment'ı veya kalıcı settings dosyaları değişmez.
- Agent teams özelliği deneyseldir (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`).
  Claude tarafından kararlı olmayan bir özellik olarak işaretlenmiştir.
- Agent teams **token maliyetlidir** — paralel subagent'lar için ek token tüketimi oluşur.
  Bu maliyeti göz önünde bulundurarak kullanın.

### 1.2 Default Dispatch Mode: Subagents

```
launch (default)         → execution_mode: "subagents"
launch --agent-teams     → execution_mode: "agent_teams"
```

Her iki modda da run state şu alanları içerir:
```json
{
  "execution_mode": "subagents" | "agent_teams",
  "requested_agent_teams": false | true,
  "task_graph_status": "not_started",
  "context_pack_status": "not_started"
}
```

### 1.3 Native Team Mode: Yalnızca Bağımsız Paralel İşler İçin

Agent teams modu şu koşulların tamamı sağlandığında kullanılır:

1. `execution_mode == "agent_teams"` (launch --agent-teams ile başlatıldı)
2. En az iki **bağımsız** araştırma, review veya ayrık dosya alanı görevi mevcutsa
3. Aynı dosyaya eşzamanlı yazma planlanmıyorsa

**Aynı owned_path'e paralel write task oluşturmak kesinlikle yasaktır.**

Sıralı iş akışları veya bağımlı görevler için agent teams modu bile olsa
subagent kullanılır.

### 1.4 Task Graph: Claude Tarafından Yönetilen Delivery Artifact

Task graph, Claude supervisor'ın run worktree içinde oluşturduğu ve yönettiği
bir delivery artifact'idir:

```
.devflow/plans/RUN-NNN-task-graph.md   ← okunabilir format
.devflow/runs/RUN-NNN.json             ← "tasks" alanı (makine okunabilir)
```

Task graph, bir deployment configuration veya infrastructure spec değildir.
Delivery sürecinde Delivery Lead'in izlediği ve güncellediği bir plan belgesidir.

Her task için zorunlu alanlar:
- `task_id`, `title`, `owner_agent`, `status`
- `depends_on`, `owned_paths`, `required_artifacts`, `approval_gate`

---

## Bölüm 2 — Target Safety Envelope

### 2.1 Plugin Hook: Deterministic Claude-Tool Safety

Plugin kaynaklı `devflow_target_guard.py` ve `hooks/hooks.json` dosyaları
target oturumuna taşınır. Bu hook, Claude Code tool çağrılarını kontrol eder:

- **Bash:** Yıkıcı git komutları ve `rm -rf` bloklanır.
- **Write / Edit:** Hassas path'lere yazma bloklanır.

### 2.2 Hook Kapsamı: Yalnızca Claude Code Tool Çağrıları

**Bu hook, kullanıcının terminalinde elle girilen komutları KORUMAZ.**
Hook yalnızca Claude Code'un kendi araç çağrılarını (Bash, Write, Edit) kontrol eder.

Hook devreye girdiğinde:
- Exit code 2 ile çıkar
- Claude'a kısa, deterministic, kullanıcı verisi içermeyen bir mesaj gönderir
- Komut veya path içeriği mesajda yer almaz

### 2.3 Bloklu Bash Komutları

Aşağıdaki komutlar Claude Code oturumu içinden bloklanır:

| Bloklu Komut | Neden |
|-------------|-------|
| `git merge` | Main merge insan onayı gerektirir |
| `git push --force` / `git push -f` | Geçmiş yok eder |
| `git branch -d` / `git branch -D` | Başkasının çalışmasını silebilir |
| `git reset --hard` / `--soft` / `--mixed` | Geri alınamaz |
| `git clean -f` | Untracked dosyaları kalıcı siler |
| `git checkout -- .` | Uncommitted değişiklikleri yok eder |
| `git restore .` | Uncommitted değişiklikleri yok eder |
| `rm -rf` | Kalıcı silme |

**Bloklanmayan güvenli komutlar:** `git status`, `git diff`, `git add`,
`git commit`, normal `git push` (force flag olmadan), `git worktree add`,
test çalıştırma komutları.

### 2.4 Bloklu Write / Edit Path'leri

Aşağıdaki path'lere yazma bloklanır:

| Pattern | Neden |
|---------|-------|
| `.env`, `.env.*` | Environment secret |
| `credential[s]` (path segment) | Credential dosyası |
| `secret[s]` (path segment) | Secret dosyası |
| `.mcp.json`, `mcp.json`, `mcp_config.json` | MCP konfigürasyonu |
| `.claude/settings.json`, `.claude/settings.local.json` | Claude ayarları |
| `.claude/hooks/` (herhangi bir dosya) | Hook koruması |

**Bloklanmayan güvenli path'ler:** Normal source code, test dosyaları,
`docs/`, `.devflow/` (context, plans, runs, reports).

### 2.5 Hook Bir Yetki Eklemez

Plugin safety hook:
- Credential, token veya API key içermez
- MCP bağlantısı kurmaz
- Ağ erişimi gerektirmez
- Yalnızca local, standard-library Python kullanır
- Kullanıcının diğer uygulamalarının işlemlerini engellemez

---

## Bölüm 3 — Değişmeyen Kurallar

### 3.1 İnsan Onayı Gerektiren İşlemler

Bu karardan bağımsız olarak, aşağıdaki işlemler **hâlâ insan onayı gerektirir:**

- Main branch merge (PR review dahil)
- Production deployment
- Production database migration çalıştırma
- Force push (bu zaten hook ile bloklanıyor)
- Credential veya permission değişikliği
- External MCP bağlantısı kurma (gerçek production ortamında)

Native team mode veya agent teams özelliği bu kuralları değiştirmez.

### 3.2 Plugin Build Güvencesi

Plugin build aşağıdakileri TAŞIR:
- `hooks/hooks.json` (plugin-level target guard hook)
- `scripts/devflow_target_guard.py` (guard script)
- `scripts/devflow_operations.py` (managed operations runner)
- `agents/`, `skills/`, `templates/`, `workflows/`, `rules/`

Plugin build aşağıdakileri KESİNLİKLE TAŞIMAZ:
- `settings.json` (framework Claude settings)
- `.claude/hooks/` (framework hook bash scripts)
- `.mcp.json`, `mcp.json` (MCP konfigürasyonu)
- Credential, token veya secret içeren herhangi bir dosya

---

## Güncellenen Skill'ler

`native-team-delivery/SKILL.md` yeni protokolü tanımlar.

`autonomous-delivery-run`, `managed-delivery-operations`, `orchestrate-delivery`
ve `task-routing` skill'leri bu kararla çelişen bir kural içermemektedir.
Mevcut kısıtlar (human approval gates, forbidden git ops, ownership boundaries)
değişmeden geçerlidir.
