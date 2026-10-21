#!/usr/bin/env bash
# sync_ponytail.sh — Ponytail plugin'ini sabit bir commit'ten .claude/vendor/ponytail/ altına kopyalar.
#
#   scripts/sync_ponytail.sh <commit-veya-tag> [kaynak-klon]
#
# Kaynak klon verilmezse github.com/DietrichGebert/ponytail geçici bir klasöre
# klonlanır. Yalnızca Claude Code plugin'inin çalışması için gerekenler
# kopyalanır (.claude-plugin, hooks, skills, commands, AGENTS.md, LICENSE);
# görseller, benchmark'lar ve diğer ajan adaptörleri alınmaz.
# Submodule kullanılmaz: CI'daki ownership diff kapısı gitlink'leri reddeder.
set -euo pipefail

REF="${1:?kullanım: scripts/sync_ponytail.sh <commit-veya-tag> [kaynak-klon]}"
SRC="${2:-}"
REPO_URL="https://github.com/DietrichGebert/ponytail"
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
DEST="$ROOT/.claude/vendor/ponytail"

tmp=""
cleanup() { if [ -n "$tmp" ]; then rm -rf "$tmp"; fi; }
trap cleanup EXIT

if [ -z "$SRC" ]; then
  tmp="$(mktemp -d)"
  git clone --quiet "$REPO_URL" "$tmp/ponytail"
  SRC="$tmp/ponytail"
fi

git -C "$SRC" checkout --quiet "$REF"
COMMIT="$(git -C "$SRC" rev-parse HEAD)"
VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$SRC/.claude-plugin/plugin.json")"

rm -rf "$DEST"
mkdir -p "$DEST/.claude-plugin"
cp "$SRC/.claude-plugin/plugin.json" "$DEST/.claude-plugin/plugin.json"
for item in hooks skills commands; do
  cp -R "$SRC/$item" "$DEST/$item"
done
cp "$SRC/AGENTS.md" "$SRC/LICENSE" "$DEST/"

cat > "$DEST/VENDORED.md" <<EOF
# Ponytail (vendored)

Kaynak: $REPO_URL
Sürüm: $VERSION
Commit: $COMMIT
Lisans: MIT (LICENSE)

Bu klasör \`scripts/sync_ponytail.sh\` ile üretilir; elle düzenlemeyin.
Güncellemek için: \`scripts/sync_ponytail.sh <yeni-commit>\`, sonra testler.
EOF

printf 'Ponytail %s (%s) -> %s\n' "$VERSION" "$COMMIT" "$DEST"
