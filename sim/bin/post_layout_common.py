#!/usr/bin/env python3
"""Shared helpers for post-layout (extracted-netlist) `sim/*-post-layout/`
experiment scripts (issue #16).

Post-layout re-verification needs a `bandgap_core` netlist body that is
genuinely derived from the routed, LVS-clean layout (`layout/bandgap-core/`,
issue #62) rather than `design/bandgap_core.sch` -- otherwise a "post-layout"
record would just be a relabeled schematic run, the exact failure mode
issue #16's own history (the reversed 2026-08-03 Champion promotion) warns
against. Building that netlist takes three steps, each with its own
non-obvious wrinkle this module documents and handles once:

1. **Extract parasitics from the composed GDS**
   (`run_klt_extract_parasitics`): `klt extract --parasitics` writes a
   flat, device-level SPICE netlist with a real per-net star RC network
   already spliced in (one series R per device terminal to a net "hub" plus
   one lumped ground capacitance at the hub, from the deck's curated
   sheet-resistance/capacitance table) -- see `docs/cli/extract.md` in
   `2AMLogic/klayout-tools`. This is a genuinely distributed parasitic
   model, not a single lumped R+C per net.

2. **Translate the device classes to simulatable vendor models**
   (`translate_extracted_netlist`): `klt extract`'s own SPICE output uses
   generic LVS device-class placeholder model names (`nfet`, `pfet`, `pnp`,
   `res_high_po`) that are NOT names ngspice's sky130 model library
   recognizes -- they exist purely for `klt lvs`'s own comparator. There is
   no `klt` flag or documented path to a directly ngspice-simulatable
   extracted netlist. This is exactly the kind of tool gap CLAUDE.md's
   friction protocol asks to surface -- see the PR this module ships with
   for the filed issue.

   The translation this module performs is deliberately narrow, scoped to
   what THIS design's own extracted device set actually contains (verified
   empirically against `layout/bandgap-core/reports/LATEST`, not assumed):

   - `nfet`/`pfet` (M-card, `L=`/`W=`/`AS=`/`AD=`/`PS=`/`PD=` only) ->
     `X`-line instantiating `sky130_fd_pr__nfet_g5v0d10v5` /
     `..._pfet_g5v0d10v5` (the same vendor subckt `design/bandgap_core.sch`
     and `design/error_amp.sch` already instantiate) with the SAME drawn
     geometry the layout extraction reports -- real per-instance diffusion
     area/perimeter, not the schematic's formulaic approximation. Adds
     `nrd`/`nrs` at the schematic's own `0.29/W_um` convention (a
     second-order diffusion series-resistance term the extracted netlist
     does not itself carry) and pins `sa=sb=sd=0` (LOD stress off, matching
     every schematic instance) since the extraction has no stress-geometry
     data to offer instead.
   - `pnp` (Q-card, `AE=`/`PE=`/... geometry, class always `pnp`) -> `X`-line
     instantiating the real vendor macro cell. sky130's PNPs are FIXED,
     non-parametric macros (`sky130_fd_pr__pnp_05v5_W0p68L0p68` /
     `..._W3p40L3p40`) with no W/L/area argument at all -- see
     `layout/bandgap-core/reports/LATEST/record.md`'s "PNP ae/pe/ne
     transcription gap" note. This design draws exactly two unit sizes
     (`AE=0.4624` um^2 small/CTAT, `AE=11.56` um^2 large/PTAT -- 8 units
     each, confirmed by direct inspection of every extracted `Q$` line),
     so `AE` alone (a simple `< 1.0` threshold) selects the right macro;
     `AE`/`PE`/etc. are otherwise discarded (the macro does not take them).
   - `res_high_po` (3-terminal `R<name> a b bulk value res_high_po`) -> a
     plain 2-terminal `R<name> a b value` primitive, at the SAME per-unit
     value `klt extract` already resolved (independently cross-checked
     against `sim/trim-lsb-chained`'s own `HEAD_OHM`/`BODY_OHM_PER_UM`
     model: the extracted 2003.841367 ohm / 5 um coarse unit and 542.118769
     ohm / 0.5 um fine unit both reproduce that model's
     `HEAD_OHM + BODY_OHM_PER_UM * length_um` formula exactly). Dropping the
     bulk terminal loses body-effect/leakage coupling to substrate, a
     documented, deliberate first-order simplification -- the star RC
     network from step 1 already carries the dominant layout-vs-schematic
     delta (real routing parasitics), and every unit's own value already
     includes its real per-instance head resistance.
   - `vsubs` (the parasitic network's synthesized substrate/ground-plane
     net, one shunt capacitor endpoint per named net) -> tied to `VSS`
     directly (text substitution), per the same substrate-identity finding
     `layout/bandgap-core/reports/LATEST/record.md`'s SUBSTRATE_NET_NOTE
     already established for device bulk terminals: this design's real
     substrate is the drawn `VSS` net, not an independent global.

3. **A discovered ngspice/sky130-model quirk this module works around**:
   sky130's `g5v0d10v5` MOS models are BSIM4 BINNED models
   (`nhv_model.1..N` / `phv_model.1..N`, selected by `L`/`W` range). Giving
   an INSTANCE's `L=`/`W=`/`AS=`/`AD=`/`PS=`/`PD=` an explicit unit suffix
   (`L=20u`, `AS=3.36p` -- exactly the form `klt extract` writes) makes
   ngspice's bin-selection fail with "could not find a valid modelname",
   reproduced in isolation down to a single-device deck, REGARDLESS of
   nesting depth -- while the bare, suffix-less form
   (`L=20`, relying on the deck's ambient `.option scale=1e-6`, which is
   exactly how `design/bandgap_core.sch`'s own xschem netlisting writes
   every `XM*` line) resolves the identical scaled value correctly. This is
   an ngspice/sky130-PDK interaction, not a `klt` gap, so it is not filed
   upstream -- `translate_extracted_netlist` strips the suffix instead.

Callers chain these three pieces plus
`build_core_wrapper`/`strip_schematic_subckts` to produce a `bandgap_core`
netlist body that is a drop-in replacement for `design/bandgap_core.sym` in
ANY existing `sim/*/testbench/*.sch` that instantiates it (same 4-pin
interface: `VOUT GDRV VDD VSS`) -- this is what lets a follow-on increment
of issue #16 reuse this module for `psrr-dc`, `line-regulation`,
`quiescent-current`, `startup-time`, `startup-stability`, `startup-ramp`
without re-deriving any of the above.

4. **One generic per-bench runner** (`run_post_layout_experiment`): the
   chaining itself, the record minting, the append-only refusal, the corner
   loop and the `provenance: extracted` record schema are IDENTICAL for
   every bench -- the only per-bench variables are the wrapped experiment
   slug, its testbench, the claim sentence and whether that bench's own
   manifest matrix is collapsed on an axis the deck sweeps internally. So
   each `sim/<slug>-post-layout/run_*.py` is a ~40-line declaration of those
   variables, not a copy of the runner (`sim/README.md`'s "copy this script"
   note predates this distillation; copying is no longer the pattern).

5. **The parasitics extraction is shared across benches**
   (`resolve_parasitics_snapshot`): every post-layout record for a given
   `layout/bandgap-core/reports/<record-id>` must measure the SAME extracted
   netlist, otherwise cross-bench comparisons (Iq at the operating point
   `output-voltage-tc` reported, say) would silently be against different
   DUTs. The first bench to run for a layout record commits the snapshot
   under its own `parasitics-snapshot/<layout-record-id>/`; later benches
   find and reuse it in place rather than re-extracting a second copy.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


class PostLayoutError(RuntimeError):
    """A problem the operator has to fix; never produces a record."""


# --------------------------------------------------------------------------
# layout resolution
# --------------------------------------------------------------------------


def resolve_latest_layout(bandgap_core_dir: Path) -> tuple[str, Path, Path]:
    """Resolve `layout/bandgap-core/reports/LATEST` to (record_id, record_dir, gds).

    Reference-only reads under `layout/` -- never writes there (issue #16's
    Affected Files scope: `layout/` is reference-only).
    """
    latest_file = bandgap_core_dir / "reports" / "LATEST"
    if not latest_file.is_file():
        raise PostLayoutError(f"no LATEST pointer at {latest_file}")
    record_id = latest_file.read_text().strip()
    record_dir = bandgap_core_dir / "reports" / record_id
    gds = record_dir / "bandgap_core_routed.gds"
    if not gds.is_file():
        raise PostLayoutError(f"no routed GDS at {gds} (LATEST -> {record_id})")
    return record_id, record_dir, gds


# --------------------------------------------------------------------------
# klt extract --parasitics
# --------------------------------------------------------------------------


def run_klt_extract_parasitics(
    gds: Path,
    out_dir: Path,
    deck: str = "sky130",
    top: str = "bandgap_core_routed",
    timeout: int = 300,
) -> tuple[Path, dict]:
    """Run `klt extract --parasitics` against `gds`, writing the SPICE
    netlist + JSON summary into `out_dir`. Returns (spice_path, json_dict).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    spice_out = out_dir / f"{top}.pex.spice"
    cmd = [
        "klt",
        "extract",
        str(gds),
        "--deck",
        deck,
        "--top",
        top,
        "--parasitics",
        "--format",
        "json",
        "-o",
        str(spice_out),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise PostLayoutError(f"klt not found on PATH: {exc}") from exc
    if proc.returncode != 0:
        raise PostLayoutError(
            f"klt extract --parasitics failed (rc={proc.returncode})\n"
            f"  cmd: {' '.join(cmd)}\n  stdout: {proc.stdout}\n  stderr: {proc.stderr}"
        )
    if not spice_out.is_file():
        raise PostLayoutError(f"klt extract did not produce {spice_out}")
    try:
        summary = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise PostLayoutError(f"klt extract --format json did not print valid JSON: {exc}") from exc
    json_out = out_dir / f"{top}.pex.json"
    json_out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return spice_out, summary


# --------------------------------------------------------------------------
# device-class translation (generic LVS placeholders -> simulatable vendor models)
# --------------------------------------------------------------------------

_UNIT_SUFFIX_RE = re.compile(r"(-?\d+\.?\d*)[UP]\b")
_M_RE = re.compile(r"^(M\$\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(nfet|pfet)\s+(.*)$")
_Q_RE = re.compile(r"^(Q\$\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+pnp\s+AE=([0-9.]+)P.*$")
_R_RE = re.compile(r"^(R\$\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+([0-9.]+)\s+res_high_po$")

# Boundary between the two PNP unit sizes this design draws (0.4624 um^2
# small/CTAT vs 11.56 um^2 large/PTAT) -- see module docstring point 2.
_PNP_AE_SMALL_LARGE_BOUNDARY_UM2 = 1.0

# design/bandgap_core.sch's / design/error_amp.sch's own nrd=nrs=0.29/W_um
# diffusion-series-resistance convention (reproduced by inspection of every
# XM* line in both schematics: 0.03625 @ W=8, 0.0145 @ W=20, 0.048333 @ W=6,
# 0.0096667 @ W=30 all solve k=0.29 exactly).
_NRD_NRS_K = 0.29


def _strip_unit_suffix(match: re.Match) -> str:
    return match.group(1)


def translate_extracted_netlist(text: str) -> tuple[str, dict[str, int]]:
    """Translate `klt extract --parasitics`'s generic device-class SPICE
    into a directly ngspice-simulatable netlist against the pinned sky130
    PDK. See the module docstring for the full rationale per device class.

    Returns (translated_text, counts) where counts tallies how many of each
    device class were translated -- callers should assert this against the
    layout record's own documented device_counts as a translation-coverage
    guard (a class this function doesn't recognize is left untouched and
    will fail loudly at ngspice load time, but a SILENT undercount would
    not).
    """
    lines = text.splitlines()
    joined: list[str] = []
    for ln in lines:
        if ln.startswith("+") and joined:
            joined[-1] += " " + ln[1:].strip()
        else:
            joined.append(ln)

    out: list[str] = []
    counts = {"mos": 0, "pnp": 0, "res": 0}
    for ln in joined:
        s = ln.strip()

        m = _M_RE.match(s)
        if m:
            name, d, g, src, b, cls, rest = m.groups()
            model = "sky130_fd_pr__nfet_g5v0d10v5" if cls == "nfet" else "sky130_fd_pr__pfet_g5v0d10v5"
            rest2 = _UNIT_SUFFIX_RE.sub(_strip_unit_suffix, rest)
            wm = re.search(r"[Ww]=([0-9.]+)\b", rest2)
            w_um = float(wm.group(1)) if wm else 1.0
            nrd_nrs = _NRD_NRS_K / w_um
            out.append(
                f"X{name[1:]} {d} {g} {src} {b} {model} {rest2} "
                f"nrd={nrd_nrs:.6f} nrs={nrd_nrs:.6f} nf=1 mult=1 sa=0 sb=0 sd=0"
            )
            counts["mos"] += 1
            continue

        m = _Q_RE.match(s)
        if m:
            name, c, b, e, ae = m.groups()
            ae_um2 = float(ae)
            model = (
                "sky130_fd_pr__pnp_05v5_W0p68L0p68"
                if ae_um2 < _PNP_AE_SMALL_LARGE_BOUNDARY_UM2
                else "sky130_fd_pr__pnp_05v5_W3p40L3p40"
            )
            out.append(f"X{name[1:]} {c} {b} {e} {model} m=1")
            counts["pnp"] += 1
            continue

        m = _R_RE.match(s)
        if m:
            name, a, b, _bulk, val = m.groups()
            out.append(f"{name} {a} {b} {val}")
            counts["res"] += 1
            continue

        out.append(ln)

    result = "\n".join(out)
    result = re.sub(r"\bvsubs\b", "VSS", result)
    return result, counts


def extract_subckt_block(text: str, name: str) -> str:
    """Pull out one `.SUBCKT <name> ... .ENDS <name>` block (case-insensitive)."""
    m = re.search(
        rf"(\.SUBCKT\s+{re.escape(name)}\b.*?\.ENDS\s+{re.escape(name)})",
        text,
        re.S | re.I,
    )
    if not m:
        raise PostLayoutError(f"no .SUBCKT {name} ... .ENDS block found")
    return m.group(1)


def parse_subckt_ports(text: str, name: str) -> tuple[str, ...]:
    """Parse the actual, as-extracted `.SUBCKT <name> <port> <port> ...`
    header's port list, in declaration order.

    `klt extract --parasitics` does not always promote the same top-level
    pin set `klt extract`'s plain (non-parasitics) pass does: a wider
    `ROUTE_WIDTH_UM` layout has been observed to additionally promote the
    synthesized substrate net (`vsubs`) to an explicit 12th `.SUBCKT` port
    that the plain-extraction 11-pin set (`D1 D2 GDRV PN TAIL VA VB VBQ VDD
    VOUT VSS`) does not carry -- see
    `spec/decision-records/DR-008-psrr-post-layout-margin-proposal.md`'s
    harness-fragility side finding. A caller that hardcodes the 11-pin order
    (`build_core_wrapper`'s previous default) silently mis-binds `XCORE`'s
    positional node list against a 12-port header in that case (ngspice then
    fails to resolve the call, reporting an "unknown subckt" style error
    instead of the real PSRR numbers) -- parsing the header actually written
    by this run's own extraction avoids assuming a fixed pin count.

    Ports may repeat (e.g. the promoted `vsubs` port, after
    `translate_extracted_netlist`'s blanket `vsubs` -> `VSS` text
    substitution, becomes a second literal `VSS` entry) -- this returns the
    header exactly as declared, duplicates included: `X<inst> <nodes...>
    <subckt>` binds a call to a `.SUBCKT` by POSITION, so a caller must
    supply as many actual nodes as the header lists, in the same positions,
    not a de-duplicated set.
    """
    m = re.search(
        rf"^\.subckt\s+{re.escape(name)}\s+(.+)$",
        text,
        re.I | re.M,
    )
    if not m:
        raise PostLayoutError(f"no .SUBCKT {name} header line found to parse ports from")
    return tuple(m.group(1).split())


def build_core_wrapper(
    core_subckt: str = "bandgap_core_routed",
    core_port_order: tuple[str, ...] = (
        "D1", "D2", "GDRV", "PN", "TAIL", "VA", "VB", "VBQ", "VDD", "VOUT", "VSS",
    ),
    exposed: tuple[str, ...] = ("VOUT", "GDRV", "VDD", "VSS"),
) -> str:
    """`.subckt bandgap_core VOUT GDRV VDD VSS ... .ends` wrapping the
    extracted, translated `bandgap_core_routed` netlist.

    `design/bandgap_core.sym` (and therefore every existing
    `sim/*/testbench/*.sch` that instantiates it) exposes exactly 4 pins:
    VOUT, GDRV, VDD, VSS (see `design/bandgap_core.sym`'s own header
    comment: "Pin order below is the order xschem emits into @pinlist").
    The routed layout promotes 11 top-level pins -- the same 4 plus 7
    amp-internal nodes (D1, D2, PN, TAIL, VA, VB, VBQ) the layout labels
    for LVS visibility (INTERNAL_NODE_LABEL_NOTE,
    `layout/bandgap-core/reports/LATEST/record.md`) but that
    `design/error_amp.sch` never exposes past `design/bandgap_core.sch`'s
    own boundary either. This wrapper maps the 4 real external pins through
    and gives the other 7 fresh, wrapper-local internal net names -- SPICE
    subckt scoping makes them genuinely internal to this one instance, byte
    for byte the same electrical topology `design/bandgap_core.sch` already
    keeps internal to its own `XAMP` call.

    `core_port_order` defaults to the usual 11-pin set but callers should
    pass the header actually parsed from this run's own extraction
    (`parse_subckt_ports`) rather than rely on the default -- see that
    function's docstring for why the promoted pin set is not always the
    same 11 (e.g. a wider `ROUTE_WIDTH_UM` layout promoting `vsubs` as a
    12th port). This function itself is agnostic to the exact count/order:
    it maps every port not in `exposed` to a fresh wrapper-local internal
    name and calls `XCORE` positionally against however many (and whichever)
    ports `core_port_order` actually lists, duplicates included.
    """
    unexposed = [p for p in core_port_order if p not in exposed]
    port_map = {p: p for p in exposed}
    port_map.update({p: f"{p}_INT" for p in unexposed})
    call_ports = " ".join(port_map[p] for p in core_port_order)
    exposed_ordered = [p for p in ("VOUT", "GDRV", "VDD", "VSS") if p in exposed]
    return (
        f".subckt bandgap_core {' '.join(exposed_ordered)}\n"
        f"XCORE {call_ports} {core_subckt}\n"
        f".ends bandgap_core\n"
    )


def strip_schematic_subckts(body_text: str, names: tuple[str, ...]) -> str:
    """Remove xschem-emitted `.subckt <name> ... .ends` blocks (with their
    `* expanding ... symbol: design/<name>.sym` header) from a netlisted
    testbench body, so a translated-layout replacement can be appended
    instead.

    The header's `.*?` gap between `expanding` and `symbol:` MUST stay tight
    (whitespace only, not DOTALL-wildcard) -- a testbench that netlists a
    THIRD schematic-level `.sym` whose own `* expanding ... symbol: ...`
    header sits between two names being stripped (e.g. the mixed-provenance
    startup benches, which also netlist `design/startup_injector.sym`
    unmodified alongside `bandgap_core`/`error_amp`) would otherwise let a
    lazy wildcard gap match starting at that THIRD header and swallow every-
    thing up to the target name's real header, deleting the third subckt's
    block as collateral damage. Reproduced and root-caused while wiring
    `sim/startup-stability-post-layout/`, issue #16: after stripping
    `bandgap_core` alone, the leftmost remaining `* expanding` line in the
    text was `design/startup_injector.sym`'s, and the old
    `\\* expanding.*?symbol:...design/error_amp\\.sym` pattern happily bound
    its start there instead of at `error_amp`'s own header, deleting the
    entire `startup_injector` block in the process. Anchoring the gap to
    `\\s+` (the fixed `* expanding   symbol:  design/<name>.sym` spacing
    xschem actually emits) makes the header match name-specific instead of
    "the nearest earlier expanding-header, whichever symbol it names".
    """
    text = body_text
    for name in names:
        pattern = (
            rf"\n\* expanding\s+symbol:\s*design/{re.escape(name)}\.sym\b.*?"
            rf"\n\.subckt\s+{re.escape(name)}\b.*?\n\.ends\n"
        )
        new_text, n = re.subn(pattern, "\n", text, flags=re.S | re.I)
        if n == 0:
            raise PostLayoutError(f"no .subckt {name} ... .ends block found to strip")
        text = new_text
    return text


# --------------------------------------------------------------------------
# generic per-bench post-layout runner (module docstring points 4 and 5)
# --------------------------------------------------------------------------

SIM_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SIM_DIR.parent
LAYOUT_BANDGAP_CORE_DIR = REPO_ROOT / "layout" / "bandgap-core"

PEX_TOP = "bandgap_core_routed"
PEX_SPICE_NAME = f"{PEX_TOP}.pex.spice"
PEX_JSON_NAME = f"{PEX_TOP}.pex.json"

# The two `.subckt` blocks xschem emits for `design/bandgap_core.sym` in every
# bench that instantiates it (`bandgap_core` calls `error_amp`); both are
# replaced wholesale by the extracted layout body, which is flat.
SCHEMATIC_SUBCKTS_TO_REPLACE = ("bandgap_core", "error_amp")


def resolve_parasitics_snapshot(
    local_snapshot_root: Path, gds: Path, layout_record_id: str
) -> tuple[Path, dict, str]:
    """Find (or produce) the `klt extract --parasitics` snapshot for one
    layout record. Returns (snapshot_dir, summary, source).

    Resolution order, per module docstring point 5:

    1. `<local_snapshot_root>/<layout_record_id>/` -- this bench already ran
       against this layout record (`sim/` is append-only: never re-extract
       over an existing snapshot).
    2. any sibling `sim/*/parasitics-snapshot/<layout_record_id>/` -- another
       post-layout bench already extracted this exact layout record; reuse it
       IN PLACE so every post-layout record for a given layout record
       measures the same extracted netlist (and so the ~320 kB snapshot is
       committed once, not once per bench).
    3. otherwise run `klt extract --parasitics` and commit the result here.
    """
    local = local_snapshot_root / layout_record_id
    if (local / PEX_SPICE_NAME).is_file():
        summary = json.loads((local / PEX_JSON_NAME).read_text())
        return local, summary, "local"

    for candidate in sorted(SIM_DIR.glob(f"*/parasitics-snapshot/{layout_record_id}")):
        if (candidate / PEX_SPICE_NAME).is_file() and (candidate / PEX_JSON_NAME).is_file():
            summary = json.loads((candidate / PEX_JSON_NAME).read_text())
            return candidate, summary, f"reused:{candidate.relative_to(REPO_ROOT)}"

    _spice, summary = run_klt_extract_parasitics(gds, local, top=PEX_TOP)
    return local, summary, "extracted"


def build_extracted_body(
    cr,
    pdk,
    run_dir: Path,
    local_snapshot_root: Path,
    wrapped_schematic: str,
) -> tuple[list[str], dict]:
    """Netlist the (unmodified) schematic testbench, then swap its
    `bandgap_core`/`error_amp` subckt definitions for the translated,
    extracted, parasitics-included routed layout. Returns (body, provenance).
    """
    layout_record_id, layout_record_dir, gds = resolve_latest_layout(LAYOUT_BANDGAP_CORE_DIR)
    pex_dir, pex_summary, pex_source = resolve_parasitics_snapshot(
        local_snapshot_root, gds, layout_record_id
    )
    spice_path = pex_dir / PEX_SPICE_NAME

    translated, counts = translate_extracted_netlist(spice_path.read_text())

    expected = pex_summary.get("device_counts", {})
    expected_mos = expected.get("nfet", 0) + expected.get("pfet", 0)
    expected_pnp = expected.get("pnp", 0)
    expected_res = expected.get("res_high_po", 0)
    if (counts["mos"], counts["pnp"], counts["res"]) != (expected_mos, expected_pnp, expected_res):
        raise PostLayoutError(
            "translation coverage mismatch against the extraction's own device_counts: "
            f"translated mos={counts['mos']} pnp={counts['pnp']} res={counts['res']}, "
            f"extraction reports nfet+pfet={expected_mos} pnp={expected_pnp} res_high_po={expected_res} "
            "-- a device class this translator doesn't recognize may have been silently skipped"
        )

    core_block = extract_subckt_block(translated, PEX_TOP)
    core_port_order = parse_subckt_ports(core_block, PEX_TOP)
    wrapper = build_core_wrapper(core_subckt=PEX_TOP, core_port_order=core_port_order)

    testbench = REPO_ROOT / wrapped_schematic
    netlist = cr.netlist_with_xschem(testbench, run_dir, pdk)
    tb_body_text = "\n".join(cr.netlist_body(netlist))
    tb_body_text = strip_schematic_subckts(tb_body_text, SCHEMATIC_SUBCKTS_TO_REPLACE)

    body = (tb_body_text + "\n\n" + wrapper + "\n" + core_block + "\n").splitlines()

    provenance = {
        "layout_record_id": layout_record_id,
        "layout_record": str((layout_record_dir / "record.md").relative_to(REPO_ROOT)),
        "layout_gds": str(gds.relative_to(REPO_ROOT)),
        "parasitics_snapshot": {
            "spice": str(spice_path.relative_to(REPO_ROOT)),
            "json": str((pex_dir / PEX_JSON_NAME).relative_to(REPO_ROOT)),
            "source": pex_source,
            "r_count": pex_summary.get("parasitics", {}).get("r_count"),
            "c_count": pex_summary.get("parasitics", {}).get("c_count"),
            "total_resistance_ohm": pex_summary.get("parasitics", {}).get("total_resistance_ohm"),
            "total_capacitance_ff": pex_summary.get("parasitics", {}).get("total_capacitance_ff"),
        },
        "device_translation_counts": counts,
        "lvs_mismatch_count_at_extraction": None,  # cross-referenced in the record body, not re-derived here
        "core_port_order": list(core_port_order),  # as actually parsed from this run's own extraction header
    }
    return body, provenance


def parse_post_layout_args(argv: list[str], doc: str = "") -> argparse.Namespace:
    """The flag set every `sim/*-post-layout/run_*.py` accepts (the subset of
    `corner-run.py`'s flags that is meaningful when the matrix, measurements
    and deck all come from the wrapped experiment's own manifest)."""
    p = argparse.ArgumentParser(description=doc)
    p.add_argument("--supersedes", default="")
    p.add_argument("--author", default="")
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--allow-pdk-mismatch", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def run_post_layout_experiment(
    cr,
    here: Path,
    slug: str,
    wrapped_experiment: str,
    wrapped_schematic: str,
    claim_tail: str,
    argv: list[str],
    temp_override: list[float] | None = None,
    supply_override: list[float] | None = None,
    process_override: list[str] | None = None,
    subset_reason: str = "",
    claim_split: str | None = None,
) -> int:
    """Run one bench's whole post-layout re-verification and write its record.

    `here` is the `sim/<slug>/` directory of the POST-LAYOUT experiment (the
    caller's own `Path(__file__).parent`); `wrapped_experiment` is the
    schematic-level slug under `sim/` whose `experiment.json` supplies the
    corner matrix, deck options and measurement limits UNCHANGED (never
    edited -- the only variable between its records and this one is the DUT
    body); `wrapped_schematic` is that bench's own testbench, netlisted
    unmodified.

    `temp_override`/`supply_override`/`process_override` restrict the runner's
    outer temperature/supply/process axis. Two distinct reasons a bench does
    this, both ending in the same `is_subset` bookkeeping:

    - the deck sweeps that axis INTERNALLY, so outer points would be identical
      reruns (`output-voltage-tc`'s box TC collapses temperature;
      `line-regulation`'s in-deck `dc v1 2.97 3.63 ...` sweep collapses supply,
      since ngspice's `.dc <source>` sweep overrides the outer `vsup` value for
      that source regardless of the corner loop);
    - issue #16's Acceptance Criteria ask for a bench "at worst corners"
      rather than over the full matrix -- which is what `process_override`
      (added by the startup increment) exists for, alongside the temperature
      and supply extremes.

    Any of the three makes the run a subset, so `subset_reason` is then
    REQUIRED -- there is no `--subset-reason` flag on this path, and
    `sim/README.md` makes the justification a prose obligation for bespoke
    scripts.

    `claim_split` names the phrase in the wrapped manifest's own `claim` at
    which its schematic-level provenance description begins; everything from
    there is dropped and `claim_tail` is appended instead. It defaults to
    `"Measures "` (what the first three post-layout benches' manifests all
    use). Passing it EXPLICITLY also makes its presence mandatory: a manifest
    whose claim does not contain the marker would otherwise silently keep its
    "... design/bandgap_core.sch ..." sentence in an `extracted`-provenance
    record, which is exactly the mislabeling issue #16 is guarding against.

    Exit status matches `corner-run.py`: 0 all checks passed, 2 a record was
    written but something failed (raises otherwise, so the caller maps
    HarnessError/PostLayoutError to 1).
    """
    args = parse_post_layout_args(argv)
    pin = cr.load_pin()
    pdk = cr.resolve_pdk(pin)
    if not pdk.matches_pin and not args.allow_pdk_mismatch:
        raise cr.HarnessError(
            f"installed PDK {pdk.variant} is open_pdks {pdk.installed_commit}, but "
            f"sim/pdk.json pins {pin['open_pdks_commit']} (use --allow-pdk-mismatch to override)"
        )
    if not shutil.which("ngspice"):
        raise cr.HarnessError("ngspice not found on PATH")
    if not shutil.which("klt"):
        raise cr.HarnessError("klt (klayout-tools) not found on PATH")

    exp = cr.load_experiment(SIM_DIR / wrapped_experiment)
    # exp.raw["claim"]'s trailing sentence describes the SCHEMATIC bench this
    # record wraps ("Measures design/bandgap_core.sch ...") -- accurate for the
    # manifest's own schematic-level records, misleading for this one. Keep the
    # spec-line identification, replace the provenance tail.
    marker = claim_split if claim_split is not None else "Measures "
    if claim_split is not None and claim_split not in exp.raw["claim"]:
        raise cr.HarnessError(
            f"{slug}: claim_split {claim_split!r} does not occur in "
            f"{wrapped_experiment}'s own claim -- the post-layout record would keep "
            "that manifest's schematic-level provenance sentence verbatim"
        )
    claim_head = exp.raw["claim"].split(marker)[0].rstrip()
    claim_text = claim_head + " " + claim_tail

    class _Args:
        quick = False
        process = process_override
        temp = temp_override
        supply = supply_override

    matrix, is_subset = cr.build_matrix(exp, _Args(), pin)
    if is_subset and not subset_reason:
        raise cr.HarnessError(
            f"{slug}: the resolved matrix is a subset of {wrapped_experiment}'s own "
            "corners but no subset_reason was supplied -- sim/README.md requires the "
            "justification in the record body"
        )
    reason = subset_reason if is_subset else ""

    git_info = cr.git_state()
    now = datetime.now(timezone.utc)
    record_id = f"{now:%Y%m%d}-{now:%H%M%S}-{git_info['sha']}"

    records_dir = here / "records"
    snapshots_dir = here / "netlist-snapshots"
    corners_dir = here / "corners" / record_id
    record_md = records_dir / f"{record_id}.md"
    record_json = records_dir / f"{record_id}.json"
    snapshot = snapshots_dir / f"{record_id}.spice"
    for path in (record_md, record_json, snapshot, corners_dir):
        if path.exists():
            raise cr.HarnessError(f"{path} already exists — sim/ is append-only, refusing to overwrite")

    run_dir = SIM_DIR / "build" / slug / record_id
    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SIM_DIR / "spiceinit", run_dir / ".spiceinit")

    body, layout_provenance = build_extracted_body(
        cr, pdk, run_dir, here / "parasitics-snapshot", wrapped_schematic
    )

    print(f"experiment      : {slug}")
    print(f"record id       : {record_id}")
    print(f"layout record   : {layout_provenance['layout_record_id']}")
    print(f"parasitics      : {layout_provenance['parasitics_snapshot']['source']}")
    print(f"corner points   : {len(matrix)}" + (" (SUBSET)" if is_subset else " (full matrix)"))

    if args.dry_run:
        print("\n-- corner list --")
        for corner in matrix:
            print(f"  {corner.id}")
        print(f"\n-- deck for {matrix[0].id} --")
        print(cr.build_deck(exp, pdk, matrix[0], body))
        print("\n(dry run: nothing written under sim/)")
        return 0

    results = []
    for i, corner in enumerate(matrix, start=1):
        log_path = corners_dir / f"{corner.id}.log"
        res = cr.run_corner(exp, pdk, corner, body, run_dir, log_path, args.timeout)
        results.append(res)
        summary = ", ".join(
            f"{c['name']}={'n/a' if c['value'] is None else format(c['value'], '.6g')}"
            for c in res["measurements"]
        )
        print(f"[{i:>3}/{len(matrix)}] {corner.id:<20} " f"{'PASS' if res['pass'] else 'FAIL'}  {summary}")

    spreads = cr.spread_checks(exp, results)
    overall = all(r["pass"] for r in results) and all(s["pass"] for s in spreads)

    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("\n".join(body) + "\n.end\n")

    record = {
        "record_id": record_id,
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "author": args.author or cr.default_author(),
        "supersedes": args.supersedes,
        "experiment": {
            "slug": slug,
            "title": exp.raw.get("title", exp.slug) + " -- POST-LAYOUT (extracted netlist)",
            "claim": claim_text,
            "provenance": "extracted",
            "provenance_source": (
                f"{layout_provenance['layout_gds']} via `klt extract --parasitics` "
                f"(layout record {layout_provenance['layout_record_id']}), translated by "
                "sim/bin/post_layout_common.py, wrapped over the unmodified "
                f"{wrapped_schematic}"
            ),
            "statistical_convention": exp.raw.get("statistical_convention", "N/A"),
        },
        "layout_provenance": layout_provenance,
        "pdk": {
            "root": str(pdk.root),
            "variant": pdk.variant,
            "installed_commit": pdk.installed_commit,
            "pinned_commit": pin["open_pdks_commit"],
            "matches_pin": pdk.matches_pin,
            "lib_file": str(pdk.lib_file),
        },
        "tools": cr.tool_versions(),
        "git": git_info,
        "matrix": {
            "process": cr.unique_in_order(c.process for c in matrix),
            "temperature_c": sorted({c.temp_c for c in matrix}),
            "supply_v": sorted({c.supply_v for c in matrix}),
            "n_points": len(matrix),
            "is_subset": is_subset,
            "subset_reason": reason,
            "points": [[c.process, c.temp_c, c.supply_v] for c in matrix],
            "point_ids": [c.id for c in matrix],
        },
        "corners": results,
        "spread_checks": spreads,
        "overall_pass": overall,
        "links": {
            "testbench": wrapped_schematic,
            "manifest": str((SIM_DIR / wrapped_experiment / "experiment.json").relative_to(REPO_ROOT)),
            "netlist_snapshot": str(snapshot.relative_to(REPO_ROOT)),
            "corners_dir": str(corners_dir.relative_to(REPO_ROOT)) + "/",
            "json": str(record_json.relative_to(REPO_ROOT)),
            "record": str(record_md.relative_to(REPO_ROOT)),
        },
    }

    records_dir.mkdir(parents=True, exist_ok=True)
    record_json.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    record_md.write_text(cr.render_record(record))

    print()
    print(f"record  : {record_md.relative_to(REPO_ROOT)}")
    print(f"json    : {record_json.relative_to(REPO_ROOT)}")
    print(f"logs    : {corners_dir.relative_to(REPO_ROOT)}/")
    print(f"overall : {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 2


def main_wrapper(cr, run) -> None:
    """`if __name__ == "__main__":` body shared by the per-bench scripts --
    maps the two harness exception types to exit status 1 (no record written),
    the same convention `corner-run.py` uses."""
    try:
        sys.exit(run(sys.argv[1:]))
    except (cr.HarnessError, PostLayoutError) as err:
        print(f"{Path(sys.argv[0]).name}: error: {err}", file=sys.stderr)
        sys.exit(1)
