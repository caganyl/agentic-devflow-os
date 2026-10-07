---
name: orchestrate-delivery
description: Delivery Lead'in plan → task graph → dispatch → QA → integration → merge recommendation akışını yönetir.
agent: delivery-lead
triggers:
  - Yeni REQ-ID teslimata alındığında
  - Feature delivery başlatılmadan önce
  - Çok-rol koordinasyonu gereken her iş
---

# Skill: Orchestrate Delivery

## Amaç

Delivery Lead'i plan oluşturmadan merge recommendation'a kadar adım adım yönlendir.

## Prosedür

### 1. Managed Run Boundary Kontrolü

`DEVFLOW_RUN_WORKTREE` ortam değişkeni tanımlıysa önce konumu doğrula:

```bash
pwd
git rev-parse --show-toplevel
git branch --show-current
```

- Kök `DEVFLOW_RUN_WORKTREE` ile eşleşmeli.
- Branch `DEVFLOW_RUN_BRANCH` ile eşleşmeli.
- Uyuşmazlık varsa delivery'yi başlatma; blocker'ı raporla ve dur.

Managed operations CLI her zaman şu şekilde ve ana oturum (supervisor)
tarafından çağrılır; delivery-lead alt ajanının Bash yetkisi yoktur:
```bash
python3 "$DEVFLOW_OPERATIONS_SCRIPT" ... --target "$DEVFLOW_RUN_WORKTREE"
```

Implementer yazabilmek için managed run'ın onaylı bir manifeste bağlı olması
gerekir: `launch --req-id REQ-NNN`. Run REQ'e bağlı değilse implementation
dispatch etme; bunu ilk adımda insana bildir.

### 2. Girdileri Doğrula

- REQ-ID var mı? Yoksa Product Analyst devreye al.
- Acceptance criteria tanımlı mı? Yoksa implementation başlatma.
- Context pack hazır mı? Yoksa `project-context-synthesis` skill'ini çalıştır.
- Ownership binding: REQ-ID için `docs/ownership/REQ-NNN.json` altında
  **onaylı** (`status: approved`) bir manifest var mı? Varsa run'ı REQ'e
  bağla — `create-run` (veya `launch`) çağrısına `--req-id REQ-NNN` ekle.
  Böylece her implementer/QA görevinin work-product kanıtı, o rolün
  manifestteki `write_paths` alanına bağlanır (bkz. ADR-008). Manifest yoksa
  veya draft ise `--req-id` geçme; binding inert kalır ve mevcut coarse
  kontroller geçerlidir.

### 3. Plan Üret

Şunları içeren bir plan yaz:

```markdown
## Delivery Plan: REQ-XXX

### Görev Özeti
[1-2 cümle]

### Bağımlılık Grafiği
- Contract Broker → Frontend + Backend (paralel)
- QA → implementation tamamlandıktan sonra
- Security Review → release öncesi

### Task Graph
| Görev | Owner | Önceki Görev | Artefakt |
|-------|-------|--------------|---------|
| Contract üret | Contract Broker | - | docs/contracts/... |
| Frontend impl | Frontend Eng | Contract | src/... |
| Backend impl | Backend Eng | Contract | src/... |
| Test yaz | QA | Implementation | tests/... |
| Security review | Security RT | Implementation | rapor |
| Release scorecard | Integration | QA + Security | scorecard |

### Risk Listesi
- [risk]: [etki] — [azaltma]

### Approval Gate'ler
- [ ] Contract onaylı
- [ ] Tüm AC testleri geçiyor
- [ ] Security review temiz
- [ ] İnsan: main merge
```

### 3b. Tasarım Fazı Protokolü (döngü kesici)

Tasarım fazı şu sırayla ve en fazla bir kez yürür:

1. **Eşik kontrolü:** ADR gerekli mi? (`solution-architect.md` → "ADR Gerekli
   mi?"). Gerekmiyorsa ADR görevi karar notuna dönüşür veya atlanır.
2. **Taslak:** solution-architect `.claude/templates/adr.md` ile tek ADR yazar.
3. **Review turu 1:** adr-reviewer → `VERDICT`.
   - APPROVE / APPROVE_WITH_NOTES → adım 5.
   - BLOCK → architect yalnızca BLOCKER'ları kapatır → adım 4.
4. **Review turu 2 (son):** adr-reviewer yalnızca önceki BLOCKER'lara bakar.
   - Hâlâ BLOCK → dur, BLOCKER listesini insana sun. Üçüncü tur yok.
5. **Tek insan kapısı:** ADR + contract + manifest için tek bir onay özeti
   sun (karar, etkilenen modüller, açık NOTES). Onaydan sonra implementation
   başlar ve tasarım dokümanlarına geri dönülmez.

Bu sınırlar `.claude/hooks/enforce-role-boundaries.sh` içindeki ADR loop
breaker ile teknik olarak da zorlanır (tur sınırı, Accepted dondurma, boyut
bütçesi).

### 4. Rolleri Dispatch Et

`task-routing` skill'ini kullanarak minimum rol setini belirle.
Her role şu formatla görev ver:

```markdown
**[Rol Adı]:** [görev tanımı]
- Girdiler: [bağımlı artefaktlar]
- Üretecekler: [beklenen artefaktlar]
- Gate: [hangi koşulda tamamlanmış sayılır]
```

### 5. Çıktıları Topla ve İzle

Her rolün çıktısını kısa structured handoff olarak topla (en fazla 10 satır;
tam doküman metnini orkestratör bağlamına geri taşıma, yol ver):
- Tamamlanan artefakt
- Açık sorunlar
- Sonraki adım

### 6. Integration ve Merge Recommendation

`release-scorecard` skill'ini çalıştır.
Tüm gate'ler geçilene kadar "merge ready" ilan etme.
İnsan onayını açıkça iste.

## Hata Durumları

- **Rol çıktısı geç geldi:** Bağımlı rolleri beklet, toplam plan güncelle.
- **Gate başarısız:** Blocker'ı önceliklendirme, bypass etme.
- **Session kesildi:** Run summary + açık task listesi üzerinden devam.
