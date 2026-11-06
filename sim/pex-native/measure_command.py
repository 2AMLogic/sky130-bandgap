#!/usr/bin/env python3
"""`klt pex --measure-command` hook for the native pex pilot (issue #335).

klt pex runs this twice (reference side, extracted side) with the netlist path
as the LAST argv element and `$KLT_PEX_SIDE` = `schematic` | `extracted`, and
reads a measurement document from stdout:
    {"corners": [{"corner_id": ..., "measurements": [{"name","value","status"}]}]}

Bench: output-voltage-TC (manifest sim/output-voltage-tc/experiment.json), the
declared 5 process x 3 supply matrix, temperature swept inside the deck.

Execution (host rule: corner grids go to the batch fleet, never a local loop):
  * default / `PEX_NATIVE_BACKEND=batch`: one `klt sim --backend batch` request
    per supply through sim/bin/batch_sim.py; a failed submit exits non-zero and
    is never retried locally.
  * `PEX_NATIVE_BACKEND=local` runs ONE corner only (`PEX_NATIVE_CORNERS`,
    e.g. `tt:3.30`) -- a debug probe. Its output is a partial matrix on
    purpose; `check_inputs.py` refuses it as evidence.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "bin"))
import pexlib  # noqa: E402
import post_layout_common as plc  # noqa: E402

MEAS_RE = re.compile(r"^meas_([A-Za-z0-9_]+)\s*=\s*(-?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)")


def side_block(side: str, text: str) -> str:
    """Flat `.subckt bandgap_core_routed` block (plus, for the schematic side,
    the `.param` lines it needs) from the netlist klt pex hands us."""
    if side == "extracted":
        text, n_res = pexlib.normalize_klt_resistors(text)
        translated, counts = plc.translate_extracted_netlist(text)
        if counts["res"] != n_res and n_res:
            raise pexlib.PexNativeError(
                f"resistor translation coverage mismatch: normalised {n_res}, translated {counts['res']}")
        return plc.extract_subckt_block(translated, pexlib.TOP)
    if side == "schematic":
        params = [ln for ln in text.splitlines() if ln.lstrip().lower().startswith(".param")]
        return "\n".join(params + [plc.extract_subckt_block(text, pexlib.TOP)])
    raise pexlib.PexNativeError(f"unknown KLT_PEX_SIDE {side!r}")


def parse_corners(spec: str | None) -> list[tuple[str, float]]:
    if not spec:
        return [(p, v) for p in pexlib.PROCESSES for v in pexlib.SUPPLIES]
    out = []
    for item in spec.split(","):
        p, v = item.split(":")
        out.append((p.strip(), float(v)))
    return out


def corner_id(process: str, supply: float) -> str:
    return f"{process}_27c_{supply:.2f}v"


def measure_local(block: str, corner: tuple[str, float], manifest: dict, pdk, workdir: Path) -> dict:
    process, supply = corner
    deck = pexlib.build_deck(block, process, supply, str(pdk.lib_file), manifest)
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "deck.spice").write_text(deck)
    (workdir / ".spiceinit").write_text((pexlib.REPO_ROOT / "sim" / "spiceinit").read_text())
    proc = subprocess.run(["ngspice", "-b", "deck.spice"], cwd=workdir, capture_output=True,
                          text=True, timeout=1800)
    (workdir / "ngspice.log").write_text(proc.stdout + "\n" + proc.stderr)
    values = {}
    for ln in (proc.stdout + "\n" + proc.stderr).splitlines():
        m = MEAS_RE.match(ln.strip())
        if m:
            values[m.group(1)] = float(m.group(2))
    return values, proc.returncode


def doc_corner(cid: str, values: dict, manifest: dict, error: str | None = None) -> dict:
    meas = []
    for m in manifest["measurements"]:
        v = values.get(m["name"])
        # klt pex requires status in pass|fail|error: graded against the manifest's
        # own (ratified) limits; the schematic-vs-extracted delta is klt's job.
        if v is None:
            status = "error"
        elif (m.get("min") is not None and v < m["min"]) or (m.get("max") is not None and v > m["max"]):
            status = "fail"
        else:
            status = "pass"
        meas.append({"name": m["name"], "value": v, "status": status})
    out = {"corner_id": cid, "measurements": meas}
    if error:
        out["error"] = error
    return out


def measure_batch(block: str, corners, manifest: dict, pdk, workdir: Path) -> list[dict]:
    import batch_sim

    pin = pdk.pin
    exp_like = _ExpLike(manifest)
    analysis, lets, meas_cards = batch_sim.split_analyses(list(manifest["deck"]["analyses"]))
    measurements = batch_sim.request_measurements(exp_like, lets, meas_cards)
    spiceinit = (pexlib.REPO_ROOT / "sim" / "spiceinit").read_text()
    wait = float(os.environ.get("PEX_NATIVE_CAPACITY_WAIT_S", "600"))
    groups = []
    for supply in sorted({s for _p, s in corners}):
        procs = [p for p, s in corners if s == supply]
        gdir = workdir / f"v{supply:.2f}"
        gdir.mkdir(parents=True, exist_ok=True)
        head = [f"* pex-native batch netlist -- generated, do not edit", f".param vsup={supply}"]
        head += [f".option {o}" for o in manifest["deck"].get("options") or []]
        netlist = gdir / "netlist.cir"
        netlist.write_text("\n".join(head + [pexlib._TB_BODY, pexlib.wrapper(pexlib.parse_ports(block, pexlib.TOP)), block, ""]))
        request = batch_sim.build_request(
            netlist.name, pin, procs, [27], analysis, measurements, spiceinit,
            batch_sim.DEFAULT_BATCH_TIMEOUT_S, capacity_wait_s=wait,
            runner_version_check="warn", poll_interval_s=30.0,
            single_step=bool(meas_cards),
        )
        req_path = gdir / "request.json"
        req_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n")
        cs = [_C(p, 27.0, supply) for p in procs]
        groups.append(batch_sim.Group(supply, gdir, netlist, req_path, cs, request))
    outcomes = batch_sim.collect(groups)  # BatchError on any failure; never local
    out = []
    for o in outcomes:
        jobs = (o.report.get("environment") or {}).get("remote") or {}
        print(f"batch group {o.group.describe()}: job {jobs.get('job_id')}", file=sys.stderr)
        for kc in o.report["corners"]:
            values = {batch_sim.plain_name(m["name"], o.group.request): m["value"]
                      for m in kc.get("measurements") or [] if m.get("value") is not None}
            err = None if values else json.dumps(kc.get("diagnostics") or [])
            out.append(doc_corner(corner_id(kc["process"], o.group.supply_v), values, manifest, err))
    return out


class _C:
    def __init__(self, process, temp_c, supply_v):
        self.process, self.temp_c, self.supply_v = process, temp_c, supply_v


class _ExpLike:
    """Duck-types the `Experiment` bits `batch_sim.request_measurements` reads."""

    def __init__(self, manifest: dict):
        class M:  # noqa: D401
            pass

        self.measurements = []
        for m in manifest["measurements"]:
            o = M()
            o.name, o.expr, o.unit = m["name"], m["expr"], m.get("unit", "")
            o.min, o.max = m.get("min"), m.get("max")
            self.measurements.append(o)


def main(argv: list[str]) -> int:
    side = os.environ.get("KLT_PEX_SIDE", "")
    netlist = Path(argv[-1])
    manifest = json.loads(pexlib.EXPERIMENT_JSON.read_text())
    text = netlist.read_text()
    block = side_block(side, text)
    cr = plc.sim_common.load_corner_run()
    pdk = cr.resolve_pdk(cr.load_pin())
    corners = parse_corners(os.environ.get("PEX_NATIVE_CORNERS"))
    backend = os.environ.get("PEX_NATIVE_BACKEND", "batch")
    work = Path(os.environ.get("KLT_PEX_ARTIFACTS_DIR") or tempfile.mkdtemp(prefix="pex-native-")) / f"measure-{side}"
    if backend == "local":
        if len(corners) != 1:
            raise pexlib.PexNativeError(
                "PEX_NATIVE_BACKEND=local runs exactly one corner (set PEX_NATIVE_CORNERS=tt:3.30); "
                "a corner grid must go to the batch fleet")
        values, rc = measure_local(block, corners[0], manifest, pdk, work)
        cs = [doc_corner(corner_id(*corners[0]), values, manifest, None if rc == 0 else f"ngspice exit {rc}")]
    elif backend == "batch":
        cs = measure_batch(block, corners, manifest, pdk, work)
    else:
        raise pexlib.PexNativeError(f"PEX_NATIVE_BACKEND must be batch|local, got {backend!r}")
    print(json.dumps({"corners": cs}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:  # noqa: BLE001 -- surface as non-zero, never a partial doc
        print(f"measure_command: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
