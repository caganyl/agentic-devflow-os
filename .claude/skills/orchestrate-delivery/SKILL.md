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

### 1. Girdileri Doğrula

- REQ-ID var mı? Yoksa Product Analyst devreye al.
- Acceptance criteria tanımlı mı? Yoksa implementation başlatma.
- Context pack hazır mı? Yoksa `project-context-synthesis` skill'ini çalıştır.

### 2. Plan Üret

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

### 3. Rolleri Dispatch Et

`task-routing` skill'ini kullanarak minimum rol setini belirle.
Her role şu formatla görev ver:

```markdown
**[Rol Adı]:** [görev tanımı]
- Girdiler: [bağımlı artefaktlar]
- Üretecekler: [beklenen artefaktlar]
- Gate: [hangi koşulda tamamlanmış sayılır]
```

### 4. Çıktıları Topla ve İzle

Her rolün çıktısını kısa structured handoff olarak topla:
- Tamamlanan artefakt
- Açık sorunlar
- Sonraki adım

### 5. Integration ve Merge Recommendation

`release-scorecard` skill'ini çalıştır.
Tüm gate'ler geçilene kadar "merge ready" ilan etme.
İnsan onayını açıkça iste.

## Hata Durumları

- **Rol çıktısı geç geldi:** Bağımlı rolleri beklet, toplam plan güncelle.
- **Gate başarısız:** Blocker'ı önceliklendirme, bypass etme.
- **Session kesildi:** Run summary + açık task listesi üzerinden devam.
