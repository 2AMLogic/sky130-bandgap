#!/usr/bin/env python3
"""Attribute `sim/psrr-dc-with-injector/`'s PSRR collapse to ONE device branch
inside `design/startup_injector.sch`, by measurement rather than by reading the
corner signature (issue #306, follow-up to #300).

What #300 left open
-------------------
`sim/psrr-dc-with-injector/records/20260923-124813-af9ff1e.md` proved the
collapse is a property of the DESIGN (schematic level, no extraction anywhere
in the loop): `psrr_band_min` FAILs 24/45 corners, binding corner
`ff / 125 degC / 3.63 V` at 24.78 dB against DR-006's 60 dB DC-1 kHz floor.
But that bench attaches `design/startup_injector.sym` as a WHOLE CELL, so it
identifies *the injector*, not one of its six devices. The `MPC1`/`MPC2`
attribution in #300's body and in that bench's README is explicitly an
inference from the corner signature (monotone in supply, fast-PMOS-selective),
not a measurement.

What this bench measures
------------------------
The same 45-corner PSRR matrix, five times, on five structurally different
bodies that differ by exactly one device branch each. Every branch that
touches GDRV -- the amplifier's high-impedance output node, the only node the
injector can act through -- gets its own variant:

  base        core + injector, unmodified (reproduces the cited record)
  core_only   the `XSU` instance removed -> the bare-core CONTROL (row 4a)
  ref_open    `MPC1`/`MPC2` removed and `NG` tied to `VSS` by a 0 V source,
              i.e. the diode-connected PMOS reference stack's GDRV load AND
              its `NG` bias both removed, with `MNI`/`MNC` still on GDRV
  inj_open    `MNI` removed -- the injector NMOS's GDRV load removed, the
              reference stack (and therefore its `NG` bias) left in place
  clamp_open  `MNC` removed -- the issue-#52 railed-branch clamp's GDRV load
              removed

A variant's *recovery* (`variant - base`, in dB, per corner) is that branch's
measured contribution to the collapse. `core_only` is the ceiling the
recoveries are read against, and it is also the CONTROL `sim/README.md`
insists on: if the harness ever stopped actually exercising the injector,
`base` would collapse onto `core_only` and the checks below would say so
instead of quietly reporting a plausible attribution.

Why a bespoke script and not a `deck.params` manifest
-----------------------------------------------------
Same reasoning as `sim/res-array-resize/run_res_array_resize.py` and
`sim/res-array-head-resistance/run_res_array_head_resistance.py`: removing a
device from a subcircuit is a BODY SUBSTITUTION, not a parameter override, so
the generic corner-runner manifest path cannot express it. `m_ref` / `m_inj` /
`m_clamp` cannot express it either -- they are multiplicity knobs with no
"0 units" setting, and they are declared *inside* the `startup_injector`
subcircuit, so a top-level `.param` from `deck.params` is shadowed and would
not reach them.

Netlist provenance: the base body is the already-committed netlist snapshot
`sim/psrr-dc-with-injector/netlist-snapshots/20260923-124813-af9ff1e.spice`,
i.e. the exact body the cited record measured -- NOT a fresh xschem netlist of
`design/`. That is deliberate and load-bearing: this is an attribution of a
collapse that a specific committed record exhibits, so the circuit under the
knife has to be that record's circuit. Once the fix for #306 lands in
`design/startup_injector.sch`, re-netlisting would silently attribute the FIXED
design instead. The six device lines this script cuts are asserted present
verbatim before any substitution, so a drifted snapshot fails loudly.

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
BUILD_DIR = SIM_DIR / "build" / "psrr-injector-attribution"

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

SLUG = "psrr-injector-attribution"
SCRIPT = "run_psrr_injector_attribution.py"
TITLE = (
    "Device-branch attribution of the startup injector's DC-1 kHz PSRR collapse "
    "(issue #306, follow-up to #300)"
)

#: The bench whose collapse is being attributed, and the exact record.
COMPANION = "sim/psrr-dc-with-injector"
CITED_RECORD_ID = "20260923-124813-af9ff1e"
BASE_SNAPSHOT = SIM_DIR / "psrr-dc-with-injector" / "netlist-snapshots" / f"{CITED_RECORD_ID}.spice"
CITED_RECORD_JSON = SIM_DIR / "psrr-dc-with-injector" / "records" / f"{CITED_RECORD_ID}.json"
WRAPPED_SCHEMATIC = "sim/psrr-dc-with-injector/testbench/tb_vref_psrr_injector.sch"

#: DR-006's DC-1 kHz band-min floor, restated here only so the checks can cite it.
PSRR_FLOOR_DB = 60.0

#: The exact device lines inside the `startup_injector` subcircuit that this
#: script cuts, plus the `XSU` instance line in the testbench wrapper. Asserted
#: present EXACTLY ONCE each before any substitution: a drifted snapshot must
#: fail loudly rather than have a substitution silently no-op.
TARGET_PREFIXES = ("XMPC1 ", "XMPC2 ", "XMNS ", "XQS ", "XMNI ", "XMNC ", "XSU ")

#: Injector `.param` lines the snapshot must still carry -- the multiplicity
#: knobs every cut device is scaled by. If any of these moved, the cited
#: record's sizing is not what this script thinks it is cutting.
EXPECTED_PARAMS = {
    ".param m_ref=1",
    ".param m_sense=1",
    ".param m_pnp=8",
    ".param m_inj=1",
    ".param m_clamp=1",
}

#: Byte-identical to `sim/psrr-dc-with-injector/experiment.json`'s `measurements`
#: expressions and limits, so every number here is directly comparable to that
#: bench's records. The three `f_*` / `n_ac_points` guards are carried over for
#: the same reason they exist there: an indexed readout off a collapsed or
#: re-gridded sweep is meaningless, and a silent re-grid would otherwise look
#: like a circuit result.
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

#: Operating-point readouts, taken from a second `op` AFTER the AC measurements
#: are already printed (an `op` re-points ngspice's current plot, so the AC
#: `let` vectors must be printed before it runs). These are diagnostics, not
#: pass/fail: they are what makes the attribution mechanistic rather than just
#: a ranking -- `v_ng` in particular is the injector's own disengagement state.
OP_ALWAYS = (("v_vref", "v(vref)"), ("v_gdrv", "v(gdrv)"), ("i_vdd", "i(v1)"))
OP_INJECTOR = (("v_ng", "v(xsu.ng)"), ("v_ne", "v(xsu.ne)"))
OP_REF_STACK = (("v_nc1", "v(xsu.nc1)"),)

#: Full 45-point PVT matrix -- the same one `sim/psrr-dc-with-injector` and
#: `sim/psrr-dc` use, so `base`/`core_only` are comparable to both row 4d and
#: row 4a corner-for-corner.
PROCESSES = ("tt", "ss", "ff", "sf", "fs")
TEMPS_C = (-40.0, 27.0, 125.0)
SUPPLIES_V = (2.97, 3.30, 3.63)


class Variant:
    """One structurally-substituted body: what is cut, and what it isolates."""

    def __init__(self, name: str, drop: tuple[str, ...], insert_after=None, insert=None,
                 op_extra=(), what: str = "", isolates: str = ""):
        self.name = name
        self.drop = drop
        self.insert_after = insert_after
        self.insert = insert
        self.op_extra = op_extra
        self.what = what
        self.isolates = isolates


VARIANTS = (
    Variant(
        "base", (), op_extra=OP_INJECTOR + OP_REF_STACK,
        what="core + injector, unmodified",
        isolates="reproduces the cited record on this script's own code path",
    ),
    Variant(
        "core_only", ("XSU ",),
        what="the `XSU startup_injector` instance removed from the testbench wrapper",
        isolates="the bare core (report row 4a) -- the CONTROL and the recovery ceiling",
    ),
    Variant(
        "ref_open", ("XMPC1 ", "XMPC2 "), insert_after="XMNC ", insert="VNGTIE NG VSS 0",
        op_extra=OP_INJECTOR,
        what="`MPC1`/`MPC2` removed; `NG` held at `VSS` by a 0 V source",
        isolates="the diode-connected PMOS reference stack: both its own GDRV load "
                 "and the `NG` bias it imposes on `MNI`",
    ),
    Variant(
        "inj_open", ("XMNI ",), op_extra=OP_INJECTOR + OP_REF_STACK,
        what="`MNI` (the injector NMOS, drain on GDRV) removed",
        isolates="`MNI`'s own drain load on GDRV, with the reference stack and its "
                 "`NG` bias left in place",
    ),
    Variant(
        "clamp_open", ("XMNC ",), op_extra=OP_INJECTOR + OP_REF_STACK,
        what="`MNC` (the issue-#52 railed-branch clamp, source on GDRV) removed",
        isolates="`MNC`'s own source load on GDRV",
    ),
)
VARIANTS_BY_NAME = {v.name: v for v in VARIANTS}


# --------------------------------------------------------------------------
# base body + substitution
# --------------------------------------------------------------------------


def load_base_body() -> list[str]:
    """Read the cited record's netlist snapshot, strip `.end`, and assert it is
    the body this script believes it is cutting.

    The snapshot read, `.end` strip and `EXPECTED_PARAMS` drift check are the
    canonical `sim_common.load_base_body()` (shared with the other bespoke
    body-substitution scripts). Only the exactly-once check on
    `TARGET_PREFIXES` below is specific to this bench's six-device cut.
    """
    lines = _load_base_body(BASE_SNAPSHOT, EXPECTED_PARAMS)
    for prefix in TARGET_PREFIXES:
        n = sum(1 for ln in lines if ln.startswith(prefix))
        if n != 1:
            raise cr.HarnessError(
                f"base snapshot {BASE_SNAPSHOT} has {n} line(s) starting '{prefix}', expected "
                "exactly 1 -- refusing to substitute against a body this script cannot verify"
            )
    return lines


def variant_body(base: list[str], variant: Variant) -> list[str]:
    body = list(base)
    for prefix in variant.drop:
        before = len(body)
        body = [ln for ln in body if not ln.startswith(prefix)]
        if len(body) != before - 1:
            raise cr.HarnessError(f"variant {variant.name}: dropping '{prefix}' removed "
                                  f"{before - len(body)} lines, expected 1")
        if variant.insert_after == prefix:
            raise cr.HarnessError(
                f"variant {variant.name}: insert anchor '{prefix}' is also dropped"
            )
    if variant.insert is not None:
        idx = next((i for i, ln in enumerate(body) if ln.startswith(variant.insert_after)), None)
        if idx is None:
            raise cr.HarnessError(
                f"variant {variant.name}: insert anchor '{variant.insert_after}' not found"
            )
        body.insert(idx + 1, variant.insert)
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

    op_meas = OP_ALWAYS + tuple(variant.op_extra)
    ctrl = [".control", "save all", AC_ANALYSIS]
    ctrl += [f"let meas_{n} = {e}" for n, e in AC_MEAS]
    ctrl += [f"print meas_{n}" for n, _ in AC_MEAS]
    # `op` re-points the current plot, so every AC readout above is already
    # printed by the time the operating point is solved.
    ctrl += ["op"]
    ctrl += [f"let meas_{n} = {e}" for n, e in op_meas]
    ctrl += [f"print meas_{n}" for n, _ in op_meas]
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
    # One run dir per point: `run_ngspice()` writes `.spiceinit` into it, so
    # sharing a dir across concurrent points would race on that file.
    run_dir = BUILD_DIR / record_id / name
    stamp = datetime.now(timezone.utc)
    raw, rc, timed_out = run_ngspice(run_dir, name, deck, timeout)
    if corners_dir is not None:
        write_log(corners_dir, name, record_id, pdk, stamp, deck, raw, rc, timed_out)
    meas = parse_measurements(raw)
    return {
        "variant": variant.name, "corner_id": cid, "process": process,
        "temperature_c": temp_c, "supply_v": supply_v,
        "ngspice_exit": rc, "timed_out": timed_out,
        "measurements": meas,
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
            m = res["measurements"]
            band = m.get("psrr_band_min")
            print(f"[{done:3d}/{total}] {res['variant']:11s} {res['corner_id']:16s} "
                  + (f"psrr_band_min={band:8.3f} dB" if band is not None
                     else f"NO MEASUREMENT (rc={res['ngspice_exit']}, timeout={res['timed_out']})"),
                  flush=True)
            results[(res["variant"], res["corner_id"])] = res
    return results


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------

#: `base` must land within this of the cited record's own per-corner
#: `psrr_band_min`. Not zero: this script's deck is assembled by a different
#: code path (own head/control block) than `corner-run.py`'s, so the tolerance
#: says "same circuit, same solver settings, same answer" rather than
#: "byte-identical deck".
REPRO_TOL_DB = 0.5
#: `clamp_open` vs `base`: anything at or below this is "not a contributor".
NEGLIGIBLE_DB = 0.25
#: How close `ref_open` must come to the `core_only` ceiling.
CEILING_TOL_DB = 2.0


def cited_band_min() -> dict[str, float]:
    if not CITED_RECORD_JSON.is_file():
        raise cr.HarnessError(f"missing cited record json: {CITED_RECORD_JSON}")
    rec = json.loads(CITED_RECORD_JSON.read_text())
    out = {}
    for c in rec["corners"]:
        for m in c["measurements"]:
            if m["name"] == "psrr_band_min" and m.get("value") is not None:
                out[c["corner_id"]] = float(m["value"])
    if not out:
        raise cr.HarnessError(f"{CITED_RECORD_JSON} carries no psrr_band_min values")
    return out


def evaluate(results, points) -> list[dict]:
    checks: list[dict] = []

    def add(name, ok, detail):
        checks.append({"name": name, "pass": bool(ok), "detail": detail})

    def band(variant, cid):
        return results[(variant, cid)]["measurements"].get("psrr_band_min")

    cited = cited_band_min()
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

    # 1. `base` reproduces the record whose collapse is being attributed.
    for cid in cids:
        b, c = band("base", cid), cited.get(cid)
        ok = b is not None and c is not None and abs(b - c) <= REPRO_TOL_DB
        add(f"base_reproduces_cited_record[{cid}]", ok,
            f"base psrr_band_min={b if b is None else round(b, 3)} dB vs "
            f"{COMPANION}/records/{CITED_RECORD_ID} {c if c is None else round(c, 3)} dB "
            f"(tolerance {REPRO_TOL_DB} dB)")

    # 2. CONTROL: with the injector gone the bench passes DR-006 everywhere. If
    #    this ever fails, the collapse is not the injector's and nothing below
    #    means what it says.
    for cid in cids:
        c = band("core_only", cid)
        add(f"control_core_only_clears_floor[{cid}]", c is not None and c >= PSRR_FLOOR_DB,
            f"core_only psrr_band_min={c if c is None else round(c, 3)} dB vs "
            f">= {PSRR_FLOOR_DB} dB (report row 4a passes 45/45; the injector is the only "
            "difference between that row and `base`)")

    # 3. `MNC` is not a contributor.
    for cid in cids:
        b, k = band("base", cid), band("clamp_open", cid)
        ok = b is not None and k is not None and abs(k - b) <= NEGLIGIBLE_DB
        add(f"clamp_not_a_contributor[{cid}]", ok,
            f"clamp_open - base = {None if (b is None or k is None) else round(k - b, 4)} dB "
            f"(|delta| must be <= {NEGLIGIBLE_DB} dB)")

    # 4. THE ATTRIBUTION. At every corner the cited record FAILS, opening the
    #    reference stack must (a) recover more than opening `MNI` does and
    #    (b) clear the DR-006 floor on its own.
    failing = [cid for cid in cids if (band("base", cid) or 0.0) < PSRR_FLOOR_DB]
    for cid in failing:
        b, r, i = band("base", cid), band("ref_open", cid), band("inj_open", cid)
        ok = None not in (b, r, i) and (r - b) > (i - b) and r >= PSRR_FLOOR_DB
        add(f"ref_stack_is_dominant[{cid}]", ok,
            f"recovery vs base: ref_open +{None if (r is None or b is None) else round(r - b, 3)} dB, "
            f"inj_open +{None if (i is None or b is None) else round(i - b, 3)} dB; "
            f"ref_open psrr_band_min={None if r is None else round(r, 3)} dB vs "
            f">= {PSRR_FLOOR_DB} dB")

    # 5. Opening the reference stack restores essentially the whole bare-core
    #    ceiling -- i.e. there is no large residual contributor left over.
    for cid in cids:
        r, c = band("ref_open", cid), band("core_only", cid)
        ok = None not in (r, c) and (c - r) <= CEILING_TOL_DB
        add(f"ref_open_restores_control[{cid}]", ok,
            f"core_only - ref_open = {None if (r is None or c is None) else round(c - r, 3)} dB "
            f"(must be <= {CEILING_TOL_DB} dB: nothing large left unattributed)")

    return checks


# --------------------------------------------------------------------------
# record
# --------------------------------------------------------------------------


def degradation_table(results, points, variant: str) -> list[str]:
    """mean (variant - core_only) grouped by each PVT axis, in dB."""
    rows: list[str] = []
    for axis, key, values in (
        ("process", lambda p: p[0], PROCESSES),
        ("temperature (degC)", lambda p: p[1], TEMPS_C),
        ("supply (V)", lambda p: p[2], SUPPLIES_V),
    ):
        cells = []
        for val in values:
            deltas = []
            for p in points:
                if key(p) != val:
                    continue
                cid = corner_id(*p)
                a = results[(variant, cid)]["measurements"].get("psrr_band_min")
                b = results[("core_only", cid)]["measurements"].get("psrr_band_min")
                if a is not None and b is not None:
                    deltas.append(a - b)
            label = val if isinstance(val, str) else f"{val:g}"
            cells.append(f"`{label}` {sum(deltas) / len(deltas):+.2f} dB" if deltas
                         else f"`{label}` n/a")
        rows.append(f"| {axis} | " + ", ".join(cells) + " |")
    return rows


def render_record(r: dict) -> str:
    L: list[str] = []

    def add(line: str = ""):
        L.append(line)

    results = r["_results"]
    points = r["_points"]
    cids = [corner_id(*p) for p in points]
    cited = r["cited"]

    add(f"# Record {r['record_id']}")
    add("")
    L.extend(render_record_id_experiment(r["record_id"], SLUG, TITLE))
    add(
        "- **Claim**: issue #306 -- identify, BY MEASUREMENT rather than by corner-signature "
        "inference, which device branch inside `design/startup_injector.sch` dominates the "
        f"DC-1 kHz PSRR collapse that `{COMPANION}/records/{CITED_RECORD_ID}.md` records "
        "(FAIL 24/45, `psrr_band_min` 24.78 dB at `ff / 125 degC / 3.63 V` against DR-006's "
        f"{PSRR_FLOOR_DB:g} dB band-min floor). #300 settled that *the injector* causes the "
        "collapse and that `klt extract --parasitics` does not; it explicitly did NOT settle "
        "which of the injector's six devices is responsible. This record measures the same "
        "45-corner matrix on five bodies that differ by exactly one GDRV-touching device "
        "branch each, so each branch's contribution is a measured dB recovery."
    )
    add(
        "- **Netlist provenance**: the base body is the committed netlist snapshot "
        f"`{BASE_SNAPSHOT.relative_to(REPO_ROOT)}` -- the exact body the cited record "
        f"measured, wrapping `{WRAPPED_SCHEMATIC}` -- NOT a fresh xschem netlist of "
        "`design/`. This is an attribution of a collapse a specific record exhibits, so the "
        "circuit under the knife must be that record's circuit; re-netlisting after #306's fix "
        "lands would silently attribute the fixed design instead. The six injector device "
        "lines and the `XSU` instance line are asserted present exactly once each, and the "
        "five injector `.param` multiplicity lines asserted unchanged, before any substitution."
    )
    L.extend(render_pdk_tools_repo_state(r))
    add(
        f"- **Corner matrix**: the full 45-point PVT matrix (process {', '.join(PROCESSES)} x "
        f"temperature {', '.join(f'{t:g}' for t in TEMPS_C)} degC x supply "
        f"{', '.join(f'{s:.2f}' for s in SUPPLIES_V)} V), run for each of the "
        f"{len(r['variants'])} variants -- {len(points) * len(r['variants'])} ngspice points. "
        f"Measurement expressions, limits, solver options and the `ac dec 10 0.1 1meg` sweep "
        f"are byte-identical to `{COMPANION}/experiment.json`'s, so every number here is "
        "directly comparable to report rows 4a and 4d corner-for-corner."
    )
    add(
        "- **Statistical convention**: N/A (deterministic corner-matrix attribution, not a "
        "distribution claim)."
    )
    add("")

    add("## Variants -- what each body cuts, and what that isolates")
    add("")
    add("| variant | substitution | isolates |")
    add("|---|---|---|")
    for v in VARIANTS:
        if v.name not in r["variants"]:
            continue
        add(f"| `{v.name}` | {v.what} | {v.isolates} |")
    add("")
    add(
        "Every device the injector places on GDRV has its own variant. GDRV is the only node "
        "the injector can act through at this operating point -- its `VSENSE` pin is a "
        "high-impedance gate and its `VDD` pin feeds only the two PMOS bulks (see "
        f"`{COMPANION}/experiment.json`'s last note) -- so this set is exhaustive over the "
        "mechanism. `MNS`/`QS` have no variant of their own because they do not touch GDRV: "
        "they reach it only through `NG`, which is exactly what `ref_open` holds fixed."
    )
    add("")

    add("## Result -- `psrr_band_min` (dB) per corner, per variant")
    add("")
    add("| corner | cited record | `base` | `core_only` | `ref_open` | `inj_open` | `clamp_open` |")
    add("|---|---|---|---|---|---|---|")
    for cid in cids:
        def cell(v):
            x = results[(v, cid)]["measurements"].get("psrr_band_min")
            if x is None:
                return "**n/a**"
            s = f"{x:.2f}"
            return s if x >= PSRR_FLOOR_DB else f"**{s}**"
        c = cited.get(cid)
        add(f"| `{cid}` | {'n/a' if c is None else f'{c:.2f}'} | " + " | ".join(
            cell(v) for v in ("base", "core_only", "ref_open", "inj_open", "clamp_open")) + " |")
    add("")
    add(
        f"**Bold** = below DR-006's {PSRR_FLOOR_DB:g} dB DC-1 kHz band-min floor. The `cited "
        f"record` column is `{COMPANION}/records/{CITED_RECORD_ID}.json`, reproduced here for "
        "the `base` cross-check, not re-measured."
    )
    add("")

    add("## Attribution -- measured recovery per branch")
    add("")
    add("| quantity | worst corner | value |")
    add("|---|---|---|")
    for label, expr in (
        ("`base` (all six devices)", "base"),
        ("`ref_open` (reference stack cut)", "ref_open"),
        ("`inj_open` (`MNI` cut)", "inj_open"),
        ("`clamp_open` (`MNC` cut)", "clamp_open"),
        ("`core_only` (CONTROL, no injector)", "core_only"),
    ):
        vals = [(results[(expr, cid)]["measurements"].get("psrr_band_min"), cid) for cid in cids]
        vals = [(x, c) for x, c in vals if x is not None]
        if not vals:
            add(f"| {label} | n/a | n/a |")
            continue
        worst, wcid = min(vals)
        n_pass = sum(1 for x, _ in vals if x >= PSRR_FLOOR_DB)
        add(f"| {label} | `{wcid}` | {worst:.2f} dB (passing {n_pass}/{len(vals)}) |")
    add("")

    for variant, blurb in (
        ("base", "the shipped injector's cost against the bare core"),
        ("ref_open", "what is left once the reference stack is cut"),
        ("inj_open", "what is left once `MNI` is cut"),
    ):
        add(f"Mean `psrr_band_min` degradation of `{variant}` vs. `core_only` -- {blurb}:")
        add("")
        add("| axis | mean degradation |")
        add("|---|---|")
        L.extend(degradation_table(results, points, variant))
        add("")

    add("## Operating point at the binding corner")
    add("")
    add("| variant | v(VREF) | v(GDRV) | v(NG) | v(NE) | v(NC1) | i(VDD) |")
    add("|---|---|---|---|---|---|---|")
    bcid = min(((results[("base", cid)]["measurements"].get("psrr_band_min", 1e9), cid)
                for cid in cids))[1]
    for v in ("base", "core_only", "ref_open", "inj_open", "clamp_open"):
        if v not in r["variants"]:
            continue
        m = results[(v, bcid)]["measurements"]

        def f(k, scale=1.0, unit=""):
            return "—" if k not in m else f"{m[k] * scale:.4f}{unit}"
        add(f"| `{v}` | {f('v_vref')} | {f('v_gdrv')} | {f('v_ng')} | {f('v_ne')} | "
            f"{f('v_nc1')} | {f('i_vdd', 1e6, ' µA')} |")
    add("")
    add(
        f"Binding corner: `{bcid}`. `v(NG)` is the injector's own disengagement state: `MNI`'s "
        "gate voltage once the core is running. It is what turns the reference stack's failure "
        "to switch off into a supply-dependent drain current out of GDRV, and it is the one "
        "number that moves between `base` and `ref_open`."
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
        "A `PASS` here is an attribution, not a spec verdict: it says the reference stack "
        f"`MPC1`/`MPC2` is the measured dominant contributor. `{COMPANION}` remains the bench "
        "that certifies the DR-006 row, and it is still FAILing on the body this record cuts."
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
        print(f"  {cid:16s} {v:11s} band_min={m.get('psrr_band_min', float('nan')):8.3f} "
              f"dc={m.get('psrr_dc', float('nan')):8.3f} vref={m.get('v_vref', float('nan')):.5f} "
              f"ng={m.get('v_ng', float('nan')):.4f}")
    return 0


def verify(args) -> int:
    pin = cr.load_pin()
    pdk = check_pdk_and_ngspice(pin, args.allow_pdk_mismatch, verbose=False)
    base_body = load_base_body()
    cited = cited_band_min()

    git_info = cr.git_state()
    now = datetime.now(timezone.utc)
    record_id = f"{now:%Y%m%d}-{now:%H%M%S}-{git_info['sha']}"
    records_dir, _, corners_dir, record_md, record_json, _ = setup_record_paths(
        HERE, record_id, with_snapshot=False
    )

    points = matrix()
    variants = list(VARIANTS)
    print(f"experiment    : {SLUG}")
    print(f"record id     : {record_id}")
    print(f"PDK           : {pdk.dir} (open_pdks {pdk.installed_commit})")
    print(f"base body     : {BASE_SNAPSHOT.relative_to(REPO_ROOT)}")
    print(f"points        : {len(points)} corners x {len(variants)} variants "
          f"= {len(points) * len(variants)} ngspice runs (jobs={args.jobs})")

    results = run_all(pdk, base_body, variants, points, args.timeout, args.jobs,
                      corners_dir, record_id)
    checks = evaluate(results, points)
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
            "statistical_convention": "N/A (deterministic corner-matrix attribution)",
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
        "jobs": args.jobs,
        "points": [
            {k: v for k, v in res.items()} for _, res in sorted(results.items())
        ],
        "checks": checks,
        "overall_pass": overall,
        "links": {
            "base_snapshot": str(BASE_SNAPSHOT.relative_to(REPO_ROOT)),
            "cited_record": f"{COMPANION}/records/{CITED_RECORD_ID}.json",
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
                   help="explore mode only: comma-separated variant names")
    p.add_argument("--corners", default="ff,125,3.63",
                   help="explore mode only: semicolon-separated process,temp,supply triples")
    p.add_argument("--jobs", type=int, default=4, help="concurrent ngspice processes")
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
