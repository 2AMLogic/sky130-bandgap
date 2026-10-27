#!/usr/bin/env python3
"""Mint the T1 item-5 `klt sim` envelopes from the committed corner records (issue #434).

T1 item 5 (Full corner verification, analog) accepts only `klt sim`-shaped
envelopes. This repo's corner benches (`sim/<bench>/records/*.json`) are run
by its own harness (`sim/bin/corner-run.py`), not by `klt sim`, so the
envelopes are **derived from those records without re-simulating**: the
ratified-row measurements are transcribed verbatim, every envelope is pinned to
the netlist snapshot its record simulated, and nothing here edits a bound.
Re-simulating every row as a fresh `klt sim` request would run on the batch
fleet and collide with the open_pdks re-pin (#370 / #395); a later re-mint
under the new pin just re-runs this script against the newer records.

Two tables below carry every judgement call, so a reviewer can audit them in
one place:

* `BENCHES` -- which bench backs which ratified spec row, which measurements
  count for that row, and (where the ratified spec states a number) the bound
  the record's own limit must equal. A record whose limit drifted from the
  ratified bound is refused, never silently graded against the wrong line.
  Measurements a bench records but no ratified row binds (measurement-validity
  guards, diagnostic controls, non-ratified cross-checks) are left out of the
  envelope and listed under `mint.excluded_measurements`; they stay in the
  source record.
* `GAP_ROWS` -- ratified rows no corner-record envelope can express, declared
  as `gap` in the manifest with a reason.

Record choice is mechanical, not hand-picked: the newest record of the bench
whose matrix has more than one point (this drops the single-corner
batch-vs-local equivalence checks of #396 and nothing else). A newer failing
record therefore supersedes an older passing one.

Usage (from the repo root)
--------------------------
    sim/signoff-envelopes/emit_klt_sim_envelopes.py --write   # (re)mint + rewrite manifest/pins
    sim/signoff-envelopes/emit_klt_sim_envelopes.py --check   # exit 1 if anything is stale
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ENVELOPE_DIR = REPO_ROOT / "sim" / "signoff-envelopes"
MANIFEST = REPO_ROOT / "signoff" / "block-manifest.json"
PINNED_INPUTS = REPO_ROOT / "signoff" / "pinned-inputs.json"

ITEM = "5"

# Ratified bounds (DR-005; PSRR band per DR-006). `None` in a `BENCHES` entry
# means the ratified spec states no number for that measurement (structural
# startup claims, supply-sweep coverage guards): the record's own limits are
# copied as recorded.
WINDOW = {"min": 1.176, "max": 1.224}  # 1.20 V +/-2 %
TC_MAX = {"max": 50.0}  # < 50 ppm/degC, box method
PSRR_MIN = {"min": 60.0}  # > 60 dB, DC..1 kHz band-min (DR-006)
IQ_MAX = 50e-6  # < 50 uA
T_START_MAX = {"max": 1e-3}  # < 1 ms
LINE_SHIFT_MAX = {"max": 48.0}  # fits the +/-2 % window (48 mV p-p)

BENCHES: list[dict[str, Any]] = [
    {
        "bench": "output-voltage-tc",
        "measurements": {
            "vref_27": ("1a", WINDOW),
            "vref_min": ("1a", WINDOW),
            "vref_max": ("1a", WINDOW),
            "tc_ppm": ("3a", TC_MAX),
        },
    },
    {
        "bench": "output-voltage-tc-post-layout",
        "measurements": {
            "vref_27": ("1b", WINDOW),
            "vref_min": ("1b", WINDOW),
            "vref_max": ("1b", WINDOW),
            "tc_ppm": ("3b", TC_MAX),
        },
    },
    {
        "bench": "psrr-dc",
        "measurements": {m: ("4a", PSRR_MIN) for m in ("psrr_dc", "psrr_1k", "psrr_band_min")},
    },
    {
        "bench": "psrr-dc-post-layout",
        "measurements": {m: ("4b", PSRR_MIN) for m in ("psrr_dc", "psrr_1k", "psrr_band_min")},
    },
    {
        "bench": "line-regulation",
        "measurements": {
            "line_shift_mv": ("5a", LINE_SHIFT_MAX),
            "sweep_start_v": ("5a", None),
            "sweep_end_v": ("5a", None),
        },
    },
    {
        "bench": "line-regulation-post-layout",
        "measurements": {
            "line_shift_mv": ("5c", LINE_SHIFT_MAX),
            "sweep_start_v": ("5c", None),
            "sweep_end_v": ("5c", None),
        },
    },
    {"bench": "quiescent-current", "measurements": {"iq": ("6a", {"max": IQ_MAX})}},
    {"bench": "quiescent-current-post-layout", "measurements": {"iq": ("6b", {"max": IQ_MAX})}},
    {
        "bench": "startup-stability",
        "measurements": {
            m: ("8a", None)
            for m in ("ncross_su", "itrav_min", "imin_off_su", "i_off_su", "i_on_su")
        },
    },
    {
        "bench": "startup-stability-post-layout",
        "measurements": {
            m: ("8b", None)
            for m in ("ncross_su", "itrav_min", "imin_off_su", "i_off_su", "i_on_su")
        },
    },
    {
        "bench": "startup-ramp",
        "measurements": {m: ("8c", T_START_MAX) for m in ("t_start_s", "t_start_f", "t_start_g")},
    },
    {
        "bench": "startup-ramp-post-layout",
        "measurements": {m: ("8d", T_START_MAX) for m in ("t_start_s", "t_start_f", "t_start_g")},
    },
]

GAP_ROWS: list[dict[str, str]] = [
    {
        "id": "1c",
        "gap": (
            "output reference, untrimmed, 3-sigma mismatch Monte Carlo: a distribution claim, "
            "not a PVT corner row; graded by T1 item 6 (klt yield), not expressible as a "
            "klt sim corner envelope"
        ),
    },
    {
        "id": "2",
        "gap": (
            "trim (range, step, bit-equivalence): sim/trim-range-monotonicity and "
            "sim/trim-lsb-chained record a trim-code sweep graded by checks, not a per-corner "
            "measurement table with a bound, so no corner envelope can be derived from them"
        ),
    },
    {
        "id": "7",
        "gap": (
            "area (< 0.08 mm2, DR-007): a layout measurement from the composed-cell bbox "
            "(layout/bandgap-core/reports/*/record.md), not a SPICE corner row"
        ),
    },
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def dump(obj: Any) -> str:
    return json.dumps(obj, indent=2) + "\n"


def newest_record(bench: str) -> Path:
    """Newest `sim/<bench>/records/*.json` corner record with a multi-point matrix."""
    candidates = []
    for path in sorted((REPO_ROOT / "sim" / bench / "records").glob("*.json")):
        if path.name.endswith("-klt-yield.json"):
            continue
        record = json.loads(path.read_text())
        if (record.get("matrix") or {}).get("n_points", 0) > 1:
            candidates.append(path)
    if not candidates:
        raise SystemExit(f"{bench}: no multi-point corner record under sim/{bench}/records/")
    return candidates[-1]


def margin(value: float, limits: dict[str, float]) -> float:
    margins = []
    if "min" in limits:
        margins.append(value - limits["min"])
    if "max" in limits:
        margins.append(limits["max"] - value)
    return min(margins)


def check_bound(bench: str, name: str, recorded: dict[str, float], expected: dict[str, float]) -> None:
    for key, bound in expected.items():
        if recorded.get(key) != bound:
            raise SystemExit(
                f"{bench}/{name}: the record's {key} limit is {recorded.get(key)!r}, but the "
                f"ratified bound is {bound!r}. Refusing to grade against a drifted limit; "
                "fix the bench or record a decision, do not edit this table to match."
            )


def split_by_row(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """One entry per spec row: a row's failure must not drag a sibling row's
    verdict (a bench's `tc_ppm` failing must not fail its `vref` window row)."""
    rows = sorted({row for row, _ in entry["measurements"].values()}, key=row_order)
    return [
        {
            "bench": entry["bench"],
            "row": row,
            "all_mapped": set(entry["measurements"]),
            "measurements": {
                n: v for n, v in entry["measurements"].items() if v[0] == row
            },
        }
        for row in rows
    ]


def mint(entry: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return `(file name, envelope)` for one (bench, row) entry."""
    bench = entry["bench"]
    record_path = newest_record(bench)
    record = json.loads(record_path.read_text())
    snapshot = record["links"]["netlist_snapshot"]
    snapshot_path = REPO_ROOT / snapshot
    if not snapshot_path.is_file():
        raise SystemExit(f"{bench}: netlist snapshot missing: {snapshot}")

    wanted: dict[str, tuple[str, dict[str, float] | None]] = entry["measurements"]
    units: dict[str, str] = {}
    limits: dict[str, dict[str, float]] = {}
    excluded: dict[str, str] = {}
    corners = []
    series: dict[str, list[tuple[float, str]]] = {name: [] for name in wanted}

    for corner in record["corners"]:
        measurements = []
        for m in corner["measurements"]:
            name = m["name"]
            if name not in wanted:
                if name not in entry["all_mapped"]:
                    excluded.setdefault(name, "no ratified spec row binds this measurement")
                continue
            bounds = {k: m[k] for k in ("min", "max") if m.get(k) is not None}
            expected = wanted[name][1]
            if expected is not None:
                check_bound(bench, name, bounds, expected)
            limits.setdefault(name, bounds)
            units[name] = m.get("unit", "")
            value = m["value"]
            passed = bool(m["pass"])
            series[name].append((value, corner["corner_id"]))
            measurements.append(
                {
                    "name": name,
                    "unit": units[name],
                    "value": value,
                    "status": "pass" if passed else "fail",
                    "margin": margin(value, bounds),
                }
            )
        supply = corner.get("supply_v")
        corners.append(
            {
                "corner_id": corner["corner_id"],
                "process": corner["process"],
                "supply_v": {"vdd": supply},
                "temperature_c": corner["temperature_c"],
                "status": "pass" if all(x["status"] == "pass" for x in measurements) else "fail",
                "measurements": measurements,
            }
        )

    missing = sorted(set(wanted) - {n for n, s in series.items() if s})
    if missing:
        raise SystemExit(f"{bench}: {record_path.name} has no measurement(s) {missing}")

    envelope_measurements = []
    for name, (row, _) in wanted.items():
        points = [(margin(v, limits[name]), v, cid) for v, cid in series[name]]
        worst_margin, worst_value, worst_corner = min(points)
        envelope_measurements.append(
            {
                "name": name,
                "unit": units[name],
                "spec_row": row,
                "limits": limits[name],
                "worst_case": {
                    "corner_id": worst_corner,
                    "value": worst_value,
                    "margin": worst_margin,
                },
                "status": "pass" if all(
                    c_m["status"] == "pass"
                    for c in corners
                    for c_m in c["measurements"]
                    if c_m["name"] == name
                )
                else "fail",
            }
        )

    n_pass = sum(c["status"] == "pass" for c in corners)
    envelope = {
        "schema_version": 3,
        "status": "pass" if n_pass == len(corners) else "fail",
        "netlist": snapshot,
        "corner_count": len(corners),
        "passed": n_pass,
        "failed": len(corners) - n_pass,
        "errored": 0,
        "metrics": {
            "sim__corner__count": len(corners),
            "sim__corner__passed_count": n_pass,
            "sim__corner__failed_count": len(corners) - n_pass,
            "sim__corner__errored_count": 0,
        },
        "coverage": {
            "measurements_declared": len(envelope_measurements),
            "measurements_with_limits": len(envelope_measurements),
        },
        "mint": {
            "minted_by": rel(Path(__file__).resolve()),
            "disclosure": (
                "Minted from the committed append-only corner record below, NOT produced by a "
                "live `klt sim` run: this repo's corner benches run under sim/bin/corner-run.py. "
                "Values, limits and per-corner verdicts are transcribed verbatim; no bound is "
                "relaxed. The record is the newest multi-point record of the bench, so a newer "
                "failing record supersedes an older passing one. Re-mint against newer records "
                "(e.g. after the open_pdks re-pin, #370) by re-running the minter."
            ),
            "spec_rows": sorted({row for row, _ in wanted.values()}),
            "recorded_from": [{"file": rel(record_path), "sha256": sha256_file(record_path)}],
            "excluded_measurements": dict(sorted(excluded.items())),
        },
        "provenance": {
            "input": {"content_hash": f"sha256:{sha256_file(snapshot_path)}", "role": "netlist"},
            "note": (
                "no klt_version: no klt invocation produced this envelope (see mint); the input "
                f"pin is the sha256 of the netlist snapshot the record simulated ({snapshot})"
            ),
        },
        "measurements": envelope_measurements,
        "corners": corners,
    }
    return f"{bench}.{entry['row']}.klt-sim.json", envelope


def build() -> dict[Path, str]:
    """Every file this minter owns, `{path: text}`."""
    out: dict[Path, str] = {}
    members = []
    pins = []
    entries = [e for bench in BENCHES for e in split_by_row(bench)]
    for index, entry in enumerate(entries):
        name, envelope = mint(entry)
        path = ENVELOPE_DIR / name
        out[path] = dump(envelope)
        pin = envelope["provenance"]["input"]["content_hash"]
        members.append(
            {"file": rel(path), "content_hash": pin, "rows": envelope["mint"]["spec_rows"]}
        )
        pins.append(
            {
                "item": ITEM,
                "index": index,
                "describes": envelope["netlist"],
                "note": (
                    f"netlist snapshot the {entry['bench']} record simulated (row {entry['row']}); the minted "
                    "envelope's provenance.input.content_hash. Re-minted by "
                    "sim/signoff-envelopes/emit_klt_sim_envelopes.py."
                ),
            }
        )

    manifest = json.loads(MANIFEST.read_text())
    manifest["evidence"][ITEM] = members
    manifest["evidence"] = dict(sorted(manifest["evidence"].items(), key=lambda kv: int(kv[0])))
    covered = [row for m in members for row in m["rows"]]
    rows = [{"id": row} for row in sorted(set(covered), key=row_order)]
    rows += [dict(gap) for gap in GAP_ROWS]
    rows.sort(key=lambda r: row_order(r["id"]))
    manifest.setdefault("spec_rows", {})[ITEM] = rows
    out[MANIFEST] = dump(manifest)

    declared = json.loads(PINNED_INPUTS.read_text())
    declared["pins"] = [p for p in declared["pins"] if str(p["item"]) != ITEM] + pins
    declared["pins"].sort(key=lambda p: (int(p["item"]), p.get("index", -1)))
    out[PINNED_INPUTS] = dump(declared)
    return out


def row_order(row_id: str) -> tuple[int, str]:
    digits = "".join(ch for ch in row_id if ch.isdigit())
    return int(digits), row_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()

    expected = build()
    if args.write:
        ENVELOPE_DIR.mkdir(parents=True, exist_ok=True)
        for path, text in expected.items():
            path.write_text(text)
        print(f"wrote {len(expected)} files (item-5 envelopes + manifest + pins)")
        return 0

    stale = [
        rel(path)
        for path, text in expected.items()
        if not path.is_file() or path.read_text() != text
    ]
    if stale:
        print("stale (re-run with --write):", *stale, sep="\n  ", file=sys.stderr)
        return 1
    print(f"{len(expected)} item-5 files fresh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
