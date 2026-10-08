#!/usr/bin/env python3
"""Re-derive DR-002's three trim criteria (monotonic-in-code, downward span,
LSB) against the routed layout's REAL chained fine-trim topology at the
CURRENT design sizing -- issue #327 (refresh of issue #106's original run).

History. Issue #106 first re-derived the criteria at the then-adopted
`n_r1=7`/`n_r2=50` sizing (record `20260806-052035-dea0ca5`, schematic-level,
Darwin host, dirty tree, a stale pre-#178 core body). Since then the design
moved: `n_r2` was re-centred 50 -> 51 and the chained array was modelled in
`design/bandgap_core.sch` (issue #193), `r_lseg_trim` became 0.5 um (issue
#106/#111), and the error-amp input pair was resized. That record is
therefore STALE against the current design (the report's row 2). This
script produces the replacement record; the old record is untouched
(`sim/` is append-only).

What changed in this script versus the #106 version:

  * Sizing is READ from `design/bandgap_core.sch` (`n_r1`, `n_r2`,
    `r_lseg`, `r_w`, `r_lseg_trim`, `n_r2_fine`), not hard-coded. `--n-r2`
    exists only for what-if sweeps and is stamped into the record.
  * The core body is a FRESH xschem netlist of
    `sim/output-voltage-tc/testbench/tb_vref_tc.sch` (xschem is available
    now), snapshotted next to the record, not the 2026-08-03 snapshot the
    old run reused.
  * Two bodies are run from that one netlist:
      - `chained` -- the graded config: the schematic's lumped
        "replica + VCVS" head-resistance model and single-device legs are
        replaced by explicit separately-contacted unit-instance chains
        (the routed layout's own `bus_res_series` decomposition), exactly
        the substitution #106 used. Trim codes 0..-16, EVERY code.
      - `lumped` -- the design's own netlist, trim applied by overriding
        `.param n_r2_trim`. A cross-check that the schematic's chained-array
        model agrees with the explicit chain; codes 0, -8, -16.
  * The (process x supply x code) grid is a set of `klt sim --backend batch`
    requests (Spot batch fleet), never a local ngspice loop. One request per
    (config, supply, code): `klt sim` cannot alter a `.param` (the supply
    here is `.param vsup`, and the trim code changes the netlist), so those
    two axes are pinned in each request's netlist and the five process
    corners go on klt's process axis. The in-deck `dc temp -40 125 11`
    box-method sweep (16 points) is the request's analysis, unchanged.
  * Matrix widened to the full 5 process x 3 supply (2.97/3.30/3.63 V)
    corner matrix the other refreshed benches use (the old run had only
    five hand-picked (process, supply) pairs).

DR-002's criteria, graded exactly as `sim/trim-range-monotonicity/
run_trim_sweep.py` does, per (process, supply) corner on the chained body:

  * monotonic-in-code: VREF(27 C) strictly increases from code -16 to 0
    (graded at every one of the 17 codes);
  * downward span (code 0 -> -16) >= 1.5 x the worst-case 3-sigma untrimmed
    MC spread. DR-002 ratified 15.620 mV (record 20260803-142259-544cc5e,
    125 C). That MC record is itself stale (pre-#193); the current-design MC
    record `20260817-121131-d7d85b6` gives 3 x 7.3466 mV = 22.040 mV at
    125 C. Both are graded; the first is DR-002's own number, the second
    is the freshness check;
  * LSB = (VREF27(0) - VREF27(-16)) / 16 <= 3.0 mV/code (25 % of the
    +/-1 % window's 12 mV half-width).

Spec discipline: no threshold here is relaxed to make a result pass. If a
criterion fails the record says so and the disposition is a design issue /
operator question, not an edit of DR-002/DR-005.

The `.save i(v1)` line the testbench carries restricts ngspice to the saved
vectors; a local deck adds `save all` itself, but the batch runner image's
klt (0.5.0) does not, so this script appends `v(vref)` to that `.save` line
in the request netlist (otherwise `v(vref)` is not found and every
measurement is empty).

Usage
-----
    sim/trim-lsb-chained/run_trim_lsb_chained.py             # full batch run
    sim/trim-lsb-chained/run_trim_lsb_chained.py --dry-run   # write requests under sim/build, submit nothing

Exit status: 0 if every check passed, 2 if a record was written but a check
failed, 1 on a harness/setup/batch error (no record written; nothing is ever
run locally).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE.parent
REPO_ROOT = SIM_DIR.parent
BUILD_DIR = SIM_DIR / "build" / "trim-lsb-chained"
DESIGN_SCH = REPO_ROOT / "design" / "bandgap_core.sch"
TB_SCH = SIM_DIR / "output-voltage-tc" / "testbench" / "tb_vref_tc.sch"

sys.path.insert(0, str(SIM_DIR / "bin"))
import batch_sim  # noqa: E402
from sim_common import (  # noqa: E402
    add_common_args,
    chain_lines,
    check_pdk_and_ngspice,
    load_corner_run,
    r1_segments_um,
    r2_segments_um,
    render_pdk_tools_repo_state,
    render_record_id_experiment,
    setup_record_paths,
)

cr = load_corner_run()

SLUG = "trim-lsb-chained"
TITLE = (
    "Re-derive DR-002's monotonic/span/LSB trim criteria against the chained "
    "fine-trim topology at the current design sizing (issue #327, refreshing issue #106)"
)

# --------------------------------------------------------------------------
# Corner / code matrix
# --------------------------------------------------------------------------
PROCESSES = ("tt", "ss", "ff", "sf", "fs")
SUPPLIES = (2.97, 3.30, 3.63)
TEMP_SWEEP_ARGS = "temp -40 125 11"  # 16-point box-method sweep, unchanged from #106
VSPAN_C = 165.0  # -40..125 C, the TC denominator
CHAINED_CODES = tuple(range(0, -17, -1))  # every downward code DR-002 certifies
LUMPED_CODES = (0, -8, -16)
CONFIGS = ("chained", "lumped")
GRADED_CONFIG = "chained"

VREF_SANITY_V = (1.10, 1.30)  # regulation-loss guard (collapse jumps VOUT ~2.85 V)
SPEC_WINDOW_HALF_V = 0.012  # +/-1 % of 1.20 V
LSB_COMFORTABLE_FRACTION = 0.25  # DR-002: LSB <= 25 % of the window half-width
SPAN_MARGIN_TARGET = 1.5
WORST_CASE_3SIGMA_DR002_V = 0.015620  # DR-002's ratified figure (20260803-142259-544cc5e, 125 C)
WORST_CASE_3SIGMA_CURRENT_V = 3 * 0.0073466  # sim/monte-carlo-untrimmed 20260817-121131-d7d85b6, 125 C, 'all'
MC_CURRENT_RECORD = "sim/monte-carlo-untrimmed/records/20260817-121131-d7d85b6.md"

MEASUREMENTS = (
    ("vref_27", ".meas dc vref_27 FIND v(vref) AT=27"),
    ("vref_min", ".meas dc vref_min MIN v(vref)"),
    ("vref_max", ".meas dc vref_max MAX v(vref)"),
)

CLIENT_CONCURRENCY = 6  # klt client jobs in flight at once (fleet-side work, not local sims)


# --------------------------------------------------------------------------
# design sizing (read from the schematic, not hard-coded)
# --------------------------------------------------------------------------
_PARAM_RE = re.compile(r"^\.param\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\S+)\s*$")
_WANTED = ("n_r1", "n_r2", "r_lseg", "r_w", "r_lseg_trim", "n_r2_fine")


def read_design_sizing(sch: Path = DESIGN_SCH) -> dict[str, float]:
    """The numeric `.param` sizing lines of `design/bandgap_core.sch` (comment
    lines start with `*`, so only the live definitions match)."""
    found: dict[str, float] = {}
    for line in sch.read_text().splitlines():
        m = _PARAM_RE.match(line.strip())
        if m and m.group(1) in _WANTED:
            try:
                found[m.group(1)] = float(m.group(2))
            except ValueError:
                continue
    missing = [k for k in _WANTED if k not in found]
    if missing:
        raise cr.HarnessError(f"{sch}: could not read numeric .param {missing}")
    return found


# --------------------------------------------------------------------------
# provenance / core-body verification
# --------------------------------------------------------------------------
ERROR_AMP_SCH = REPO_ROOT / "design" / "error_amp.sch"
STARTUP_INJECTOR_SCH = REPO_ROOT / "design" / "startup_injector.sch"
_NON_DEVICE_NAMES = {"CORE_PARAMS", "RES_HEAD_MODEL", "AMP_PARAMS"}
_SCH_NAME_RE = re.compile(r"\{[^}]*?\bname=([A-Z][A-Z0-9_]*)\b")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def schematic_instances(sch: Path) -> set[str]:
    """Upper-case instance refdes of an xschem schematic (pins/labels are lower-case)."""
    return {n for n in _SCH_NAME_RE.findall(Path(sch).read_text()) if n not in _NON_DEVICE_NAMES}


def expected_netlist_devices(core_sch: Path = DESIGN_SCH, amp_sch: Path = ERROR_AMP_SCH) -> dict[str, set[str]]:
    """netlist instance names the current schematics must produce, per subckt.
    Device refdes `M1` is netlisted as `XM1` (sky130 symbols are subckt instances);
    the sub-block instance `XAMP` keeps its name."""
    def netname(n: str) -> str:
        return n if n.startswith("X") else "X" + n

    return {
        "bandgap_core": {netname(n) for n in schematic_instances(core_sch)},
        "error_amp": {netname(n) for n in schematic_instances(amp_sch)},
    }


def subckt_instances(body: list[str]) -> dict[str, set[str]]:
    """{subckt name: instance tokens beginning with X} of a netlist body."""
    out: dict[str, set[str]] = {}
    cur = None
    for line in body:
        t = line.split()
        if not t:
            continue
        if t[0].lower() == ".subckt":
            cur = t[1]
            out[cur] = set()
        elif t[0].lower() == ".ends":
            cur = None
        elif cur and t[0].upper().startswith("X"):
            out[cur].add(t[0].upper())
    return out


def verify_core_body(body: list[str], core_sch: Path = DESIGN_SCH, amp_sch: Path = ERROR_AMP_SCH) -> dict:
    """Fail unless the netlist body used as the bench input carries exactly the
    devices of the CURRENT schematics (core: output/bias mirrors, amp, PNPs,
    resistor legs; error amp: input pair, mirrors, cascode/CC). The bench's
    netlist is generated fresh from them each run; this guards a stale or
    hand-edited body and a schematic that grew a device the chained
    substitution does not know about."""
    have = subckt_instances(body)
    want = expected_netlist_devices(core_sch, amp_sch)
    problems = []
    for sub, names in want.items():
        got = have.get(sub)
        if got is None:
            problems.append(f".subckt {sub} absent from the netlist")
            continue
        if not names:
            problems.append(f"no devices parsed from the {sub} schematic")
        if names - got:
            problems.append(f"{sub}: schematic devices missing from netlist: {sorted(names - got)}")
        got = {n for n in got if not n.endswith("_HD")}  # RES_HEAD_MODEL code-block replicas
        if got - names:
            problems.append(f"{sub}: netlist devices not in schematic: {sorted(got - names)}")
    if problems:
        raise cr.HarnessError("core body does not match the current schematic -- " + "; ".join(problems))
    return {sub: sorted(names) for sub, names in want.items()}


def input_provenance(body: list[str]) -> dict:
    files = {
        "design/bandgap_core.sch": DESIGN_SCH,
        "design/error_amp.sch": ERROR_AMP_SCH,
        "design/startup_injector.sch": STARTUP_INJECTOR_SCH,
        str(TB_SCH.relative_to(REPO_ROOT)): TB_SCH,
    }
    return {
        "schematic_sha256": {k: sha256_file(v) for k, v in files.items()},
        "netlist_body_sha256": hashlib.sha256("\n".join(body).encode()).hexdigest(),
        "startup_injector_in_bench": False,
    }


# --------------------------------------------------------------------------
# body construction
# --------------------------------------------------------------------------
_HD_PREFIXES = ("XR2A_HD", "ER2A_HD", "XR2B_HD", "ER2B_HD", "XR1_HD", "ER1_HD")
_LEG_PREFIXES = ("XR2A", "XR2B", "XR1")


def _first_token(line: str) -> str:
    parts = line.split(None, 1)
    return parts[0] if parts else ""


def chained_body(body: list[str], sizing: dict, n_r2: int, code: int) -> list[str]:
    """Replace the schematic's lumped head-resistance model + single-device
    legs with explicit unit-instance chains at `code`."""
    n_r1 = int(sizing["n_r1"])
    r_lseg = sizing["r_lseg"]
    r_w = sizing["r_w"]
    trim_um = sizing["r_lseg_trim"]
    fine = int(sizing["n_r2_fine"])
    r2_seg = r2_segments_um(n_r2, code, trim_um, r_lseg, fine)
    r1_seg = r1_segments_um(n_r1, r_lseg)
    seen: dict[str, int] = {}
    out: list[str] = []
    for line in body:
        tok = _first_token(line)
        if tok in _HD_PREFIXES:
            seen[tok] = seen.get(tok, 0) + 1
            continue
        if tok in _LEG_PREFIXES:
            seen[tok] = seen.get(tok, 0) + 1
            if tok == "XR2A":
                out.extend(chain_lines("R2A", "VA", "VOUT", r2_seg, "VSS", r_w))
            elif tok == "XR2B":
                out.extend(chain_lines("R2B", "VB", "VOUT", r2_seg, "VSS", r_w))
            else:
                out.extend(chain_lines("R1", "VBQ", "VB", r1_seg, "VSS", r_w))
            continue
        out.append(line)
    expected = set(_HD_PREFIXES) | set(_LEG_PREFIXES)
    bad = {k: seen.get(k, 0) for k in expected if seen.get(k, 0) != 1}
    if bad:
        raise cr.HarnessError(
            f"fresh netlist does not carry each of {sorted(expected)} exactly once: {bad} -- "
            "design/bandgap_core.sch's resistor model changed; update chained_body()"
        )
    return out


def lumped_body(body: list[str], code: int) -> list[str]:
    """The design's own netlist with `.param n_r2_trim` set to `code`."""
    out, hits = [], 0
    for line in body:
        if line.strip() == ".param n_r2_trim=0":
            hits += 1
            out.append(f".param n_r2_trim={code}")
        else:
            out.append(line)
    if hits != 1:
        raise cr.HarnessError(f"expected exactly one '.param n_r2_trim=0' in the fresh netlist, found {hits}")
    return out


def with_vref_saved(body: list[str]) -> list[str]:
    out, hits = [], 0
    for line in body:
        if line.strip() == ".save i(v1)":
            hits += 1
            out.append(".save i(v1) v(vref)")
        else:
            out.append(line)
    if hits != 1:
        raise cr.HarnessError(f"expected exactly one '.save i(v1)' line in the testbench netlist, found {hits}")
    return out


# --------------------------------------------------------------------------
# requests
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Job:
    config: str
    supply_v: float
    code: int

    @property
    def name(self) -> str:
        sign = "p" if self.code >= 0 else "n"
        return f"{self.config}_v{self.supply_v:.2f}_trim{sign}{abs(self.code)}"


def build_jobs() -> list[Job]:
    jobs = []
    for config in CONFIGS:
        codes = CHAINED_CODES if config == "chained" else LUMPED_CODES
        for supply in SUPPLIES:
            for code in codes:
                jobs.append(Job(config, supply, code))
    return jobs


def build_request(job: Job, pin: dict, timeout_s: int) -> dict:
    return {
        "netlist": "netlist.cir",
        "engine": "ngspice",
        "backend": "batch",
        "models": {"pdk": pin["variant"], "lib": pin["ngspice_lib"]},
        "corners": {"process": list(PROCESSES), "temperature_c": [27]},
        "analysis": {"kind": "dc", "args": TEMP_SWEEP_ARGS},
        "measurements": [{"name": n, "spice": s, "unit": "V"} for n, s in MEASUREMENTS],
        "options": {"timeout_s": timeout_s, "keep_artifacts": True},
        "batch": {
            "poll_interval_s": 10,
            "capacity_wait_s": 3600,
            "runner_version_check": "enforce",
        },
    }


def write_groups(jobs, base_body, sizing, n_r2, pin, out_dir: Path, timeout_s: int):
    groups, by_dir = [], {}
    saved = with_vref_saved(base_body)
    for job in jobs:
        body = chained_body(saved, sizing, n_r2, job.code) if job.config == "chained" else lumped_body(saved, job.code)
        gdir = out_dir / job.name
        gdir.mkdir(parents=True, exist_ok=True)
        netlist = gdir / "netlist.cir"
        netlist.write_text(
            "\n".join([f"* {SLUG} {job.name} -- generated by sim/{SLUG}/run_trim_lsb_chained.py, do not edit",
                       f".param vsup={job.supply_v}"] + body + [""])
        )
        request = build_request(job, pin, timeout_s)
        request_path = gdir / "request.json"
        request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n")
        g = batch_sim.Group(job.supply_v, gdir, netlist, request_path, [], request)
        groups.append(g)
        by_dir[gdir] = job
    return groups, by_dir


def run_batch(groups):
    outcomes = []
    for i in range(0, len(groups), CLIENT_CONCURRENCY):
        chunk = groups[i : i + CLIENT_CONCURRENCY]
        done = batch_sim.collect(chunk)
        outcomes.extend(done)
        for o in done:
            remote = (o.report.get("environment") or {}).get("remote") or {}
            print(f"  [{len(outcomes):>2}/{len(groups)}] {o.group.dir.name:<28} job={remote.get('job_id')} "
                  f"status={o.report.get('status')} wall={o.wall_s:.0f}s")
    return outcomes


def fold_results(outcomes, by_dir) -> tuple[dict, dict, list[dict]]:
    """-> (results {(config, process, supply, code): {vref_27, vref_min, vref_max, tc_ppm}},
    missing {key: reason}, execution list)."""
    results: dict = {}
    missing: dict = {}
    execution: list[dict] = []
    for o in outcomes:
        job = by_dir[o.group.dir]
        env = o.report.get("environment") or {}
        remote = env.get("remote") or {}
        execution.append(
            {
                "request": job.name,
                "job_id": remote.get("job_id"),
                "instance_type": remote.get("instance_type"),
                "lifecycle": remote.get("lifecycle"),
                "ami_id": remote.get("ami_id"),
                "engine_version": env.get("engine_version"),
                "models_lib_sha256": env.get("models_lib_sha256"),
                "fleet_elapsed_s": remote.get("elapsed_seconds"),
                "wall_s": round(o.wall_s, 1),
                "klt_status": o.report.get("status"),
            }
        )
        seen = set()
        for c in o.report["corners"]:
            proc = c["process"]
            seen.add(proc)
            vals = {m["name"]: m.get("value") for m in c.get("measurements") or []}
            key = (job.config, proc, job.supply_v, job.code)
            if key in results or key in missing:
                raise cr.HarnessError(f"duplicate corner result for {key}")
            if any(vals.get(n) is None for n, _ in MEASUREMENTS) or c.get("status") == "error":
                # nonconvergent / errored point: reported explicitly, never dropped
                missing[key] = (f"{c.get('status')}: "
                                f"{[d.get('message') for d in c.get('diagnostics') or []]}")
                continue
            v27, vmin, vmax = vals["vref_27"], vals["vref_min"], vals["vref_max"]
            results[key] = {
                "vref_27": v27,
                "vref_min": vmin,
                "vref_max": vmax,
                "tc_ppm": (vmax - vmin) / (v27 * VSPAN_C) * 1e6,
            }
        if seen != set(PROCESSES):
            raise cr.HarnessError(f"{job.name}: processes returned {sorted(seen)} != requested {sorted(PROCESSES)}")
    return results, missing, execution


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------
def evaluate(results: dict, missing: dict | None = None) -> list[dict]:
    missing = missing or {}
    checks: list[dict] = []

    def add(name, ok, detail):
        checks.append({"name": name, "pass": bool(ok), "detail": detail})

    for supply in SUPPLIES:
        for proc in PROCESSES:
            cid = f"{GRADED_CONFIG}_{proc}_{supply:.2f}v"
            gaps = [c for c in CHAINED_CODES if (GRADED_CONFIG, proc, supply, c) not in results]
            if gaps:
                why = "; ".join(f"code {c}: {missing.get((GRADED_CONFIG, proc, supply, c), 'no result returned')}"
                                for c in gaps)
                for name in ("collapse_free", "monotonic", "range_covers_mc_spread",
                             "range_covers_current_mc_spread", "lsb_comfortable"):
                    add(f"{name}[{cid}]", False,
                        f"UNGRADED: {len(gaps)} of {len(CHAINED_CODES)} codes missing/nonconvergent ({why})")
                continue
            r = {c: results[(GRADED_CONFIG, proc, supply, c)] for c in CHAINED_CODES}
            reg = all(VREF_SANITY_V[0] <= r[c]["vref_max"] <= VREF_SANITY_V[1] for c in CHAINED_CODES)
            add(f"collapse_free[{cid}]", reg,
                f"all {len(CHAINED_CODES)} downward codes stay on the operating branch (vref_max in {VREF_SANITY_V})")
            series = [r[c]["vref_27"] for c in sorted(CHAINED_CODES)]
            steps = [b - a for a, b in zip(series, series[1:])]
            add(f"monotonic[{cid}]", all(s > 0 for s in steps),
                f"vref_27 strictly increasing from code -16 to 0 over all {len(series)} codes; "
                f"smallest single-code step {min(steps) * 1000:.4f} mV, largest {max(steps) * 1000:.4f} mV")
            span = r[0]["vref_27"] - r[-16]["vref_27"]
            for tag, sigma3 in (("range_covers_mc_spread", WORST_CASE_3SIGMA_DR002_V),
                                ("range_covers_current_mc_spread", WORST_CASE_3SIGMA_CURRENT_V)):
                need = SPAN_MARGIN_TARGET * sigma3
                add(f"{tag}[{cid}]", span >= need,
                    f"downward trim span (code 0..-16) = {span * 1000:.3f} mV, required >= "
                    f"{SPAN_MARGIN_TARGET} x {sigma3 * 1000:.3f} mV = {need * 1000:.3f} mV")
            lsb = span / 16.0
            bound = LSB_COMFORTABLE_FRACTION * SPEC_WINDOW_HALF_V
            add(f"lsb_comfortable[{cid}]", lsb <= bound,
                f"LSB={lsb * 1000:.4f} mV/code, required <= {LSB_COMFORTABLE_FRACTION:.0%} of window "
                f"half-width ({bound * 1000:.3f} mV)")
    lump_gaps = [k for k in (("lumped", p, v, c) for v in SUPPLIES for p in PROCESSES for c in LUMPED_CODES)
                 if k not in results]
    add("lumped_crosscheck_complete", not lump_gaps,
        f"all {len(SUPPLIES) * len(PROCESSES) * len(LUMPED_CODES)} lumped cross-check points returned"
        if not lump_gaps else
        "missing lumped points: " + "; ".join(f"{k[1]}/{k[2]:.2f}V/code {k[3]}: {missing.get(k, 'no result')}"
                                             for k in lump_gaps))
    return checks


def corner_summary(results: dict, config: str, proc: str, supply: float) -> dict | None:
    """Per-corner metrics; None if any code of the config is missing at this corner."""
    codes = CHAINED_CODES if config == "chained" else LUMPED_CODES
    if any((config, proc, supply, c) not in results for c in codes):
        return None
    r = {c: results[(config, proc, supply, c)] for c in codes}
    span = r[0]["vref_27"] - r[-16]["vref_27"]
    out = {"span_mv": span * 1000, "lsb_mv": span / 16 * 1000, "v0": r[0]["vref_27"], "v16": r[-16]["vref_27"]}
    if config == "chained":
        series = [r[c]["vref_27"] for c in sorted(codes)]
        steps = [b - a for a, b in zip(series, series[1:])]
        out["step_min_mv"] = min(steps) * 1000
        out["step_max_mv"] = max(steps) * 1000
    return out


# --------------------------------------------------------------------------
# record
# --------------------------------------------------------------------------
def render_record(r: dict) -> str:
    L: list[str] = []
    add = L.append
    results = {(k.split("|")[0], k.split("|")[1], float(k.split("|")[2]), int(k.split("|")[3])): v
               for k, v in r["results"].items()}
    s = r["sizing"]

    add(f"# Record {r['record_id']}")
    add("")
    L.extend(render_record_id_experiment(r["record_id"], SLUG, TITLE))
    add(
        "- **Claim**: issue #327 -- re-derive (not re-cite) DR-002's three trim criteria (monotonic-in-code, "
        "downward span, LSB) against the routed layout's chained fine-trim topology at the CURRENT design "
        f"sizing (`n_r1={s['n_r1']:g}`, `n_r2={s['n_r2']:g}`, `r_lseg_trim={s['r_lseg_trim']:g}` um, "
        f"`n_r2_fine={s['n_r2_fine']:g}`, read from `design/bandgap_core.sch`), over the full 5-process x "
        "3-supply corner matrix and the -40..125 C range. Replaces the STALE `n_r1=7`/`n_r2=50` record "
        "`20260806-052035-dea0ca5` (not edited)."
    )
    add(
        "- **Netlist provenance**: a fresh xschem netlist of `sim/output-voltage-tc/testbench/tb_vref_tc.sch` "
        f"(snapshot `{r['links']['snapshot']}`). Config `chained` replaces the schematic's lumped head-resistance "
        "model and single-device legs with explicit separately-contacted `sky130_fd_pr__res_high_po` unit "
        "chains at the routed layout's decomposition; config `lumped` is the design's own netlist with "
        "`.param n_r2_trim` overridden. `.save i(v1)` gains `v(vref)` (the batch image's klt does not add "
        "`save all`)."
    )
    L.extend(render_pdk_tools_repo_state({**r, "jobs": None}))
    add(f"- **Execution**: Spot batch fleet via `klt sim --backend batch` ({len(r['execution'])} requests; "
        f"klt client `{r['klt_version']}`; remote ngspice `{r['execution'][0]['engine_version']}`; "
        f"instance `{r['execution'][0]['instance_type']}`; models resolved on the fleet image "
        f"(sha256 `{r['execution'][0]['models_lib_sha256']}` vs pinned local `{r['local_models_sha256']}` -- "
        f"{'match' if r['models_sha_match'] else '**MISMATCH**'})). Job ids are in the table below.")
    add(
        "- **Corner matrix**: process tt/ss/ff/sf/fs x supply 2.97/3.30/3.63 V (15 corners); config `chained` at "
        "all 17 downward codes 0..-16, config `lumped` at codes 0/-8/-16; each with the in-deck "
        f"`dc {TEMP_SWEEP_ARGS}` box-method sweep (16 points). One request per (config, supply, code) with the "
        "five processes on klt's process axis (`klt sim` cannot alter `.param vsup` or the netlist's trim code)."
    )
    add("- **Metric scope**: monotonicity, downward span, DR-002 endpoint-average LSB `(V(0)-V(-16))/16`, "
        "adjacent-code steps and the 1.5x3-sigma comparison all use VREF at **27 C** (the trim temperature, "
        "`.meas ... AT=27` on the in-deck sweep). Only `collapse_free` (vref_max within sanity band) and the "
        "`tc_ppm` column cover the full -40..125 C sweep (16 points, box method). Temperature sampling: "
        "-40 to 125 C in 11 C steps. Code range: every integer 0..-16 (`chained`).")
    prov = r["provenance"]
    add("- **Input provenance**: schematic sha256 " + ", ".join(f"`{k}`={v[:16]}" for k, v in prov["schematic_sha256"].items())
        + f"; generated netlist body sha256 `{prov['netlist_body_sha256'][:16]}`; core body verified device-for-device "
        "against `design/bandgap_core.sch` and `design/error_amp.sch` (amplifier, output/bias mirrors, both PNPs, "
        "resistor legs). The startup injector (`design/startup_injector.sch`) is a separate cell attached at GDRV and is "
        "**not** in this bench; the DC solver is seeded by the testbench `.nodeset` instead (disclosed scope: trim "
        "resistor evidence is independent of the injector, which loads GDRV not the R legs).")
    if r.get("missing_points"):
        add(f"- **MISSING/NONCONVERGENT POINTS ({len(r['missing_points'])})**: "
            + "; ".join(f"`{k}`: {v}" for k, v in r["missing_points"].items()))
    add("- **Statistical convention**: N/A (deterministic sizing/topology sweep, not a distribution claim).")
    add("")

    add("## Per-code resistance step (analytic cross-reference)")
    add("")
    add("| r_lseg_trim (um) | rhead (ohm, fixed) | rbody (ohm) | step (ohm/code) |")
    add("|---|---|---|---|")
    head, per_um = 379.705147, 324.827244
    add(f"| {s['r_lseg_trim']:g} | {head:.3f} | {per_um * s['r_lseg_trim']:.3f} | {head + per_um * s['r_lseg_trim']:.3f} |")
    add("")
    add("(PDK model-card constants, DR-003; analytic only -- the ngspice sweep is what the checks are gated on.)")
    add("")

    for config in CONFIGS:
        codes = CHAINED_CODES if config == "chained" else LUMPED_CODES
        add(f"## Config `{config}`" + (" (graded)" if config == GRADED_CONFIG else " (cross-check, graded for the same criteria as an agreement witness)"))
        add("")
        hdr = "| process | supply (V) | VREF27 @0 (V) | VREF27 @-16 (V) | span (mV) | LSB (mV/code) |"
        sep = "|---|---|---|---|---|---|"
        if config == "chained":
            hdr += " min step (mV) | max step (mV) | monotonic? | span >= 1.5x3s (DR-002) | span >= 1.5x3s (current MC) | LSB <= 3.000? |"
            sep += "---|---|---|---|---|---|"
        add(hdr)
        add(sep)
        for supply in SUPPLIES:
            for proc in PROCESSES:
                c = corner_summary(results, config, proc, supply)
                if c is None:
                    add(f"| {proc} | {supply:.2f} | **INCOMPLETE -- code(s) missing/nonconvergent; see Checks** |" + " |" * 4)
                    continue
                row = f"| {proc} | {supply:.2f} | {c['v0']:.6f} | {c['v16']:.6f} | {c['span_mv']:.3f} | {c['lsb_mv']:.4f} |"
                if config == "chained":
                    cid = f"{config}_{proc}_{supply:.2f}v"
                    ck = {x["name"]: x["pass"] for x in r["checks"]}
                    yn = lambda n: "yes" if ck[f"{n}[{cid}]"] else "**NO**"  # noqa: E731
                    row += (f" {c['step_min_mv']:.4f} | {c['step_max_mv']:.4f} | {yn('monotonic')} | "
                            f"{yn('range_covers_mc_spread')} | {yn('range_covers_current_mc_spread')} | {yn('lsb_comfortable')} |")
                add(row)
        add("")
        if config == "chained":
            add("### Config `chained` -- VREF(27 C) (V) by code, tt")
            add("")
            add("| code | " + " | ".join(f"{v:.2f} V" for v in SUPPLIES) + " | TC(0..125C box) @3.30 V (ppm/C) |")
            add("|---|" + "---|" * (len(SUPPLIES) + 1))
            def cell(v, code, field="vref_27", fmt=".6f"):
                m = results.get((config, "tt", v, code))
                return "MISSING" if m is None else format(m[field], fmt)
            for code in codes:
                add(f"| {code:+d} | " + " | ".join(cell(v, code) for v in SUPPLIES)
                    + f" | {cell(3.30, code, 'tc_ppm', '.2f')} |")
            add("")
            add("Every other corner's per-code data is in the record JSON.")
            add("")

    add("## Cross-check: `lumped` (schematic model) vs `chained` (explicit chain)")
    add("")
    add("| process | supply (V) | max |dVREF27| over codes 0/-8/-16 (mV) | LSB lumped (mV) | LSB chained (mV) |")
    add("|---|---|---|---|---|")
    worst = 0.0
    for supply in SUPPLIES:
        for proc in PROCESSES:
            keys = [(cfg, proc, supply, c) for cfg in ("lumped", "chained") for c in LUMPED_CODES]
            if any(k not in results for k in keys):
                add(f"| {proc} | {supply:.2f} | INCOMPLETE | n/a | n/a |")
                continue
            d = max(abs(results[("lumped", proc, supply, c)]["vref_27"] - results[("chained", proc, supply, c)]["vref_27"])
                    for c in LUMPED_CODES) * 1000
            worst = max(worst, d)
            lsb_l = (results[("lumped", proc, supply, 0)]["vref_27"] - results[("lumped", proc, supply, -16)]["vref_27"]) / 16 * 1000
            lsb_c = (results[("chained", proc, supply, 0)]["vref_27"] - results[("chained", proc, supply, -16)]["vref_27"]) / 16 * 1000
            add(f"| {proc} | {supply:.2f} | {d:.4f} | {lsb_l:.4f} | {lsb_c:.4f} |")
    add("")
    add(f"Worst lumped-vs-chained VREF(27 C) difference at the sampled codes: {worst:.4f} mV.")
    add("")

    add("## Checks (graded config `chained`)")
    add("")
    n_fail = sum(1 for c in r["checks"] if not c["pass"])
    for c in r["checks"]:
        add(f"- {'PASS' if c['pass'] else 'FAIL'} `{c['name']}` — {c['detail']}")
    add("")
    add(f"- **Overall: {'PASS' if r['overall_pass'] else 'FAIL'}** ({n_fail} check(s) failed of {len(r['checks'])})")
    add("")
    add("## Determination")
    add("")
    add(r["determination"])
    add("")
    add("## Batch execution")
    add("")
    add("| request | fleet job id | status | instance | lifecycle | fleet elapsed (s) | submit-to-collect wall (s) |")
    add("|---|---|---|---|---|---|---|")
    for e in r["execution"]:
        add(f"| {e['request']} | `{e['job_id']}` | {e['klt_status']} | {e['instance_type']} | {e['lifecycle']} | "
            f"{e['fleet_elapsed_s']} | {e['wall_s']} |")
    add("")
    add("- **Links**:")
    add(f"  - wrapped schematic: `{TB_SCH.relative_to(REPO_ROOT)}`")
    add(f"  - netlist snapshot: `{r['links']['snapshot']}`")
    add("  - superseded (stale) record: `sim/trim-lsb-chained/records/20260806-052035-dea0ca5.md` (untouched)")
    add(f"  - current-design MC (3-sigma freshness check): `{MC_CURRENT_RECORD}`")
    add("  - DR-002's own LSB formula / criteria: `sim/trim-range-monotonicity/records/20260803-170704-b976d0f.md`")
    add(f"  - runner: `sim/{SLUG}/run_trim_lsb_chained.py`")
    add(f"  - logs and exact requests/netlists: `{r['links']['corners_dir']}`")
    add(f"  - record_json: `{r['links']['json']}`")
    add("  - decision record: `spec/decision-records/DR-002-trim-network-scoping.md`")
    add(f"- **Timestamp / author**: {r['timestamp']}, {r['author']}")
    add(f"- **Supersedes**: {r['supersedes'] or '(none — first record for this claim)'}")
    add("")
    add(
        f"Written by `sim/{SLUG}/run_trim_lsb_chained.py`. Append-only: never edit this file — "
        "a correction is a new record with a `Supersedes` field (see `sim/README.md`)."
    )
    add("")
    return "\n".join(L)


def build_determination(results: dict, checks: list[dict], sizing: dict) -> str:
    def fails(prefix):
        return [c["name"] for c in checks if not c["pass"] and c["name"].startswith(prefix + "[")]

    seg = [
        f"**Re-derived (not re-cited) at the current design** (`n_r1={sizing['n_r1']:g}`, `n_r2={sizing['n_r2']:g}`, "
        f"`r_lseg_trim={sizing['r_lseg_trim']:g}` um), explicit chained fine-trim topology, "
        f"{len(PROCESSES) * len(SUPPLIES)} corners x 17 codes."
    ]
    summaries = [c for c in (corner_summary(results, GRADED_CONFIG, p, v) for v in SUPPLIES for p in PROCESSES) if c]
    n_inc = len(SUPPLIES) * len(PROCESSES) - len(summaries)
    if n_inc:
        seg.append(f"**{n_inc} corner(s) INCOMPLETE** (missing/nonconvergent codes); metrics below cover the rest only.")
    if not summaries:
        return "\n".join(seg + ["No corner returned a complete code set; nothing can be certified."])
    lsbs = [c["lsb_mv"] for c in summaries]
    spans = [c["span_mv"] for c in summaries]
    seg.append(
        f"Measured LSB {min(lsbs):.4f}-{max(lsbs):.4f} mV/code (bound 3.000); downward span "
        f"{min(spans):.3f}-{max(spans):.3f} mV (needs >= {SPAN_MARGIN_TARGET * WORST_CASE_3SIGMA_DR002_V * 1000:.3f} mV "
        f"on DR-002's ratified 3-sigma, >= {SPAN_MARGIN_TARGET * WORST_CASE_3SIGMA_CURRENT_V * 1000:.3f} mV on the "
        "current-design MC's)."
    )
    for label, prefix in (("Monotonic-in-code", "monotonic"), ("Span (DR-002 ratified 3-sigma)", "range_covers_mc_spread"),
                          ("Span (current-design MC 3-sigma)", "range_covers_current_mc_spread"),
                          ("LSB <= 3.000 mV/code", "lsb_comfortable"), ("Collapse-free", "collapse_free")):
        f = fails(prefix)
        total = len(PROCESSES) * len(SUPPLIES)
        seg.append(f"- {label}: **{'PASS' if not f else 'FAIL'} {total - len(f)}/{total}**"
                   + (f" (failing: {', '.join(n.split('[')[1].rstrip(']') for n in f)})" if f else ""))
    if all(c["pass"] for c in checks):
        seg.append("All DR-002 criteria hold at every corner; spec row 2 (Trim) has a current-design verdict. "
                   "Schematic-level only: a post-layout (extracted routed chain) trim check remains a possible follow-up.")
    else:
        seg.append("At least one criterion fails. DR-002/DR-005 are NOT relaxed by this record; the disposition is a "
                   "design issue plus an operator question under `spec/`.")
    return "\n".join(seg)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def local_ngspice_free_netlist(pdk, out_dir: Path) -> list[str]:
    """xschem netlist of the testbench (no simulation involved)."""
    netlist = cr.netlist_with_xschem(TB_SCH, out_dir, pdk)
    return cr.netlist_body(netlist)


def verify(args) -> int:
    pin = cr.load_pin()
    pdk = check_pdk_and_ngspice(pin, args.allow_pdk_mismatch, verbose=False)
    sizing = read_design_sizing()
    n_r2 = int(args.n_r2) if args.n_r2 is not None else int(sizing["n_r2"])
    sizing = {**sizing, "n_r2": float(n_r2)}
    git_info = cr.git_state()
    now = datetime.now(timezone.utc)
    record_id = f"{now:%Y%m%d}-{now:%H%M%S}-{git_info['sha']}"

    print(f"experiment : {SLUG}")
    print(f"record id  : {record_id}")
    print(f"sizing     : {sizing} (read from {DESIGN_SCH.relative_to(REPO_ROOT)})")

    run_dir = BUILD_DIR / record_id
    body = local_ngspice_free_netlist(pdk, run_dir)
    # the netlist's own params must agree with the schematic sizing we read
    text = "\n".join(body)
    for k in ("n_r1", "n_r2", "r_lseg_trim"):
        want = sizing[k]
        m = re.search(rf"^\.param {k}=(\S+)$", text, re.M)
        if not m or float(m.group(1)) != want:
            raise cr.HarnessError(f"fresh netlist .param {k}={m.group(1) if m else None} != sizing {want}")

    verified_devices = verify_core_body(body)
    provenance = input_provenance(body)
    print(f"core body  : verified against current schematics ({sum(len(v) for v in verified_devices.values())} devices)")

    jobs = build_jobs()
    timeout_s = args.timeout
    groups, by_dir = write_groups(jobs, body, sizing, n_r2, pin, run_dir / "requests", timeout_s)
    print(f"requests   : {len(groups)} under {(run_dir / 'requests').relative_to(REPO_ROOT)}")
    if args.dry_run:
        print("(dry run: nothing submitted, nothing written under sim/ records)")
        return 0

    records_dir, snapshots_dir, corners_dir, record_md, record_json, snapshot = setup_record_paths(
        HERE, record_id, with_snapshot=True
    )
    try:
        outcomes = run_batch(groups)
    except batch_sim.BatchError as err:
        print(f"run_trim_lsb_chained: batch error: {err}", file=sys.stderr)
        return 1
    results, missing, execution = fold_results(outcomes, by_dir)

    local_sha = batch_sim.sha256_file(pdk.lib_file)
    sha_match = all(e["models_lib_sha256"] == local_sha for e in execution)
    checks = evaluate(results, missing)
    if not sha_match:
        checks.append({"name": "models_lib_sha256", "pass": False,
                       "detail": "remote model library sha256 differs from the pinned local one"})
    overall = all(c["pass"] for c in checks)

    # evidence trail: snapshot + per-request inputs and per-corner logs
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("\n".join(body) + "\n.end\n")
    for o in outcomes:
        job = by_dir[o.group.dir]
        dst = corners_dir / job.name
        dst.mkdir(parents=True, exist_ok=True)
        for fname in ("request.json", "netlist.cir", "klt-report.json"):
            src = o.group.dir / fname
            if src.is_file():
                shutil.copyfile(src, dst / fname)
        for sub in sorted((o.group.dir / "klt-out").glob("*_novdd_27C")):
            proc = sub.name.split("_")[0]
            for fname, new in (("ngspice.log", f"{proc}.log"), ("corner.cir", f"{proc}.cir")):
                if (sub / fname).is_file():
                    shutil.copyfile(sub / fname, dst / new)

    record = {
        "record_id": record_id,
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "author": args.author or cr.default_author(),
        "supersedes": args.supersedes,
        "sizing": sizing,
        "pdk": {"variant": pdk.variant, "installed_commit": pdk.installed_commit,
                "matches_pin": pdk.matches_pin, "lib_file": str(pdk.lib_file)},
        "tools": cr.tool_versions(),
        "klt_version": cr.first_line(["klt", "--version"]) if hasattr(cr, "first_line") else "klt",
        "local_models_sha256": local_sha,
        "models_sha_match": sha_match,
        "git": git_info,
        "execution": execution,
        "results": {f"{c}|{p}|{v}|{k}": m for (c, p, v, k), m in results.items()},
        "missing_points": {f"{c}|{p}|{v}|{k}": why for (c, p, v, k), why in missing.items()},
        "grid": {"processes": list(PROCESSES), "supplies_v": list(SUPPLIES), "temp_sweep": TEMP_SWEEP_ARGS,
                 "temp_points": 16, "temp_range_c": [-40, 125], "chained_codes": list(CHAINED_CODES),
                 "lumped_codes": list(LUMPED_CODES), "requests": len(jobs)},
        "provenance": provenance,
        "verified_core_devices": verified_devices,
        "request_netlist_sha256": {j.name: sha256_file(g.dir / "netlist.cir") for g, j in
                                   ((g, by_dir[g.dir]) for g in groups)},
        "checks": checks,
        "overall_pass": overall,
        "determination": build_determination(results, checks, sizing),
        "links": {
            "corners_dir": str(corners_dir.relative_to(REPO_ROOT)) + "/",
            "json": str(record_json.relative_to(REPO_ROOT)),
            "record": str(record_md.relative_to(REPO_ROOT)),
            "snapshot": str(snapshot.relative_to(REPO_ROOT)),
        },
    }
    records_dir.mkdir(parents=True, exist_ok=True)
    record_json.write_text(json.dumps(record, indent=2, sort_keys=True, default=str) + "\n")
    record_md.write_text(render_record(record))

    print()
    print(f"record  : {record_md.relative_to(REPO_ROOT)}")
    print(f"json    : {record_json.relative_to(REPO_ROOT)}")
    print(f"overall : {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 2


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--n-r2", type=int, default=None,
                   help="override n_r2 (default: read from design/bandgap_core.sch); what-if use only")
    add_common_args(p, timeout_default=1800)
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    return verify(parse_args(argv))


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except cr.HarnessError as err:
        print(f"run_trim_lsb_chained: error: {err}", file=sys.stderr)
        sys.exit(1)
