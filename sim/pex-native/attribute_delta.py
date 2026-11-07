#!/usr/bin/env python3
"""Attribute the native-pex pilot's Vref delta (issue #486).

Read-only analysis of a committed pilot record (default
`records/20261106-pilot/`); it never writes into the record.

    attribute_delta.py legs   [--record DIR]   # resistor-only network: leg table, per-link parasitic
    attribute_delta.py rtc                     # normaliser check: model vs fixed R at -40/27/125 C
    attribute_delta.py probe  [--record DIR]   # tt/27C/3.30V, 5 single-corner local ngspice runs
    attribute_delta.py all    [--record DIR]   # all three, as the README section's tables

`legs` is pure Python (numpy). `rtc` is ONE ngspice run, `probe` is five
sequential single-corner runs (schematic, extracted, and three ablations of the
extracted netlist) -- a debug probe, never a corner grid; anything wider must go
through `klt sim` to the batch fleet.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "bin"))
import pexlib  # noqa: E402

DEFAULT_RECORD = HERE / "records" / "20261106-pilot"
PINS = ("VOUT", "VA", "VB", "VBQ")
#: leg name -> (start pin, end pin) of the resistor-only network
LEGS = {"R1": ("VB", "VBQ"), "R2A": ("VOUT", "VA"), "R2B": ("VOUT", "VB")}
_TERM_RE = re.compile(r"__t\d+$")
PROBE_CORNER = ("tt", 3.30)
_FLOAT = r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?"


def base_net(node: str) -> str:
    """`$7__t1` -> `$7`: the star hub a terminal node hangs off."""
    return _TERM_RE.sub("", node)


# --------------------------------------------------------------------------
# resistor-only network
# --------------------------------------------------------------------------


def parse_resistors(text: str) -> tuple[list[tuple], list[tuple]]:
    """Return (devices, parasitics). devices: (name, a, b, ohms) from klt's
    `X$n a b bulk res_high_po r=V` cards; parasitics: every plain `R` card."""
    devices, parasitics = [], []
    for ln in pexlib._join_continuations(text):
        s = ln.strip()
        m = pexlib._X_RES_RE.match(s)
        if m:
            name, a, b, _bulk, val = m.groups()
            devices.append((name, a, b, float(val)))
        elif s[:1] == "R":
            p = s.split()
            parasitics.append((p[0], p[1], p[2], float(p[3])))
    return devices, parasitics


def effective_resistance(edges: list[tuple], a: str, b: str) -> float:
    """Two-terminal resistance of a resistor network (nodal analysis)."""
    import numpy as np

    nodes = sorted({n for e in edges for n in e[:2]})
    idx = {n: i for i, n in enumerate(nodes)}
    # keep only the connected component holding `a` (dangling islands are singular)
    adj: dict[str, set[str]] = {}
    for x, y, _v in edges:
        adj.setdefault(x, set()).add(y)
        adj.setdefault(y, set()).add(x)
    comp, todo = {a}, [a]
    while todo:
        for nb in adj.get(todo.pop(), ()):
            if nb not in comp:
                comp.add(nb)
                todo.append(nb)
    if b not in comp:
        raise ValueError(f"{b} not connected to {a}")
    order = sorted(comp)
    ci = {n: i for i, n in enumerate(order)}
    g = np.zeros((len(order), len(order)))
    for x, y, v in edges:
        if x in ci and y in ci:
            c = 1.0 / v
            i, j = ci[x], ci[y]
            g[i, i] += c
            g[j, j] += c
            g[i, j] -= c
            g[j, i] -= c
    keep = [i for n, i in ci.items() if n != a]
    kk = {i: k for k, i in enumerate(keep)}
    rhs = np.zeros(len(keep))
    rhs[kk[ci[b]]] = 1.0
    sol = np.linalg.solve(g[np.ix_(keep, keep)], rhs)
    return float(sol[kk[ci[b]]])


def assign_legs(devices: list[tuple]) -> dict[str, list[tuple]]:
    """Group device cards into legs: components of the device graph over base
    nets with the four pin nets cut; the pin pair a component touches names it."""
    by_net: dict[str, list[int]] = {}
    for i, (_n, a, b, _v) in enumerate(devices):
        for node in (a, b):
            by_net.setdefault(base_net(node), []).append(i)
    seen: set[int] = set()
    legs: dict[str, list[tuple]] = {}
    for start in range(len(devices)):
        if start in seen:
            continue
        comp, pins, todo = [], set(), [start]
        seen.add(start)
        while todo:
            i = todo.pop()
            comp.append(devices[i])
            for node in devices[i][1:3]:
                net = base_net(node)
                if net in PINS:
                    pins.add(net)
                    continue
                for j in by_net[net]:
                    if j not in seen:
                        seen.add(j)
                        todo.append(j)
        name = next((k for k, v in LEGS.items() if set(v) == pins), None)
        if name is None:
            raise ValueError(f"device component touching pins {sorted(pins)} matches no leg")
        legs[name] = comp
    return legs


def analyse_legs(text: str) -> dict:
    devices, parasitics = parse_resistors(text)
    legs = assign_legs(devices)
    edges = [(a, b, v) for _n, a, b, v in parasitics] + [(a, b, v) for _n, a, b, v in devices]
    star: dict[str, float] = {}
    for _n, a, b, v in parasitics:  # star arm: `<terminal node> <hub> ohms`
        star[a] = v if base_net(a) == b else star.get(a, v)
    term_count: dict[str, int] = {}
    for _n, a, b, _v in devices:
        for node in (a, b):
            term_count[base_net(node)] = term_count.get(base_net(node), 0) + 1
    out: dict = {"n_device_cards": len(devices), "n_r_cards": len(parasitics), "legs": {}}
    links: list[float] = []
    for name, (p, q) in LEGS.items():
        cards = legs[name]
        dev_sum = sum(c[3] for c in cards)
        total = effective_resistance(edges, p, q)
        internal = {base_net(n) for c in cards for n in c[1:3]} - set(PINS)
        link_r = []
        for net in sorted(internal):
            arms = [star[n] for c in cards for n in c[1:3] if base_net(n) == net and n in star]
            if term_count.get(net) == 2 and len(arms) == 2:
                link_r.append(sum(arms))
        links += link_r
        out["legs"][name] = {
            "n_units": len(cards), "device_sum_ohm": dev_sum, "extracted_ohm": total,
            "delta_pct": 100.0 * (total / dev_sum - 1.0),
            "internal_link_parasitic_ohm": sum(link_r),
            "pin_net_and_other_ohm": total - dev_sum - sum(link_r),
        }
    r1, r2b = out["legs"]["R1"], out["legs"]["R2B"]
    out["K_device"] = r2b["device_sum_ohm"] / r1["device_sum_ohm"]
    out["K_extracted"] = r2b["extracted_ohm"] / r1["extracted_ohm"]
    out["K_change_pct"] = 100.0 * (out["K_extracted"] / out["K_device"] - 1.0)
    out["link"] = {
        "n_links": len(links), "min_ohm": min(links), "median_ohm": statistics.median(links),
        "max_ohm": max(links), "old_star_link_ohm": 459.4543,
        "n_within_5pct_of_old_star": sum(abs(x / 459.4543 - 1) < 0.05 for x in links),
    }
    return out


# --------------------------------------------------------------------------
# ngspice helpers
# --------------------------------------------------------------------------


def _pdk():
    import post_layout_common as plc

    cr = plc.sim_common.load_corner_run()
    return cr.resolve_pdk(cr.load_pin())


def _run_ngspice(deck: str, workdir: Path) -> str:
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "deck.spice").write_text(deck)
    (workdir / ".spiceinit").write_text((pexlib.REPO_ROOT / "sim" / "spiceinit").read_text())
    proc = subprocess.run(["ngspice", "-b", "deck.spice"], cwd=workdir, capture_output=True,
                          text=True, timeout=1800)
    log = proc.stdout + "\n" + proc.stderr
    (workdir / "ngspice.log").write_text(log)
    return log


# --------------------------------------------------------------------------
# step 3: normaliser value + temperature behaviour
# --------------------------------------------------------------------------

TEMPS = (-40, 27, 125)


def _ref_cards(prefixes: tuple[str, ...]) -> list[str]:
    ref = (HERE / "reference" / "bandgap_core_composed.spice").read_text()
    return [ln for ln in ref.splitlines() if ln.split(" ", 1)[0] in prefixes]


def _ref_params() -> list[str]:
    ref = (HERE / "reference" / "bandgap_core_composed.spice").read_text()
    return [ln for ln in ref.splitlines() if ln.startswith(".param")]


def rtc_deck(pdk_lib: str, units: dict[str, float]) -> str:
    """Resistance-vs-T deck. Each model card is paired with the fixed `R` card
    `normalize_klt_resistors` + `translate_extracted_netlist` would emit for it."""
    lines = ["* normaliser value/TC check (issue #486)", f'.lib "{pdk_lib}" tt'] + _ref_params()
    probes = []
    for i, (label, ohms) in enumerate(units.items()):
        length = {"unit_L5": 5, "unit_L0p5": 0.5}[label]
        lines += [f"Vm{i} m{i} 0 1", f"Xm{i} m{i} 0 0 sky130_fd_pr__res_high_po W=1 L={length} mult=1 m=1",
                  f"Vf{i} f{i} 0 1", f"Rf{i} f{i} 0 {ohms}"]
        probes += [(f"model_{label}", f"vm{i}"), (f"fixed_{label}", f"vf{i}")]
    # whole schematic legs, exactly as the reference writes them (head-aware, E-source scaled)
    leg_cards = {
        "R2A": (("XR2A", "XR2A_HD", "ER2A_HD"), {"VOUT": "pA", "VA": "0"}),
        "R2B": (("XR2B", "XR2B_HD", "ER2B_HD"), {"VOUT": "pB", "VB": "0"}),
        "R1": (("XR1", "XR1_HD", "ER1_HD"), {"VB": "pC", "VBQ": "0"}),
    }
    for (leg, (prefixes, pinmap)), src in zip(leg_cards.items(), ("vA", "vB", "vC")):
        for card in _ref_cards(prefixes):
            toks = [pinmap.get(t, t) for t in card.split()]
            toks = ["0" if t == "VSS" else t for t in toks]
            lines.append(" ".join(toks))
        lines.append(f"{src} {pinmap and [v for v in pinmap.values() if v != '0'][0]} 0 1")
        probes.append((f"schematic_{leg}", src.lower()))
    lines.append(".control")
    for t in TEMPS:
        lines.append(f"dc temp {t} {t} 1")
        for label, src in probes:
            lines.append(f'echo "RTC {t} {label} $&{src}#branch"')
    lines += ["quit", ".endc", ".end", ""]
    return "\n".join(lines)


def run_rtc(workdir: Path | None = None) -> dict:
    pdk = _pdk()
    deck = rtc_deck(str(pdk.lib_file), {"unit_L5": 2003.841367, "unit_L0p5": 542.118769})
    log = _run_ngspice(deck, workdir or Path(tempfile.mkdtemp(prefix="attr-rtc-")))
    out: dict = {}
    for m in re.finditer(rf"^RTC (\S+) (\S+) ({_FLOAT})\s*$", log, re.M):
        t, label, cur = int(m.group(1)), m.group(2), float(m.group(3))
        out.setdefault(label, {})[t] = 1.0 / abs(cur)
    if not out:
        raise RuntimeError("no RTC lines in ngspice output:\n" + log[-2000:])
    return out


# --------------------------------------------------------------------------
# step 2: single-corner probe, five variants of the same cell
# --------------------------------------------------------------------------

_PARASITIC_RE = re.compile(r"^(R(?!\$)\S+)\s+(\S+)\s+(\S+)\s+(" + _FLOAT + r")\s*$")
SHORT_OHM = "1m"
_X_RAW_RE = re.compile(
    r"^X(\$\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+res_high_po\s+r=\S+\s+L=([0-9.]+)U\s+W=([0-9.]+)U\s*$"
)
PROBE_NODES = {
    "VREF": "vref", "VA": "xbg.va_int", "VB": "xbg.vb_int", "VBQ": "xbg.vbq_int", "VOUT": "vref",
}


def _short_parasitics(text: str, only_array: bool | None) -> str:
    """Set parasitic `R` cards to ~0 ohm. only_array=None: all; True: leave only
    resistor-array-terminal stars (shorting the rest); False: short only those."""
    array_nodes = set()
    for ln in text.splitlines():
        m = pexlib._X_RES_RE.match(ln.strip())
        if m:
            array_nodes.update(m.group(2, 3))
    out = []
    for ln in text.splitlines():
        m = _PARASITIC_RE.match(ln.strip())
        if m:
            is_array = m.group(2) in array_nodes or m.group(3) in array_nodes
            short = only_array is None or (only_array and not is_array) or (only_array is False and is_array)
            if short:
                ln = f"{m.group(1)} {m.group(2)} {m.group(3)} {SHORT_OHM}"
        out.append(ln)
    return "\n".join(out) + "\n"


def _model_resistors(text: str) -> str:
    """Replace klt's `X$n ... res_high_po r=V L= W=` cards by the PDK model
    resistor of that geometry (what the schematic uses) instead of a fixed R."""
    out = []
    for ln in text.splitlines():
        m = _X_RAW_RE.match(ln.strip())
        if m:
            name, a, b, bulk, length, width = m.groups()
            ln = (f"XRM{name} {a} {b} {bulk} sky130_fd_pr__res_high_po "
                  f"W={float(width):g} L={float(length):g} mult=1 m=1")
        out.append(ln)
    return "\n".join(out) + "\n"


def _extracted_block(text: str) -> str:
    import measure_command as mc

    return mc.side_block("extracted", text)


def variants(extracted_text: str, reference_text: str) -> dict[str, str]:
    import measure_command as mc

    return {
        "schematic": mc.side_block("schematic", reference_text),
        "extracted": _extracted_block(extracted_text),
        "extracted_model_R": _extracted_block(_model_resistors(extracted_text)),
        "array_parasitics_only": _extracted_block(_short_parasitics(extracted_text, True)),
        "no_parasitics": _extracted_block(_short_parasitics(extracted_text, None)),
    }


def probe_deck(block: str, pdk_lib: str) -> str:
    process, supply = PROBE_CORNER
    manifest = json.loads(pexlib.EXPERIMENT_JSON.read_text())
    head = [f"* attribute_delta probe {process} 27C {supply:.2f}V", f".param vsup={supply}"]
    head += [f".option {o}" for o in manifest["deck"].get("options") or []]
    head += [".temp 27", f'.lib "{pdk_lib}" {process}']
    control = [".control", "save all", "op"]
    for label in ("VREF", "VA", "VB", "VBQ"):
        control.append(f"print v({PROBE_NODES[label]})")
    control += ["quit", ".endc", ".end", ""]
    core_ports = pexlib.parse_ports(block, pexlib.TOP)
    return "\n".join(head + [pexlib._TB_BODY, pexlib.wrapper(core_ports), block, ""] + control)


def run_probe(record: Path, workdir: Path | None = None) -> dict:
    pdk = _pdk()
    ext = (record / "extracted.spice").read_text()
    ref = (HERE / "reference" / "bandgap_core_composed.spice").read_text()
    root = workdir or Path(tempfile.mkdtemp(prefix="attr-probe-"))
    res: dict = {}
    for name, block in variants(ext, ref).items():
        log = _run_ngspice(probe_deck(block, str(pdk.lib_file)), root / name)
        by_node = {m.group(1): float(m.group(2))
                   for m in re.finditer(rf"^v\((\S+)\)\s*=\s*({_FLOAT})\s*$", log, re.M)}
        vals = {k: by_node[PROBE_NODES[k]] for k in ("VREF", "VA", "VB", "VBQ") if PROBE_NODES[k] in by_node}
        if set(vals) != {"VREF", "VA", "VB", "VBQ"}:
            raise RuntimeError(f"probe {name}: missing nodes, got {vals}\n{log[-2000:]}")
        vals["dVBE"] = vals["VB"] - vals["VBQ"]
        res[name] = vals
    return res


def decompose(probe: dict, legs: dict, k_schematic: float) -> dict:
    """Split the extracted-minus-schematic VREF delta (volts).

    VREF = VB + K * dVBE  (the R2B/R1 divider carries the PTAT current), so
        dVREF = dVB + (K_e - K_s) * dVBE_s + K_e * (dVBE_e - dVBE_s) + residual.
    The normaliser share is measured directly: extracted vs the same extracted
    netlist with PDK-model resistors in place of the fixed-R cards."""
    s, e = probe["schematic"], probe["extracted"]
    k_e = legs["K_extracted"]
    total = e["VREF"] - s["VREF"]
    parts = {
        "K_ratio": (k_e - k_schematic) * s["dVBE"],
        "branch_current_VB": e["VB"] - s["VB"],
        "dVBE_change": k_e * (e["dVBE"] - s["dVBE"]),
        "normaliser": e["VREF"] - probe["extracted_model_R"]["VREF"],
    }
    # the normaliser acts through the same nodes, so it is NOT added to the
    # identity above; report it as an independent measured share and let the
    # identity's own residual stand as the unexplained part.
    identity = parts["K_ratio"] + parts["branch_current_VB"] + parts["dVBE_change"]
    return {
        "total_V": total, **{f"{k}_V": v for k, v in parts.items()},
        "identity_sum_V": identity, "unexplained_V": total - identity,
        "array_parasitics_V": probe["array_parasitics_only"]["VREF"] - probe["no_parasitics"]["VREF"],
        "non_array_parasitics_V": e["VREF"] - probe["array_parasitics_only"]["VREF"],
        "no_parasitics_minus_schematic_V": probe["no_parasitics"]["VREF"] - s["VREF"],
    }


# --------------------------------------------------------------------------
# markdown
# --------------------------------------------------------------------------


def md_legs(a: dict) -> str:
    rows = ["| leg | units | device sum (ohm) | extracted incl. parasitics (ohm) | delta | internal-link parasitic (ohm) | pin-net/other (ohm) |",
            "|---|---|---|---|---|---|---|"]
    for n, v in a["legs"].items():
        rows.append(f"| `{n}` ({'->'.join(LEGS[n])}) | {v['n_units']} | {v['device_sum_ohm']:.2f} | "
                    f"{v['extracted_ohm']:.1f} | {v['delta_pct']:+.1f} % | "
                    f"{v['internal_link_parasitic_ohm']:.1f} | {v['pin_net_and_other_ohm']:.1f} |")
    k = a["link"]
    rows += ["", f"K = R2B/R1: device {a['K_device']:.4f}, extracted {a['K_extracted']:.4f} ({a['K_change_pct']:+.2f} %).",
             f"{k['n_links']} chain-internal links: {k['min_ohm']:.1f} / {k['median_ohm']:.1f} / {k['max_ohm']:.1f} ohm "
             f"(min/median/max); {k['n_within_5pct_of_old_star']} within 5 % of the old 2 x 229.7 = 459.5 ohm star."]
    return "\n".join(rows)


def md_probe(p: dict) -> str:
    cols = list(p)
    rows = ["| node | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for node in ("VREF", "VA", "VB", "VBQ", "dVBE"):
        rows.append(f"| `{node}` | " + " | ".join(f"{p[c][node]:.6f}" for c in cols) + " |")
    return "\n".join(rows)


def md_rtc(r: dict) -> str:
    rows = ["| resistor | " + " | ".join(f"{t} C" for t in TEMPS) + " |", "|---|" + "---|" * len(TEMPS)]
    for label, by_t in r.items():
        rows.append(f"| `{label}` | " + " | ".join(f"{by_t[t]:.3f}" for t in TEMPS) + " |")
    return "\n".join(rows)


def md_decomp(d: dict) -> str:
    mv = lambda x: f"{x * 1e3:+.3f}"  # noqa: E731
    return "\n".join([
        "| share of extracted - schematic `VREF` | mV |", "|---|---|",
        f"| total | {mv(d['total_V'])} |",
        f"| K-ratio change at fixed dVBE | {mv(d['K_ratio_V'])} |",
        f"| branch-current change (shift of VB) | {mv(d['branch_current_VB_V'])} |",
        f"| dVBE change x K | {mv(d['dVBE_change_V'])} |",
        f"| unexplained (identity residual) | {mv(d['unexplained_V'])} |",
        f"| normaliser (extracted vs model-R, measured) | {mv(d['normaliser_V'])} |",
        f"| memo: resistor-array parasitics | {mv(d['array_parasitics_V'])} |",
        f"| memo: all other-net parasitics | {mv(d['non_array_parasitics_V'])} |",
        f"| memo: no-parasitic extracted - schematic | {mv(d['no_parasitics_minus_schematic_V'])} |",
    ])


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("legs", "rtc", "probe", "all"))
    ap.add_argument("--record", type=Path, default=DEFAULT_RECORD)
    ap.add_argument("--json", action="store_true", help="emit JSON instead of markdown")
    args = ap.parse_args(argv)
    text = (args.record / "extracted.spice").read_text()
    result: dict = {}
    if args.cmd in ("legs", "all", "probe"):
        result["legs"] = analyse_legs(text)
    if args.cmd in ("rtc", "all"):
        result["rtc"] = run_rtc()
    if args.cmd in ("probe", "all"):
        result["probe"] = run_probe(args.record)
        rtc = result.get("rtc") or run_rtc()
        k_s = rtc["schematic_R2B"][27] / rtc["schematic_R1"][27]
        result["rtc"] = rtc
        result["K_schematic"] = k_s
        result["decomposition"] = decompose(result["probe"], result["legs"], k_s)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if "legs" in result:
        print("### Leg resistance\n\n" + md_legs(result["legs"]) + "\n")
    if "rtc" in result:
        print("### Resistor value and temperature behaviour\n\n" + md_rtc(result["rtc"]) + "\n")
    if "probe" in result:
        print(f"### Probe {PROBE_CORNER[0]} / 27 C / {PROBE_CORNER[1]:.2f} V (V)\n\n" + md_probe(result["probe"]) + "\n")
        print(f"K schematic (model R2B/R1 at 27 C) = {result['K_schematic']:.4f}\n")
        print("### Attribution\n\n" + md_decomp(result["decomposition"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
