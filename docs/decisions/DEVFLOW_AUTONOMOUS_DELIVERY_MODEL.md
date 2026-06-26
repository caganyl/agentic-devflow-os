# DevFlow Autonomous Delivery Model

Bu doküman Agentic DevFlow OS'un delivery modelini, framework/target repo
ayrımını ve agent team çalışma yaklaşımını açıklar.

## Framework Repo / Target Repo Ayrımı

### Framework Repo (`~/Developer/agentic-devflow-os`)

Framework repo yazılım geliştirme sürecinin kendisini tanımlar:

- **Agent rol tanımları** (`.claude/agents/`) — her rolün ne yapıp yapamayacağı
- **Workflow tanımları** (`.claude/workflows/`) — hangi iş türünde hangi akış
- **Skill kataloğu** (`.claude/skills/`) — uzmanlaşmış prosedürler
- **Rule'lar** (`.claude/rules/`) — kaynak hiyerarşisi, routing, sınırlar
- **Context şablonları** (`.claude/templates/`) — task packet, context pack vb.
- **Plugin build sistemi** (`scripts/build_devflow_plugin.py`)

Framework repo production kodu, migration dosyası veya target project
credential'ı içermez. Ürün kodu üretmez; ürün kodunun nasıl üretileceğini tanımlar.

### Target Project Repo (ör. `~/Developer/projects/startup-crm`)

Target project gerçek ürünü barındırır. Framework bu repo'ya şu şekilde entegre olur:

1. Plugin build çalıştırılır: `python3 scripts/build_devflow_plugin.py`
2. `dist/devflow-plugin/` target project'e kopyalanır
3. Target project'te `.devflow/` yapısı oluşturulur
4. Delivery Lead ilk context pack ve source register'ı hazırlar

## Target Project `.devflow/` Alanı

Target project'te `.devflow/` altında framework ile çalışmanın durumu tutulur:

```
.devflow/
├── context/          ← context pack'ler ve source register
├── tasks/            ← task packet'ler
├── runs/             ← agent run summary'leri
└── reports/          ← scorecard ve merge recommendation'lar
```

Bu alan Git'te takip edilir. Secret, credential veya kişisel veri içermez.

## Kaynak Hiyerarşisi

Framework içinde ve target project çalışmasında kaynak güvenilirliği:

```
1. Git target project repository
   → resmi requirement, contract, code, test, handoff ve kararlar

2. NotebookLM
   → read-only evidence retrieval
   → büyük proje dokümanları için bağlam
   → CANONICAL DEĞİL; "doğrulanması gerekiyor" etiketi taşır

3. Obsidian
   → seçilmiş stratejik ürün bağlamı
   → kişisel notlar
   → CANONICAL DEĞİL; proje gerçeği değil

4. Agent output
   → ANCAK Git artefaktına dönüştürülüp doğrulanırsa resmi sayılır
   → Session içi sonuçlar ephemeral'dir
```

NotebookLM ve Obsidian için framework repo'ya gerçek MCP bağlantısı eklenmez.
Context flow şablonları ve skill'ler bu kaynakların nasıl kullanılacağını tanımlar.

## Agent Team Çalışma Modeli

### Planlama Aşaması

Delivery Lead şunu yapar:
- Task türünü belirler (`.claude/rules/task-routing.md`)
- Context pack ihtiyacını belirler (`project-context-synthesis` skill)
- Minimum agent rol setini seçer
- Task graph ve bağımlılık grafiği üretir
- Riskli işleri approval gate'e taşır

### Implementation Aşaması

- Planning/research/review rolleri paralel çalışabilir
- Implementation rolleri yalnızca ownership path'leri ayrıksa paralel çalışır
- Contract onayı olmadan Frontend + Backend paralel başlamaz
- Aynı dosya alanına iki rol aynı anda atanmaz

### Sonuçların Toplanması

Delivery Lead:
- Her rolün çıktısını kısa structured handoff olarak toplar
- Traceability matrisini günceller (`requirement-traceability` skill)
- Tüm gate'ler karşılanana kadar delivery'yi tamamlanmış ilan etmez

## Otomatik vs. İnsan Onaylı İşlemler

### Otomatik (Agent'lar bağımsız yürütür)

- Kod okuma, grep, keşif
- Taslak üretimi (requirement, ADR, contract, test, handoff)
- Local test çalıştırma
- Review raporu üretimi (security, design, evalops)
- Context pack ve source register güncelleme

### İnsan Onayı Gerektirir

- **main branch merge**
- **Production deployment**
- **Production database migration**
- Secret veya API key değişikliği
- Cloud resource oluşturma/silme
- Model/provider değişikliği (AI feature'lar)
- Gerçek external MCP bağlantısı kurma
- Geri döndürülemez veri operasyonları

## Agent Team'in Deneysel Doğası

Agentic DevFlow OS'un agent team modeli **deneyseldir**. Bu şu anlama gelir:

- Agent koordinasyonu zaman zaman beklenen sırayı takip etmeyebilir
- Long-running session'larda context kesilebilir
- Paralel agent çalışmasında beklenmedik çakışmalar oluşabilir
- Rol sınırları ihlal edilebilir (hook'lar bunu engeller)

### Recovery Yaklaşımı

Session kesildiğinde:
1. `.claude/templates/run-summary.md` formatındaki son run summary'ye bak
2. Açık task listesini kontrol et
3. Son başarılı artefaktı bul
4. Delivery Lead koordinasyonuyla devam et
5. Tamamlanmamış görev tamamlanmadan "bitti" ilan etme

## İlk Target-Project Run Öncesi Yapılacaklar

Target project'e framework uygulanmadan önce şu adımları tamamla:

1. **Plugin build:** `python3 scripts/build_devflow_plugin.py`
2. **Plugin kopyalama:** `dist/devflow-plugin/` içeriğini target project'e kopyala
3. **`.devflow/` yapısını oluştur** target project'te
4. **İlk context pack:** Delivery Lead ile `project-context-synthesis` skill çalıştır
5. **Source register:** `.claude/templates/source-register.yaml` şablonunu doldur
6. **İlk task routing kararı:** Task türünü belirle ve minimum rol setini seç
7. **İnsan onayı:** İlk run başlamadan önce Delivery Lead planını insan ile gözden geçir

Bu adımlar tamamlanmadan gerçek agent run başlatma.
