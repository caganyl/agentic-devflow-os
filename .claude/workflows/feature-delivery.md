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
3. **Solution Architect** — mimari karar (yalnızca ADR eşiği sağlanırsa)
   - **ADR Reviewer** — tek turda VERDICT; en fazla 2 tur, sonrası insan kararı
4. **Contract Broker** — API/event/DB contract (frontend+backend paralel başlamadan önce)
5. **Frontend Engineer** — UI implementation (contract sonrası)
6. **Backend Engineer** — API ve service implementation (contract sonrası)
7. **Database Engineer** — schema ve migration (gerekirse)
8. **QA Automation** — test yazma ve acceptance verification
9. **Security Red Team** — security review (release öncesi)
10. **Docs Writer** — değişen klasörlerin README'leri, kök README blokları, değişen dosyalara yorum (QA sonrası, tek writer)
11. **Integration/Release** — release scorecard ve merge recommendation

## Gerekli Skill'ler

- `orchestrate-delivery` — delivery akışını yönetme
- `requirement-grilling` — AC belirsizse implementation öncesi, insanla
- `tdd-vertical-slice` — implementer ve QA test disiplini
- `stack-verification` — "bitti" öncesi sabit doğrulama sırası
- `pr-review-triage` — PR açıldıktan sonra review yorumları
- `documentation-sync` — QA sonrası README ve yorumlar
- Ön koşul: onaylı mimari profil (`project-onboarding` workflow'u)
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

- ADR ikinci turda hâlâ BLOCK: dur, BLOCKER listesini insana sun; üçüncü tur yok
- Implementer ownership/branch nedeniyle reddedildi: tasarıma dönme; `launch --req-id` veya manifest onayı için insana raporla

- Contract belirsizliği: Contract Broker'a geri dön
- Test başarısızlığı: QA Automation ile birlikte root cause analizi
- Security bulgu: Security Red Team severity'ye göre blocker/non-blocker belirler
- Session kesilmesi: run summary ve açık task listesi üzerinden devam
