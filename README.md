# Agentic DevFlow OS

Claude Code merkezli, evidence-driven ve güvenlik odaklı AI yazılım geliştirme işletim sistemi.

## Amaç

Bu repository; farklı projelerde tekrar kullanılacak Claude Code kuralları, agent rolleri,
skill'ler, hook'lar, kalite kapıları, handoff şablonları ve proje yönetim standartlarını içerir.

## Temel İlkeler

- Git repository, projenin teknik gerçek kaynağıdır.
- NotebookLM, requirement ve araştırma için evidence katmanıdır.
- Obsidian, kişisel araştırma ve öğrenme hafızasıdır.
- Hiçbir önemli özellik requirement ve acceptance criteria olmadan geliştirilmez.
- Paralel geliştirme contract-first ve worktree izolasyonu ile yürür.
- Her önemli değişiklik test, security review ve handoff ile kapanır.
- Main merge, production deployment, secret yönetimi ve geri döndürülemez işlemler insan onayı gerektirir.

## Repository Yapısı

- `.claude/` — Claude Code agent, skill, command, rule, hook ve şablonları
- `docs/` — Requirement, ADR, contract, test, security ve handoff kayıtları
- `design/` — PRODUCT.md, DESIGN.md, prototip ve tasarım kanıtları
- `evals/` — AI/RAG değerlendirme veri setleri ve scorecard'lar
- `.github/` — CI/CD ve kalite kapıları
