#!/usr/bin/env bash
# layout/bin/run-bandgap-routed-flow.sh -- issue #62's routed-layout flow:
# generate the matched device groups at their real schematic counts, place
# them, draw real inter-block routing and top-level pins via
# `klt gen-compose`'s connectivity[]/pins[], then run `klt drc`, `klt extract`
# and `klt lvs` against the xschem-derived reference netlist and fail the
# flow on any non-clean gated result.
#
# Mirrors layout/bin/run-bandgap-floorplan-flow.sh's structure and
# evidence-record convention. That script (issue #15's placement-only DRC
# skeleton) is intentionally left in place and unmodified -- its records are
# append-only evidence, and this flow writes new records alongside them.
#
# Usage:
#   layout/bin/setup-venv.sh          # once, or after bumping requirements.txt
#   layout/bin/run-bandgap-routed-flow.sh
#
# Requires: layout/.venv (see setup-venv.sh) and a resolvable sky130A PDK
# install (same pin as sim/pdk.json; `volare enable --pdk sky130 <sha>`).
#
# Gate (the script's exit status): DRC clean, composed area within the
# < 0.05 mm^2 budget *at the real 108-unit ladder count*, every expected
# device class (`pnp`/`nfet`/`pfet`/`res_generic_po`) present in the
# extracted netlist, and a non-zero promoted `pin_count`. `klt lvs`-clean is
# recorded but NOT gated -- see gen_bandgap_routed.py's ROUTING_LAYER_NOTE
# and the generated record.md for why it is blocked upstream.
set -euo pipefail

LAYOUT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$LAYOUT_DIR/.." && pwd)"
CELL_DIR="$LAYOUT_DIR/bandgap-core"
KLT="$LAYOUT_DIR/.venv/bin/klt"
PDK_VARIANT=sky130A

if [[ ! -x "$KLT" ]]; then
  echo "run-bandgap-routed-flow.sh: $KLT not found -- run layout/bin/setup-venv.sh first" >&2
  exit 1
fi

if ! "$KLT" pdk find --pdk "$PDK_VARIANT" >/dev/null; then
  echo "run-bandgap-routed-flow.sh: no resolvable $PDK_VARIANT PDK -- see sim/pdk.json for the pin" >&2
  exit 1
fi

TS_UTC="$(date -u +%Y%m%d-%H%M%S)"
SHORT_SHA="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
RECORD_ID="${TS_UTC}-${SHORT_SHA}"
OUT_DIR="$CELL_DIR/reports/$RECORD_ID"
mkdir -p "$OUT_DIR"
echo "run-bandgap-routed-flow.sh: record $RECORD_ID -> $OUT_DIR"

set +e
python3 "$LAYOUT_DIR/bin/gen_bandgap_routed.py" \
  --out-dir "$OUT_DIR" --record-id "$RECORD_ID" --repo-root "$REPO_ROOT" \
  --klt "$KLT" --pdk-variant "$PDK_VARIANT" \
  --reference "$CELL_DIR/reference.spice"
STATUS=$?
set -e

# Keep a "latest" pointer, same convention as the floorplan/trivial-cell flows.
echo "$RECORD_ID" > "$CELL_DIR/reports/LATEST"

echo "run-bandgap-routed-flow.sh: done (exit $STATUS). See $OUT_DIR/record.md"
exit "$STATUS"
