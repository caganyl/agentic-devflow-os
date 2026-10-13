# Context Pack: [görev adı]

<!-- Tek context pack formatı budur. 300-500 kelime; belge içeriği değil yol +
     ilgili bölüm. Dağıtım kuralları: .claude/rules/context-distribution.md.
     Konum: .devflow/context/RUN-NNN-<rol>.md -->

## Meta

- **Task ID:** TASK-[NNN]
- **REQ-ID:** REQ-[NNN]
- **Hedef agent:** [rol adı]
- **Oluşturulma:** YYYY-MM-DD

---

## Görev Özeti

[1-2 cümle: agent'ın ne yapması gerekiyor]

## İlgili Requirement

**REQ-[NNN]:** [requirement başlığı]

İlgili Acceptance Criteria:
- AC-01: [kriter]
- AC-02: [kriter]

Kaynak: `docs/product/requirements/REQ-XXX.md`

## İlgili Contract'lar

- **API Contract:** `docs/contracts/openapi/REQ-XXX.yaml`
  - Özet: [ilgili endpoint'ler ve schema'lar]
- **DB Contract:** `docs/contracts/database/REQ-XXX.md` (varsa)
  - Özet: [ilgili tablolar]

## İlgili Mimari Kararlar

- **ADR-NNN:** [başlık] — yalnızca Status ve Decision özeti
  - Etki: [bu görev için önemi]

## Evidence (NotebookLM — doğrulanmamış)

> Bu bölümdeki bilgiler NotebookLM evidence'ından alınmıştır.
> Canonical kaynak için yukarıdaki Git referanslarına bakın.

- **Bulgu:** [...]
  - Kaynak: [doküman adı]
  - Güven: high / medium / low
  - Not: "Git'te doğrulanması gerekiyor"

## Stratejik Bağlam (Obsidian — kişisel not)

> Bu bölüm ürün yönü ve öncelik bağlamı içindir.
> Resmi requirement için yukarıdaki Git referanslarına bakın.

- [kısa stratejik not özeti]

## Bilinen Riskler

- [risk 1]: [etki ve azaltma]

## Kapsam Dışı

Bu context pack'te şunlar kasıtlı olarak yer almıyor:
- [kapsam dışı alan 1]
- [kapsam dışı alan 2]

## Kaynak Register

`.devflow/source-register.json` (şablon: `source-register.yaml`).
