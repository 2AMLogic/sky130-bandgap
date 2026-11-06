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
# `--force-reinstall` is load-bearing on the `--force` path: plain
# `pip install -r` treats an already-installed build with the same package
# version as "satisfied", so a pin change could appear to install while
# leaving the old build in place and the flows would run against a `klt` the
# repo no longer pins. (The pin is a PyPI version, `==0.8.0`; it was once a
# git commit.)
"$VENV/bin/pip" install --quiet --force-reinstall --no-deps \
  -r "$LAYOUT_DIR/requirements.txt"
"$VENV/bin/pip" install --quiet -r "$LAYOUT_DIR/requirements.txt"

echo "setup-venv.sh: installed"
"$VENV/bin/klt" --version
"$VENV/bin/klt" pdk find --pdk sky130A || {
  echo "setup-venv.sh: WARNING: no resolvable sky130A PDK install found." >&2
  echo "  See sim/pdk.json for this repo's pinned install command." >&2
}
