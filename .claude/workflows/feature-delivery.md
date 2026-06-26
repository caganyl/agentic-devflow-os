# Workflow: Feature Delivery

## Ne Zaman Çağrılır?

Onaylı bir REQ-ID ile yeni bir ürün özelliği geliştirildiğinde.
Requirement ve acceptance criteria mevcut olmalı; yoksa önce `new-product-discovery` çalıştırılır.

## Girdiler

- REQ-ID ve requirement dosyası
- Acceptance criteria listesi
- İlgili ADR'lar
- Onaylı veya taslak contract (yoksa Contract Broker devreye girer)
- Context pack

## Kullanılacak Roller

Sırayla ve minimum set prensibine göre:

1. **Delivery Lead** — plan, task graph, bağımlılık haritası
2. **Product Analyst** — acceptance criteria netleştirme (gerekirse)
3. **Solution Architect** — mimari karar (gerekirse)
4. **Contract Broker** — API/event/DB contract (frontend+backend paralel başlamadan önce)
5. **Frontend Engineer** — UI implementation (contract sonrası)
6. **Backend Engineer** — API ve service implementation (contract sonrası)
7. **Database Engineer** — schema ve migration (gerekirse)
8. **QA Automation** — test yazma ve acceptance verification
9. **Security Red Team** — security review (release öncesi)
10. **Integration/Release** — release scorecard ve merge recommendation

## Gerekli Skill'ler

- `orchestrate-delivery` — delivery akışını yönetme
- `task-routing` — minimum rol seti seçimi
- `api-contract-design` — contract oluşturma
- `db-migration-safety` — migration güvenliği
- `qa-acceptance-verification` — test coverage doğrulama
- `adversarial-security-review` — güvenlik incelemesi
- `release-scorecard` — merge hazırlığı

## Approval Gate'ler

- [ ] Contract onaylanmış (frontend+backend paralel başlamadan önce)
- [ ] Tüm acceptance criteria testleri geçiyor
- [ ] Security review tamamlanmış
- [ ] QA sign-off verilmiş
- [ ] Integration/Release scorecard üretilmiş
- [ ] **İnsan onayı: main merge**

## Üretilecek Artefaktlar

- Feature branch'te implementation kodu
- Test dosyaları
- Contract dosyası (`docs/contracts/`)
- Güncellenmiş handoff (`docs/handoffs/REQ-XXX.md`)
- Release scorecard

## Completion Kriteri

- Tüm acceptance criteria testleri geçiyor
- Lint, typecheck, test suite temiz
- Security review onaylanmış
- Integration/Release scorecard "merge ready"

## Handoff Formatı

Bkz. `.claude/templates/handoff.md`

## Failure / Recovery

- Contract belirsizliği: Contract Broker'a geri dön
- Test başarısızlığı: QA Automation ile birlikte root cause analizi
- Security bulgu: Security Red Team severity'ye göre blocker/non-blocker belirler
- Session kesilmesi: run summary ve açık task listesi üzerinden devam
