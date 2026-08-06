#!/usr/bin/env python3
"""layout/bin/measure_fixed_offset_variants.py -- measure what `klt lvs`
reports for this cell's chained resistor arrays under each of the four
combinations of klayout-tools#583/#587's `fixed_offset_ohm` accounting, so
the routed flow's decision *not* to adopt the deferral rests on a re-runnable
measurement rather than a hand calculation.

Why this exists
---------------
sky130's curated extraction deck models `res_high_po` as
`R = L / W * sheet_rho_ohm_sq + fixed_offset_ohm` (klayout-tools#518 via
#519). This flow draws each logical schematic resistor as a *series chain of
separately contacted* primitives (`res_r2`/`res_trim`/`res_r1`, 70/70/7 per
logical device -- required so every DR-002 trim tap lands on real,
individually contacted metal; see `gen_bandgap_routed.py`'s
RES_HEAD_RESISTANCE_NOTE), so `options.combine_devices` sums the head/end
term once per drawn primitive rather than once for the logical device.

klayout-tools#559 filed that as an accounting question; #583 answered it by
deferring the correction until after `combine_devices()` folds the chain, and
#587 both fixed a case-sensitive device-class lookup (which had silently
missed the `kdb.NetlistSpiceReader`-uppercased `RES_HIGH_PO` on this flow's
pre-extracted request shape) and added
`run_extract(..., apply_resistor_fixed_offset=False)` so a caller can defer
the per-primitive offset at *extraction* time.

Whether to adopt that is a *design* question, not a tooling one: DR-003
(issue #98) ratified, with independent real-SPICE evidence, that this layout
physically pays the head/end term once per separately contacted instance.
This harness measures all four combinations against one record's own drawn
`.gds` so the question can be answered from numbers:

    variant             extraction offset      klt lvs layout.deck
    ------------------  ---------------------  --------------------
    primary_nodeck      applied per primitive  absent   <- the shipped flow
    primary_deck        applied per primitive  present  (double-counts)
    deferred_nodeck     deferred (omitted)     absent   (body R only)
    deferred_deck       deferred (omitted)     present  <- #587's pairing

It is deliberately NOT part of `run-bandgap-routed-flow.sh`'s gate: it
changes nothing, reads an existing record, and writes only its own
append-only evidence directory.

Usage
-----
    layout/.venv/bin/python layout/bin/measure_fixed_offset_variants.py \\
        --record layout/bandgap-core/reports/<record-id> \\
        --out-dir layout/bandgap-core/fixed-offset-variants/<record-id>

Requires `layout/.venv` (see `setup-venv.sh`) -- it imports `klayout_tools`
directly, because the deferral is a `run_extract` Python-API parameter that
the `klt extract` CLI threads no flag for (filed generically as
klayout-tools#588).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

CELL = "bandgap_core_routed"
REFERENCE_TOP = "bandgap_core"
DECK = "sky130"

#: The four accounting combinations, as (label, defer_at_extract, pass_deck).
VARIANTS: tuple[tuple[str, bool, bool], ...] = (
    ("primary_nodeck", False, False),
    ("primary_deck", False, True),
    ("deferred_nodeck", True, False),
    ("deferred_deck", True, True),
)

#: Which resistor `device.property` findings to report per variant, keyed by
#: the reference-side device name the flow's `reference.spice` uses.
RESISTORS = ("R2A", "R2B", "R1")


def _require(path: Path, what: str) -> Path:
    if not path.is_file():
        raise SystemExit(f"measure_fixed_offset_variants.py: {what} not found: {path}")
    return path


def _run_variant(
    *,
    label: str,
    defer: bool,
    pass_deck: bool,
    gds: Path,
    reference: Path,
    primary_netlist: Path,
    work: Path,
) -> dict[str, Any]:
    from klayout_tools.extract import run_extract  # noqa: PLC0415
    from klayout_tools.lvs import run_lvs  # noqa: PLC0415

    if defer:
        netlist = work / f"{CELL}.extract.deferred.spice"
        # Same arguments the flow's own `klt extract` step uses (deck + top,
        # no --pdk), differing only in the deferral this measurement is about.
        run_extract(
            str(gds),
            DECK,
            output=str(netlist),
            top=CELL,
            apply_resistor_fixed_offset=False,
        )
    else:
        netlist = primary_netlist

    layout: dict[str, Any] = {"netlist": str(netlist), "top": CELL}
    if pass_deck:
        layout["deck"] = DECK
    request = {
        "schema": "klt.lvs.request/1",
        "engine": "klayout",
        "layout": layout,
        "reference": {"netlist": str(reference), "top": REFERENCE_TOP},
        "hints": {"same_nets": []},
        "options": {"combine_devices": True},
    }
    request_path = work / f"lvs.{label}.request.json"
    request_path.write_text(json.dumps(request, indent=2) + "\n")
    report = run_lvs(str(request_path))

    resistors: dict[str, dict[str, float]] = {}
    for mismatch in report.get("mismatches") or []:
        if mismatch.get("category") != "device.property":
            continue
        device = mismatch.get("device") or {}
        name = device.get("reference")
        prop = mismatch.get("property") or {}
        if name in RESISTORS and prop.get("name") == "r":
            resistors[name] = {
                "layout": prop.get("layout"),
                "reference": prop.get("reference"),
            }
    return {
        "variant": label,
        "extraction_fixed_offset": "deferred" if defer else "per_primitive",
        "lvs_layout_deck": DECK if pass_deck else None,
        "status": report.get("status"),
        "mismatch_count": report.get("mismatch_count"),
        "category_counts": report.get("category_counts"),
        "devices_matched": (report.get("counts") or {}).get("devices", {}).get("matched"),
        "nets_matched": (report.get("counts") or {}).get("nets", {}).get("matched"),
        "resistor_r": resistors,
    }


def _render_record(payload: dict[str, Any]) -> str:
    lines = [
        "# `res_high_po` fixed-offset accounting variants",
        "",
        f"- Record ID: `{payload['record_id']}`",
        f"- Source layout record: `{payload['source_record']}`",
        f"- `klt` pin: `{payload['klt_pin']}`",
        f"- Repo state: `{payload['repo_sha']}`",
        "",
        "Generated by `layout/bin/measure_fixed_offset_variants.py`. Reads the",
        "source record's own drawn `.gds` and re-runs `klt lvs` under each of the",
        "four `fixed_offset_ohm` accounting combinations. Nothing here feeds the",
        "routed flow's gate -- this is evidence for *why* the flow keeps the",
        "per-primitive accounting, per DR-003 (issue #98).",
        "",
        "| variant | extraction offset | `layout.deck` | `mismatch_count` | `devices.matched` | R2A/R2B `r` (Ω) | R1 `r` (Ω) |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["variants"]:
        r2 = row["resistor_r"].get("R2A", {}).get("layout")
        r1 = row["resistor_r"].get("R1", {}).get("layout")
        lines.append(
            "| `{v}` | {o} | {d} | **{m}** | {dm} | {r2} | {r1} |".format(
                v=row["variant"],
                o=row["extraction_fixed_offset"],
                d=f"`{row['lvs_layout_deck']}`" if row["lvs_layout_deck"] else "absent",
                m=row["mismatch_count"],
                dm=row["devices_matched"],
                r2="matched" if r2 is None else f"{r2:,.6f}",
                r1="matched" if r1 is None else f"{r1:,.6f}",
            )
        )
    lines += [
        "",
        f"Reference-side values, unchanged across variants: `R2A`/`R2B` = "
        f"{payload['reference_r'].get('R2A')}, `R1` = {payload['reference_r'].get('R1')}.",
        "",
        "## What this measures",
        "",
        "- `primary_nodeck` is the shipped flow's own request shape.",
        "- `primary_deck` double-counts: the extractor already baked the offset",
        "  into every primitive, and `klt lvs` adds it once more post-combine.",
        "- `deferred_nodeck` reports body resistance only (no head/end term).",
        "- `deferred_deck` is klayout-tools#587's intended pairing: defer at",
        "  extraction, apply once per post-combine device.",
        "",
        "## Conclusion recorded by this run",
        "",
        *_conclusion_lines(payload),
        "",
    ]
    return "\n".join(lines)


def _conclusion_lines(payload: dict[str, Any]) -> list[str]:
    """Render the conclusion from THIS run's numbers, not a fixed narrative.

    The measured verdict has changed once already (issue #108's chained-value
    `reference.spice` convention turned "no variant is a lever" into "only the
    shipped variant matches"), so the prose is derived rather than asserted --
    a future re-run that moves the numbers again cannot leave a stale claim
    behind.
    """
    rows = payload["variants"]
    by_label = {row["variant"]: row for row in rows}
    shipped = by_label.get("primary_nodeck", {})
    deferred = by_label.get("deferred_deck", {})
    shipped_n = shipped.get("mismatch_count")
    deferred_n = deferred.get("mismatch_count")
    lines = [
        f"`mismatch_count` is **{payload['mismatch_counts_summary']}** across the four",
        f"variants: the shipped `primary_nodeck` shape reports **{shipped_n}** "
        f"(`devices.matched` = {shipped.get('devices_matched')}), and",
        f"klayout-tools#587's own `deferred_deck` pairing reports **{deferred_n}** "
        f"(`devices.matched` = {deferred.get('devices_matched')}).",
    ]
    if shipped_n is not None and deferred_n is not None:
        if deferred_n > shipped_n:
            lines += [
                "",
                "Adopting the deferral would therefore be a **regression**, not a fix:",
                "`reference.spice` states the CHAINED value (the sum every drawn",
                "primitive in this repo's own decomposition pays -- issue #108,",
                "matching-plan Section 7y), which is exactly what the shipped",
                "per-primitive accounting sums the layout side to. Deferring makes the",
                "layout report the single-device value instead, which no longer agrees",
                "with the reference, so the resistor `device.property` mismatches come",
                "back.",
            ]
        elif deferred_n == shipped_n:
            lines += [
                "",
                "The deferral is not a lever on issue #62's AC4 number: adopting it",
                "would change only *which* resistance `klt lvs` prints.",
            ]
        else:
            lines += [
                "",
                "The deferral REDUCES the mismatch count -- re-read DR-003 (issue #98)",
                "before adopting it: a lower count reached by re-reporting the folded",
                "array at the single-device value would mask the ratified-real head",
                "resistance rather than fix it.",
            ]
    lines += [
        "",
        "Either way the choice is a design question, not a tooling one: DR-003",
        "(issue #98) ratified with independent real-SPICE evidence that this layout",
        "physically pays the head/end term once per separately contacted instance.",
        "See `layout/matching-plan.md` Section 7z.",
    ]
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--record", required=True, type=Path, help="layout record directory to read"
    )
    parser.add_argument(
        "--out-dir", required=True, type=Path, help="where to write the evidence record"
    )
    parser.add_argument("--record-id", default=None)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)

    record = args.record.resolve()
    gds = _require(record / f"{CELL}.gds", "layout GDS")
    reference = _require(record / "reference.spice", "reference netlist")
    primary = _require(record / f"{CELL}.extract.spice", "primary extracted netlist")

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    record_id = args.record_id or out_dir.name

    repo_sha = subprocess.run(
        ["git", "-C", str(args.repo_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    pin_line = ""
    requirements = args.repo_root / "layout" / "requirements.txt"
    if requirements.is_file():
        for line in requirements.read_text().splitlines():
            if line.strip().startswith("klayout-tools @"):
                pin_line = line.strip()

    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="fixed-offset-variants-") as tmp:
        work = Path(tmp)
        for label, defer, pass_deck in VARIANTS:
            print(f"measure_fixed_offset_variants.py: {label} ...", flush=True)
            rows.append(
                _run_variant(
                    label=label,
                    defer=defer,
                    pass_deck=pass_deck,
                    gds=gds,
                    reference=reference,
                    primary_netlist=primary,
                    work=work,
                )
            )

    reference_r: dict[str, Any] = {}
    for row in rows:
        for name, values in row["resistor_r"].items():
            reference_r.setdefault(name, values.get("reference"))

    counts = sorted({row["mismatch_count"] for row in rows})
    summary = str(counts[0]) if len(counts) == 1 else "/".join(str(c) for c in counts)

    payload = {
        "schema_version": 1,
        "harness": "layout/bin/measure_fixed_offset_variants.py",
        "record_id": record_id,
        "source_record": str(record.relative_to(args.repo_root.resolve())),
        "repo_sha": repo_sha,
        "klt_pin": pin_line,
        "cell": CELL,
        "reference_r": reference_r,
        "variants": rows,
        "mismatch_counts_summary": summary,
    }
    (out_dir / "variants.json").write_text(json.dumps(payload, indent=2) + "\n")
    (out_dir / "record.md").write_text(_render_record(payload))
    print(f"measure_fixed_offset_variants.py: wrote {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
