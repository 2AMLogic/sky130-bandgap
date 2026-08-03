#!/usr/bin/env bash
# layout/bin/run-trivial-cell-flow.sh -- the DRC/LVS flow's gating proof
# (issue #14): generate a trivial known-good cell, run it through
# `klt drc`/`klt extract`/`klt lvs` headlessly, and check the reports into
# layout/trivial-cell/reports/<record-id>/.
#
# Usage:
#   layout/bin/setup-venv.sh          # once, or after bumping requirements.txt
#   layout/bin/run-trivial-cell-flow.sh
#
# Requires: layout/.venv (see setup-venv.sh) and a resolvable sky130A PDK
# install (same pin as sim/pdk.json; `volare enable --pdk sky130 <sha>`).
set -euo pipefail

LAYOUT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$LAYOUT_DIR/.." && pwd)"
CELL_DIR="$LAYOUT_DIR/trivial-cell"
KLT="$LAYOUT_DIR/.venv/bin/klt"
CELL=trivial_mos_array
PDK_VARIANT=sky130A

if [[ ! -x "$KLT" ]]; then
  echo "run-trivial-cell-flow.sh: $KLT not found -- run layout/bin/setup-venv.sh first" >&2
  exit 1
fi

if ! "$KLT" pdk find --pdk "$PDK_VARIANT" >/dev/null; then
  echo "run-trivial-cell-flow.sh: no resolvable $PDK_VARIANT PDK -- see sim/pdk.json for the pin" >&2
  exit 1
fi

TS_UTC="$(date -u +%Y%m%d-%H%M%S)"
SHORT_SHA="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
RECORD_ID="${TS_UTC}-${SHORT_SHA}"
OUT_DIR="$CELL_DIR/reports/$RECORD_ID"
mkdir -p "$OUT_DIR"
echo "run-trivial-cell-flow.sh: record $RECORD_ID -> $OUT_DIR"

# --- 1. Generate the trivial known-good cell -------------------------------
"$KLT" gen mos_array --pdk "$PDK_VARIANT" --cell-name "$CELL" \
  -o "$OUT_DIR/$CELL.gds" --format json > "$OUT_DIR/gen.json"

# --- 2. DRC against the sky130 deck -----------------------------------------
"$KLT" drc "$OUT_DIR/$CELL.gds" --deck sky130 --format json > "$OUT_DIR/drc.json" || true

# --- 3. Extract a schematic-equivalent netlist ------------------------------
"$KLT" extract "$OUT_DIR/$CELL.gds" --deck sky130 --top "$CELL" \
  -o "$OUT_DIR/$CELL.extract.spice" --format json > "$OUT_DIR/extract.json"

# --- 4. LVS: known-good reference (must report "match") --------------------
cp "$CELL_DIR/reference.spice" "$OUT_DIR/reference.spice"
cat > "$OUT_DIR/lvs.request.json" <<EOF
{
  "schema": "klt.lvs.request/1",
  "engine": "klayout",
  "layout": { "file": "$CELL.gds", "deck": "sky130", "top": "$CELL" },
  "reference": { "netlist": "reference.spice", "top": "$CELL" }
}
EOF
"$KLT" lvs "$OUT_DIR/lvs.request.json" --format json > "$OUT_DIR/lvs.json" || true

# --- 5. Negative control 1/2: device-parameter-only corruption -------------
cp "$CELL_DIR/reference.broken-device.spice" "$OUT_DIR/reference.broken-device.spice"
cat > "$OUT_DIR/lvs.broken-device.request.json" <<EOF
{
  "schema": "klt.lvs.request/1",
  "engine": "klayout",
  "layout": { "file": "$CELL.gds", "deck": "sky130", "top": "$CELL" },
  "reference": { "netlist": "reference.broken-device.spice", "top": "$CELL" }
}
EOF
"$KLT" lvs "$OUT_DIR/lvs.broken-device.request.json" --format json \
  > "$OUT_DIR/lvs.broken-device.json" || true

# --- 6. Negative control 2/2: topology-only corruption (shorted net) -------
cp "$CELL_DIR/reference.broken-topology.spice" "$OUT_DIR/reference.broken-topology.spice"
cat > "$OUT_DIR/lvs.broken-topology.request.json" <<EOF
{
  "schema": "klt.lvs.request/1",
  "engine": "klayout",
  "layout": { "file": "$CELL.gds", "deck": "sky130", "top": "$CELL" },
  "reference": { "netlist": "reference.broken-topology.spice", "top": "$CELL" }
}
EOF
"$KLT" lvs "$OUT_DIR/lvs.broken-topology.request.json" --format json \
  > "$OUT_DIR/lvs.broken-topology.json" || true

# --- 7. Combined human-readable report --------------------------------------
"$KLT" report "$OUT_DIR/drc.json" "$OUT_DIR/lvs.json" --format github-summary \
  > "$OUT_DIR/report.md"

# --- 8. Record summary (pass/fail verdicts, evidence-record style) ---------
python3 "$LAYOUT_DIR/bin/render-record.py" \
  --out-dir "$OUT_DIR" --record-id "$RECORD_ID" --repo-root "$REPO_ROOT" \
  --klt "$KLT" --pdk-variant "$PDK_VARIANT" \
  > "$OUT_DIR/record.md"

# Keep a "latest" pointer so the README's quick-start doesn't need a
# hardcoded record id. This is a plain text file, not a symlink, so it
# survives a shallow checkout / non-symlink-preserving copy unchanged.
echo "$RECORD_ID" > "$CELL_DIR/reports/LATEST"

echo "run-trivial-cell-flow.sh: done. See $OUT_DIR/record.md"
