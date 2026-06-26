---
name: api-contract-design
description: Contract-first yaklaşımla frontend/backend paralelliği için OpenAPI, event, DB schema ve shared type sözleşmeleri üretir.
agent: contract-broker
triggers:
  - Frontend ve Backend paralel çalışmaya başlamadan önce
  - Yeni API endpoint eklenirken
  - Event bus veya message schema değiştiğinde
  - Shared type eklenirken
---

# Skill: API Contract Design

## Amaç

Frontend ve Backend aynı anda üretemez — önce anlaşmaları gerekir.
Bu skill o anlaşmayı (contract) üretir ve her iki tarafın bağlı kalmasını sağlar.

## Contract Türleri

| Tür | Format | Dosya Yolu |
|-----|--------|-----------|
| REST API | OpenAPI 3.x YAML | `docs/contracts/api-*.yaml` |
| Event/Message | AsyncAPI veya JSON Schema | `docs/contracts/events-*.yaml` |
| Database Schema | SQL DDL veya migration | `docs/contracts/db-*.sql` |
| Shared Types | TypeScript veya JSON Schema | `docs/contracts/types-*.ts` |

## Prosedür

### 1. Requirement'tan Interface Çıkar

Acceptance criteria'dan şu soruların cevabını bul:
- Frontend hangi veriyi nasıl gösterecek?
- Backend hangi işlemi yapacak?
- Hangi alanlar zorunlu / opsiyonel?
- Hata senaryoları neler?

### 2. Contract Taslağı Yaz

OpenAPI örneği:
```yaml
openapi: "3.0.0"
info:
  title: "REQ-XXX API"
  version: "1.0.0"
paths:
  /resource:
    get:
      summary: "..."
      parameters: []
      responses:
        "200":
          description: "Success"
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Resource"
        "400":
          description: "Validation error"
        "401":
          description: "Unauthorized"
components:
  schemas:
    Resource:
      type: object
      required: [id, name]
      properties:
        id:
          type: string
        name:
          type: string
```

### 3. Contract Review Kontrol Listesi

```
- [ ] Tüm zorunlu alanlar belirtilmiş
- [ ] Hata senaryoları (400, 401, 403, 404, 500) tanımlanmış
- [ ] Pagination varsa belirtilmiş
- [ ] Breaking change yoksa versiyon aynı
- [ ] Frontend ve Backend temsilcisi onayladı
```

### 4. Contract Onaylandıktan Sonra

- Frontend ve Backend paralel çalışmaya başlayabilir
- Contract değişikliği için yeni PR ve her iki tarafın onayı gerekir
- Breaking change = versiyon artışı

## Contract İhlali Durumunda

Contract değişikliğini sessizce yapma.
Önce Contract Broker'a bildir, yeni contract üret, her iki tarafın onayını al.
