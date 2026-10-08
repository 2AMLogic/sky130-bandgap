#!/usr/bin/env bash
# Thin wrapper so the CI workflow (and local runs) have a single stable
# entry point, independent of how the underlying check is implemented.
#
# Usage: scripts/ci/check-signoff-freshness.sh
#
# Re-runs `klt signoff --manifest` against the committed block manifest and
# requires the rendered tier report to be byte-identical to the committed
# signoff/signoff-report.json, the verdict of record. Requires klt on PATH --
# the pinned released version, installed by .github/workflows/ci.yml's
# `signoff` job (the pin lives in
# check_signoff_freshness.py's KLT_VERSION; the job reads it from there).
set -euo pipefail

if ! command -v klt >/dev/null 2>&1; then
    echo "FATAL: klt (klayout-tools) is required on PATH." >&2
    echo "       pip install klayout-tools==\$(python3 scripts/ci/check_signoff_freshness.py --print-version)   # pinned released version" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec python3 "$SCRIPT_DIR/check_signoff_freshness.py"
