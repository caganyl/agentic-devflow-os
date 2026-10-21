# Ajan Ortak Kuralları

DevFlow rollerinin hepsi için geçerlidir. Rol dosyası kendi yazma yolunu ve
kesin sınırlarını ayrıca verir; çelişkide daha dar olan kural geçerlidir.

## Kaynak Sırası

`.claude/rules/source-of-truth.md` sırası geçerlidir. NotebookLM ve Obsidian
bulgusu karar değil kanıttır; "doğrulanması gerekiyor" diye işaretlenir.

## Branch ve Worktree

- main'e yazılmaz. Oturum main üzerinde başladıysa branch/worktree açma;
  kullanıcıdan `claude --worktree <görev-adı>` ile yeni oturum iste.
- Alt ajan branch oluşturmaz, değiştirmez, worktree yaratmaz. Bir branch'te
  tek writer ajan çalışır.

## Managed Run Sınırı

`DEVFLOW_RUN_WORKTREE` tanımlıysa tek yazılabilir kök odur ve branch
`DEVFLOW_RUN_BRANCH` olmalıdır. Bash'in varsa yazmadan önce
`git rev-parse --show-toplevel` ve `git rev-parse --abbrev-ref HEAD` ile
doğrula; uyuşmazlıkta yazma, blocker raporla. Başka worktree'ye geçme.
Run state (`.devflow/runs/`) ve raporlar (`.devflow/reports/`) yalnızca
operations CLI ile yazılır; kayıt komutlarını (`record-*`,
`update-task-status`) sonucunda listele, ana oturum çalıştırır.

## Rol Sınırı

- Başka rolün artefaktını (requirement, ADR, contract, kod, test, rapor)
  üretme; eksikliği sonucunda belirt.
- Commit, push, merge, PR yorumu ve thread çözme insan adımıdır.
- İnsan kapısında veya ownership/branch reddinde tasarım dokümanlarına dönme,
  aynı işlemi tekrar deneme; blokajı ve gereken insan adımını tek özetle
  bildir ve dur.

## Ponytail (Yalın Implementasyon)

`claude-devflow` ve `launch`, Ponytail kurallarını yalnızca implementer ve QA
alt ajanlarına verir (backend, frontend, database, ai-data, qa-automation).
Bu rollerde Ponytail'in "en küçük tam değişiklik" merdiveni minimal
implementasyonun tanımıdır. Çelişkide DevFlow kuralı kazanır:

- Kapsamı AC, run'a kaydedilmiş contract, mimari profil ve manifestteki
  `write_paths` belirler. Ponytail kapsamı daraltmaz; AC'den çıkan testler
  kesilmez (`tdd-vertical-slice` her seam için test ister).
- AC belirsizse "en küçük versiyonu" seçme; blocker raporla.
- Yeni bağımlılık yine insan onayı ister.
- `ultra` seviyesi kullanılmaz; kapsam tartışması insan ve product-analyst işidir.
- `shortcut:` yorumları silinmez; sonuçta ve handoff notunda listelenir.

## Kod Haritası (opsiyonel)

Oturum başında "Code map: available" görünüyorsa projede Graphify ile
kurulmuş yerel bir sembol grafiği vardır. Grep ile dosya dosya gezmek
yerine tek sorgu kullan:

- `python3 "$DEVFLOW_CODE_MAP_SCRIPT" affected "<Sembol>"`: bu sembol
  değişirse etkilenen çağıranlar. Paylaşılan bir sınıf, interface veya
  fonksiyonun imzasını değiştirmeden önce implementer çalıştırır; reviewer
  ve security-red-team etki alanını bununla çıkarır.
- `explain "<Sembol>"`, `path "<A>" "<B>"`, `query "<soru>"` (bütçe ≤1500).

Kurallar: Harita kanıttır, gerçeğin kaynağı değildir (sırası
`source-of-truth.md`'de); bulgu dosya:satır ile doğrulanmadan sonuca
yazılmaz. "Harita eski" notu gelirse sonucu doğrula. Haritayı yalnızca
insan veya ana oturum kurar (`claude-devflow map`); alt ajan `build`
çalıştırmaz. Frontend → backend bağı HTTP üzerinden olduğu için haritada
görünmez; o sınır contract'tır.

## Bağlam ve Sonuç

- Belgeleri yalnızca görevin dokunduğu bölüm kadar oku. Eksik bağlamda
  sonucun başına `CONTEXT_REQUEST:` bloğu koy (en fazla 3 yol + bölüm).
- Sonuç en fazla 10 satır: üretilen artefakt yolları, çalıştırılan komutlar
  ve sonuçları, açık blocker'lar, handoff'a girecek not. Handoff dosyasını
  yalnızca yazma yolu `docs/handoffs/` olan rol yazar.
