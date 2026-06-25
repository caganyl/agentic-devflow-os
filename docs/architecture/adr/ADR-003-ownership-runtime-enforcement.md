# ADR-003: Ownership Runtime Enforcement

- **Status:** Proposed
- **Date:** 2026-06-25
- **Owner:** Human maintainer
- **Related controls:** PROJECT_CONSTITUTION.md, CLAUDE.md,
  AGENT_CAPABILITY_MATRIX.md, ADR-001-role-based-hook-enforcement.md,
  ADR-002-task-ownership-manifest.md

## Context

ADR-002, `docs/ownership/REQ-XXX.json` adında insan onaylı bir task ownership
manifest sözleşmesi ve bu sözleşmeyi doğrulayan/yetkilendiren
`scripts/validate_ownership_manifest.py` aracını tanımladı. O ADR bilerek
hiçbir hook veya `.claude/settings.json` enforcement eklemedi; yalnızca
sonraki bir enforcement aşamasının üzerine inşa edeceği sözleşmeyi ve
`--authorize-agent` modunu oluşturdu.

ADR-001'in `.claude/hooks/enforce-role-boundaries.sh` hook'u, Frontend
Engineer, Backend Engineer, Database Engineer, QA Automation ve AI/Data
Engineer rollerini ("implementer agent") bilerek path enforcement kapsamı
dışında bıraktı, çünkü o aşamada task-level ownership bilgisi yoktu.

ADR-002 ile sözleşme stabilize olduktan sonra, bu beş implementer rolü için
hâlâ teknik bir Claude runtime enforcement eksikti: bir implementer agent,
ownership manifesti hiç var olmasa, draft kalsa veya kendi `write_paths`
alanı dışında bir hedefe yazmaya çalışsa bile `Edit`/`Write` çağrısı önceden
engellenmiyordu. Enforcement yalnızca agent prompt yönlendirmesine
dayanıyordu.

## Decision

`.claude/hooks/enforce-role-boundaries.sh` içine, yalnızca implementer
agent'lar için geçerli olan bir ownership runtime enforcement bloğu
eklenir. Bu blok şu beş agent'ı kapsar:

- `frontend-engineer`
- `backend-engineer`
- `database-engineer`
- `qa-automation`
- `ai-data-engineer`

Bu agent'lardan biri bir `Edit` veya `Write` çağrısı yaptığında, hook
Claude'un PreToolUse aşamasında aşağıdaki zinciri sırayla doğrular:

1. **Branch biçimi:** Mevcut branch `req-XXX-kisa-aciklama` desenine uymalı
   (`XXX` en az 3 rakam). Uymuyorsa deny.
2. **Manifest varlığı:** Branch'teki rakamlara karşılık gelen
   `docs/ownership/REQ-XXX.json` dosyası repository'de bulunmalı. Bulunmuyorsa
   deny.
3. **Manifest durumu:** Manifest `approved` durumda olmalı. `draft`,
   `superseded` veya `closed` ise deny.
4. **Agent ownership:** Çağrıyı yapan agent, manifestin `owners[].agent`
   listesinde tanımlı olmalı. Tanımlı değilse deny.
5. **Target path:** Hedef dosya yolu, o agent'a ait `owners[].write_paths`
   girdilerinden birinin altında olmalı. Değilse deny.

Bu beş koşulun tamamı doğrulandığında çağrıya izin verilir (boş stdout, exit
code `0`). Herhangi biri başarısız olduğunda hook
`permissionDecision: "deny"` içeren bir JSON çıktısı üretir ve `exit 0` ile
döner — Claude Code PreToolUse sözleşmesine göre deny kararı yine de bu
çıktı üzerinden uygulanır.

Doğrulama ve yetkilendirme mantığının kendisi
`scripts/validate_ownership_manifest.py` içindedir (ADR-002 kapsamında
tanımlandı); hook bu scripti `--manifest`, `--root`, `--branch`,
`--authorize-agent` ve `--target` argümanlarıyla çağırır ve script'in
exit code'una göre allow/deny kararı verir. Hook bu mantığı yeniden
uygulamaz, yalnızca Claude runtime'ına bağlar.

Bu mekanizma **fail-closed** çalışır: branch deseni uyuşmazsa, manifest
yoksa, manifest `approved` değilse, agent owner değilse, hedef path
agent'ın `write_paths` alanı dışındaysa veya validator script'i herhangi
bir nedenle hata döndürürse sonuç her zaman deny'dir. Hiçbir belirsiz veya
hatalı durum varsayılan olarak allow'a düşmez.

## Alternatives Considered

1. **Yalnızca agent prompt yönlendirmesine güvenmeyi sürdürmek**
   - Reddedildi. ADR-002'nin manifest sözleşmesi teknik olarak hiçbir yere
     bağlanmazsa, "insan onaylı ownership" kavramı yalnızca dokümantasyon
     düzeyinde kalır ve implementer agent'lar manifest dışı path'lere
     yazabilir.

2. **Validator mantığını hook içine (bash/inline) yeniden yazmak**
   - Reddedildi. Mantığın iki yerde (Python script ve bash hook) ayrı ayrı
     bakımı, ADR-002'de tanımlanan path-normalizasyon ve forbidden-path
     kontrollerinin zamanla birbirinden sapması riskini taşır. Hook,
     tek bir doğruluk kaynağı olan `scripts/validate_ownership_manifest.py`
     script'ini çağırır.

3. **Bash üzerinden yapılan dosya değişikliklerini de bu aşamada kapsamak**
   - Ertelendi. Bash komutlarının (`sed -i`, `tee`, yönlendirmeli yazma vb.)
     hangi dosyaya yazdığını güvenilir biçimde tespit etmek farklı bir
     teknik problemdir ve ADR-001'in mevcut Bash blok listesiyle
     karıştırılmamalıdır. Bu kapsam, ayrı bir CI diff enforcement
     ADR/PR'ına bırakılır.

4. **Enforcement'ı yalnızca CI'da (merge-time diff kontrolü) yapmak**
   - Reddedildi (bu aşamada tek başına yeterli değil). CI kontrolü, hatalı
     bir yazmanın PR'a kadar fark edilmemesine izin verir. Runtime
     enforcement, implementer agent çağrısını **önceden** engelleyerek
     daha erken bir kontrol katmanı sağlar; CI diff kontrolü bunun yerine
     geçmez, tamamlayıcısıdır ve sonraki bir aşamada eklenecektir.

## Consequences

- Frontend, Backend, Database, QA Automation ve AI/Data Engineer
  agent'larının `Edit`/`Write` çağrıları artık yalnızca approved manifest,
  doğru REQ branch, doğru owner ve izinli `write_paths` koşulu birlikte
  sağlandığında geçer; aksi halde teknik olarak reddedilir.
- ADR-001'in dokümantasyon/review rolleri için path allowlist davranışı ve
  Bash blok listesi değişmeden kalır; bu ADR yalnızca implementer agent'lar
  için `Edit`/`Write` davranışını genişletir.
- `docs/ownership/README.md`'deki "Sonraki Aşama" bölümünde tarif edilen
  boşluk (manifestin hook'a bağlanmamış olması) bu ADR ile kapanır.
- Bu enforcement yalnızca Claude'un `Edit`/`Write` araç çağrılarını kapsar.
  Bash üzerinden yapılan dosya değişiklikleri ve normal terminalden yapılan
  manuel değişiklikler bu mekanizmanın kapsamı dışındadır; bunlar için
  merge-time CI diff enforcement sonraki bir ADR/PR kapsamındadır.
- Hook dosyaları (`.claude/hooks/**`) yalnızca insan maintainer tarafından
  normal terminalden değiştirilir; Claude session'ları bu dosyaları
  düzenleyemez.
- Nihai kabul ve `main` branch'e merge insan onayına bağlıdır; bu ADR tek
  başına bir merge veya deployment yetkisi vermez.

## Evidence

- ADR-001-role-based-hook-enforcement.md
- ADR-002-task-ownership-manifest.md
- `.claude/hooks/enforce-role-boundaries.sh` (implementer ownership bloğu)
- `scripts/validate_ownership_manifest.py` ve
  `tests/test_validate_ownership_manifest.py`
- `tests/test_enforce_role_boundaries.py` (izole fixture repository'ler
  üzerinde hook davranışını uçtan uca doğrulayan testler)
- PROJECT_CONSTITUTION.md (branching policy, human approval gates)
- CLAUDE.md (delivery rules)

## Implementation Impact

- `.claude/hooks/enforce-role-boundaries.sh` içine implementer agent'lar
  için ownership runtime enforcement bloğu eklenir (branch deseni, manifest
  varlığı, `approved` durumu, agent ownership ve target path kontrolü).
- Yeni test dosyası: `tests/test_enforce_role_boundaries.py`. Bu testler
  her biri kendi temporary fixture repository'sinde (`git init`, REQ
  branch, kopyalanmış validator script, requirement/acceptance-
  criteria/contract referans dosyaları, `docs/ownership/REQ-XXX.json`)
  çalışır; gerçek repository veya worktree dosyalarına yazmaz.
- `docs/ownership/README.md` ve `docs/decisions/AGENT_CAPABILITY_MATRIX.md`
  bu runtime enforcement davranışını yansıtacak şekilde güncellenir.
- Bu ADR `.claude/settings.json`, `.claude/agents/**`,
  `scripts/validate_ownership_manifest.py`,
  `tests/test_validate_ownership_manifest.py`, mevcut requirement/contract/
  handoff/release dosyalarını veya ADR-001/ADR-002'yi değiştirmez.

## Approval

- **Required approver:** Human maintainer
- **Approval status:** Pending
- **Approval evidence:** Reviewed pull request and merge to main
