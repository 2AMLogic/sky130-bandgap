#!/usr/bin/env bash
# check-dr-duplicate-numbers.sh - Fail if two files in
# spec/decision-records/ share the same DR-NNN prefix.
#
# Why (#126): main once carried two decision records both numbered DR-006
# (spec/decision-records/DR-006-mcc-area-budget.md and
# spec/decision-records/DR-006-psrr-frequency-qualification.md), merged
# concurrently by #124 and #125 -- both picked "the next unused NNN" against
# the same base commit and neither saw the other. A decision record's whole
# purpose is unambiguous citation, so a duplicate number silently breaks
# that. This guard catches the collision at lint time instead of after
# merge.
#
# Usage:
#   check-dr-duplicate-numbers.sh [ROOT]
#     ROOT  Repository root containing spec/decision-records/. Defaults to
#           `git rev-parse --show-toplevel`, then the script's own repo
#           root.
#
# Exit codes: 0 = every DR-NNN prefix in spec/decision-records/ is unique
# (or the directory has no DR-*.md files); 1 = two or more files share a
# DR-NNN prefix (offenders listed on stderr).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -ge 1 && -n "${1:-}" ]]; then
  ROOT="$1"
else
  if ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)"; then
    :
  else
    # .loom/scripts/ -> .loom/ -> repo root
    ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
  fi
fi

DR_DIR="$ROOT/spec/decision-records"

if [[ ! -d "$DR_DIR" ]]; then
  echo "check-dr-duplicate-numbers: no $DR_DIR — nothing to check (ok)."
  exit 0
fi

shopt -s nullglob
files=("$DR_DIR"/DR-*.md)
shopt -u nullglob

if [[ ${#files[@]} -eq 0 ]]; then
  echo "check-dr-duplicate-numbers: no DR-*.md files under $DR_DIR — nothing to check (ok)."
  exit 0
fi

declare -A seen=()
found=0

for file in "${files[@]}"; do
  base="$(basename "$file")"
  if [[ "$base" =~ ^(DR-[0-9]+)- ]]; then
    prefix="${BASH_REMATCH[1]}"
  else
    # Doesn't match the DR-NNN-<slug>.md convention (e.g. TEMPLATE.md
    # sitting alongside them) -- not this guard's concern.
    continue
  fi

  if [[ -n "${seen[$prefix]:-}" ]]; then
    echo "DUPLICATE DR NUMBER: ${prefix}" >&2
    echo "  ${seen[$prefix]}" >&2
    echo "  ${base}" >&2
    found=1
  else
    seen[$prefix]="$base"
  fi
done

if [[ "$found" -ne 0 ]]; then
  echo "" >&2
  echo "check-dr-duplicate-numbers: FAIL — two or more decision records in" >&2
  echo "spec/decision-records/ share the same DR-NNN prefix. A decision" >&2
  echo "record's number must be unique so citations are unambiguous (see" >&2
  echo "spec/README.md). Renumber one of the offending files to the next" >&2
  echo "unused NNN and update its inbound citations." >&2
  exit 1
fi

echo "check-dr-duplicate-numbers: OK — ${#files[@]} decision record(s), all DR-NNN prefixes unique."
exit 0
