# Workflow: New Product Discovery

## Ne Zaman Çağrılır?

Yeni bir ürün fikri, pazar fırsatı veya stratejik initiative değerlendirildiğinde.
Henüz REQ-ID atanmamış, scope belirsiz erken keşif aşamasında kullanılır.

## Girdiler

- Ürün fikri açıklaması veya problem statement
- Varsa rakip analiz notları
- Varsa kullanıcı araştırması verileri
- Obsidian'dan seçilmiş stratejik bağlam (isteğe bağlı)
- NotebookLM evidence pack (isteğe bağlı)

## Kullanılacak Roller

1. **Delivery Lead** — plan ve bağımlılıklar (dağıtımı ana oturum yapar)
2. **Product Analyst** — PRD, kullanıcı hikayeleri, acceptance criteria taslağı
3. **Design Reviewer** — kullanıcı akışı, bilgi mimarisi, erken UX değerlendirmesi
4. **Solution Architect** — teknik fizibilite notu ve sistem entegrasyonu; ADR yalnızca eşik sağlanırsa

## Gerekli Skill'ler

- `project-context-synthesis` — mevcut bağlam derleme
- `requirement-grilling` — ana oturum insanla tek tek soru sorarak belirsizlikleri kapatır; AC, kapsam dışı ve terim sözlüğü üretir
- `requirement-traceability` — requirement zinciri kurma
- `task-routing` — doğru agent setini seçme

## Approval Gate'ler

- [ ] Problem statement insan tarafından onaylanmış
- [ ] PRD taslağı insan tarafından review edilmiş
- [ ] Teknik feasibility değerlendirmesi tamamlanmış
- [ ] REQ-ID atanmış ve requirement dosyası oluşturulmuş

## Üretilecek Artefaktlar

- `docs/product/requirements/REQ-XXX.md` — requirement dosyası
- Teknik fizibilite notu (`docs/decisions/`); ADR (`docs/architecture/adr/ADR-NNN-*.md`) yalnızca eşik sağlanırsa
- Handoff güncellemesi

## Completion Kriteri

- REQ-ID atanmış ve acceptance criteria tanımlanmış
- Teknik feasibility değerlendirmesi tamamlanmış
- Feature Delivery workflow'una geçiş kararı alınmış veya reddedilmiş

## Handoff Formatı

```markdown
## Discovery: [Ürün Fikri Adı]
- REQ-ID: REQ-XXX (veya "henüz atanmadı")
- Problem statement özeti
- Kapsam kararı: devam / beklet / reddedildi
- Açık sorular
- Sonraki adım
```

## Failure / Recovery

- Scope creep: Product Analyst ile yeniden scope sınırı çiz
- Teknik belirsizlik: kısa bir spike veya fizibilite notu iste; ADR yalnızca eşik sağlanırsa
- Stakeholder anlaşmazlığı: insan approval gate'e taşı
