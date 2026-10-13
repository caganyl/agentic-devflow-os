# Ownership & Merge

Bir REQ'in fikirden main merge'e kadar yolu, ownership manifestinin nasıl
onaylandığı ve insan merge kontrolü. Teknik kararlar: ADR-002 (manifest),
ADR-003 (runtime hook), ADR-004 (CI diff gate), ADR-008 (managed run binding).

## 1. REQ Yaşam Döngüsü

```
Fikir → (belirsizse) ana oturum + insan: requirement-grilling
  → product-analyst: docs/product/requirements/REQ-NNN.md (+ AC)
  → (ADR eşiği varsa) solution-architect + adr-reviewer (en fazla 2 tur)
  → contract-broker: docs/contracts/… (veya manifestte contract_exception)
  → İNSAN: docs/ownership/REQ-NNN.json status=approved
  → implementer'lar: req-NNN-* branch'i veya launch --req-id REQ-NNN
  → QA → Security → Docs Writer (handoff) → Integration/Release (scorecard)
  → İNSAN: commit/push, PR, merge checklist (§6), main merge
```

Bir adım atlanmaz. REQ-ID biçimi `REQ-` + en az 3 rakam
(`schema.json`: `^REQ-[0-9]{3,}$`); numara ataması insan kararıdır.

## 2. Manifest

`docs/ownership/REQ-NNN.json`, `schema.json`'a uyar; şablon `TEMPLATE.json`.
Manifesti yalnızca **insan maintainer** oluşturur ve `approved` yapar;
implementer ajanlar değiştiremez. `devflow-manifest <REQ-no>` `draft`
manifest üretir.

| Alan | Açıklama |
| --- | --- |
| `req_id`, `status` | `REQ-NNN` (dosya adıyla aynı); `draft`, `approved`, `superseded`, `closed` |
| `approval` | `approved` iken `approved_by` ve `approved_at` zorunlu |
| `references.requirement` / `acceptance_criteria` | Var olan dosyalara repository-relative yol |
| `references.contracts` / `contract_exception` | En az bir contract **veya** `reason`, `approved_by`, `approved_at` dolu istisna |
| `references.adrs` | İlgili ADR yolları (boş olabilir; verilenler mevcut olmalı) |
| `owners[].agent` | `frontend-engineer`, `backend-engineer`, `database-engineer`, `qa-automation`, `ai-data-engineer` |
| `owners[].write_paths` | Ajanın yazabileceği göreli yollar; owner'lar arasında overlap yasak |

Korunan yollar `write_paths`'e konamaz (normalize edilmiş tam eşleşme ve
`.claude/`, `docs/ownership/` gibi prefix kontrolleri): `PROJECT_CONSTITUTION.md`,
`CLAUDE.md`, `AGENTS.md`, `.claude/settings.json`, `.claude/hooks/*.sh`,
`scripts/validate_ownership_manifest.py`, `docs/ownership/README.md`,
`TEMPLATE.json`, `schema.json`.

Doğrulama:

```bash
python3 scripts/validate_ownership_manifest.py --manifest docs/ownership/REQ-042.json --root .
python3 scripts/validate_ownership_manifest.py --manifest docs/ownership/REQ-042.json --root . \
  --branch req-042-login-flow --authorize-agent frontend-engineer --target apps/web/src/LoginForm.tsx
```

## 3. Runtime Enforcement

`.claude/hooks/enforce-role-boundaries.sh`, beş implementer ajanın her
Write/Edit çağrısında `--authorize-agent` modunu çağırır. Hepsi sağlanmalı:

1. Branch `req-NNN-kisa-aciklama` (rakamlar manifestle karakter karakter
   aynı: `req-42-…` geçersiz) **veya** `launch --req-id REQ-NNN` ile açılmış
   aktif managed run branch'i (`devflow/run-*` = `DEVFLOW_RUN_BRANCH`; REQ
   bağı imzalı run state'ten okunur),
2. `docs/ownership/REQ-NNN.json` var ve `approved`,
3. Ajan manifestte owner,
4. Hedef yol o ajanın `write_paths` alanı altında.

Hook yalnızca Claude araç çağrılarını görür; Bash veya terminalden yapılan
değişiklikleri CI yakalar. Ret bir tasarım sorunu değildir; gereken insan
adımı raporlanır.

## 4. CI Diff Enforcement

`.github/workflows/ownership-governance.yml` her PR'da iki iş çalıştırır:
**PR Quality** (hook sözdizimi, Python derleme, tüm unittest'ler,
`git diff --check`) ve **Ownership Diff Gate** (`pull_request_target`, güvenilir
base kodundan `scripts/validate_ownership_diff.py`). CI ajan kimliğini değil,
değişen path'in yetkisini doğrular. Branch sınıfına göre:

| Branch | Kural |
| --- | --- |
| `req-NNN-*` | Her değişen dosya **base commit**'teki onaylı manifestin tam olarak bir owner `write_paths`'i altında; `docs/ownership/` değişemez; rename'de eski ve yeni yol denetlenir |
| `ownership-REQ-NNN-*` (registry) | Yalnızca kendi exact `docs/ownership/REQ-NNN.json` dosyası; silme yok |
| Diğer (governance) | Yalnızca `.agents/plugins/`, `.agents/skills/`, `.claude/`, `.codex/agents/`, `.github/`, `docs/`, `scripts/`, `tests/`, `design/`, `evals/` ve izinli kök dosyalar (`README.md`, `CLAUDE.md`, `AGENTS.md`, `PROJECT_CONSTITUTION.md`, `.gitignore`, `hooks/hooks.json` …); `docs/ownership/REQ-<rakam>.json` asla |

Symlink (`120000`) ve gitlink (`160000`) değişiklikleri her sınıfta reddedilir.

```bash
python3 scripts/validate_ownership_diff.py --root . --base-sha <base> --head-sha <head> --branch req-042-login-flow
```

## 5. Feature Bootstrap PR

`req-NNN-*` branch'inde manifest base'de yoksa ve head'de eklenmişse PR
**bootstrap** sayılır: requirement, AC, manifest ve kaynak aynı diff'te
taşınabilir; ayrı manifest PR'ı gerekmez.

- Manifest head'de `approved`, `approved_by`/`approved_at` dolu ve `req_id`
  branch numarasıyla aynı olmalı.
- `references.requirement` ve `acceptance_criteria` yalnızca
  `docs/product/requirements/` ve `docs/product/acceptance-criteria/`
  altında; bu iki dosya diff'te bulunmalı ve coverage denetiminden muaftır.
  Diğer her dosya (contract, ADR, kod, test) bir owner `write_paths`'i altında
  olmalıdır.
- Bootstrap manifestleri şunlara yetki veremez: `.claude/`, `.github/`,
  `scripts/`, `docs/ownership/`, `docs/architecture/`, kök kontrol dosyaları,
  `.env`/secret yolları ve `src`, `tests`, `docs`, `apps`, `lib`, `evals`,
  `docs/contracts` gibi geniş kökler (altlarındaki dar `req-NNN-…` yolları
  kabul edilir). Diff'te başka bir `docs/ownership/` dosyası olamaz.
- Merge sonrası kapsamı genişletmek bir `ownership-REQ-NNN-*` registry PR'ıdır.

## 6. Registry Branch ve İnsan Merge Checklist'i

Registry branch (`ownership-REQ-NNN-kisa-aciklama`): requirement, AC ve
contract **önce** base'de olmalıdır; insan manifesti `TEMPLATE.json`'dan
oluşturur veya günceller (hatalı manifest, scope değişikliği, `superseded`/
`closed` geçişi de böyle yapılır — asla implementation branch'inden).
CI şema, referansların base'de varlığı ve exact path'i doğrular; onayın
gerçekten bir insandan geldiğini veya `write_paths`'in doğru genişlikte
olduğunu **doğrulayamaz** — bu insan review'udur.

Main'e her merge öncesi insan maintainer:

- [ ] Branch sınıfı doğru (`req-NNN-*`, `ownership-REQ-NNN-*` veya governance)
      ve diff bu sınıfın kuralına uyuyor; beklenmeyen dosya yok.
- [ ] Diff'te secret, token, private key veya kişisel veri yok.
- [ ] Manifest base'de `approved`; her path tek owner'ın `write_paths`'i altında;
      contract veya onaylı `contract_exception` var.
- [ ] AC dosyası teslim edilen davranışla eşleşiyor; handoff güncel.
- [ ] Test, lint, typecheck sonuçları raporlanmış; UI değiştiyse loading/empty/
      error/permission/mobile, AI değiştiyse eval kontrolü yapılmış.
- [ ] Migration varsa rollback notu var; production, secret, cloud, ödeme veya
      kullanıcı verisi etkisi ayrı insan onayıyla.
- [ ] Security bulguları kapatılmış veya kabul kararı kayıtlı.
- [ ] **PR Quality** ve **Ownership Diff Gate** son commit için yeşil.
- [ ] Onaylayan ve tarih PR'da veya handoff'ta kayıtlı.

Biri sağlanmıyorsa PR merge edilmez, ilgili role geri gönderilir.

**Plan sınırı:** Mevcut private GitHub planında branch protection/rulesets
kullanılamıyor; required check teknik olarak zorlanmaz (ADR-004). Bu yüzden
yukarıdaki checklist, özellikle iki CI işinin yeşil olduğunu görmek, zorunlu
telafi edici kontroldür. Uygun plana geçildiğinde Ownership Diff Gate
required check yapılmalıdır.

## Açık Kararlar

- REQ numarası atamasının sahibi ve mekanizması tanımlı değildir.
- Merge sonrası fark edilen manifest hatası için zorunlu ek inceleme tanımlı
  değildir; karar insan maintainer'dadır.
