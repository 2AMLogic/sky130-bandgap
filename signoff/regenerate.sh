#!/usr/bin/env bash
# Regenerate signoff/signoff-report.json -- the committed `klt signoff
# --manifest` tier-verdict report this repo treats as the verdict of record
# for its T1 checklist state (issue #282).
#
# Run from the repo root:
#     ./signoff/regenerate.sh
#
# Grader distribution discipline (load-bearing, see signoff/README.md
# "Grader distribution discipline"): this script grades with a throwaway
# venv + the *pip registry wheel* of the pinned klayout-tools version, NOT
# whatever `klt` happens to already be on PATH. A `uv tool install
# git+https://github.com/2AMLogic/klayout-tools` snapshot or a full-checkout
# install under the same version string can grade this checklist
# differently -- observed live across the fleet for 0.5.0 (an 11-item-era
# full-repo install under the name "0.5.0" vs. the v0.5.0 tag snapshot whose
# bundled checklist predates item 11 entirely, klayout-tools#2216).
set -euo pipefail

# Keep in sync with the `signoff` job's pip install in
# .github/workflows/ci.yml and scripts/ci/check_signoff_freshness.py's
# KLT_VERSION.
KLT_VERSION="0.6.0"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# 1. Refresh the generic-evidence wrapper's pinned hash of the aggregated
#    characterization report (T1 item 8 cites this wrapper; its pin is a
#    pure derivation from the report it wraps, so refreshing is mechanical).
CHAR_HASH="$(sha256sum design/block-characterization-report.md | cut -d' ' -f1)"
python3 - "$CHAR_HASH" <<'EOF'
import json
import pathlib
import sys

hash_hex = sys.argv[1]
envelope_path = pathlib.Path("signoff/evidence/characterization.generic.json")
envelope = json.loads(envelope_path.read_text())
envelope["provenance"]["input"]["content_hash"] = f"sha256:{hash_hex}"
envelope_path.write_text(json.dumps(envelope, indent=2) + "\n")

manifest_path = pathlib.Path("signoff/block-manifest.json")
manifest = json.loads(manifest_path.read_text())
manifest["evidence"]["8"]["content_hash"] = f"sha256:{hash_hex}"
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
EOF

# 2. Grade the block manifest with the pinned registry wheel. Exit code 3 is
#    `klt signoff`'s documented "ran successfully, but at least one T1 item
#    is unmet" -- expected for this block today -- so only the other exit
#    codes (1 = bad manifest/unparseable doc, 2 = usage error) are failures.
python3 -m venv "$WORK/venv"
"$WORK/venv/bin/pip" install --quiet "klayout-tools==$KLT_VERSION"

# The *identity* of the grading build matters as much as its version string
# -- see the module docstring above. The released registry wheel reports the
# git tag it was built from; assert it before trusting anything it grades.
python3 - "$WORK" "$KLT_VERSION" <<'EOF'
import json
import subprocess
import sys

work_dir, version = sys.argv[1], sys.argv[2]
info = json.loads(subprocess.run(
    [f"{work_dir}/venv/bin/klt", "version", "--format", "json"],
    capture_output=True, text=True, check=True).stdout)
if info.get("package_version") != version or info.get("git_tag") != f"v{version}" \
        or info.get("is_release") is not True:
    print(f"FATAL: grading klt is not the released {version} registry wheel -- "
          f"got package_version={info.get('package_version')} "
          f"git_tag={info.get('git_tag')} is_release={info.get('is_release')}. "
          "A same-version snapshot/full-checkout install grades differently; "
          "refusing to grade with it.", file=sys.stderr)
    sys.exit(1)
EOF

set +e
"$WORK/venv/bin/klt" signoff \
    --manifest signoff/block-manifest.json \
    --tiers-doc signoff/design-evidence-tiers.md \
    --format json > signoff/signoff-report.json
SIGNOFF_RC=$?
set -e
if [ "$SIGNOFF_RC" -ne 0 ] && [ "$SIGNOFF_RC" -ne 3 ]; then
    echo "FATAL: klt signoff exited $SIGNOFF_RC (not a rendered tier report)" >&2
    exit "$SIGNOFF_RC"
fi

python3 - "$KLT_VERSION" <<'EOF'
import json
import sys

report = json.load(open("signoff/signoff-report.json"))
print(f"graded with klayout-tools=={sys.argv[1]} (PyPI registry wheel)")
print(f"{report['block']}: kind={report['kind']} tier={report['tier']} "
      f"T1 {report['t1_met_count']}/{report['t1_item_count']} items met")
for item in report["items"]:
    if item["tier"] == "T1":
        marker = "MET  " if item["status"] == "met" else "UNMET"
        print(f"  [{marker}] #{item['id']:<2} {item['title']}"
              f"{'' if item['status'] == 'met' else ' -- ' + str(item['reason'])}")
EOF
