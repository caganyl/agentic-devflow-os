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

1. **Delivery Lead** — süreci yönetir, bağımlılıkları belirler
2. **Product Analyst** — PRD, kullanıcı hikayeleri, acceptance criteria taslağı
3. **Design Reviewer** — kullanıcı akışı, bilgi mimarisi, erken UX değerlendirmesi
4. **Solution Architect** — teknik feasibility, sistem entegrasyonu, ADR taslağı

## Gerekli Skill'ler

- `project-context-synthesis` — mevcut bağlam derleme
- `requirement-traceability` — requirement zinciri kurma
- `task-routing` — doğru agent setini seçme

## Approval Gate'ler

- [ ] Problem statement insan tarafından onaylanmış
- [ ] PRD taslağı insan tarafından review edilmiş
- [ ] Teknik feasibility değerlendirmesi tamamlanmış
- [ ] REQ-ID atanmış ve requirement dosyası oluşturulmuş

## Üretilecek Artefaktlar

- `docs/product/requirements/REQ-XXX.md` — requirement dosyası
- `docs/architecture/adr/ADRNNN-*.md` — ilgili mimari kararlar (varsa)
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
- Teknik belirsizlik: Solution Architect'e ADR çalışması ver
- Stakeholder anlaşmazlığı: insan approval gate'e taşı
