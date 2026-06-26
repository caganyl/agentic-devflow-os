---
name: autonomous-delivery-run
description: Delivery Lead'in run state, context pack, workflow ve task-routing kullanarak tam bir delivery döngüsü yürütmesini öğretir.
agent: delivery-lead
triggers:
  - Yeni bir REQ-ID için delivery başlatılacağında
  - Aktif run oluşturulduktan sonra
  - Delivery akışı kesmeden devam ettirilmesi gerektiğinde
---

# Skill: Autonomous Delivery Run

## Amaç

Delivery Lead'i `launch` ile başlayan ve merge recommendation ile biten
tam delivery döngüsünde adım adım yönlendir.

## Prosedür

### 1. Run Başlat

```bash
# Framework tarafından çalıştır (framework repo, target repo değil):
python3 scripts/devflow_operations.py launch \
  --target PATH \
  --objective "REQ-XXX: kısa açıklama"

# Önce planı doğrula:
python3 scripts/devflow_operations.py launch \
  --target PATH \
  --dry-run
```

`launch` komutu şunları yapar:
- Target çalışma ağacının temiz olduğunu doğrular
- `<target-parent>/.devflow-worktrees/<target-name>/run-NNN` worktree'yi oluşturur
- Yeni `devflow/run-run-NNN` branch'i açar
- `.devflow/` ve run state'i YALNIZCA run worktree içine yazar
- Main checkout'a dokunmaz
- Claude supervisor'ı `--plugin-dir` ile interaktif modda başlatır

**Önemli:** `create-run` veya `init-target` yalnızca main/master dışındaki
branch'lerden çalıştırılabilir. `launch` bu kontrolü otomatik yapar.

### 2. Context Pack Hazırla

`project-context-synthesis` skill'ini kullanarak şu kaynakları derle:

- Git-tracked requirement (REQ-XXX)
- İlgili contracts (`docs/contracts/`)
- İlgili ADR'lar (`docs/architecture/adr/`)
- Seçilmiş NotebookLM evidence (yalnızca label + özet, ham içerik değil)
- Seçilmiş Obsidian notları (yalnızca label + özet, tüm vault değil)

Context pack'i `.devflow/context/` altına yaz.

### 3. Task Routing

`task-routing` skill'ini kullanarak minimum rol setini belirle:

```
Task türü → Tablo → Minimum rol seti
```

Rol seçiminde şu faktörler belirleyicidir:
1. Task türü (feature, bug, AI/RAG, release vb.)
2. Bağımlılıklar (hangi rol diğerinden önce gelir)
3. Risk seviyesi (yüksek risk → daha fazla review rolü)
4. Ownership sınırları (aynı dosya alanına paralel assignment yapma)
5. Mevcut artefaktlar (contract varsa Contract Broker atla)

### 4. Task Graph Oluştur

Her görev için task packet oluştur (`.devflow/task-packets/` altında):

```markdown
| Görev | Owner | Önceki Görev | Artefakt |
|-------|-------|--------------|---------|
| Contract üret | Contract Broker | — | docs/contracts/... |
| Backend impl | Backend Eng | Contract | src/... |
| Frontend impl | Frontend Eng | Contract | src/... |
| Test yaz | QA | Implementation | tests/... |
| Security review | Security RT | Implementation | rapor |
| Release scorecard | Integration | QA + Security | scorecard |
```

### 5. Dispatch Et ve İzle

Her rolün çıktısını topla. Approval gate'leri kontrol et:

- `contract_approved`
- `tests_passing`
- `security_review_complete`
- `qa_sign_off`

Run state'ini güncelle: `.devflow/runs/RUN-NNN.json`.

### 6. Delivery Doğrulama

`release-scorecard` skill'ini çalıştır.

Tüm gate'ler geçilmeden "merge ready" ilan etme.
Human approval gate'i açıkça iste.

```bash
# Doğrulama raporu üret (gerçek Git işlemi yapmaz):
python3 scripts/devflow_operations.py prepare-delivery \
  --target PATH

# Gate'ler geçildi — onay kanıtı doğrulama (gerçek Git işlemi yapmaz):
python3 scripts/devflow_operations.py prepare-delivery \
  --target PATH \
  --confirm-delivery
```

**Bu sürümde `prepare-delivery` hiçbir gerçek Git mutasyonu çalıştırmaz.**
Commit, push ve PR insan tarafından yapılır.

**Main merge insan tarafından yapılır. Agent merge yapmaz.**

## Kısıtlar

- Aynı ownership alanında paralel implementation başlatma.
- Contract onaylanmadan frontend/backend paralel başlatma.
- Requirement ID olmadan yeni ürün davranışı icat etme.
- Acceptance criteria olmadan implementation başlatma.
- Security review tamamlanmadan release önerme.
- Main branch'te doğrudan değişiklik yapma.
- Run worktree dışında dosya oluşturma veya değiştirme.

## Session Kesilirse

Run state ve context pack üzerinden devam et:

1. `.devflow/project.json` → `current_run_id`
2. `.devflow/runs/RUN-NNN.json` → status, açık gates
3. `.devflow/context/` → mevcut context pack
4. `orchestrate-delivery` skill'ini çalıştır

Yarım kalan görev tamamlanmadan delivery bitmiş ilan etme.
