#!/usr/bin/env python3
"""Gate + render one `layout/bandgap-core/erc/<record-id>/` evidence record.

Invoked by ``layout/bin/run-erc-supply-flow.sh`` after the ``klt erc`` runs
have written their JSON into the record directory. Keeps the pass/fail logic
in one place so the committed ``record.md`` cannot disagree with the committed
JSON it summarises.

The gate is T1 item 11's own pass condition, which is deliberately **not** the
report's overall ``status``:

* every declared supply resolves to exactly one electrical island -- no
  ``erc.unconnected_net`` and no ``erc.supply_short`` naming it;
* both supplies appear in ``erc_coverage.checked`` (the check actually ran);
* the report's ``provenance.input.content_hash`` equals the sha256 of the GDS
  it names, so the report cannot drift from the layout it claims to describe.

The supply spec's two n-well ``ties[]`` entries are gated too (``gate_tie_report``)
and the swapped-net negative control is gated the other way round
(``gate_negative_control``) -- see ``layout/bandgap-core/erc/README.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

SUPPLIES = ("VDD", "VSS")
TIES = ("nwell_tie_vdd", "nwell_tie_vss")


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def gate_supply_report(report: dict, gds: pathlib.Path) -> tuple[bool, list[str]]:
    """Return (ok, reasons). ``reasons`` lists every gate failure, not just the first."""
    reasons: list[str] = []

    declared = sha256_file(gds)
    got = ((report.get("provenance") or {}).get("input") or {}).get("content_hash")
    if got != f"sha256:{declared}":
        reasons.append(
            f"provenance.input.content_hash {got!r} does not match sha256 of {gds.name} "
            f"(sha256:{declared})"
        )

    checked = set((report.get("erc_coverage") or {}).get("checked") or [])
    for net in SUPPLIES:
        if f'erc.net_connectivity:["{net}"]' not in checked:
            reasons.append(f"erc.net_connectivity for {net} is not in erc_coverage.checked")

    for finding in report.get("erc_findings") or []:
        rule = finding.get("rule")
        if rule not in ("erc.unconnected_net", "erc.supply_short"):
            continue
        named = {finding.get("net"), finding.get("other_net")} & set(SUPPLIES)
        if named:
            reasons.append(f"{rule} names {sorted(named)}: {finding.get('description')}")

    return (not reasons), reasons


def gate_tie_report(report: dict) -> tuple[bool, list[str]]:
    """Gate the supply spec's n-well ``ties[]``: computed, not skipped, zero findings.

    ``erc.missing_tie`` reports zero both when every well is tied and when the
    rule never ran (empty ``ties[]``) or a tie was skipped as a degenerate
    selection, so the gate demands the evidence that it ran: each tie in
    ``erc_coverage.checked``, nothing in ``skipped``, no ``ties_disclosure``.
    """
    reasons: list[str] = []
    cov = report.get("erc_coverage") or {}
    checked = set(cov.get("checked") or [])
    for tie in TIES:
        if f'erc.missing_tie:["{tie}"]' not in checked:
            reasons.append(f"erc.missing_tie for {tie} is not in erc_coverage.checked")
    if cov.get("skipped"):
        reasons.append(f"erc_coverage.skipped is not empty: {cov['skipped']}")
    if report.get("ties_disclosure"):
        reasons.append("report still carries a ties_disclosure")
    for finding in report.get("erc_findings") or []:
        if finding.get("rule") == "erc.missing_tie":
            reasons.append(f"erc.missing_tie: {finding.get('description')}")
    return (not reasons), reasons


def gate_negative_control(report: dict, well_shapes: int) -> tuple[bool, list[str]]:
    """The swapped-net control must flag every n-well shape, or the clean result proves nothing."""
    reasons: list[str] = []
    n = sum(1 for f in report.get("erc_findings") or [] if f.get("rule") == "erc.missing_tie")
    if n != well_shapes:
        reasons.append(f"negative control reported {n} erc.missing_tie, expected {well_shapes}")
    return (not reasons), reasons


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--record-id", required=True)
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--klt", required=True)
    ap.add_argument("--gds-records", nargs="+", required=True)
    ap.add_argument("--newest", required=True)
    args = ap.parse_args()

    out_dir = pathlib.Path(args.out_dir)
    repo_root = pathlib.Path(args.repo_root)
    cell_dir = repo_root / "layout" / "bandgap-core"

    lines: list[str] = []
    overall_ok = True

    lines.append(f"# `klt erc` supply record — `{args.record_id}`")
    lines.append("")
    lines.append(
        "T1 item 11 (power delivery, **structural**) evidence for `bandgap-core`. "
        "Generated by `layout/bin/run-erc-supply-flow.sh`; do not hand-edit — "
        "re-run the flow to append a new record. Read "
        "[`../README.md`](../README.md) first for what this does and does not "
        "establish."
    )
    lines.append("")

    # --- supply runs -------------------------------------------------------
    lines.append("## Supply-spec runs (`erc-supply-spec.json`)")
    lines.append("")
    lines.append(
        "| routed GDS | GDS sha256 | report `provenance.input.content_hash` | "
        "supplies checked | `erc.unconnected_net` / `erc.supply_short` on a supply | "
        "n-well ties checked / `erc.missing_tie` | gate |"
    )
    lines.append("|---|---|---|---|---|---|---|")

    supply_reports: dict[str, dict] = {}
    for rec in args.gds_records:
        report_path = out_dir / f"erc.{rec}.json"
        report = json.loads(report_path.read_text())
        supply_reports[rec] = report
        gds = cell_dir / "reports" / rec / "bandgap_core_routed.gds"
        ok, reasons = gate_supply_report(report, gds)
        tie_ok, tie_reasons = gate_tie_report(report)
        ok = ok and tie_ok
        reasons = reasons + tie_reasons
        overall_ok = overall_ok and ok
        checked = set((report.get("erc_coverage") or {}).get("checked") or [])
        n_checked = sum(
            1 for net in SUPPLIES if f'erc.net_connectivity:["{net}"]' in checked
        )
        offending = [
            f
            for f in (report.get("erc_findings") or [])
            if f.get("rule") in ("erc.unconnected_net", "erc.supply_short")
            and ({f.get("net"), f.get("other_net")} & set(SUPPLIES))
        ]
        n_ties = sum(
            1 for t in TIES if f'erc.missing_tie:["{t}"]' in checked
        )
        n_missing = sum(
            1 for f in report.get("erc_findings") or [] if f.get("rule") == "erc.missing_tie"
        )
        lines.append(
            f"| `{rec}` | `{sha256_file(gds)[:16]}…` | "
            f"`{((report.get('provenance') or {}).get('input') or {}).get('content_hash', '')[7:23]}…` | "
            f"{n_checked}/2 (VDD, VSS) | **{len(offending)}** | "
            f"{n_ties}/2 / **{n_missing}** | "
            f"{'**PASS**' if ok else '**FAIL**'} |"
        )
        if not ok:
            for r in reasons:
                lines.append(f"| | | | | | | {r} |")

    lines.append("")
    newest_report = supply_reports[args.newest]
    cov = newest_report.get("erc_coverage") or {}
    inapplicable = {e["id"]: e["reason"] for e in cov.get("inapplicable") or []}
    lines.append(
        f"Newest GDS (`{args.newest}`): `erc_status` "
        f"`{newest_report.get('erc_status')}`, `erc_finding_count` "
        f"{newest_report.get('erc_finding_count')}, overall `status` "
        f"`{newest_report.get('status')}`, produced by "
        f"`klt {(newest_report.get('provenance') or {}).get('klt_version')}` / "
        f"KLayout `{(newest_report.get('provenance') or {}).get('klayout_version')}`."
    )
    lines.append("")
    lines.append(
        "**`erc.missing_tie` is computed.** The spec declares two n-well `ties[]` "
        "entries (`nwell_tie_vdd`, `nwell_tie_vss`), each in `erc_coverage.checked` "
        "(and in `checked_by_well_assertion`, because the well-class selection is "
        "the caller's `well_requires_boxes`), with `erc_coverage.skipped` empty and "
        "no `ties_disclosure`. Zero findings is therefore a result, not an absence; "
        "the negative control below shows the declaration can fail."
    )
    lines.append("")

    # --- antenna (reported, not gated) -------------------------------------
    lines.append("## Antenna / gate accumulation (reported, not this item's subject)")
    lines.append("")
    lines.append(
        "Reported here because the same run produces it. An antenna verdict is "
        "not item 11's subject and does not gate this record "
        "([klayout-tools#1994](https://github.com/2AMLogic/klayout-tools/issues/1994))."
    )
    lines.append("")
    lines.append("| gate net | `gate_area_um2` (poly ∩ diff) | `antenna_verdict` |")
    lines.append("|---|---|---|")
    for g in newest_report.get("gates") or []:
        lines.append(
            f"| `{g.get('net')}` | {g.get('gate_area_um2')} | `{g.get('antenna_verdict')}` |"
        )
    devices = (newest_report.get("provenance") or {}).get("devices") or []
    lines.append("")
    if devices:
        lines.append("Device bodies carved out of the conductor roles by `--deck sky130`:")
        lines.append("")
        for d in devices:
            lines.append(
                f"- `{d.get('name')}` on role `{d.get('on')}` "
                f"(`body_layer` {d.get('body_layer')}), "
                f"{d.get('body_area_um2')} µm², source `{d.get('source')}`"
            )
        lines.append("")

    # --- negative control --------------------------------------------------
    spec = json.loads((cell_dir / "erc-supply-spec.json").read_text())
    well_shapes = sum(len(t.get("well_requires_boxes") or []) for t in spec.get("ties") or [])
    lines.append("## Negative control (swapped tie nets)")
    lines.append("")
    lines.append(
        "`erc-nwell-tie-spec.negative-control.json` is the supply spec with each "
        "tie's well boxes declared to the **opposite** net. Run against "
        f"`{args.newest}`, a tie check that works must flag every n-well shape; "
        "if this run came back clean, the clean tie result above would prove nothing."
    )
    lines.append("")
    nc_path = out_dir / f"erc.negative-control-nwell-swapped.{args.newest}.json"
    nc = json.loads(nc_path.read_text())
    nc_ok, nc_reasons = gate_negative_control(nc, well_shapes)
    overall_ok = overall_ok and nc_ok
    miss = [f for f in nc.get("erc_findings") or [] if f["rule"] == "erc.missing_tie"]
    shorts = [f for f in nc.get("erc_findings") or [] if f["rule"] == "erc.supply_short"]
    lines.append("| declared net | `erc.missing_tie` |")
    lines.append("|---|---|")
    for net in SUPPLIES:
        lines.append(f"| `{net}` | {sum(1 for f in miss if f.get('net') == net)} |")
    lines.append("")
    lines.append(
        f"Total `erc.missing_tie`: **{len(miss)}** of {well_shapes} n-well shapes "
        f"(`erc.supply_short`: {len(shorts)}) -- "
        f"{'**PASS**' if nc_ok else '**FAIL**: ' + '; '.join(nc_reasons)}."
    )
    lines.append("")

    lines.append("## Verdict")
    lines.append("")
    lines.append(f"**{'PASS' if overall_ok else 'FAIL'}** — item 11's structural gate.")
    lines.append("")
    lines.append(
        "Item 11's structural half: supply islands and n-well ties, both computed, "
        "with a negative control. The machine-graded verdict of record is "
        "`signoff/signoff-report.json` (see `signoff/README.md`), which also grades "
        "the LVS half. See [`../README.md`](../README.md)."
    )
    lines.append("")

    (out_dir / "record.md").write_text("\n".join(lines) + "\n")
    print(f"erc_supply_record.py: wrote {out_dir / 'record.md'}")
    if not overall_ok:
        print("erc_supply_record.py: GATE FAILED", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
