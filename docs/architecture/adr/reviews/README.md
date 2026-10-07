# ADR Review Kayıtları

Bu klasöre yalnızca `adr-reviewer` yazar: her tur için bir dosya,
`ADR-NNN-review-<tur>.md`. Dosyalar değiştirilemez ve bir ADR için en fazla
2 tur açılabilir (`.claude/hooks/enforce-role-boundaries.sh`, ADR loop breaker).
İkinci turdan sonra açık BLOCKER kalırsa karar insana aittir.
