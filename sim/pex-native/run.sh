#!/usr/bin/env bash
# Native `klt pex` pilot on the pinned klt (issue #335). From a clean checkout:
#
#   sim/pex-native/run.sh [STAMP]
#
# Extracts the routed cell with the PINNED klt (uvx, never the host tool),
# refuses mismatched inputs, then runs `klt pex --measure-command`. The 15-corner
# fan-out goes to the batch fleet from inside measure_command.py; a failed
# submit fails this script -- it is never retried locally.
set -euo pipefail

KLT_PIN="klayout-tools==0.8.0"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STAMP="${1:-$(date -u +%Y%m%d-%H%M%S)-$(git -C "$ROOT" rev-parse --short HEAD)}"
LAYOUT_ID="$(cat "$ROOT/layout/bandgap-core/reports/LATEST")"
GDS="$ROOT/layout/bandgap-core/reports/$LAYOUT_ID/bandgap_core_routed.gds"
OUT="$ROOT/sim/pex-native/records/$STAMP"
REF="$ROOT/sim/pex-native/reference/bandgap_core_composed.spice"

[[ -e "$OUT" ]] && { echo "refusing: $OUT exists (records are append-only)" >&2; exit 1; }
mkdir -p "$OUT"

python3 -I "$ROOT/sim/pex-native/compose_reference.py" --check \
  || { echo "reference is stale: run sim/pex-native/compose_reference.py" >&2; exit 1; }

# 1. extract with the pin, then check reference/extracted comparability.
uvx --from "$KLT_PIN" klt pex --extract-only --deck sky130 --top bandgap_core_routed \
  --outdir "$OUT/extract" -o "$OUT/extracted.spice" --format json "$GDS" \
  > "$OUT/extract-only.json" || [[ $? -eq 4 ]]
python3 -I "$ROOT/sim/pex-native/check_inputs.py" inputs --reference "$REF" --extracted "$OUT/extracted.spice"

# 2. native pex, command-measured. rc 0/3/4 all carry a report (3 = failed deltas).
export PEX_NATIVE_BACKEND=batch PEX_NATIVE_CAPACITY_WAIT_S=600
set +e
uvx --from "$KLT_PIN" klt pex --deck sky130 --top bandgap_core_routed \
  --measure-command "python3 -I $ROOT/sim/pex-native/measure_command.py" \
  --reference-netlist "$REF" --measure-timeout-s 7200 \
  --outdir "$OUT/pex" -o "$OUT/pex-report.json" --format json "$GDS" \
  > "$OUT/pex-stdout.json" 2> "$OUT/pex-stderr.txt"
rc=$?
set -e
echo "$rc" > "$OUT/pex.rc"

# 3. provenance: hashes + versions.
python3 -I - "$OUT" "$GDS" "$REF" "$KLT_PIN" "$LAYOUT_ID" <<'PY'
import hashlib, json, sys
out, gds, ref, pin, layout = sys.argv[1:]
h = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
json.dump({"klt_pin": pin, "layout_record": layout, "gds_sha256": h(gds), "reference_sha256": h(ref),
           "extracted_sha256": h(out + "/extracted.spice"),
           "delta_limits_sha256": h(out + "/../../delta-limits.json")},
          open(out + "/inputs.json", "w"), indent=2, sort_keys=True)
PY
[[ $rc -eq 0 || $rc -eq 3 ]] || { echo "klt pex exited $rc; see $OUT/pex-stderr.txt" >&2; exit "$rc"; }
