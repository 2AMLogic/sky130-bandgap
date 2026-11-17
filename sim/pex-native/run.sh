#!/usr/bin/env bash
# Native `klt pex` pilot on the pinned klt (issue #335). From a clean checkout:
#
#   sim/pex-native/run.sh [STAMP] [--critical-net NET]... [--distributed-rc]
#
# Extracts the routed cell with the PINNED klt (uvx, never the host tool),
# refuses mismatched inputs, then runs `klt pex --measure-command`. The 15-corner
# fan-out goes to the batch fleet from inside measure_command.py; a failed
# submit fails this script -- it is never retried locally.
#
# Optional extraction-model flags (issue #541): --critical-net takes ONE net per
# flag (repeat the flag; klt never splits on commas, so `VB,VBQ` is one literal
# net name that matches nothing -- refused here) and --distributed-rc swaps the
# star parasitic model for a distributed ladder on the named nets. They are
# threaded into BOTH klt pex steps so the graded and comparable netlists come
# from the same extraction, and are recorded in the record's inputs.json. With
# no flags the klt pex argv is exactly what it always was.
set -euo pipefail

KLT_PIN="klayout-tools==0.8.0"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ $# -gt 0 && "$1" != --* ]]; then STAMP="$1"; shift; else
  STAMP="$(date -u +%Y%m%d-%H%M%S)-$(git -C "$ROOT" rev-parse --short HEAD)"; fi
CRITICAL_NETS=()
DISTRIBUTED_RC=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --critical-net)
      case "${2:-}" in
        *,*) echo "refusing: '$2' -- one net per --critical-net flag (klt does not split on \
commas; pass --critical-net VB --critical-net VBQ)" >&2; exit 1 ;;
        "")  echo "refusing: --critical-net needs a value" >&2; exit 1 ;;
      esac
      CRITICAL_NETS+=("$2"); shift 2 ;;
    --distributed-rc) DISTRIBUTED_RC=1; shift ;;
    *) echo "refusing: unknown argument '$1' (usage: run.sh [STAMP] [--critical-net NET]... [--distributed-rc])" >&2; exit 1 ;;
  esac
done
[[ $DISTRIBUTED_RC -eq 1 && ${#CRITICAL_NETS[@]} -eq 0 ]] && \
  { echo "refusing: --distributed-rc requires at least one --critical-net NET" >&2; exit 1; }
EXTRACT_FLAGS=()
for net in "${CRITICAL_NETS[@]}"; do EXTRACT_FLAGS+=(--critical-net "$net"); done
[[ $DISTRIBUTED_RC -eq 1 ]] && EXTRACT_FLAGS+=(--distributed-rc)
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
  --outdir "$OUT/extract" -o "$OUT/extracted.spice" --format json "${EXTRACT_FLAGS[@]}" "$GDS" \
  > "$OUT/extract-only.json" || [[ $? -eq 4 ]]
python3 -I "$ROOT/sim/pex-native/check_inputs.py" inputs --reference "$REF" --extracted "$OUT/extracted.spice"

# 2. native pex, command-measured. rc 0/3/4 all carry a report (3 = failed deltas).
export PEX_NATIVE_BACKEND=batch PEX_NATIVE_CAPACITY_WAIT_S=600
set +e
uvx --from "$KLT_PIN" klt pex --deck sky130 --top bandgap_core_routed \
  --measure-command "python3 -I $ROOT/sim/pex-native/measure_command.py" \
  --reference-netlist "$REF" --measure-timeout-s 7200 \
  --outdir "$OUT/pex" -o "$OUT/pex-netlist.spice" --format json "${EXTRACT_FLAGS[@]}" "$GDS" \
  > "$OUT/pex-stdout.json" 2> "$OUT/pex-stderr.txt"
rc=$?
set -e
echo "$rc" > "$OUT/pex.rc"

# 3. provenance: hashes + versions. `extraction_flags` is written only when the
# run is not a default one, so a default record's inputs.json is byte-identical
# to the pilot's schema while a flagged record is distinguishable without
# parsing the klt report.
python3 -I - "$OUT" "$GDS" "$REF" "$KLT_PIN" "$LAYOUT_ID" "$DISTRIBUTED_RC" "${CRITICAL_NETS[@]}" <<'PY'
import hashlib, json, sys
out, gds, ref, pin, layout, dist, *nets = sys.argv[1:]
h = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
record = {"klt_pin": pin, "layout_record": layout, "gds_sha256": h(gds), "reference_sha256": h(ref),
          "extracted_sha256": h(out + "/extracted.spice"),
          "delta_limits_sha256": h(out + "/../../delta-limits.json")}
if nets or dist == "1":
    record["extraction_flags"] = {"critical_nets": nets, "distributed_rc": dist == "1"}
json.dump(record, open(out + "/inputs.json", "w"), indent=2, sort_keys=True)
PY
[[ $rc -eq 0 || $rc -eq 3 ]] || { echo "klt pex exited $rc; see $OUT/pex-stderr.txt" >&2; exit "$rc"; }
