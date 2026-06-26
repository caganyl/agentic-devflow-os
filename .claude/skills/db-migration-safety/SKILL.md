---
name: db-migration-safety
description: Migration önerisi, rollback planı, approval gate ve destructive database işlem sınırlarını uygular.
agent: database-engineer
triggers:
  - Yeni database migration yazılacağında
  - Schema değişikliği gerektiğinde
  - Production migration onayı alınmadan önce
---

# Skill: DB Migration Safety

## Amaç

Database değişikliklerini güvenli yap. Yanlış migration geri alınamaz veri kaybına
veya downtime'a yol açabilir.

## Migration Güvenlik Seviyeleri

| İşlem | Güvenlik | İnsan Onayı |
|-------|----------|-------------|
| Yeni tablo ekleme | Güvenli | Hayır (PR review yeterli) |
| Sütun ekleme (nullable) | Güvenli | Hayır |
| Index ekleme | Dikkatli (lock riski) | Büyük tabloda evet |
| Sütun adı değiştirme | Riskli (breaking change) | Evet |
| Sütun silme | Riskli (veri kaybı) | Evet |
| NOT NULL kısıtı ekleme | Riskli | Evet |
| Tablo silme | Yıkıcı | Evet + bekletme |
| Toplu veri güncelleme | Riskli (lock, performance) | Evet |

## Prosedür

### 1. Migration Taslağı

```sql
-- Migration: add_xxx_to_yyy
-- Date: YYYY-MM-DD
-- Author: database-engineer
-- Risk Level: low/medium/high
-- Rollback: see down() below

-- up()
ALTER TABLE yyy ADD COLUMN xxx VARCHAR(255);

-- down()
ALTER TABLE yyy DROP COLUMN xxx;
```

### 2. Rollback Planı

Her migration için rollback talimatı yaz:
- down() migration SQL'i
- Veri kaybı riski var mı?
- Rollback çalıştırılması için gereken süre tahmini
- Rollback sonrası uygulama çalışır durumda mı?

### 3. Yıkıcı İşlem Koruması

Sütun veya tablo silinmeden önce şu adımları takip et:
1. Uygulama kodunda alan kullanılıyor mu? (grep ile kontrol)
2. Son 30 günde veri yazılmış mı? (query ile kontrol)
3. İnsan onayı al
4. 24 saat bekleme (production'da)
5. Sil

### 4. Büyük Tablo Migration

10M+ satır olan tablolarda:
- Lock almadan çalışan migration yöntemini tercih et
- Batch processing kullan
- Maintenance window planla
- İnsan onayı ve briefing yap

### 5. Migration Test Kontrol Listesi

```
- [ ] up() testi: migration çalışıyor
- [ ] down() testi: rollback çalışıyor
- [ ] Uygulama migrasyondan sonra çalışıyor
- [ ] Foreign key kısıtları sağlam
- [ ] Index'ler doğru oluştu
- [ ] Production benzeri veri ile test edildi (boyut önemli)
```

## Kesin Sınırlar

- Production migration'ı insan onayı olmadan çalıştırma
- down() olmadan migration commit etme
- Destructive işlemi doğrulama adımları tamamlanmadan yapma
