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

## Bağlam ve Sonuç

- Belgeleri yalnızca görevin dokunduğu bölüm kadar oku. Eksik bağlamda
  sonucun başına `CONTEXT_REQUEST:` bloğu koy (en fazla 3 yol + bölüm).
- Sonuç en fazla 10 satır: üretilen artefakt yolları, çalıştırılan komutlar
  ve sonuçları, açık blocker'lar, handoff'a girecek not. Handoff dosyasını
  yalnızca yazma yolu `docs/handoffs/` olan rol yazar.
