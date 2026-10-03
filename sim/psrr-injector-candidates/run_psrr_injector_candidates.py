#!/usr/bin/env python3
"""Screen candidate FIXES for the startup injector's DC-1 kHz PSRR collapse
against the full 45-corner matrix, on the same body `sim/psrr-injector-attribution/`
attributed the collapse on (issues #306, #315).

What this bench is for
----------------------
`sim/psrr-injector-attribution/` answered *which branch* of
`design/startup_injector.sch` causes the collapse
(`sim/psrr-dc-with-injector/records/20260923-124813-af9ff1e.md`: FAIL 24/45,
`psrr_band_min` 24.78 dB at `ff / 125 degC / 3.63 V` against DR-006's 60 dB
floor). It deliberately only ever *cuts* branches, so it can say what to fix
but never whether a given fix works.

This bench is the other half: it ADDS devices instead of cutting them, so a
candidate circuit change can be measured across the whole 45-corner PSRR
matrix *before* anyone draws it in `design/startup_injector.sch` and pays for
the expensive regression suite (`sim/startup-stability/`, see DR-012 for what
that costs on an x86_64 Linux sweep host). Its variants are therefore
candidates, not controls:

  base           the committed body, unmodified (reproduces the cited record)
  ref3           `MPC1`/`MPC2` extended to a THREE-high diode-connected
                 reference stack (`+ MPC3`, same unit device, series node
                 `GDRV -> NC1 -> NC2 -> NG`), nothing else touched. This is
                 DR-011's candidate 1 and issue #315's item 1.
  ngclamp        `MNG`, a weak (W=1 L=20) NMOS from `NG` to `VSS` gated by
                 `VSENSE`, added to the SHIPPED two-high stack. Pulls `MNI`'s
                 gate to a few mV once the core is running, instead of leaving
                 it pinned at `QS`'s VBE (measured `v(NG)` = `v(NE)` = 0.506 V
                 at `sf / -40 degC / 3.63 V`) where `MNI` still conducts. No
                 existing device is resized.
  ref3_ngclamp   both of the above together.

Why `ngclamp` exists, in one measured line: with `ref3` alone, cutting EITHER
the reference stack OR `MNI` recovers the full bare-core ceiling at
`sf / -40 degC / 3.63 V` (68.5 / 68.3 dB vs 54.6 dB for a 3-high + stacked-`MNI`
body), i.e. the cold-corner residual is the SERIES path
`GDRV -> stack -> NG -> MNI -> VSS`, not either device alone. `NG` cannot fall
below `QS`'s VBE while `MNS` is the only pull-down, so `MNI` never fully turns
off at the cold corners; `MNG` removes exactly that floor. See DR-012 for the
full candidate table, including the ones this bench's variants do not carry
(bulk-to-`GDRV` rewiring, `MNI` cascoding, a four-high stack).

Netlist provenance: the base body is the committed snapshot
`sim/psrr-dc-with-injector/netlist-snapshots/20260923-124813-af9ff1e.spice` --
the exact body the cited record measured -- NOT a fresh xschem netlist of
`design/`. Same reasoning as the attribution bench: a candidate's improvement
is only meaningful against the circuit the FAIL was recorded on, and
re-netlisting after a fix lands would silently screen the fixed design against
itself. Every card this script retargets, clones or inserts next to is
asserted present exactly once before the substitution, and the injector's five
`.param` multiplicity lines are asserted unchanged, so a drifted snapshot
fails loudly instead of screening something else.

What a PASS here does NOT mean: this bench measures PSRR only. A candidate
that passes here is a candidate, not a landable change -- `sim/startup-stability/`
(eviction/traverse margin) and `sim/startup-ramp/` still gate it, and
`sim/psrr-dc-with-injector/` remains the bench that certifies the DR-006 row
once a fix is drawn in the schematic.

**This is not a theoretical caveat.** `ref3_ngclamp` clears DR-006 at 45/45
here, and DR-012 Part 1b then measures `MPC3` -- the half of it that buys the
hot corners -- taking `sim/startup-stability`'s tightest `itrav_min` corner
(`ss, 125 degC, 2.97 V`) from 6.87 nA to 0.65 nA, i.e. BELOW that manifest's
1 nA floor, while `MNG` alone costs 3 %. A PSRR screen can tell you a candidate
is worth certifying; it cannot tell you the candidate is safe.

Exit status: 0 if every check passed, 2 if a record was written but a check
failed, 1 on a harness/setup error (no record written).
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE.parent
REPO_ROOT = SIM_DIR.parent
BUILD_DIR = SIM_DIR / "build" / "psrr-injector-candidates"

sys.path.insert(0, str(SIM_DIR / "bin"))
from sim_common import (  # noqa: E402
    check_pdk_and_ngspice,
    load_base_body as _load_base_body,
    load_corner_run,
    parse_measurements,
    render_pdk_tools_repo_state,
    render_record_id_experiment,
    run_ngspice,
    setup_record_paths,
    write_log,
)

cr = load_corner_run()

SLUG = "psrr-injector-candidates"
SCRIPT = "run_psrr_injector_candidates.py"
TITLE = (
    "Candidate screening: non-resize fixes for the startup injector's DC-1 kHz PSRR "
    "collapse (issues #306, #315)"
)

#: The bench that certifies the DR-006 row, and the record whose FAIL is screened against.
COMPANION = "sim/psrr-dc-with-injector"
CITED_RECORD_ID = "20260923-124813-af9ff1e"
BASE_SNAPSHOT = SIM_DIR / "psrr-dc-with-injector" / "netlist-snapshots" / f"{CITED_RECORD_ID}.spice"
CITED_RECORD_JSON = SIM_DIR / "psrr-dc-with-injector" / "records" / f"{CITED_RECORD_ID}.json"
WRAPPED_SCHEMATIC = "sim/psrr-dc-with-injector/testbench/tb_vref_psrr_injector.sch"

#: Report row 4a -- the bare core, no injector. The ceiling every candidate is
#: read against, taken from its committed record rather than re-measured here.
CEILING_BENCH = "sim/psrr-dc"
CEILING_RECORD_ID = "20260909-232410-e8e2e46"
CEILING_RECORD_JSON = SIM_DIR / "psrr-dc" / "records" / f"{CEILING_RECORD_ID}.json"

#: The companion bench this screening feeds, and the attribution it builds on.
ATTRIBUTION = "sim/psrr-injector-attribution"

#: DR-006's DC-1 kHz band-min floor.
PSRR_FLOOR_DB = 60.0

#: Cards every variant's substitution anchors on. Asserted present exactly once
#: each before anything is rewritten.
TARGET_PREFIXES = ("XMPC1 ", "XMPC2 ", "XMNS ", "XQS ", "XMNI ", "XMNC ", "XSU ")

EXPECTED_PARAMS = {
    ".param m_ref=1",
    ".param m_sense=1",
    ".param m_pnp=8",
    ".param m_inj=1",
    ".param m_clamp=1",
}

#: Byte-identical to `sim/psrr-dc-with-injector/experiment.json`'s measurement
#: expressions and limits (and to the attribution bench's), so every number
#: here is directly comparable to report rows 4a and 4d corner-for-corner.
AC_MEAS = (
    ("psrr_dc", "-db(v(vref)[0])"),
    ("f_dc", "real(frequency[0])"),
    ("psrr_1k", "-db(v(vref)[40])"),
    ("f_1k", "real(frequency[40])"),
    ("psrr_band_min", "minimum(-db(v(vref)[0,40]))"),
    ("psrr_1m", "-db(v(vref)[70])"),
    ("f_1m", "real(frequency[70])"),
    ("n_ac_points", "length(v(vref))"),
)
AC_ANALYSIS = "ac dec 10 0.1 1meg"
DECK_OPTIONS = ("wnflag=1", "reltol=1e-6", "vntol=1e-9", "abstol=1e-15")

#: Operating-point readouts after the AC measurements are printed (an `op`
#: re-points ngspice's current plot). `v_ng` is the mechanism this bench is
#: about: `MNI`'s gate voltage once the core is running.
OP_ALWAYS = (
    ("v_vref", "v(vref)"),
    ("v_gdrv", "v(gdrv)"),
    ("i_vdd", "i(v1)"),
    ("v_ng", "v(xsu.ng)"),
    ("v_ne", "v(xsu.ne)"),
    ("v_nc1", "v(xsu.nc1)"),
)

PROCESSES = ("tt", "ss", "ff", "sf", "fs")
TEMPS_C = (-40.0, 27.0, 125.0)
SUPPLIES_V = (2.97, 3.30, 3.63)

#: The weak `NG` clamp card. `m=1` literal rather than a `mult='m_ngclamp'`
#: knob: this is a netlist-level screen, and the knob is a schematic concern
#: for whoever draws the landed change. Geometry fields follow xschem's own
#: pfet/nfet template scaling off W (ad = as = 0.29*W, pd = ps = 2*(W+0.29),
#: nrd = nrs = 0.29/W) so the card is what a W=1 L=20 instance of this device
#: would netlist as from `design/startup_injector.sch`.
MNG_CARD = (
    "XMNG NG VSENSE VSS VSS sky130_fd_pr__nfet_g5v0d10v5 L=20 W=1 nf=1 "
    "ad=0.29 as=0.29 pd=2.58 ps=2.58 nrd=0.29 nrs=0.29 sa=0 sb=0 sd=0 m=1"
)


# --------------------------------------------------------------------------
# variants
# --------------------------------------------------------------------------


class Edit:
    """One body substitution. Exactly one of the three shapes:

    `retarget`  -- replace the four terminal nodes of the card starting with
                   `anchor`, keeping its device/model/parameter fields.
    `clone`     -- insert a copy of `anchor`'s card after it, renamed `name`
                   and rewired to `nodes` (same device and parameters).
    `insert`    -- insert a literal card after `anchor`'s card.
    """

    def __init__(self, anchor: str, *, retarget=None, clone=None, nodes=None, insert=None,
                 set_line=None):
        self.anchor = anchor
        self.set_line = set_line
        self.retarget = retarget
        self.clone = clone
        self.nodes = nodes
        self.insert = insert


class Variant:
    def __init__(self, name: str, edits: tuple[Edit, ...], what: str = "", costs: str = ""):
        self.name = name
        self.edits = edits
        self.what = what
        self.costs = costs


REF3_EDITS = (
    # MPC2 moves off NG onto a new internal node NC2 ...
    Edit("XMPC2 ", retarget=("NC2", "NC2", "NC1", "VDD")),
    # ... and MPC3, the same unit device, closes GDRV -> NC1 -> NC2 -> NG.
    Edit("XMPC2 ", clone="XMPC3", nodes=("NG", "NG", "NC2", "VDD")),
)
NGCLAMP_EDITS = (Edit("XMNS ", insert=MNG_CARD),)

VARIANTS = (
    Variant(
        "base", (),
        what="the committed body, unmodified",
        costs="none -- reproduces the cited record on this script's own code path",
    ),
    Variant(
        "ref3", REF3_EDITS,
        what="`MPC1`/`MPC2` extended to a three-high diode-connected reference stack "
             "(`+ MPC3`, same W=1 L=20 unit device, series node `GDRV -> NC1 -> NC2 -> NG`)",
        costs="one added device; one more matched device in the layout's reference group "
              "(`klt gen diff_pair` cannot express a three-device group). No resize.",
    ),
    Variant(
        "ngclamp", NGCLAMP_EDITS,
        what="`MNG` (W=1 L=20 NMOS, `NG` -> `VSS`, gate on `VSENSE`) added to the shipped "
             "two-high stack",
        costs="one added device; it draws from `NG` during the startup traverse, so it trades "
              "against `sim/startup-stability`'s `itrav_min` margin. No resize.",
    ),
    Variant(
        "ref3_ngclamp", REF3_EDITS + NGCLAMP_EDITS,
        what="three-high reference stack AND the `MNG` clamp",
        costs="two added devices, no resize; same `itrav_min` trade as `ngclamp`",
    ),
)
def _knob(name: str, anchor: str, value: str, base_edits=NGCLAMP_EDITS) -> Variant:
    return Variant(
        name, base_edits + (Edit(anchor, set_line=f"{anchor}{value}"),),
        what=f"`MNG` clamp with `{anchor}{value}` (a multiplicity/knob change on the shipped two-high body)",
        costs="added `MNG`; knob change trades running conduction against eviction margin",
    )


EXTRA_VARIANTS = (
    _knob("ng_mref0p5", ".param m_ref=", "0.5"),
    _knob("ng_mref0p25", ".param m_ref=", "0.25"),
    _knob("ng_mpnp4", ".param m_pnp=", "4"),
    _knob("ng_mpnp16", ".param m_pnp=", "16"),
)
VARIANTS_BY_NAME = {v.name: v for v in VARIANTS + EXTRA_VARIANTS}

#: The candidate this record is primarily about, and the one whose per-corner
#: DR-006 verdict is a check rather than a reported number.
CANDIDATE = "ref3_ngclamp"
#: Candidates whose insufficiency is itself part of the record's argument.
INSUFFICIENT = ("base", "ref3", "ngclamp")


# --------------------------------------------------------------------------
# base body + substitution
# --------------------------------------------------------------------------


def load_base_body() -> list[str]:
    """Read the cited record's netlist snapshot and assert it is the body this
    script believes it is editing (shared `sim_common.load_base_body()` plus an
    exactly-once check on every anchor card)."""
    lines = _load_base_body(BASE_SNAPSHOT, EXPECTED_PARAMS)
    for prefix in TARGET_PREFIXES:
        n = sum(1 for ln in lines if ln.startswith(prefix))
        if n != 1:
            raise cr.HarnessError(
                f"base snapshot {BASE_SNAPSHOT} has {n} line(s) starting '{prefix}', expected "
                "exactly 1 -- refusing to substitute against a body this script cannot verify"
            )
    return lines


def _split_card(line: str) -> tuple[str, list[str], str]:
    """`NAME n1 n2 n3 n4 <rest>` -> (name, [n1..n4], rest)."""
    parts = line.split()
    if len(parts) < 6:
        raise cr.HarnessError(f"card is not a 4-terminal device line: {line!r}")
    return parts[0], parts[1:5], " ".join(parts[5:])


def _anchor_index(body: list[str], anchor: str, variant_name: str) -> int:
    idx = [i for i, ln in enumerate(body) if ln.startswith(anchor)]
    if len(idx) != 1:
        raise cr.HarnessError(
            f"variant {variant_name}: anchor '{anchor}' matched {len(idx)} line(s), expected 1"
        )
    return idx[0]


def variant_body(base: list[str], variant: Variant) -> list[str]:
    body = list(base)
    for edit in variant.edits:
        i = _anchor_index(body, edit.anchor, variant.name)
        if edit.set_line is not None:
            body[i] = edit.set_line
            continue
        name, _nodes, rest = _split_card(body[i])
        if edit.retarget is not None:
            body[i] = " ".join([name, *edit.retarget, rest])
        elif edit.clone is not None:
            body.insert(i + 1, " ".join([edit.clone, *edit.nodes, rest]))
        elif edit.insert is not None:
            body.insert(i + 1, edit.insert)
        else:  # pragma: no cover -- constructor misuse
            raise cr.HarnessError(f"variant {variant.name}: empty edit on '{edit.anchor}'")
    return body


def build_deck(pdk, variant: Variant, process: str, temp_c: float, supply_v: float,
               body: list[str]) -> str:
    head = [
        f"* {SLUG} deck -- generated by sim/{SLUG}/{SCRIPT}, do not edit",
        f"* variant: {variant.name} ({variant.what})",
        f"* corner: {corner_id(process, temp_c, supply_v)}",
        f".param vsup={supply_v}",
    ]
    head += [f".option {opt}" for opt in DECK_OPTIONS]
    head += [f".temp {cr.fmt_temp(temp_c)}", f'.lib "{pdk.lib_file}" {process}']

    ctrl = [".control", "save all", AC_ANALYSIS]
    ctrl += [f"let meas_{n} = {e}" for n, e in AC_MEAS]
    ctrl += [f"print meas_{n}" for n, _ in AC_MEAS]
    ctrl += ["op"]
    ctrl += [f"let meas_{n} = {e}" for n, e in OP_ALWAYS]
    ctrl += [f"print meas_{n}" for n, _ in OP_ALWAYS]
    ctrl += ["quit", ".endc", ".end", ""]
    return "\n".join(head + body + ctrl)


def corner_id(process: str, temp_c: float, supply_v: float) -> str:
    return f"{process}_{cr.fmt_temp(temp_c)}c_{supply_v:.2f}v"


def matrix() -> list[tuple[str, float, float]]:
    return [(p, t, s) for p in PROCESSES for t in TEMPS_C for s in SUPPLIES_V]


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------


def run_point(pdk, base_body, variant: Variant, process, temp_c, supply_v, timeout,
              corners_dir: Path | None, record_id: str) -> dict:
    cid = corner_id(process, temp_c, supply_v)
    name = f"{variant.name}__{cid}"
    deck = build_deck(pdk, variant, process, temp_c, supply_v, variant_body(base_body, variant))
    run_dir = BUILD_DIR / record_id / name
    stamp = datetime.now(timezone.utc)
    raw, rc, timed_out = run_ngspice(run_dir, name, deck, timeout)
    if corners_dir is not None:
        write_log(corners_dir, name, record_id, pdk, stamp, deck, raw, rc, timed_out)
    return {
        "variant": variant.name, "corner_id": cid, "process": process,
        "temperature_c": temp_c, "supply_v": supply_v,
        "ngspice_exit": rc, "timed_out": timed_out,
        "measurements": parse_measurements(raw),
    }


def run_all(pdk, base_body, variants, points, timeout, jobs, corners_dir, record_id) -> dict:
    work = [(v, p, t, s) for v in variants for (p, t, s) in points]
    total = len(work)
    results: dict[tuple[str, str], dict] = {}
    done = 0

    def task(item):
        v, p, t, s = item
        return run_point(pdk, base_body, v, p, t, s, timeout, corners_dir, record_id)

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for res in pool.map(task, work):
            done += 1
            band = res["measurements"].get("psrr_band_min")
            print(f"[{done:3d}/{total}] {res['variant']:13s} {res['corner_id']:16s} "
                  + (f"psrr_band_min={band:8.3f} dB" if band is not None
                     else f"NO MEASUREMENT (rc={res['ngspice_exit']}, "
                          f"timeout={res['timed_out']})"),
                  flush=True)
            results[(res["variant"], res["corner_id"])] = res
    return results


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------

#: `base` must land within this of the cited record's own per-corner
#: `psrr_band_min` -- "same circuit, same answer", not "byte-identical deck".
REPRO_TOL_DB = 0.5
#: How close the candidate must come to row 4a's bare-core ceiling.
CEILING_TOL_DB = 2.0
#: How low `MNG` must hold `NG` (`MNI`'s gate) once the core is running. A few
#: tens of mV is "off" for a device whose threshold is several hundred mV; the
#: bound is deliberately loose because the POINT is the order of magnitude, not
#: a precise voltage.
NG_OFF_V = 0.05


def _band_min_by_corner(path: Path, label: str) -> dict[str, float]:
    if not path.is_file():
        raise cr.HarnessError(f"missing {label}: {path}")
    rec = json.loads(path.read_text())
    out = {}
    for c in rec["corners"]:
        for m in c["measurements"]:
            if m["name"] == "psrr_band_min" and m.get("value") is not None:
                out[c["corner_id"]] = float(m["value"])
    if not out:
        raise cr.HarnessError(f"{path} carries no psrr_band_min values")
    return out


def cited_band_min() -> dict[str, float]:
    return _band_min_by_corner(CITED_RECORD_JSON, "cited record json")


def ceiling_band_min() -> dict[str, float]:
    return _band_min_by_corner(CEILING_RECORD_JSON, "row 4a ceiling record json")


def evaluate(results, points, variants) -> list[dict]:
    checks: list[dict] = []
    names = {v.name for v in variants}

    def add(name, ok, detail):
        checks.append({"name": name, "pass": bool(ok), "detail": detail})

    def band(variant, cid):
        res = results.get((variant, cid))
        return None if res is None else res["measurements"].get("psrr_band_min")

    cited = cited_band_min()
    ceiling = ceiling_band_min()
    cids = [corner_id(p, t, s) for p, t, s in points]

    # 0. Every point produced a usable, guard-clean measurement.
    for (v, cid), res in sorted(results.items()):
        m = res["measurements"]
        need = [n for n, _ in AC_MEAS if n != "psrr_1m"]
        have = all(n in m for n in need)
        guards_ok = (
            have
            and m["n_ac_points"] == 71
            and 0.09 <= m["f_dc"] <= 0.11
            and 900.0 <= m["f_1k"] <= 1100.0
            and 900000.0 <= m["f_1m"] <= 1100000.0
        )
        add(f"sweep_guards[{v}/{cid}]", guards_ok,
            (f"n_ac_points={m.get('n_ac_points')} f_dc={m.get('f_dc')} f_1k={m.get('f_1k')} "
             f"f_1m={m.get('f_1m')} (expect 71 / 0.1 Hz / 1 kHz / 1 MHz)") if have
            else f"no usable measurement (rc={res['ngspice_exit']}, timeout={res['timed_out']})")

    # 1. `base` reproduces the record the candidates are screened against. If
    #    this fails, nothing below is comparable to row 4d.
    if "base" in names:
        for cid in cids:
            b, c = band("base", cid), cited.get(cid)
            ok = b is not None and c is not None and abs(b - c) <= REPRO_TOL_DB
            add(f"base_reproduces_cited_record[{cid}]", ok,
                f"base psrr_band_min={b if b is None else round(b, 3)} dB vs "
                f"{COMPANION}/records/{CITED_RECORD_ID} {c if c is None else round(c, 3)} dB "
                f"(tolerance {REPRO_TOL_DB} dB)")

    # 2. THE CANDIDATE CLAIM: `ref3_ngclamp` clears DR-006's floor everywhere.
    if CANDIDATE in names:
        for cid in cids:
            x = band(CANDIDATE, cid)
            add(f"candidate_clears_floor[{cid}]", x is not None and x >= PSRR_FLOOR_DB,
                f"`{CANDIDATE}` psrr_band_min={x if x is None else round(x, 3)} dB vs "
                f">= {PSRR_FLOOR_DB} dB (DR-006)")

        # 3. ... and leaves no large residual against row 4a's bare-core ceiling.
        for cid in cids:
            x, c = band(CANDIDATE, cid), ceiling.get(cid)
            ok = None not in (x, c) and (c - x) <= CEILING_TOL_DB
            add(f"candidate_within_bare_core_ceiling[{cid}]", ok,
                f"{CEILING_BENCH} row 4a {None if c is None else round(c, 3)} dB - "
                f"`{CANDIDATE}` {None if x is None else round(x, 3)} dB = "
                f"{None if None in (x, c) else round(c - x, 3)} dB "
                f"(must be <= {CEILING_TOL_DB} dB)")

    # 4. Evidence guard, not a defect: each lesser candidate must still FAIL
    #    somewhere, which is why the landed fix needs both devices. If a future
    #    PDK/design change makes one of them sufficient, this fires and says the
    #    record's rationale is stale rather than letting it quietly rot.
    for v in INSUFFICIENT:
        if v not in names:
            continue
        vals = [(band(v, cid), cid) for cid in cids]
        vals = [(x, c) for x, c in vals if x is not None]
        worst = min(vals) if vals else (None, "n/a")
        n_fail = sum(1 for x, _ in vals if x < PSRR_FLOOR_DB)
        add(f"{v}_still_fails_somewhere", n_fail > 0,
            f"`{v}` FAILs {n_fail}/{len(vals)} corners, worst "
            f"{'n/a' if worst[0] is None else round(worst[0], 3)} dB at `{worst[1]}` "
            f"(this record's argument for the extra device(s) depends on this being > 0)")

    # 5. MECHANISM: `MNG` is doing what it was added to do -- collapsing `NG`,
    #    i.e. turning `MNI` off, rather than improving PSRR by some other route.
    if CANDIDATE in names and "ref3" in names:
        for cid in cids:
            a = results.get((CANDIDATE, cid), {}).get("measurements", {}).get("v_ng")
            b = results.get(("ref3", cid), {}).get("measurements", {}).get("v_ng")
            ok = None not in (a, b) and a <= NG_OFF_V and a < b
            add(f"ng_clamp_holds_mni_off[{cid}]", ok,
                f"v(NG) ref3={None if b is None else round(b, 4)} V -> "
                f"`{CANDIDATE}`={None if a is None else round(a, 4)} V "
                f"(must be <= {NG_OFF_V} V and below `ref3`'s)")

    return checks


# --------------------------------------------------------------------------
# record
# --------------------------------------------------------------------------


def render_record(r: dict) -> str:
    L: list[str] = []

    def add(line: str = ""):
        L.append(line)

    results = r["_results"]
    points = r["_points"]
    cids = [corner_id(*p) for p in points]
    cited = r["cited"]
    ceiling = r["ceiling"]
    shown = [v for v in VARIANTS if v.name in r["variants"]]

    def band(v, cid):
        res = results.get((v, cid))
        return None if res is None else res["measurements"].get("psrr_band_min")

    add(f"# Record {r['record_id']}")
    add("")
    L.extend(render_record_id_experiment(r["record_id"], SLUG, TITLE))
    add(
        "- **Claim**: issues #306/#315 -- measure, across the full 45-corner matrix, whether a "
        "NON-RESIZE candidate change to `design/startup_injector.sch` clears DR-006's "
        f"{PSRR_FLOOR_DB:g} dB DC-1 kHz `psrr_band_min` floor on the exact body "
        f"`{COMPANION}/records/{CITED_RECORD_ID}.md` records FAILing 24/45 (worst 24.78 dB at "
        "`ff / 125 degC / 3.63 V`). The attribution this builds on "
        f"(`{ATTRIBUTION}/`) cuts branches and so can only say what to fix; this record adds "
        "devices and says whether the fix works. It is a PSRR screen, NOT a spec verdict: "
        "`sim/startup-stability/` (eviction/traverse margin) and `sim/startup-ramp/` still gate "
        f"any landed change, and `{COMPANION}` remains the bench that certifies the row."
    )
    add(
        "- **Netlist provenance**: the base body is the committed netlist snapshot "
        f"`{BASE_SNAPSHOT.relative_to(REPO_ROOT)}` -- the exact body the cited record measured, "
        f"wrapping `{WRAPPED_SCHEMATIC}` -- NOT a fresh xschem netlist of `design/`. Each "
        "anchor card is asserted present exactly once and the injector's five `.param` "
        "multiplicity lines asserted unchanged before any substitution."
    )
    L.extend(render_pdk_tools_repo_state(r))
    add(
        f"- **Corner matrix**: the full 45-point PVT matrix (process {', '.join(PROCESSES)} x "
        f"temperature {', '.join(f'{t:g}' for t in TEMPS_C)} degC x supply "
        f"{', '.join(f'{s:.2f}' for s in SUPPLIES_V)} V) for each of the {len(shown)} "
        f"variants -- {len(points) * len(shown)} ngspice points. Measurement expressions, "
        f"limits, solver options and the `{AC_ANALYSIS}` sweep are byte-identical to "
        f"`{COMPANION}/experiment.json`'s, so every number is directly comparable to report "
        "rows 4a and 4d corner-for-corner."
    )
    add("- **Statistical convention**: N/A (deterministic corner-matrix screen).")
    add("")

    add("## Candidates -- what each body adds, and what it costs")
    add("")
    add("| variant | substitution | cost |")
    add("|---|---|---|")
    for v in shown:
        add(f"| `{v.name}` | {v.what} | {v.costs} |")
    add("")
    add(
        "No existing device is resized in any variant: every `W`/`L`/`mult` in the body is the "
        "shipped value. That is deliberate -- DR-011 closed the resize-only path empirically "
        "(every `MNI` resize that cleared PSRR either broke the `sim/startup-stability` DC "
        "sweep's convergence or eroded its `itrav_min` floor below the ratified minimum)."
    )
    add("")

    add("## Result -- `psrr_band_min` (dB) per corner, per candidate")
    add("")
    header = "| corner | row 4a ceiling | cited record |" + "".join(
        f" `{v.name}` |" for v in shown)
    add(header)
    add("|---" * (3 + len(shown)) + "|")
    for cid in cids:
        def cell(v):
            x = band(v, cid)
            if x is None:
                return "**n/a**"
            s = f"{x:.2f}"
            return s if x >= PSRR_FLOOR_DB else f"**{s}**"
        c4a = ceiling.get(cid)
        c = cited.get(cid)
        add(f"| `{cid}` | {'n/a' if c4a is None else f'{c4a:.2f}'} | "
            f"{'n/a' if c is None else f'{c:.2f}'} |"
            + "".join(f" {cell(v.name)} |" for v in shown))
    add("")
    add(
        f"**Bold** = below DR-006's {PSRR_FLOOR_DB:g} dB floor. `row 4a ceiling` is the bare "
        f"core without the injector, `{CEILING_BENCH}/records/{CEILING_RECORD_ID}.json`, and "
        f"`cited record` is `{COMPANION}/records/{CITED_RECORD_ID}.json`; both are quoted from "
        "their committed records, not re-measured here."
    )
    add("")

    add("## Summary per candidate")
    add("")
    add("| variant | worst corner | worst `psrr_band_min` | corners >= 60 dB |")
    add("|---|---|---|---|")
    for v in shown:
        vals = [(band(v.name, cid), cid) for cid in cids]
        vals = [(x, c) for x, c in vals if x is not None]
        if not vals:
            add(f"| `{v.name}` | n/a | n/a | n/a |")
            continue
        worst, wcid = min(vals)
        n_pass = sum(1 for x, _ in vals if x >= PSRR_FLOOR_DB)
        add(f"| `{v.name}` | `{wcid}` | {worst:.2f} dB | {n_pass}/{len(vals)} |")
    add("")

    add("## Mechanism -- the operating point at the two binding corners")
    add("")
    add("| corner | variant | v(VREF) | v(GDRV) | v(NG) | v(NE) | v(NC1) | i(VDD) |")
    add("|---|---|---|---|---|---|---|---|")
    base_worst = min(((band("base", cid) or 1e9, cid) for cid in cids))[1]
    cand_name = CANDIDATE if CANDIDATE in r["variants"] else shown[-1].name
    ref3_worst = min(((band("ref3", cid) or 1e9, cid) for cid in cids))[1] \
        if "ref3" in r["variants"] else base_worst
    for cid in dict.fromkeys((base_worst, ref3_worst)):
        for v in shown:
            m = results[(v.name, cid)]["measurements"]

            def f(k, scale=1.0, unit=""):
                return "—" if k not in m else f"{m[k] * scale:.4f}{unit}"
            add(f"| `{cid}` | `{v.name}` | {f('v_vref')} | {f('v_gdrv')} | {f('v_ng')} | "
                f"{f('v_ne')} | {f('v_nc1')} | {f('i_vdd', 1e6, ' µA')} |")
    add("")
    add(
        f"`{base_worst}` is `base`'s binding corner and `{ref3_worst}` is `ref3`'s -- they are "
        "different corners, which is the whole reason a stack-height-only fix is not enough: "
        "extending the reference stack closes the hot-corner failure and uncovers a cold-corner "
        "residual. `v(NG)` is why: with `MNS` over the diode-connected `QS` as the only "
        "pull-down, `NG` cannot fall below that stack's own floor (read `v(NE)` in the same "
        "row), so `MNI` -- gate on `NG`, drain on GDRV -- never fully turns off, and the "
        "residual is the SERIES path `GDRV -> stack -> NG -> MNI -> VSS` rather than either "
        f"device alone. `MNG` in `{cand_name}` removes that floor, and `v(NG)` collapsing to a "
        "few mV is the measured signature of it."
    )
    add("")

    add("## Checks")
    add("")
    add("| check | verdict | detail |")
    add("|---|---|---|")
    for c in r["checks"]:
        add(f"| `{c['name']}` | {'PASS' if c['pass'] else '**FAIL**'} | {c['detail']} |")
    add("")
    add(f"**Overall: {'PASS' if r['overall_pass'] else 'FAIL'}**")
    add("")
    add(
        "A PASS here means one thing only: on this body, at every one of the 45 corners, the "
        f"`{CANDIDATE}` candidate's DC-1 kHz PSRR clears DR-006's floor and sits within "
        f"{CEILING_TOL_DB:g} dB of the bare core's own ceiling. It says nothing about startup "
        "margin, and it is not a report-row verdict: landing the change means drawing it in "
        f"`design/startup_injector.sch`, re-running `{COMPANION}` from the schematic, and "
        "re-running `sim/startup-stability/` + `sim/startup-ramp/` for the regression. See "
        "DR-012 for what that regression costs on an x86_64 Linux sweep host."
    )
    add("")
    add("")
    add(
        f"Written by `sim/{SLUG}/{SCRIPT}`. Append-only: never edit this file -- a correction "
        "is a new record with a `Supersedes` field (see `sim/README.md`)."
    )
    add("")
    return "\n".join(L)


# --------------------------------------------------------------------------
# modes
# --------------------------------------------------------------------------


def explore(args) -> int:
    pin = cr.load_pin()
    pdk = check_pdk_and_ngspice(pin, args.allow_pdk_mismatch, verbose=False)
    base_body = load_base_body()
    variants = [VARIANTS_BY_NAME[n] for n in args.variants]
    points = [tuple(pt.split(",")) for pt in args.corners.split(";")]
    points = [(p, float(t), float(s)) for p, t, s in points]
    print(f"PDK: {pdk.dir} (open_pdks {pdk.installed_commit})")
    print(f"base body: {BASE_SNAPSHOT.relative_to(REPO_ROOT)}")
    print("(explore mode: nothing is written under sim/<experiment>/)")
    results = run_all(pdk, base_body, variants, points, args.timeout, args.jobs, None, "explore")
    print()
    for (v, cid), res in sorted(results.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        m = res["measurements"]
        print(f"  {cid:16s} {v:13s} band_min={m.get('psrr_band_min', float('nan')):8.3f} "
              f"dc={m.get('psrr_dc', float('nan')):8.3f} "
              f"vref={m.get('v_vref', float('nan')):.5f} ng={m.get('v_ng', float('nan')):.4f}")
    return 0


def verify(args) -> int:
    pin = cr.load_pin()
    pdk = check_pdk_and_ngspice(pin, args.allow_pdk_mismatch, verbose=False)
    base_body = load_base_body()
    cited = cited_band_min()
    ceiling = ceiling_band_min()

    git_info = cr.git_state()
    now = datetime.now(timezone.utc)
    record_id = f"{now:%Y%m%d}-{now:%H%M%S}-{git_info['sha']}"
    records_dir, _, corners_dir, record_md, record_json, _ = setup_record_paths(
        HERE, record_id, with_snapshot=False
    )

    points = matrix()
    variants = [VARIANTS_BY_NAME[n] for n in args.variants]
    print(f"experiment    : {SLUG}")
    print(f"record id     : {record_id}")
    print(f"PDK           : {pdk.dir} (open_pdks {pdk.installed_commit})")
    print(f"base body     : {BASE_SNAPSHOT.relative_to(REPO_ROOT)}")
    print(f"points        : {len(points)} corners x {len(variants)} variants "
          f"= {len(points) * len(variants)} ngspice runs (jobs={args.jobs})")

    results = run_all(pdk, base_body, variants, points, args.timeout, args.jobs,
                      corners_dir, record_id)
    checks = evaluate(results, points, variants)
    overall = all(c["pass"] for c in checks)

    record = {
        "record_id": record_id,
        "timestamp": now.isoformat(),
        "author": args.author or cr.default_author(),
        "experiment": {
            "slug": SLUG, "title": TITLE,
            "provenance": "schematic",
            "provenance_source": str(BASE_SNAPSHOT.relative_to(REPO_ROOT)),
            "wrapped_schematic": WRAPPED_SCHEMATIC,
            "statistical_convention": "N/A (deterministic corner-matrix screen)",
        },
        "pdk": {
            "family": pin["family"], "variant": pdk.variant, "dir": str(pdk.dir),
            "installed_commit": pdk.installed_commit,
            "pinned_commit": pin["open_pdks_commit"],
            "matches_pin": pdk.matches_pin,
            "lib_file": str(pdk.lib_file),
        },
        "tools": cr.tool_versions(),
        "git": git_info,
        "matrix": {
            "process": list(PROCESSES), "temperature_c": list(TEMPS_C),
            "supply_v": list(SUPPLIES_V), "is_subset": False,
        },
        "variants": [v.name for v in variants],
        "cited_record": f"{COMPANION}/records/{CITED_RECORD_ID}.md",
        "cited": cited,
        "ceiling_record": f"{CEILING_BENCH}/records/{CEILING_RECORD_ID}.md",
        "ceiling": ceiling,
        "jobs": args.jobs,
        "points": [dict(res) for _, res in sorted(results.items())],
        "checks": checks,
        "overall_pass": overall,
        "links": {
            "base_snapshot": str(BASE_SNAPSHOT.relative_to(REPO_ROOT)),
            "cited_record": f"{COMPANION}/records/{CITED_RECORD_ID}.json",
            "ceiling_record": f"{CEILING_BENCH}/records/{CEILING_RECORD_ID}.json",
            "attribution": f"{ATTRIBUTION}/",
            "companion_manifest": f"{COMPANION}/experiment.json",
            "runner": f"sim/{SLUG}/{SCRIPT}",
        },
        "_results": results,
        "_points": points,
    }

    records_dir.mkdir(parents=True, exist_ok=True)
    record_md.write_text(render_record(record))
    record_json.write_text(json.dumps(
        {k: v for k, v in record.items() if not k.startswith("_")}, indent=2) + "\n")
    print(f"\nrecord: {record_md.relative_to(REPO_ROOT)}")
    print(f"Overall: {'PASS' if overall else 'FAIL'}")
    for c in checks:
        if not c["pass"]:
            print(f"  FAIL {c['name']}: {c['detail']}")
    return 0 if overall else 2


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--explore", action="store_true",
                   help="run selected variants/corners, print results, write NOTHING under sim/")
    p.add_argument("--variants", default=",".join(v.name for v in VARIANTS),
                   type=lambda s: [x.strip() for x in s.split(",") if x.strip()],
                   help="comma-separated variant names (default: all)")
    p.add_argument("--corners", default="ff,125,3.63",
                   help="explore mode only: semicolon-separated process,temp,supply triples")
    p.add_argument("--jobs", type=int, default=2,
                   help="concurrent ngspice processes (default 2 -- these hosts are shared)")
    p.add_argument("--timeout", type=int, default=1800, help="per-point ngspice timeout (s)")
    p.add_argument("--author", default="", help="record author (default: git user.email)")
    p.add_argument("--allow-pdk-mismatch", action="store_true",
                   help="run even if the installed PDK differs from the sim/pdk.json pin")
    args = p.parse_args(argv)
    unknown = [v for v in args.variants if v not in VARIANTS_BY_NAME]
    if unknown:
        p.error(f"unknown variant(s) {unknown}; known: {sorted(VARIANTS_BY_NAME)}")
    if args.jobs < 1:
        p.error("--jobs must be >= 1")
    return args


def main(argv) -> int:
    args = parse_args(argv)
    return explore(args) if args.explore else verify(args)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except cr.HarnessError as err:
        print(f"{SCRIPT}: error: {err}", file=sys.stderr)
        sys.exit(1)
