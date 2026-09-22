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
# `signoff` job (keep that pin in sync with signoff/regenerate.sh).
set -euo pipefail

if ! command -v klt >/dev/null 2>&1; then
    echo "FATAL: klt (klayout-tools) is required on PATH." >&2
    echo "       pip install klayout-tools==0.6.0   # pinned released version" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec python3 "$SCRIPT_DIR/check_signoff_freshness.py"
