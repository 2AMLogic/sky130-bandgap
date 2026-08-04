#!/usr/bin/env bash
# Source or run me: creates/refreshes layout/.venv with the pinned `klt`
# build from layout/requirements.txt.
#
#   layout/bin/setup-venv.sh          # create if missing, otherwise no-op
#   layout/bin/setup-venv.sh --force  # reinstall even if .venv/bin/klt exists
set -euo pipefail

LAYOUT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$LAYOUT_DIR/.venv"

if [[ -x "$VENV/bin/klt" && "${1:-}" != "--force" ]]; then
  echo "setup-venv.sh: $VENV already has klt installed (pass --force to reinstall)"
  "$VENV/bin/klt" --version
  exit 0
fi

echo "setup-venv.sh: creating $VENV"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
# `--force-reinstall` is load-bearing on the `--force` path, and its absence
# was a silent reproducibility hole: requirements.txt pins `klayout-tools` by
# git *commit*, but the pinned commits share a package *version* (0.2.0), so
# plain `pip install -r` sees the requirement as already satisfied and leaves
# the OLD build in place. A pin bump then appears to install while changing
# nothing, and the flow runs against a `klt` the repo no longer pins.
"$VENV/bin/pip" install --quiet --force-reinstall --no-deps \
  -r "$LAYOUT_DIR/requirements.txt"
"$VENV/bin/pip" install --quiet -r "$LAYOUT_DIR/requirements.txt"

echo "setup-venv.sh: installed"
"$VENV/bin/klt" --version
"$VENV/bin/klt" pdk find --pdk sky130A || {
  echo "setup-venv.sh: WARNING: no resolvable sky130A PDK install found." >&2
  echo "  See sim/pdk.json for this repo's pinned install command." >&2
}
