#!/usr/bin/env bash
# Agentic DevFlow OS — zero-step target provisioning.
#
# Prepares the current directory so a `claude-devflow` session comes up fully
# operational: plugin built, git repo on a req-XXX branch, CLAUDE.md routing
# policy in place, rules distributed, docs skeleton and a bootstrap ownership
# manifest present.
#
# Idempotent: every step is skipped when already satisfied. Safe to run before
# every session launch.
#
# Usage: devflow_bootstrap.sh [TARGET_DIR]

set -euo pipefail

TARGET="${1:-$PWD}"
DEVFLOW_HOME="${DEVFLOW_HOME:-$HOME/Developer/agentic-devflow-os}"
PLUGIN_DIR="$DEVFLOW_HOME/dist/devflow-plugin"

BOOTSTRAP_REQ="001"
BOOTSTRAP_BRANCH="req-${BOOTSTRAP_REQ}-bootstrap"

say() { printf 'devflow: %s\n' "$1"; }
die() { printf 'devflow: HATA: %s\n' "$1" >&2; exit 1; }

[ -d "$TARGET" ] || die "hedef dizin yok: $TARGET"
cd "$TARGET"
TARGET_ABS="$(pwd -P)"

# ---------------------------------------------------------------------------
# 0. Never provision the framework repo itself.
# ---------------------------------------------------------------------------
if [ -d "$DEVFLOW_HOME" ]; then
  FRAMEWORK_ABS="$(cd "$DEVFLOW_HOME" && pwd -P)"
  case "$TARGET_ABS" in
    "$FRAMEWORK_ABS" | "$FRAMEWORK_ABS"/*)
      say "framework repo içindesin, target provisioning atlandı"
      exit 0
      ;;
  esac
fi

# ---------------------------------------------------------------------------
# 1. Build the plugin when missing or stale.
# ---------------------------------------------------------------------------
MANIFEST="$PLUGIN_DIR/.claude-plugin/plugin.json"
NEEDS_BUILD=0
if [ ! -f "$MANIFEST" ]; then
  NEEDS_BUILD=1
elif [ -n "$(find "$DEVFLOW_HOME/.claude" "$DEVFLOW_HOME/scripts" "$DEVFLOW_HOME/hooks" \
              -type f -newer "$MANIFEST" -print -quit 2>/dev/null)" ]; then
  NEEDS_BUILD=1
fi

if [ "$NEEDS_BUILD" -eq 1 ]; then
  say "plugin build ediliyor"
  python3 "$DEVFLOW_HOME/scripts/build_devflow_plugin.py" >/dev/null \
    || die "plugin build başarısız"
fi

# ---------------------------------------------------------------------------
# 2. Git repository and a non-protected req-XXX branch.
# ---------------------------------------------------------------------------
if ! git rev-parse --git-dir >/dev/null 2>&1; then
  say "git repository başlatılıyor"
  git init -q
fi

if ! git rev-parse --verify -q HEAD >/dev/null 2>&1; then
  git commit -q --allow-empty -m "chore: initialize project"
fi

BRANCH="$(git branch --show-current 2>/dev/null || true)"
case "$BRANCH" in
  req-[0-9][0-9][0-9]*-*)
    : # already on a valid implementation branch
    ;;
  *)
    if git rev-parse --verify -q "$BOOTSTRAP_BRANCH" >/dev/null 2>&1; then
      git checkout -q "$BOOTSTRAP_BRANCH"
    else
      git checkout -q -b "$BOOTSTRAP_BRANCH"
    fi
    say "branch: $BOOTSTRAP_BRANCH (main korumalı, implementer'lar req-XXX ister)"
    ;;
esac

# ---------------------------------------------------------------------------
# 3. Directory skeleton.
# ---------------------------------------------------------------------------
mkdir -p \
  .claude/rules \
  docs/product docs/architecture/adr docs/contracts docs/ownership \
  docs/handoffs docs/quality/security-reports docs/release \
  design/reviews evals \
  backend frontend migrations tests ai

# ---------------------------------------------------------------------------
# 4. Routing policy + rules. Never overwrite an existing CLAUDE.md.
# ---------------------------------------------------------------------------
TEMPLATE="$PLUGIN_DIR/templates/TARGET_CLAUDE.md"
if [ ! -f CLAUDE.md ]; then
  if [ -f "$TEMPLATE" ]; then
    cp "$TEMPLATE" CLAUDE.md
    say "CLAUDE.md yerleştirildi (routing policy)"
  else
    say "UYARI: $TEMPLATE bulunamadı, CLAUDE.md yazılamadı"
  fi
fi

if [ -d "$PLUGIN_DIR/rules" ]; then
  for rule in "$PLUGIN_DIR"/rules/*.md; do
    [ -f "$rule" ] || continue
    dest=".claude/rules/$(basename "$rule")"
    [ -f "$dest" ] || cp "$rule" "$dest"
  done
fi

# ---------------------------------------------------------------------------
# 5. Bootstrap requirement + ownership manifest.
#
# Implementer agents are gated on an approved manifest whose referenced
# requirement file actually exists. Without this pair a fresh project cannot
# accept any implementer write at all.
# ---------------------------------------------------------------------------
REQ_DOC="docs/product/REQ-${BOOTSTRAP_REQ}.md"
if [ ! -f "$REQ_DOC" ]; then
  cat > "$REQ_DOC" <<'REQMD'
# REQ-001: Proje İskeleti ve Teslimat Altyapısı

## Amaç

Projenin çalışabilir bir iskelete ve DevFlow teslimat akışına sahip olması.
Bu requirement, ürün davranışı tanımlamaz; yalnızca sonraki REQ'lerin
üzerinde çalışacağı temeli kurar.

## Kapsam

- Kaynak dizin yapısı (`backend/`, `frontend/`, `migrations/`, `tests/`, `ai/`)
- Bağımlılık ve ortam kurulumu
- Test altyapısı ve çalıştırma komutu
- Lint ve typecheck yapılandırması

## Kapsam Dışı

- Ürün özellikleri ve kullanıcıya dönük davranış
- Production deployment ve altyapı

## Acceptance Criteria

- AC-1: Depo `req-XXX-*` biçiminde bir implementation branch üzerindedir.
- AC-2: `backend/`, `frontend/`, `migrations/`, `tests/` ve `ai/` dizinleri mevcuttur.
- AC-3: Bağımlılıklar kurulabilir ve kurulum komutu dokümantedir.
- AC-4: Test suite çalıştırılabilir ve sonuç raporlanabilir.
- AC-5: Lint ve typecheck komutları tanımlıdır.

## Riskler

- İskelet kararları (framework, dizin yapısı) sonradan değişirse migration maliyeti doğar.

## Notlar

Gerçek ürün davranışı REQ-002 ve sonrasında tanımlanır. Bu manifest yalnızca
iskelet çalışması için geçerlidir; feature REQ'leri kendi manifestini gerektirir.
REQMD
  say "$REQ_DOC oluşturuldu"
fi

MANIFEST_FILE="docs/ownership/REQ-${BOOTSTRAP_REQ}.json"
if [ ! -f "$MANIFEST_FILE" ]; then
  APPROVER="$(git config user.name 2>/dev/null || true)"
  [ -n "$APPROVER" ] || APPROVER="local-maintainer"
  STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  cat > "$MANIFEST_FILE" <<JSON
{
  "schema_version": 1,
  "req_id": "REQ-${BOOTSTRAP_REQ}",
  "title": "Proje iskeleti ve teslimat altyapısı",
  "status": "approved",
  "approval": {
    "approved_by": "${APPROVER}",
    "approved_at": "${STAMP}"
  },
  "references": {
    "requirement": "${REQ_DOC}",
    "acceptance_criteria": "${REQ_DOC}",
    "contracts": [],
    "contract_exception": {
      "reason": "Iskelet asamasi; kullaniciya donuk API yuzeyi henuz yok, contract gerekmiyor.",
      "approved_by": "${APPROVER}",
      "approved_at": "${STAMP}"
    },
    "adrs": []
  },
  "owners": [
    { "agent": "backend-engineer",  "write_paths": ["backend"] },
    { "agent": "frontend-engineer", "write_paths": ["frontend"] },
    { "agent": "database-engineer", "write_paths": ["migrations"] },
    { "agent": "qa-automation",     "write_paths": ["tests"] },
    { "agent": "ai-data-engineer",  "write_paths": ["ai"] }
  ]
}
JSON

  VALIDATOR="$PLUGIN_DIR/scripts/validate_ownership_manifest.py"
  [ -f "$VALIDATOR" ] || VALIDATOR="$DEVFLOW_HOME/scripts/validate_ownership_manifest.py"
  if [ -f "$VALIDATOR" ]; then
    if python3 "$VALIDATOR" --manifest "$MANIFEST_FILE" --root "$TARGET_ABS" >/dev/null 2>&1; then
      say "$MANIFEST_FILE oluşturuldu ve doğrulandı (approved)"
    else
      say "UYARI: $MANIFEST_FILE doğrulamayı geçemedi:"
      python3 "$VALIDATOR" --manifest "$MANIFEST_FILE" --root "$TARGET_ABS" >&2 || true
    fi
  fi
fi

# ---------------------------------------------------------------------------
# 6. .devflow workspace + gitignore.
# ---------------------------------------------------------------------------
if [ ! -d .devflow ]; then
  OPS="$PLUGIN_DIR/scripts/devflow_operations.py"
  [ -f "$OPS" ] || OPS="$DEVFLOW_HOME/scripts/devflow_operations.py"
  if [ -f "$OPS" ]; then
    python3 "$OPS" init-target --target "$TARGET_ABS" >/dev/null 2>&1 \
      && say ".devflow/ workspace başlatıldı" \
      || say "not: .devflow/ init-target atlandı (zorunlu değil)"
  fi
fi

touch .gitignore
for entry in ".devflow/cache/" ".devflow/logs/"; do
  grep -qxF "$entry" .gitignore || printf '%s\n' "$entry" >> .gitignore
done

# ---------------------------------------------------------------------------
# 7. Report.
# ---------------------------------------------------------------------------
say "hazır — $(basename "$TARGET_ABS") | branch: $(git branch --show-current)"
