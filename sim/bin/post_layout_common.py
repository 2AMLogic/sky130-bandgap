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

Callers (see `sim/output-voltage-tc-post-layout/run_post_layout_vref_tc.py`
for the reference usage) chain these three pieces plus
`build_core_wrapper`/`strip_schematic_subckts` to produce a `bandgap_core`
netlist body that is a drop-in replacement for `design/bandgap_core.sym` in
ANY existing `sim/*/testbench/*.sch` that instantiates it (same 4-pin
interface: `VOUT GDRV VDD VSS`) -- this is what lets a follow-on increment
of issue #16 reuse this module for `psrr-dc`, `line-regulation`,
`quiescent-current`, `startup-time`, `startup-stability`, `startup-ramp`
without re-deriving any of the above.
"""

from __future__ import annotations

import json
import re
import subprocess
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
    """
    text = body_text
    for name in names:
        pattern = (
            rf"\n\* expanding.*?symbol:\s*design/{re.escape(name)}\.sym.*?"
            rf"\n\.subckt\s+{re.escape(name)}\b.*?\n\.ends\n"
        )
        new_text, n = re.subn(pattern, "\n", text, flags=re.S | re.I)
        if n == 0:
            raise PostLayoutError(f"no .subckt {name} ... .ends block found to strip")
        text = new_text
    return text
