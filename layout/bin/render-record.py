#!/usr/bin/env python3
"""Render layout/trivial-cell/reports/<record-id>/record.md from the `klt`
JSON envelopes `run-trivial-cell-flow.sh` just produced in that directory.

Standard library only (matches sim/bin/corner-run.py's convention of no
extra runtime dependency beyond what the harness itself needs).

Exits non-zero (after writing record.md, so the evidence trail still gets a
record of the failure) if any of the four expected verdicts don't hold:
DRC clean, LVS match on the good reference, LVS mismatch on each of the two
negative-control references. That mirrors the trivial-cell flow's actual
job: it exists to prove the round trip works, so a silent verdict flip is
exactly the regression this script is here to catch.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _load(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def _git(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--record-id", required=True)
    ap.add_argument("--repo-root", required=True, type=Path)
    ap.add_argument("--klt", required=True)
    ap.add_argument("--pdk-variant", required=True)
    args = ap.parse_args()

    out_dir: Path = args.out_dir
    gen = _load(out_dir / "gen.json")
    drc = _load(out_dir / "drc.json")
    extract = _load(out_dir / "extract.json")
    lvs_good = _load(out_dir / "lvs.json")
    lvs_bad_dev = _load(out_dir / "lvs.broken-device.json")
    lvs_bad_topo = _load(out_dir / "lvs.broken-topology.json")

    sha = _git(args.repo_root, "rev-parse", "HEAD")
    branch = _git(args.repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    dirty = _git(args.repo_root, "status", "--porcelain") != ""

    klt_version = subprocess.run(
        [args.klt, "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()
    pdk_info_raw = subprocess.run(
        [args.klt, "pdk", "find", "--pdk", args.pdk_variant, "--format", "json"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    pdk_info = json.loads(pdk_info_raw)

    checks = [
        ("DRC on trivial_mos_array is clean", drc.get("status") == "clean"),
        ("LVS matches the known-good reference", lvs_good.get("status") == "match"),
        (
            "LVS negative control (device-parameter corruption) reports mismatch",
            lvs_bad_dev.get("status") == "mismatch",
        ),
        (
            "LVS negative control (topology corruption) reports mismatch",
            lvs_bad_topo.get("status") == "mismatch",
        ),
    ]
    all_pass = all(ok for _, ok in checks)

    lines: list[str] = []
    a = lines.append
    a(f"# Layout DRC/LVS record: {args.record_id}")
    a("")
    a(
        "Trivial-cell proof of the `klt`-driven DRC/LVS flow (issue #14) -- "
        "**not** bandgap-core layout, which is a later issue's scope."
    )
    a("")
    a("## Overall verdict: " + ("PASS" if all_pass else "FAIL"))
    a("")
    for desc, ok in checks:
        a(f"- [{'x' if ok else ' '}] {desc}")
    a("")
    a("## Flow")
    a("")
    a(
        "1. `klt gen mos_array --pdk "
        f"{args.pdk_variant} --cell-name trivial_mos_array` "
        "-- default params (2x2 array, 1 dummy column/side, nfet, no well)."
    )
    a("2. `klt drc trivial_mos_array.gds --deck sky130`")
    a("3. `klt extract trivial_mos_array.gds --deck sky130 --top trivial_mos_array`")
    a(
        "4. `klt lvs` against `reference.spice` (known-good) and two "
        "negative-control references (`reference.broken-device.spice`, "
        "`reference.broken-topology.spice`)."
    )
    a("")
    a("## Cell")
    a("")
    a(f"- Generator: `mos_array` (`klt gen --list` for the full params schema)")
    a(f"- `device_count` (real, non-dummy): {gen.get('device_count')}")
    a(f"- bbox (um): {gen.get('bbox_um')}")
    a(f"- `matched_group_id`: {gen.get('drc_hints', {}).get('matched_group_id')}")
    a("")
    a("## Results")
    a("")
    a("| Stage | Status | Detail |")
    a("| --- | --- | --- |")
    a(
        "| DRC | "
        f"{drc.get('status')} | violation_count={drc.get('violation_count')} |"
    )
    a(
        "| Extract | "
        f"{extract.get('status')} | device_count={extract.get('device_count')}, "
        f"net_count={extract.get('net_count')}, pin_count={extract.get('pin_count')} |"
    )
    a(
        "| LVS (good reference) | "
        f"{lvs_good.get('status')} | mismatch_count={lvs_good.get('mismatch_count')}, "
        f"category_counts={lvs_good.get('category_counts')} |"
    )
    a(
        "| LVS negative control: device parameter | "
        f"{lvs_bad_dev.get('status')} | mismatch_count={lvs_bad_dev.get('mismatch_count')} |"
    )
    a(
        "| LVS negative control: topology (shorted net) | "
        f"{lvs_bad_topo.get('status')} | mismatch_count={lvs_bad_topo.get('mismatch_count')} |"
    )
    a("")
    good_mismatches = lvs_good.get("mismatches", [])
    non_warning = [m for m in good_mismatches if m.get("severity") != "warning"]
    ambiguous_net = [
        m
        for m in good_mismatches
        if m.get("category") == "topology" and m.get("net") is not None
    ]
    unused_class = [
        m
        for m in good_mismatches
        if m.get("category") == "topology" and m.get("net") is None
    ]
    body_unverified = [
        m for m in good_mismatches if m.get("category") == "device.body_unverified"
    ]
    a(
        f"The good-reference LVS run's `mismatch_count` "
        f"({lvs_good.get('mismatch_count')}) is nonzero but `status` is "
        f"`\"match\"` -- all {len(good_mismatches)} entries are "
        f"`severity: \"warning\"` (0 at `severity: \"error\"`; see "
        "`lvs.json`), documented, expected quirks for this minimal, highly "
        "symmetric cell:"
    )
    a(
        f"- `device.body_unverified` (x{len(body_unverified)}): the curated "
        "sky130 extraction deck draws no distinct NMOS substrate/tap layer, "
        "so every body terminal compares against a deck-synthesized "
        "`vsubs` net rather than a real schematic net (documented in "
        "`klt extract`'s own \"Coverage\" docs)."
    )
    a(
        f"- `topology`, ambiguous net pairing (x{len(ambiguous_net)}): the "
        "array's unit devices are electrically interchangeable (no two "
        "devices connect to a common net that would anchor a unique "
        "pairing), so `NetlistComparer` resolves the correspondence "
        "structurally rather than uniquely -- expected for a fully "
        "symmetric matched array, not a defect."
    )
    a(
        f"- `topology`, unused device class on both sides (x{len(unused_class)}): "
        "device classes the sky130 deck can recognise (e.g. `pfet`, `pnp`, "
        "`resistor`) but that this cell draws none of -- not a real mismatch."
    )
    if non_warning:
        a(
            f"- **{len(non_warning)} `severity: \"error\"` entries were "
            "present -- this is NOT a clean match and the assertion above "
            "should have failed.**"
        )
    a("")
    a("## Provenance")
    a("")
    a(f"- Record ID: `{args.record_id}`")
    a(f"- `klt` version: `{klt_version}` (pinned commit, see `layout/requirements.txt`)")
    a(
        f"- KLayout engine version: "
        f"`{drc.get('provenance', {}).get('klayout_version')}`"
    )
    a(f"- PDK: `{pdk_info.get('variant')}`, `{pdk_info.get('version')}`")
    a(
        "- PDK pin cross-check: compare `version` above against "
        "`sim/pdk.json`'s `open_pdks_commit` -- this flow does not itself "
        "enforce the pin (unlike `sim/bin/corner-run.py`), so a mismatch "
        "here is a manual reproducibility note, not a hard failure."
    )
    a(f"- Repo state: `{sha}` on `{branch}`" + (" (dirty)" if dirty else ""))
    a("")
    a("## Links")
    a("")
    a("- [`gen.json`](gen.json), [`trivial_mos_array.gds`](trivial_mos_array.gds)")
    a("- [`drc.json`](drc.json)")
    a("- [`extract.json`](extract.json), [`trivial_mos_array.extract.spice`](trivial_mos_array.extract.spice)")
    a("- [`lvs.request.json`](lvs.request.json), [`lvs.json`](lvs.json), [`reference.spice`](reference.spice)")
    a(
        "- [`lvs.broken-device.request.json`](lvs.broken-device.request.json), "
        "[`lvs.broken-device.json`](lvs.broken-device.json), "
        "[`reference.broken-device.spice`](reference.broken-device.spice)"
    )
    a(
        "- [`lvs.broken-topology.request.json`](lvs.broken-topology.request.json), "
        "[`lvs.broken-topology.json`](lvs.broken-topology.json), "
        "[`reference.broken-topology.spice`](reference.broken-topology.spice)"
    )
    a("- [`report.md`](report.md) -- combined `klt report --format github-summary` rendering")
    a("")

    print("\n".join(lines))
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
