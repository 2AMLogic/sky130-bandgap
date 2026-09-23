#!/usr/bin/env bash
# layout/bin/run-erc-supply-flow.sh -- T1 item 11 (power delivery,
# structural) evidence: run `klt erc` with this repo's supply spec against
# every committed routed bandgap-core GDS, plus the two known-gap n-well tie
# reproductions, and append one record under layout/bandgap-core/erc/.
#
# Usage (cold machine):
#   layout/bin/run-erc-supply-flow.sh            # create .venv-erc if missing
#   layout/bin/run-erc-supply-flow.sh --force    # reinstall the pinned klt
#
# Requires: python3 with venv, network access on first run. It needs NO PDK
# install -- `klt erc --deck sky130` resolves the curated deck from the klt
# package itself, and `--pdk sky130` selects a built-in antenna-limit table,
# so unlike run-bandgap-routed-flow.sh this flow is PDK-install-free.
#
# Gate (this script's exit status), which is item 11's own pass condition and
# deliberately NOT the report's overall `status`:
#   - zero erc.unconnected_net naming VDD or VSS
#   - zero erc.supply_short naming VDD or VSS
#   - both supplies present in erc_coverage.checked
#   - the report's provenance.input.content_hash equals the sha256 of the GDS
#     it was run against
# An antenna verdict or a floating-gate finding is a real defect but is not
# this item's subject and does not fail this gate (klayout-tools#1994).
#
# erc.missing_tie is NOT computed by the supply run and is not gated here --
# see layout/bandgap-core/erc/README.md and the ties_disclosure block in
# layout/bandgap-core/erc-supply-spec.json for why, and for what stands in.
set -euo pipefail

LAYOUT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$LAYOUT_DIR/.." && pwd)"
VENV="$LAYOUT_DIR/.venv-erc"
KLT="$VENV/bin/klt"

# Every `klt erc` invocation below runs from the repo root with REPO-RELATIVE
# input paths, and this is load-bearing, not cosmetic. `klt erc` echoes the
# paths it was handed verbatim into its report's own `file` and `spec` fields,
# and `klt signoff` RE-READS the spec off disk from that `spec` field when it
# grades T1 item 11 (docs/cli/signoff.md: "klt signoff reads the ERC spec
# document off disk" -- without it, "every declared supply resolved to one
# island" and "no supply was ever declared" are indistinguishable, since both
# report zero findings). An absolute path baked into a committed report
# resolves on exactly one machine, which is the provenance-hygiene hazard
# `design-evidence-tiers.md`'s "Provenance hygiene in evidence records"
# section warns about and which already cost this repo item 6's citation
# (signoff/README.md's item-6 row). Repo-relative paths make the committed
# report gradeable anywhere the repo is checked out.
cd "$REPO_ROOT"
CELL_DIR="layout/bandgap-core"

# Routed GDSs to check, newest last. The newest is the one the block's
# freshness rule cares about; the older ones are kept because
# design/block-characterization-report.md and DR-007/DR-008 still cite their
# geometry, so an item-11 read of them stays directly comparable.
GDS_RECORDS=(
  20260811-221633-a0ee5e7
  20260817-020222-13476b7
  20260923-070209-dbd57a9
)

if [[ ! -x "$KLT" || "${1:-}" == "--force" ]]; then
  echo "run-erc-supply-flow.sh: creating $VENV from layout/requirements-erc.txt"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  # --force-reinstall for the same reason setup-venv.sh needs it: the pin is
  # by git ref, and pip will happily consider an already-installed build with
  # the same package version "satisfied".
  "$VENV/bin/pip" install --quiet --force-reinstall \
    -r "$LAYOUT_DIR/requirements-erc.txt"
fi
"$KLT" --version

TS_UTC="$(date -u +%Y%m%d-%H%M%S)"
SHORT_SHA="$(git rev-parse --short HEAD)"
RECORD_ID="${TS_UTC}-${SHORT_SHA}"
OUT_DIR="$CELL_DIR/erc/$RECORD_ID"
mkdir -p "$OUT_DIR"
echo "run-erc-supply-flow.sh: record $RECORD_ID -> $OUT_DIR"

run_erc() {
  # run_erc <spec-path> <gds-record-id> <output-basename>
  local spec="$1" rec="$2" base="$3"
  local gds="$CELL_DIR/reports/$rec/bandgap_core_routed.gds"
  [[ -f "$gds" ]] || { echo "run-erc-supply-flow.sh: missing $gds" >&2; exit 1; }
  echo "  klt erc $rec <- $(basename "$spec")"
  # `klt erc` exits 3 on "antenna or connectivity violations" and 4 on "no
  # antenna checks". Its own docs say to gate on the payload's `status`, not
  # the exit code ("Exit codes" in docs/cli/erc.md), and the known-gap tie
  # specs below are *expected* to report violations. So exits 3/4 are captured
  # and passed through to the record gate; only a real failure to run (1) or a
  # usage error (2) aborts the flow here.
  local rc=0
  "$KLT" erc "$gds" "$spec" --deck sky130 --pdk sky130 --format json \
    > "$OUT_DIR/$base.json" || rc=$?
  case "$rc" in
    0|3|4) ;;
    *)
      echo "run-erc-supply-flow.sh: klt erc failed (exit $rc) for $rec" >&2
      cat "$OUT_DIR/$base.json" >&2 || true
      exit 1
      ;;
  esac
}

for rec in "${GDS_RECORDS[@]}"; do
  run_erc "$CELL_DIR/erc-supply-spec.json" "$rec" "erc.$rec"
done

# Known-gap reproductions run against the newest GDS only -- they are friction
# evidence for 2AMLogic/klayout-tools#2339, not a per-layout verdict.
NEWEST="${GDS_RECORDS[${#GDS_RECORDS[@]}-1]}"
run_erc "$CELL_DIR/erc-nwell-tie-spec.known-gap.vdd.json" "$NEWEST" \
  "erc.known-gap-nwell-vdd.$NEWEST"
run_erc "$CELL_DIR/erc-nwell-tie-spec.known-gap.vss.json" "$NEWEST" \
  "erc.known-gap-nwell-vss.$NEWEST"

python3 "$LAYOUT_DIR/bin/erc_supply_record.py" \
  --out-dir "$OUT_DIR" --record-id "$RECORD_ID" --repo-root "$REPO_ROOT" \
  --klt "$KLT" --gds-records "${GDS_RECORDS[@]}" --newest "$NEWEST"

# Refresh the committed `klt signoff` manifest's item-11 citation, so the
# block's machine-graded T1 tracker points at the record this run just wrote
# rather than at a previous one. Regrading is signoff/regenerate.sh's job --
# run it next (CI's `signoff` job re-grades and fails on any drift).
python3 "$LAYOUT_DIR/bin/erc_signoff_citation.py" \
  --record-id "$RECORD_ID" --newest "$NEWEST"
