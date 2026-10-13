---
paths:
  - ".devflow/context/**"
  - ".devflow/task-packets/**"
  - ".claude/templates/context-pack.md"
---

# Context Distribution Rules

Bu kurallar ajanlara hangi bağlamın verileceğini tanımlar. Context pack
formatı: `.claude/templates/context-pack.md`. Üretim adımları:
`project-context-synthesis` skill'i.

## Temel İlke

Her ajan yalnızca kendi görevi için gereken minimum bağlamı alır. Tüm vault,
tüm doküman seti veya tam repo içeriği tek bir ajana gönderilmez. Belge
içeriği yerine yol + 5-10 satırlık özet verilir.

## Rol Başına Bağlam

| Rol | Verilecek bağlam |
|---|---|
| Product Analyst | PRD geçmişi, kullanıcı araştırması özeti, ilgili REQ'ler, seçilmiş Obsidian notları |
| Solution Architect | ADR indeksi + ilgili ADR'ların yalnızca Status ve Decision bölümleri, sistem sınırları, NotebookLM teknik bulguları |
| Contract Broker | Mevcut contract'lar, frontend/backend arayüz beklentileri, requirement'tan veri modeli ipuçları |
| Frontend Engineer | Kayıtlı contract, design spec/mockup referansı, profilin Frontend bölümü |
| Backend Engineer | Kayıtlı contract, profilin Backend bölümü, güvenlik kısıtları özeti |
| Database Engineer | DB schema contract, migration geçmişi özeti, rollback gereksinimleri |
| AI/Data Engineer | AI/ML ADR'ları, eval konfigürasyonu, model ve provider kısıtları |
| QA Automation | Acceptance criteria (tam liste), mevcut test durumu, regression risk alanları |
| Security Red Team | Tehdit modeli (varsa), auth/authz contract'ları, bilinen güvenlik kısıtları |
| Design Reviewer | UI mockup/spec referansları, erişilebilirlik gereksinimleri, tasarım sistemi |
| Docs Writer | Değişen dosya listesi, mimari profil yolu, kök README'deki `devflow:auto` blokları |

## Kademeli Bağlam

İlk paket dar tutulur. Alt ajan eksik bağlamı sonucunun başında
`CONTEXT_REQUEST:` bloğuyla (en fazla 3 yol + bölüm) ister; orkestratör en
fazla 2 tur ek bağlam verir. Üçüncü istek görevin yanlış bölündüğünün
işaretidir: görevi küçült veya insana sor.

## Hassas Veri

Hiçbir ajana gönderilmez: API key, token, secret, production credential,
kişisel kullanıcı verisi, ham NotebookLM belgesi (yalnızca evidence özeti),
tam Obsidian vault içeriği (yalnızca seçilmiş not özeti).
