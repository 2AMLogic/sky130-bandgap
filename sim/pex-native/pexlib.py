#!/usr/bin/env python3
"""Shared helpers for the native `klt pex` pilot (issue #335).

Pilot bench: the output-voltage-TC bench (spec rows 1a/1b) on the composed,
injector-inclusive cell. Three jobs live here so `measure_command.py`,
`check_inputs.py` and the tests share one implementation:

* `compose_reference()` -- the SCHEMATIC reference netlist, flattened to the
  extracted cell's own pin list (`klt pex` compares the reference's pins with
  the extracted cell's, so a 4-pin reference cannot be compared with the
  13-pin routed cell). Nets the layout labels for LVS visibility (D1 D2 NE NG
  PN TAIL VA VB VBQ) are nets of the same name in the flat schematic.
* `check_reference()` / `check_matrix()` -- the input checks the pilot refuses
  to run without (pin list/order, injector present, full corner matrix).
* `build_deck()` -- the per-corner ngspice deck, built from the bench manifest
  `sim/output-voltage-tc/experiment.json` so measurements are defined once.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
DESIGN_NETLIST_DIR = REPO_ROOT / "design" / "netlist"
EXPERIMENT_JSON = REPO_ROOT / "sim" / "output-voltage-tc" / "experiment.json"

sys.path.insert(0, str(REPO_ROOT / "scripts" / "ci"))

# Re-exported on purpose: `pexlib.sha256_text` / `pexlib.sha256_file` is how
# `compose_reference.py` and `grade_deltas.py` already reach them.
from content_hash import sha256_file, sha256_text  # noqa: E402, F401

TOP = "bandgap_core_routed"
#: The four pins the testbench instantiates `bandgap_core` through.
EXPOSED = ("VOUT", "GDRV", "VDD", "VSS")
#: Pin list/order `klt pex` 0.8.0 extracts for the composed routed cell.
ROUTED_PORTS = (
    "D1", "D2", "GDRV", "NE", "NG", "PN", "TAIL", "VA", "VB", "VBQ", "VDD", "VOUT", "VSS",
)
#: Declared PVT matrix of the pilot bench (process x supply; temperature is
#: swept inside the deck). Must equal the experiment manifest's matrix.
PROCESSES = ("tt", "ss", "ff", "sf", "fs")
SUPPLIES = (2.97, 3.3, 3.63)
INJECTOR_DEVICES = ("XMPC1", "XMPC2", "XMNS", "XQS", "XMNI", "XMNC")


class PexNativeError(RuntimeError):
    """An input check failed; the pilot must not produce evidence."""


def corner_ids() -> list[str]:
    return [f"{p}_27c_{v:.2f}v" for p in PROCESSES for v in SUPPLIES]


# --------------------------------------------------------------------------
# reference composition
# --------------------------------------------------------------------------


def _join_continuations(text: str) -> list[str]:
    out: list[str] = []
    for ln in text.splitlines():
        if ln.startswith("+") and out:
            out[-1] += " " + ln[1:].strip()
        else:
            out.append(ln)
    return out


def _devices_and_params(lines: list[str]) -> tuple[list[str], list[str]]:
    devs, params = [], []
    for ln in lines:
        s = ln.strip()
        if re.match(r"^\.param\b", s, re.I):
            params.append(s)
        elif re.match(r"^[XRCEMQ]", s):
            devs.append(s)
    return devs, params


def _remap(card: str, mapping: dict[str, str], n_nodes_by_prefix=None) -> str:
    """Rename nodes of an `X...` card whose node list ends at the first token
    that is a subckt/model name (starts with `sky130_` or is not a node)."""
    toks = card.split()
    name, rest = toks[0], toks[1:]
    nodes = []
    i = 0
    while i < len(rest) and not rest[i].startswith("sky130_"):
        nodes.append(rest[i])
        i += 1
    tail = rest[i:]
    return " ".join([name] + [mapping.get(n, n) for n in nodes] + tail)


def compose_reference(design_dir: Path = DESIGN_NETLIST_DIR) -> str:
    """Flat schematic reference `.subckt bandgap_core_routed <13 pins>`:
    core + error amp + startup injector, device-level, same pins as the
    routed layout. Deterministic for a given set of design netlists."""
    core_text = (design_dir / "bandgap_core.spice").read_text()
    inj_text = (design_dir / "startup_injector.spice").read_text()

    m = re.search(r"^\.subckt error_amp\b.*?^\.ends\b", core_text, re.S | re.M | re.I)
    if not m:
        raise PexNativeError("design/netlist/bandgap_core.spice has no embedded .subckt error_amp")
    amp_block = m.group(0)
    core_top = core_text[: m.start()]

    core_devs, core_params = _devices_and_params(_join_continuations(core_top))
    amp_devs, amp_params = _devices_and_params(_join_continuations(amp_block))
    inj_devs, inj_params = _devices_and_params(_join_continuations(inj_text))

    # XAMP VB VA GDRV TAIL VDD VSS error_amp  <->  VINP VINN AOUT ITAIL VDD VSS
    xamp = [d for d in core_devs if d.startswith("XAMP ")]
    if len(xamp) != 1:
        raise PexNativeError("expected exactly one XAMP card in design/netlist/bandgap_core.spice")
    core_devs = [d for d in core_devs if not d.startswith("XAMP ")]
    xt = xamp[0].split()
    actual = xt[1:7]
    amp_map = dict(zip(("VINP", "VINN", "AOUT", "ITAIL", "VDD", "VSS"), actual))
    inj_map = {"VSENSE": "VOUT"}  # injector senses the output (reference.spice: MMNS gate = VOUT)

    flat = list(core_devs)
    flat += [_remap(d, amp_map) for d in amp_devs]
    flat += [_remap(d, inj_map) for d in inj_devs]
    names = [d.split()[0] for d in flat]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise PexNativeError(f"device name collision composing the reference: {dup}")

    seen, params = set(), []
    for p in core_params + amp_params + inj_params:
        if p not in seen:
            seen.add(p)
            params.append(p)
    header = [
        "* sim/pex-native schematic reference -- GENERATED by compose_reference.py, do not edit.",
        "* Flat, device-level composed cell (core + error_amp + startup_injector) with the",
        "* routed layout's 13-pin list, so `klt pex` compares like with like (issue #335).",
        f"* inputs: {', '.join(f'design/netlist/{n}.spice' for n in ('bandgap_core', 'startup_injector'))}",
    ]
    body = [f".subckt {TOP} {' '.join(ROUTED_PORTS)}"] + flat + [f".ends {TOP}", ""]
    return "\n".join(header + params + body)


# --------------------------------------------------------------------------
# input checks
# --------------------------------------------------------------------------


def parse_ports(text: str, name: str) -> tuple[str, ...]:
    m = re.search(rf"^\.subckt\s+{re.escape(name)}\s+(.+)$", text, re.I | re.M)
    if not m:
        raise PexNativeError(f"no .SUBCKT {name} header found")
    return tuple(m.group(1).split())


def check_reference(reference_text: str, extracted_text: str) -> None:
    """Raise `PexNativeError` unless the schematic reference can be compared
    with the extracted cell: identical pin list in identical order, and the
    startup injector is present in both."""
    ref_ports = parse_ports(reference_text, TOP)
    ext_ports = parse_ports(extracted_text, TOP)
    if tuple(p.upper() for p in ref_ports) != tuple(p.upper() for p in ext_ports):
        raise PexNativeError(
            "reference/extracted pin mismatch: reference declares "
            f"{' '.join(ref_ports)} but the extracted cell declares {' '.join(ext_ports)} "
            "(pin list AND order must match; bare-core vs composed-cell compares different circuits)"
        )
    cards = {ln.split()[0].upper() for ln in _join_continuations(reference_text)
             if ln.strip() and not ln.lstrip().startswith(("*", "."))}
    missing = [d for d in INJECTOR_DEVICES if d not in cards]
    if missing:
        raise PexNativeError(
            f"reference lacks the startup injector (missing device cards {missing}); the extracted "
            "cell draws it, so a bare-core reference is a different circuit"
        )
    if not {"NE", "NG"} <= {p.upper() for p in ext_ports}:
        raise PexNativeError("extracted cell does not promote the injector nets NE/NG: injector not drawn")


def check_matrix(measurement_doc: dict, expected: list[str] | None = None) -> None:
    """Raise unless `measurement_doc` (the `{"corners": [...]}` document a
    measure command prints) carries every declared corner exactly once, each
    with at least one measurement entry (an errored corner must be present
    with status "error", never dropped)."""
    expected = expected or corner_ids()
    got = [c.get("corner_id") for c in measurement_doc.get("corners", [])]
    dups = sorted({g for g in got if got.count(g) > 1})
    missing = [e for e in expected if e not in got]
    extra = [g for g in got if g not in expected]
    if missing or dups or extra:
        raise PexNativeError(
            f"incomplete corner matrix: {len(got)} of {len(expected)} corners; "
            f"missing={missing} duplicate={dups} unexpected={extra}"
        )
    for c in measurement_doc["corners"]:
        if not c.get("measurements"):
            raise PexNativeError(f"corner {c.get('corner_id')} has no measurement entries")


# --------------------------------------------------------------------------
# pinned-klt (0.8.0) extraction dialect
# --------------------------------------------------------------------------

# klt 0.8.0 writes each resistor as a SUBCKT-call card
#   X$98 <a> <b> <bulk> res_high_po r=2003.841367 L=5U W=1U
# whereas the 3-terminal R-card form `R$n a b bulk <value> res_high_po` is what
# `sim/bin/post_layout_common.translate_extracted_netlist` recognises. Left
# alone, every resistor reaches ngspice as an unknown subckt. Normalise the
# card here (value-preserving) instead of editing the shared translator.
_X_RES_RE = re.compile(
    r"^X(\$\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+res_high_po\s+r=([0-9.eE+-]+)\b.*$"
)


def normalize_klt_resistors(text: str) -> tuple[str, int]:
    """Rewrite klt-0.8.0 `X$n a b bulk res_high_po r=V ...` cards to the
    `R$n a b bulk V res_high_po` form. Returns (text, n_rewritten)."""
    out, n = [], 0
    for ln in text.splitlines():
        m = _X_RES_RE.match(ln.strip())
        if m:
            name, a, b, bulk, val = m.groups()
            out.append(f"R{name} {a} {b} {bulk} {val} res_high_po")
            n += 1
        else:
            out.append(ln)
    return "\n".join(out) + "\n", n


# --------------------------------------------------------------------------
# deck
# --------------------------------------------------------------------------

_TB_BODY = """V1 VDD 0 'vsup'
.save i(v1)
XBG VREF GDRV VDD 0 bandgap_core
.nodeset v(vref)=1.2 v(gdrv)=2.2
"""


def wrapper(core_ports: tuple[str, ...]) -> str:
    port_map = {p: (p if p in EXPOSED else f"{p}_INT") for p in core_ports}
    call = " ".join(port_map[p] for p in core_ports)
    return f".subckt bandgap_core {' '.join(EXPOSED)}\nXCORE {call} {TOP}\n.ends bandgap_core\n"


def build_deck(core_block: str, process: str, supply_v: float, pdk_lib: str, manifest: dict) -> str:
    """Per-corner ngspice deck: same preamble/analyses/measurement lets as
    `sim/bin/corner-run.py::build_deck()` for `output-voltage-tc`, DUT body =
    `core_block` (a flat `.subckt bandgap_core_routed`) behind the 4-pin wrapper."""
    deck = manifest.get("deck", {})
    head = [f"* pex-native corner deck {process} 27C {supply_v:.2f}V", f".param vsup={supply_v}"]
    head += [f".option {o}" for o in deck.get("options") or []]
    head += [".temp 27", f'.lib "{pdk_lib}" {process}']
    control = [".control", "save all"] + list(deck.get("analyses") or ["op"])
    for m in manifest["measurements"]:
        control.append(f"let meas_{m['name']} = {m['expr']}")
    for m in manifest["measurements"]:
        control.append(f"print meas_{m['name']}")
    control += ["quit", ".endc", ".end", ""]
    core_ports = parse_ports(core_block, TOP)
    return "\n".join(head + [_TB_BODY, wrapper(core_ports), core_block, ""] + control)
