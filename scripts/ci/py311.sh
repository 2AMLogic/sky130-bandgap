#!/usr/bin/env bash
# Resolve a Python 3.11 interpreter for local runs, so the local test command
# matches the pin CI enforces: .github/workflows/ci.yml sets
# python-version "3.11" in every job, while dispatch hosts default to a newer
# python3, where a newer-than-3.11 stdlib API passes locally and fails in CI
# (issue #587; PR #586's pathlib.Path.walk was the first hit).
#
# Lookup order (this never installs anything):
#   1. python3.11 on PATH (what setup-python provides on CI runners)
#   2. newest uv-managed cpython-3.11 under ~/.local/share/uv/python
#   3. fallback: python3, with a one-line stderr warning that CI pins 3.11
#
# Usage:
#   scripts/ci/py311.sh --print   # print the interpreter path (npm scripts)
#   scripts/ci/py311.sh -m unittest discover -s layout/tests   # exec wrapper
#
# The resolved interpreter and its version are announced on stderr, so the
# --print command substitution in npm scripts still surfaces them.
set -euo pipefail

MODE="exec"
if [[ "${1:-}" == "--print" ]]; then
    MODE="print"
    shift
    if [[ $# -gt 0 ]]; then
        echo "py311.sh: --print takes no arguments" >&2
        exit 2
    fi
fi

newest_uv_311() {
    local cand newest=""
    while IFS= read -r cand; do
        [[ -x "$cand" ]] && newest="$cand"
    done < <(printf '%s\n' "$HOME"/.local/share/uv/python/cpython-3.11*/bin/python3.11 | sort -V)
    printf '%s\n' "$newest"
}

if command -v python3.11 >/dev/null 2>&1; then
    PY="$(command -v python3.11)"
elif newest="$(newest_uv_311)" && [[ -n "$newest" ]]; then
    PY="$newest"
else
    PY="python3"
    echo "py311.sh: WARNING: no Python 3.11 found on PATH or under ~/.local/share/uv/python; falling back to $($PY --version 2>&1). CI pins 3.11 (.github/workflows/ci.yml) and is the authority: a newer-only API passes locally and fails there." >&2
fi

echo "py311.sh: using $("$PY" --version 2>&1) at $PY" >&2

if [[ "$MODE" == "print" ]]; then
    printf '%s\n' "$PY"
else
    exec "$PY" "$@"
fi
