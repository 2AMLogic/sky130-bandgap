#!/usr/bin/env bash
# layout/bin/run-bandgap-floorplan-flow.sh -- issue #15's floorplan skeleton
# proof: generate the matched device groups, place them on an explicit 2D
# grid, wrap them in an overall guard ring, and DRC the result via #14's
# klt-driven flow. Mirrors layout/bin/run-trivial-cell-flow.sh's structure
# and evidence-record convention (see layout/matching-plan.md for the
# written matching plan this skeleton implements).
#
# Usage:
#   layout/bin/setup-venv.sh          # once, or after bumping requirements.txt
#   layout/bin/run-bandgap-floorplan-flow.sh
#
# Requires: layout/.venv (see setup-venv.sh) and a resolvable sky130A PDK
# install (same pin as sim/pdk.json; `volare enable --pdk sky130 <sha>`).
set -euo pipefail

LAYOUT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$LAYOUT_DIR/.." && pwd)"
CELL_DIR="$LAYOUT_DIR/bandgap-core"
KLT="$LAYOUT_DIR/.venv/bin/klt"
PDK_VARIANT=sky130A

if [[ ! -x "$KLT" ]]; then
  echo "run-bandgap-floorplan-flow.sh: $KLT not found -- run layout/bin/setup-venv.sh first" >&2
  exit 1
fi

if ! "$KLT" pdk find --pdk "$PDK_VARIANT" >/dev/null; then
  echo "run-bandgap-floorplan-flow.sh: no resolvable $PDK_VARIANT PDK -- see sim/pdk.json for the pin" >&2
  exit 1
fi

TS_UTC="$(date -u +%Y%m%d-%H%M%S)"
SHORT_SHA="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
RECORD_ID="${TS_UTC}-${SHORT_SHA}"
OUT_DIR="$CELL_DIR/reports/$RECORD_ID"
mkdir -p "$OUT_DIR"
echo "run-bandgap-floorplan-flow.sh: record $RECORD_ID -> $OUT_DIR"

set +e
python3 "$LAYOUT_DIR/bin/gen_bandgap_floorplan.py" \
  --out-dir "$OUT_DIR" --record-id "$RECORD_ID" --repo-root "$REPO_ROOT" \
  --klt "$KLT" --pdk-variant "$PDK_VARIANT"
STATUS=$?
set -e

# Keep a "latest" pointer, same convention as layout/trivial-cell/reports/LATEST.
echo "$RECORD_ID" > "$CELL_DIR/reports/LATEST"

echo "run-bandgap-floorplan-flow.sh: done (exit $STATUS). See $OUT_DIR/record.md"
exit "$STATUS"
