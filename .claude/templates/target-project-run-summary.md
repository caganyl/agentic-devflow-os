# Target Project Run Summary

## Meta

- **Run ID:** RUN-[NNN]
- **Target Project:** [target repo path]
- **Branch:** devflow/run-run-[nnn]
- **Tarih:** YYYY-MM-DD HH:MM UTC
- **Workflow:** [workflow adı]
- **Durum:** completed / partial / failed / interrupted

---

## Tamamlanan İşler

| Task | Owner | Artefakt | Sonuç |
|------|-------|---------|-------|
| [görev 1] | [rol] | [dosya yolu] | tamamlandı |
| [görev 2] | [rol] | [dosya yolu] | tamamlandı |

## Açık Görevler (Tamamlanmayan)

| Task | Engel | Sonraki Adım |
|------|-------|-------------|
| [görev] | [neden tamamlanmadı] | [kim ne yapmalı] |

## Üretilen Artefaktlar

- [ ] `[dosya yolu]` — [açıklama]
- [ ] `[dosya yolu]` — [açıklama]

## Approval Gate Durumu

- [ ] Contract onaylı (`contract_approved`)
- [ ] Test suite geçiyor (`tests_passing`)
- [ ] Security review tamamlandı (`security_review_complete`)
- [ ] QA sign-off verildi (`qa_sign_off`)
- [ ] İnsan onayı: **[bekliyor / alındı / gerekmiyor]** (`human_approval`)

## Source Register Durumu

- [ ] Git canonical kaynaklar kayıtlı
- [ ] NotebookLM: yalnızca label ve freshness (ham içerik yok)
- [ ] Obsidian: yalnızca seçilmiş note reference (tüm vault değil)

## Managed Operations Log

```
init-target: YYYY-MM-DD
create-run RUN-NNN: YYYY-MM-DD
prepare-delivery (dry-run): YYYY-MM-DD
prepare-delivery --confirm-delivery: [bekliyor / YYYY-MM-DD]
```

## Bilinen Sorunlar

- [sorun 1]: [etki ve durum]

## Recovery Talimatı (Session Kesilirse)

Bu özet ve aşağıdaki bilgiler ile devam edilebilir:

1. Aktif run: `RUN-[NNN]` → `.devflow/runs/RUN-[NNN].json`
2. Context pack: `.devflow/context/[pack-adı].md`
3. Açık görevler: yukarıdaki tablo
4. `autonomous-delivery-run` skill'ini kullanarak devam et

## Sonraki Run İçin Notlar

- [not 1]
