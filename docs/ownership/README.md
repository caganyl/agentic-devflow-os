# Task Ownership Manifest

## Amaç

Bu dizin, her REQ-ID için hangi implementer agent'ın hangi dosya yollarına
yazabileceğini tanımlayan **canonical görev ownership kaydını** içerir.
Manifest, `docs/ownership/REQ-XXX.json` dosyası olarak tutulur ve
`docs/ownership/schema.json` ile doğrulanır.

Bu paket, henüz hook veya CI enforcement eklemez. Bu aşamada yalnızca
manifest sözleşmesi (schema, template) ve manifesti doğrulayan/yetkilendiren
`scripts/validate_ownership_manifest.py` aracı tanımlanır. Hook ve CI
enforcement bu manifesti kullanacak şekilde sonraki aşamada eklenecektir
(bkz. `docs/architecture/adr/ADR-002-task-ownership-manifest.md`).

## Manifestin Sahibi

Manifest dosyası yalnızca **insan maintainer** tarafından oluşturulur ve
`approved` duruma geçirilir. Implementer agent'lar (Frontend Engineer,
Backend Engineer, Database Engineer, QA Automation, AI/Data Engineer)
manifesti **değiştiremez**; manifest onların yazma yetkisinin girdisidir,
çıktısı değildir.

Bir manifest taslak (`draft`) durumdayken implementer agent o REQ-ID
kapsamında kod yazamaz. İnsan maintainer gerekli referansları doldurup
durumu `approved` yaptıktan sonra implementasyon başlayabilir.

## Ön Koşullar

Bir implementer agent, ilgili REQ-ID için aşağıdakiler olmadan dosya
yazamaz:

- Onaylı (`approved`) bir ownership manifest.
- `references.requirement` ve `references.acceptance_criteria` alanlarının
  repository içinde gerçekten var olan dosyalara işaret etmesi.
- En az bir contract referansı (`references.contracts`) **veya**
  `references.contract_exception` içinde boş olmayan `reason`,
  `approved_by` ve `approved_at` alanları.

Bu koşullardan biri eksikse manifest `approved` olarak kabul edilmemelidir
ve implementer agent yazma yetkisi alamaz.

## Branch ve Writer Kuralı

- Branch standardı: `req-XXX-kisa-aciklama` (örnek: `req-042-login-flow`).
- `XXX`, manifestteki `REQ-XXX` değerindeki rakamlarla **karakter karakter
  aynı** olmalıdır; baştaki sıfırlar korunur. Örnek: `REQ-042` için geçerli
  branch `req-042-login-flow`'tur, `req-42-login-flow` **geçersizdir** ve
  `--authorize-agent` modu bu branch'i reddeder.
- Her branch ve worktree'de yalnızca **bir writer agent** çalışır
  (PROJECT_CONSTITUTION.md ile uyumlu).
- Aynı REQ-ID için birden fazla branch/worktree kullanılabilir (örnek:
  frontend ve backend için ayrı branch'ler). Ancak manifest içinde
  owner'lar arasında **path overlap yasaktır** — iki farklı owner aynı veya
  iç içe geçen bir yola yazamaz. Bu, hangi branch'te çalışıldığından
  bağımsız olarak geçerlidir.

## Manifest Alanları

| Alan | Açıklama |
| --- | --- |
| `schema_version` | Şu an yalnızca `1`. |
| `req_id` | `REQ-XXX` biçiminde, dosya adıyla eşleşmeli. |
| `status` | `draft`, `approved`, `superseded` veya `closed`. |
| `approval` | `approved` durumda `approved_by` ve `approved_at` zorunlu. |
| `references.requirement` | Requirement dosyasına repository-relative yol. |
| `references.acceptance_criteria` | Acceptance criteria dosyasına yol. |
| `references.contracts` | Onaylı contract dosya yolları (en az biri **veya** exception gerekir). |
| `references.contract_exception` | Contract yoksa insan onaylı istisna kaydı. |
| `references.adrs` | İlgili ADR dosya yolları (boş olabilir, verilenler mevcut olmalı). |
| `owners[].agent` | `frontend-engineer`, `backend-engineer`, `database-engineer`, `qa-automation`, `ai-data-engineer`'den biri. |
| `owners[].write_paths` | Bu agent'ın yazabileceği göreli, repository içi yol(lar)ı. |
| `owners[].notes` | Kapsam notu (opsiyonel). |

## Validator Kullanımı

Manifesti doğrulamak için:

```bash
python3 scripts/validate_ownership_manifest.py \
  --manifest docs/ownership/REQ-042.json \
  --root .
```

Bir agent'ın belirli bir dosyaya yazma yetkisi olup olmadığını kontrol etmek
için (gelecekteki hook/CI enforcement bu modu kullanacaktır):

```bash
python3 scripts/validate_ownership_manifest.py \
  --manifest docs/ownership/REQ-042.json \
  --root . \
  --branch req-042-login-flow \
  --authorize-agent frontend-engineer \
  --target apps/web/src/features/example/LoginForm.tsx
```

Bu mod yalnızca manifest `approved` durumdaysa, branch adı `req_id` ile
eşleşiyorsa, agent manifestte tanımlıysa ve target path o agent'ın kendi
`write_paths` alanlarından birinin altındaysa başarılı olur.

## Korunan Governance/Enforcement Dosyaları

Validator, `write_paths` içindeki her yolu normalize edilmiş
(repository-relative, `./` öneki temizlenmiş, `..` içermeyen) biçimiyle
kontrol eder. Bu normalize edilmiş yol aşağıdaki tam-path listesindeki bir
girdiyle eşleşirse manifest reddedilir; `./CLAUDE.md` gibi bir yazım da
`CLAUDE.md` ile aynı şekilde reddedilir:

- `PROJECT_CONSTITUTION.md`
- `CLAUDE.md`
- `AGENTS.md`
- `.claude/settings.json`
- `.claude/hooks/enforce-role-boundaries.sh`
- `.claude/hooks/protect-main.sh`
- `.claude/hooks/protect-sensitive-paths.sh`
- `scripts/validate_ownership_manifest.py`
- `docs/ownership/README.md`
- `docs/ownership/TEMPLATE.json`
- `docs/ownership/schema.json`

Bu tam-path kontrolü, mevcut forbidden directory-prefix kontrollerine
(`.claude/`, `docs/ownership/`, vb.) **ek bir güvenlik katmanıdır**; prefix
kontrollerinin yerini almaz.

## Sonraki Aşama

`ADR-001-role-based-hook-enforcement.md`, Frontend/Backend/Database/QA/
AI-Data Engineer rolleri için path enforcement'ı bu manifest standardı
oluşturulana kadar erteledi. Bu manifest ve validator yayınlandıktan sonra,
hook ve CI enforcement'ın `--authorize-agent` modunu kullanarak bu rolleri
de teknik olarak kilitlemesi sonraki bir ADR/PR kapsamındadır.
