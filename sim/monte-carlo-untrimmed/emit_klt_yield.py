#!/usr/bin/env python3
"""Emit a `klt yield` JSON envelope for a `run_mc_untrimmed.py` record (issue #180).

`klt yield` (klayout-tools 0.2.0, pinned by `layout/requirements.txt`) turns a
Monte Carlo sample set + spec limits into a yield estimate that always
carries its confidence interval, Cpk/sigma-to-spec, and a sample-size
verdict -- a machine-checkable envelope alongside this experiment's own
ngspice-driven `record.md`/`record.json` pair, per issue #180's acceptance
criteria and `klt signoff`'s aggregation contract.

This is a post-hoc reader, not part of the simulation run: `klt yield`
consumes a plain sample-set document ({"measurements": [{"name", "samples",
"limits"}, ...]}), which this script builds by re-parsing the `all`-config
mismatch points' raw per-sample `vout` values out of the record's own
`corners/<record_id>/*.log` files (the same files `run_mc_untrimmed.py`
already wrote and the record already cites) -- no new simulation, no new
netlist. Only the `all` config (every family's mismatch active at once) is
included: that is the spec-relevant row the record's own tables single out;
the `pnp`/`resistor`/`mos` isolated re-runs are contributor-breakdown
diagnostics, not independent yield claims (see the record's own caption).
Only *converged* samples are included -- the same `mc_solve_yield` exclusion
`run_mc_untrimmed.py` applies (issue #10's startup artifact is not a
mismatch datum) -- so the sample count and yield figure this emits are
directly comparable to the record's own table, not a re-definition of it.

Usage
-----
    sim/monte-carlo-untrimmed/emit_klt_yield.py <record_id>

Writes `sim/monte-carlo-untrimmed/records/<record_id>-klt-yield.json` (the
raw `klt yield --format json` payload) and prints a one-line summary per
temperature. Exit status: 0 on success, 1 if `klt` or its native extension is
unavailable (in which case the record must say so per issue #180's
acceptance criteria) or the expected corner logs are missing, 2 if `klt
yield` itself reports an error.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE.parent
REPO_ROOT = SIM_DIR.parent

sys.path.insert(0, str(SIM_DIR / "bin"))
from sim_common import parse_samples, partition_by_window  # noqa: E402

sys.path.insert(0, str(HERE))
import run_mc_untrimmed as record_mod  # noqa: E402

# Mirrors run_mc_untrimmed.py's own module-level constants -- kept in sync by
# hand (both are small, stable, and cited by the same record).
SPEC_WINDOW_V = (1.176, 1.224)
OPERATING_VOUT_V = (0.9, 1.5)
TEMPS_C = [-40.0, 27.0, 125.0]
SUPPLY_V = 3.3
MM_SECTION = "tt_mm"


def corner_id_for(temp_c: float) -> str:
    return f"{MM_SECTION}_all_{temp_c:g}c_{SUPPLY_V:.2f}v"


def measurement_name(temp_c: float) -> str:
    sign = "m" if temp_c < 0 else ""
    return f"vout_all_{sign}{abs(temp_c):g}c"


def load_vout_samples(log_path: Path) -> list[float]:
    if not log_path.is_file():
        raise SystemExit(f"error: missing corner log: {log_path}")
    text = log_path.read_text()
    parsed = parse_samples(text, ("vout", "vgdrv"))
    if not parsed:
        raise SystemExit(f"error: no Monte Carlo samples parsed from {log_path}")
    converged, _excluded = partition_by_window(parsed, "vout", OPERATING_VOUT_V)
    return [s["vout"] for s in converged]


def build_sample_set(record_id: str) -> dict:
    corners_dir = HERE / "corners" / record_id
    measurements = []
    for t in TEMPS_C:
        corner_id = corner_id_for(t)
        samples = load_vout_samples(corners_dir / f"{corner_id}.log")
        measurements.append(
            {
                "name": measurement_name(t),
                "unit": "V",
                "samples": samples,
                "limits": {"min": SPEC_WINDOW_V[0], "max": SPEC_WINDOW_V[1]},
                "source_corners": [corner_id],
            }
        )
    return {"measurements": measurements}


def main(argv: list[str]) -> int:
    if len(argv) != 1 or not re.match(r"^\d{8}-\d{6}-[0-9a-f]+$", argv[0]):
        print(f"usage: {Path(__file__).name} <record_id>", file=sys.stderr)
        return 1
    record_id = argv[0]

    record_json = HERE / "records" / f"{record_id}.json"
    if not record_json.is_file():
        print(f"error: no such record: {record_json}", file=sys.stderr)
        return 1

    if not shutil.which("klt"):
        print(
            "klt not found on PATH -- cannot emit a klt yield envelope; the "
            "record must state this rather than silently omitting it (issue #180)",
            file=sys.stderr,
        )
        return 1

    sample_set = build_sample_set(record_id)
    sample_set_path = HERE / "records" / f"{record_id}-klt-yield-input.json"
    sample_set_path.write_text(json.dumps(sample_set, indent=2) + "\n")

    proc = subprocess.run(
        ["klt", "yield", str(sample_set_path), "--format", "json"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(proc.stdout, file=sys.stdout)
        print(proc.stderr, file=sys.stderr)
        print(
            f"error: klt yield exited {proc.returncode} -- see stderr above; the "
            "record must disclose this rather than silently omitting the envelope",
            file=sys.stderr,
        )
        return 2

    out_path = HERE / "records" / f"{record_id}-klt-yield.json"
    out_path.write_text(proc.stdout if proc.stdout.endswith("\n") else proc.stdout + "\n")

    # Complete the record: this envelope is meant to sit "alongside" the
    # ngspice-driven record (issue #180's acceptance criteria), so fold its
    # links and a summary table into record.md/record.json now that it
    # exists -- both files are otherwise still exactly what run_mc_untrimmed.py
    # wrote a moment ago in the same, still-uncommitted run; this is
    # completing that record's generation, not editing a published one (see
    # sim/README.md's append-only rule, which governs already-committed
    # records).
    record = json.loads(record_json.read_text())
    for key, value in record_mod.klt_yield_links(record_id):
        record["links"][key] = value
    record_json.write_text(json.dumps(record, indent=2) + "\n")
    record_md = HERE / "records" / f"{record_id}.md"
    record_md.write_text(record_mod.render_record(record))

    payload = json.loads(proc.stdout)
    print(f"klt yield envelope written: {out_path.relative_to(REPO_ROOT)}")
    print(f"sample-set input written:   {sample_set_path.relative_to(REPO_ROOT)}")
    print(f"record updated:             {record_md.relative_to(REPO_ROOT)}")
    for m in payload.get("measurements", []):
        emp = m.get("yield", {}).get("empirical", {})
        print(
            f"  {m['name']:<16} n={m.get('n')} "
            f"empirical yield={emp.get('estimate'):.4f} "
            f"CI=[{emp.get('confidence_interval', {}).get('low'):.4f}, "
            f"{emp.get('confidence_interval', {}).get('high'):.4f}] "
            f"(confidence={emp.get('confidence')})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
