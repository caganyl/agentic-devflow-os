#!/usr/bin/env bash
# Agentic DevFlow OS — draft ownership manifest generator.
#
# Creates docs/ownership/REQ-<NNN>.json in DRAFT status for a requirement that
# already exists at docs/product/REQ-<NNN>.md. Implementer agents stay blocked
# until a human flips status to "approved" — the approval gate is deliberate and
# this script never crosses it.
#
# Usage: devflow_new_manifest.sh <REQ-NUMBER> [TARGET_DIR]
#   devflow_new_manifest.sh 002

set -euo pipefail

RAW_REQ="${1:-}"
TARGET="${2:-$PWD}"

say() { printf 'devflow: %s\n' "$1"; }
die() { printf 'devflow: HATA: %s\n' "$1" >&2; exit 1; }

[ -n "$RAW_REQ" ] || die "kullanım: devflow-manifest <REQ-no>   (örn: devflow-manifest 002)"

REQ_NUM="${RAW_REQ#REQ-}"
REQ_NUM="${REQ_NUM#req-}"
case "$REQ_NUM" in
  [0-9][0-9][0-9]*) : ;;
  *) die "REQ numarası en az 3 hane olmalı: '$RAW_REQ'" ;;
esac

cd "$TARGET"
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[ -n "$ROOT" ] || die "burası bir git repository değil: $TARGET"
cd "$ROOT"

REQ_ID="REQ-${REQ_NUM}"
REQ_DOC="docs/product/${REQ_ID}.md"
MANIFEST_FILE="docs/ownership/${REQ_ID}.json"

[ -f "$REQ_DOC" ] || die "$REQ_DOC yok. Önce product-analyst'e requirement + acceptance criteria yazdır."
[ ! -f "$MANIFEST_FILE" ] || die "$MANIFEST_FILE zaten var."

mkdir -p docs/ownership

TITLE="$(sed -n 's/^# *//p' "$REQ_DOC" | head -1)"
[ -n "$TITLE" ] || TITLE="$REQ_ID"
TITLE="${TITLE//\"/}"

cat > "$MANIFEST_FILE" <<JSON
{
  "schema_version": 1,
  "req_id": "${REQ_ID}",
  "title": "${TITLE}",
  "status": "draft",
  "approval": {
    "approved_by": "",
    "approved_at": ""
  },
  "references": {
    "requirement": "${REQ_DOC}",
    "acceptance_criteria": "${REQ_DOC}",
    "contracts": [],
    "adrs": []
  },
  "owners": [
    { "agent": "backend-engineer",  "write_paths": ["backend"] },
    { "agent": "frontend-engineer", "write_paths": ["frontend"] },
    { "agent": "qa-automation",     "write_paths": ["tests"] }
  ]
}
JSON

say "$MANIFEST_FILE oluşturuldu (status: draft)"
cat <<EOF

Sıradaki adımlar (insan onay kapısı — agent bunu yapamaz):
  1. owners[] listesini bu REQ'e göre düzenle; write_paths çakışmamalı.
  2. Frontend + backend paralel gidecekse references.contracts doldur,
     yoksa references.contract_exception ekle (reason/approved_by/approved_at).
  3. status alanını "approved" yap ve approval.approved_by / approved_at doldur.
  4. Doğrula:
     python3 <plugin>/scripts/validate_ownership_manifest.py \\
       --manifest ${MANIFEST_FILE} --root ${ROOT}

Manifest approved olana kadar implementer agent'lar bu REQ için yazamaz.
EOF
