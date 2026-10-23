#!/usr/bin/env python3
"""Store a layout flow's raw outputs in the fleet artifact store (issue #426).

Thin CLI over `sim/bin/sim_common.publish_corner_evidence()` so the layout
flows share the sim harness's publisher rather than duplicating it.

  publish_layout_evidence.py check
      Exit non-zero unless `klt artifact put` can run here. The flow calls
      this before creating any directory.
  publish_layout_evidence.py publish STAGING_DIR --bench NAME --run-id ID
      Write manifests/artifacts/<NAME>-<ID>.manifest.json (+ .md summary) for
      every file under STAGING_DIR. Fails closed; no local fallback.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))
import sim_common  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    pub = sub.add_parser("publish")
    pub.add_argument("staging_dir", type=Path)
    pub.add_argument("--bench", required=True)
    pub.add_argument("--run-id", required=True)
    args = ap.parse_args(argv)
    try:
        sim_common.require_artifact_store()
        if args.cmd == "publish":
            manifest = sim_common.publish_corner_evidence(
                args.staging_dir, REPO_ROOT, bench=args.bench, run_id=args.run_id
            )
            if manifest is None:
                print("publish_layout_evidence: staging dir is empty", file=sys.stderr)
                return 1
            print(manifest)
    except sim_common.EvidenceStoreError as err:
        print(f"publish_layout_evidence: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
