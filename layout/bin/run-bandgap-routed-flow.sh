#!/usr/bin/env bash
# layout/bin/run-bandgap-routed-flow.sh -- issue #62's routed-layout flow:
# generate the matched device groups at their real schematic counts, place
# them, draw real inter-block routing and top-level pins via
# `klt gen-compose`'s connectivity[]/pins[], then run `klt drc`, `klt extract`
# and `klt lvs` against the xschem-derived reference netlist and fail the
# flow on any non-clean gated result.
#
# Mirrors the evidence-record convention of run-bandgap-floorplan-flow.sh,
# the #15 placement-only DRC flow this one supersedes, removed in #217 (#215)
# -- its one historical record is left in place as append-only evidence, and
# this flow writes new records alongside it.
#
# Usage:
#   layout/bin/setup-venv.sh          # once, or after bumping requirements.txt
#   layout/bin/run-bandgap-routed-flow.sh
#
# Raw outputs (GDS, .gen.json, extract/LVS payloads, renders) are staged in the
# git-ignored layout/bandgap-core/staging/<record-id>/ and stored in the fleet
# artifact store (manifests/artifacts/layout-bandgap-core-<record-id>.manifest.json,
# issue #426); only record.md and the verdict JSONs are committed under
# reports/<record-id>/. Needs $KLT_ARTIFACT_BROKER and a `klt` with
# `artifact put` on PATH; without them the flow exits before writing anything
# (no local fallback). `reports/LATEST` is no longer updated.
#
# Requires: layout/.venv (see setup-venv.sh) and a resolvable sky130A PDK
# install (same pin as sim/pdk.json; `ciel enable --pdk-family sky130 <sha>`).
#
# Gate (the script's exit status): DRC clean, composed area within the
# < 0.05 mm^2 budget *at the real 108-unit ladder count*, every expected
# device class (`pnp`/`nfet`/`pfet`/`res_generic_po`) present in the
# extracted netlist, and a non-zero promoted `pin_count`. `klt lvs`-clean is
# recorded but NOT gated -- see gen_bandgap_routed.py's RES_TRIM_TOPOLOGY_NOTE/
# ROUTING_PLANE_NOTE and the generated record.md for why it is blocked
# upstream.
set -euo pipefail

LAYOUT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$LAYOUT_DIR/.." && pwd)"
CELL_DIR="$LAYOUT_DIR/bandgap-core"
KLT="$LAYOUT_DIR/.venv/bin/klt"
PDK_VARIANT=sky130A

# Fail closed before creating any directory (issue #426).
python3 "$LAYOUT_DIR/bin/publish_layout_evidence.py" check || exit 1

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
OUT_DIR="$CELL_DIR/staging/$RECORD_ID"
SUMMARY_DIR="$CELL_DIR/reports/$RECORD_ID"
mkdir -p "$OUT_DIR"
echo "run-bandgap-routed-flow.sh: record $RECORD_ID -> $OUT_DIR"

set +e
python3 "$LAYOUT_DIR/bin/gen_bandgap_routed.py" \
  --out-dir "$OUT_DIR" --record-id "$RECORD_ID" --repo-root "$REPO_ROOT" \
  --klt "$KLT" --pdk-variant "$PDK_VARIANT" \
  --reference "$CELL_DIR/reference.spice"
STATUS=$?
set -e

# Store the raw outputs, then commit only the summary. A publish failure
# leaves the staged files in place and nothing under reports/.
python3 "$LAYOUT_DIR/bin/publish_layout_evidence.py" publish "$OUT_DIR" \
  --bench layout-bandgap-core --run-id "$RECORD_ID" || exit 1

mkdir -p "$SUMMARY_DIR"
for f in record.md drc.json extract.json lvs.json lvs.combined.json met2-drc.json; do
  [[ -f "$OUT_DIR/$f" ]] && cp "$OUT_DIR/$f" "$SUMMARY_DIR/$f"
done

echo "run-bandgap-routed-flow.sh: done (exit $STATUS). See $SUMMARY_DIR/record.md"
exit "$STATUS"
