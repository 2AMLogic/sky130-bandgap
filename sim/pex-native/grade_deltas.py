#!/usr/bin/env python3
"""Grade a `klt pex` report's per-corner deltas against `delta-limits.json` (issue #335).

    grade_deltas.py REPORT.json [--limits delta-limits.json] [-o graded.json]

Also enforces the full declared matrix (every corner x every limited observable
present, errored rows count as failures). Exit 0 all within limits, 2 some
delta exceeds its limit, 1 report incomplete. Ratified absolute limits are NOT
touched here; they are graded independently from the manifest.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pexlib  # noqa: E402


def grade(report: dict, limits: dict) -> dict:
    rows = {(r["corner_id"], r["spec_row"]): r for r in report.get("delta", [])}
    out, missing = [], []
    for cid in pexlib.corner_ids():
        for ob in limits["observables"]:
            r = rows.get((cid, ob["name"]))
            if r is None or r.get("schematic_value") is None or r.get("extracted_value") is None:
                missing.append(f"{cid}/{ob['name']}")
                continue
            d = r["extracted_value"] - r["schematic_value"]
            out.append({"corner_id": cid, "observable": ob["name"], "unit": ob["unit"],
                        "schematic": r["schematic_value"], "extracted": r["extracted_value"],
                        "delta": round(d, 6), "abs_delta_max": ob["abs_delta_max"],
                        "within_limit": abs(d) <= ob["abs_delta_max"]})
    return {"rows": out, "missing": missing,
            "n_within": sum(r["within_limit"] for r in out),
            "n_exceeded": sum(not r["within_limit"] for r in out)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("report", type=Path)
    ap.add_argument("--limits", type=Path, default=pexlib.HERE / "delta-limits.json")
    ap.add_argument("-o", type=Path)
    a = ap.parse_args()
    g = grade(json.loads(a.report.read_text()), json.loads(a.limits.read_text()))
    g["limits_sha256"] = pexlib.sha256_file(a.limits)
    text = json.dumps(g, indent=2, sort_keys=True) + "\n"
    (a.o.write_text(text) if a.o else sys.stdout.write(text))
    print(f"{g['n_within']} within, {g['n_exceeded']} exceeded, {len(g['missing'])} missing", file=sys.stderr)
    sys.exit(1 if g["missing"] else 2 if g["n_exceeded"] else 0)
