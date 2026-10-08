#!/usr/bin/env python3
"""Spot-batch execution boundary for `corner-run.py` (issue #320).

`corner-run.py --backend batch` routes an experiment's PVT matrix through
`klt sim --backend batch` (2am's EDA batch fleet) instead of running one
local `ngspice -b` per corner. This module owns everything between "the
matrix and the xschem netlist body are ready" and "a list of per-corner
result dicts in the exact shape `corner-run.py::run_corner()` returns":

  1. `build_groups()`   -- one `klt sim` request per supply voltage (see the
     note below), each carrying the unchanged process x temperature axes,
     the manifest's analysis, measurement expressions and limits.
  2. `collect()`        -- run every request (`klt sim ... --backend batch`),
     retrieve its report + retained artifacts.
  3. `assemble()`       -- fold the reports back into matrix order, with
     missing / duplicate / unexpected corners made *loud* (they block an
     overall PASS), and the exit / timeout / failure distinction preserved
     as far as `klt sim`'s report exposes it.

Why one request per supply voltage. `klt sim` applies `corners.supply_v`
with ngspice's `alter <source>=<value>`, which cannot change a `.param`; this
bench's supply is the `.param vsup` that the netlist's B-sources multiply
into the swept forcing voltage. So `vsup` is pinned in each request's
netlist (the same `.param vsup=<v>` line the local deck carries) and the
three supplies become three concurrently submitted batch jobs. The 251-point
`dc valpha 0 1 0.004` sweep inside a corner is never partitioned or
shortened.

Nothing here ever falls back to running a corner locally: a failed
submission, an interrupted job or a missing corner is reported as such and
can never yield an overall PASS.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

#: Experiments whose deck shape this adapter has been validated against.
#: Everything else keeps the local runner; extending the list is a deliberate
#: change (issue #320 limits the scope to the startup-stability path).
BATCH_ENABLED_SLUGS = frozenset({"startup-stability"})

#: Per-corner ngspice budget on the fleet when `--timeout` is not given.
#: The local 300 s default is meaningless for a 251-point homotopy-stepped DC
#: sweep (issue #320 measured ~6.4 ks per corner on an AWS sweep host).
DEFAULT_BATCH_TIMEOUT_S = 10800

#: klt exit codes that still carry a full report on stdout (`docs/cli/sim.md`
#: "Exit codes": 0 pass, 3 limit failure, 4 error/inconclusive/not_checked).
REPORT_EXIT_CODES = (0, 3, 4)

#: Diagnostic codes that mean "the engine hit its timeout budget" -- the
#: per-corner `options.timeout_s` kill, or the whole fleet job's cap.
TIMEOUT_CODES = frozenset({"timeout", "batch_job_timeout"})

#: Diagnostic codes that mean the job's outcome was never observed.
INCOMPLETE_CODES = frozenset({"batch_poll_timeout", "lost_shard"})


class BatchError(RuntimeError):
    """Batch execution could not produce a report at all (submission failed,
    klt unusable, malformed report). Never produces a record, never falls
    back to local execution."""


@dataclass
class Group:
    """One `klt sim` request: every (process, temperature) at one supply."""

    supply_v: float
    dir: Path
    netlist_path: Path
    request_path: Path
    corners: list  # corner-run `Corner`s, in matrix order
    request: dict = field(default_factory=dict)


@dataclass
class GroupOutcome:
    group: Group
    submitted_at: str
    collected_at: str
    wall_s: float
    rc: int | None
    report: dict | None
    error: str | None
    stderr_tail: str = ""
    report_path: Path | None = None


# --------------------------------------------------------------------------
# request construction
# --------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def spiceinit_lines(spiceinit_text: str) -> list[str]:
    """`sim/spiceinit` -> the `options.ngspice_init` lines that reproduce it.

    klt writes each string as one line of a `.spiceinit` in the corner's
    working directory, which is how the local runner applies the same file.
    Comments (`*` lines and `;` tails) are dropped; they carry no ngspice
    semantics.
    """
    out = []
    for raw in spiceinit_text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if line and not line.startswith("*"):
            out.append(line)
    return out


_LET_RE = re.compile(r"^let\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$", re.IGNORECASE)


def split_analyses(analyses: list[str]) -> tuple[dict, dict[str, str]]:
    """Split a manifest `deck.analyses` list into klt's `analysis` object and
    the `let` definitions that follow it.

    The first entry must be the analysis card (`dc ...`, `op`, `tran ...`);
    every later entry must be a `let name = expr` line. `klt sim` owns a
    single `.control` block and accepts exactly one analysis plus scalar
    `expr` measurements, so intermediate vectors are inlined into the
    measurement expressions by `inline_lets()` rather than emitted as
    separate (non-scalar, unprintable) measurements.
    """
    if not analyses:
        return {"kind": "op", "args": ""}, {}
    head = analyses[0].strip()
    kind, _, args = head.partition(" ")
    if kind.lower() not in {"op", "dc", "tran", "ac"}:
        raise BatchError(f"first deck.analyses entry is not an analysis card: {head!r}")
    lets: dict[str, str] = {}
    for entry in analyses[1:]:
        m = _LET_RE.match(entry.strip())
        if not m:
            raise BatchError(
                f"deck.analyses entry {entry!r} is neither the leading analysis "
                "nor a `let name = expr` line; cannot express it as a klt sim request"
            )
        lets[m.group(1)] = m.group(2).strip()
    return {"kind": kind.lower(), "args": args.strip()}, lets


def inline_lets(expr: str, lets: dict[str, str]) -> str:
    """Substitute `let`-defined vectors into a measurement expression.

    Definitions are expanded in declaration order (a later `let` may use an
    earlier one) and each use is parenthesised, so the result is the same
    ngspice computation the local deck performs through the intermediate
    vector -- verified to give identical results for the `name[a,b]` slice
    form this bench uses.
    """
    expanded: dict[str, str] = {}
    for name, body in lets.items():
        expanded[name] = "(" + _substitute(body, expanded) + ")"
    return _substitute(expr, expanded)


def _substitute(text: str, table: dict[str, str]) -> str:
    for name, repl in table.items():
        text = re.sub(rf"(?<![\w.]){re.escape(name)}(?![\w(])", lambda _m, r=repl: r, text)
    return text


def request_measurements(exp, lets: dict[str, str]) -> list[dict]:
    out = []
    for m in exp.measurements:
        entry: dict = {"name": m.name, "expr": inline_lets(m.expr, lets)}
        if m.unit:
            entry["unit"] = m.unit
        limits = {k: v for k, v in (("min", m.min), ("max", m.max)) if v is not None}
        if limits:
            entry["limits"] = limits
        out.append(entry)
    return out


def netlist_text(exp, corner, body: list[str]) -> str:
    """The circuit-body file one request `.include`s: exactly the preamble
    `corner-run.py::build_deck()` puts before `.lib`, then the xschem body.
    (`.lib`, `.temp`, `save all`, the analysis and the measurement `let`s are
    added by klt's own per-corner deck.)"""
    deck = exp.raw.get("deck", {})
    head = [
        f"* {exp.slug} batch netlist -- generated by sim/bin/batch_sim.py, do not edit",
        f".param vsup={corner.supply_v}",
    ]
    for name, value in (deck.get("params") or {}).items():
        head.append(f".param {name}={value}")
    for opt in deck.get("options") or []:
        head.append(f".option {opt}")
    return "\n".join(head + body + [""])


def build_groups(
    exp,
    pin: dict,
    matrix: list,
    body: list[str],
    spiceinit_text: str,
    out_dir: Path,
    timeout_s: int,
    *,
    capacity_wait_s: float,
    runner_version_check: str,
    poll_interval_s: float,
) -> list[Group]:
    """Write one netlist + request per supply voltage into `out_dir`."""
    if exp.slug not in BATCH_ENABLED_SLUGS:
        raise BatchError(
            f"--backend batch is only enabled for {sorted(BATCH_ENABLED_SLUGS)} "
            f"(issue #320); {exp.slug!r} keeps the local runner"
        )
    analysis, lets = split_analyses(list((exp.raw.get("deck") or {}).get("analyses") or []))
    measurements = request_measurements(exp, lets)

    supplies: list[float] = []
    for c in matrix:
        if c.supply_v not in supplies:
            supplies.append(c.supply_v)

    groups = []
    for supply in supplies:
        members = [c for c in matrix if c.supply_v == supply]
        processes = _unique(c.process for c in members)
        temps = [int(t) if float(t).is_integer() else t for t in _unique(c.temp_c for c in members)]
        # klt expands the cross product itself; refuse a matrix that is not
        # one (a quick_subset can be), instead of silently running extras.
        if {(c.process, c.temp_c) for c in members} != {(p, t) for p in processes for t in temps}:
            raise BatchError(
                f"supply {supply} V: the requested corners are not a process x temperature "
                "cross product, which a single klt sim request cannot express"
            )
        gdir = out_dir / f"v{supply:.2f}"
        gdir.mkdir(parents=True, exist_ok=True)
        netlist_path = gdir / "netlist.cir"
        netlist_path.write_text(netlist_text(exp, members[0], body))
        request = {
            "netlist": netlist_path.name,
            "engine": "ngspice",
            "backend": "batch",
            "models": {"pdk": pin["variant"], "lib": pin["ngspice_lib"]},
            "corners": {"process": processes, "temperature_c": temps},
            "analysis": analysis,
            "measurements": measurements,
            "options": {
                "timeout_s": timeout_s,
                "keep_artifacts": True,
                "ngspice_init": spiceinit_lines(spiceinit_text),
            },
            "batch": {
                "poll_interval_s": poll_interval_s,
                "capacity_wait_s": capacity_wait_s,
                "runner_version_check": runner_version_check,
            },
        }
        request_path = gdir / "request.json"
        request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n")
        groups.append(Group(supply, gdir, netlist_path, request_path, members, request))
    return groups


def _unique(values) -> list:
    out: list = []
    for v in values:
        if v not in out:
            out.append(v)
    return out


# --------------------------------------------------------------------------
# submission and collection
# --------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_klt(group: Group, klt: str = "klt") -> GroupOutcome:
    """Submit one request through `klt sim --backend batch` and wait for it.

    The only thing this runs locally is the klt client (S3 put/get + polling).
    Any failure to obtain a report is returned as `error`, never retried
    locally.
    """
    outdir = group.dir / "klt-out"
    cmd = [
        klt, "sim", str(group.request_path),
        "--backend", "batch", "--format", "json", "-o", str(outdir),
    ]
    started, t0 = _now(), time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    except OSError as exc:
        return GroupOutcome(group, started, _now(), time.monotonic() - t0, None, None,
                            f"could not launch klt: {exc}")
    wall = time.monotonic() - t0
    report, error = None, None
    if proc.returncode in REPORT_EXIT_CODES:
        try:
            report = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            error = f"klt exited {proc.returncode} but stdout is not a JSON report: {exc}"
        else:
            if not isinstance(report, dict) or not isinstance(report.get("corners"), list):
                report, error = None, "klt report has no corners[] array"
    else:
        error = f"klt sim exited {proc.returncode}: {(proc.stderr or proc.stdout).strip()[-2000:]}"
    group.dir.mkdir(parents=True, exist_ok=True)
    report_path = None
    if report is not None:
        report_path = group.dir / "klt-report.json"
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return GroupOutcome(group, started, _now(), wall, proc.returncode, report, error,
                        (proc.stderr or "")[-2000:], report_path)


def collect(groups: list[Group], runner: Callable[[Group], GroupOutcome] = run_klt) -> list[GroupOutcome]:
    """Submit every group concurrently (they are independent fleet jobs) and
    return the outcomes in group order. Any group without a report aborts the
    run: a partial batch must never be presented as a matrix result."""
    with ThreadPoolExecutor(max_workers=len(groups)) as pool:
        outcomes = list(pool.map(runner, groups))
    failed = [o for o in outcomes if o.report is None]
    if failed:
        lines = [f"  supply {o.group.supply_v:.2f} V: {o.error}" for o in failed]
        done = [o for o in outcomes if o.report is not None]
        raise BatchError(
            "batch submission/collection failed; no results were recorded and nothing was "
            "run locally:\n" + "\n".join(lines)
            + (f"\n  ({len(done)} of {len(outcomes)} job(s) did return a report; "
               "their fleet job ids are in the klt output under each group's klt-out/)"
               if done else "")
        )
    return outcomes


# --------------------------------------------------------------------------
# folding reports back into corner-run result dicts
# --------------------------------------------------------------------------


def _key(process, temp, supply) -> tuple:
    return (str(process), float(temp), round(float(supply), 6))


def _diag_summary(diags: list[dict]) -> str:
    return "; ".join(f"{d.get('code')}[{d.get('severity')}]: {d.get('message', '')}".strip() for d in diags)


def corner_result(exp, corner, kc: dict, timeout_s: int, evaluate: Callable, job: dict, log_rel: str) -> dict:
    """One klt corner entry -> the dict `corner-run.py::run_corner()` returns."""
    diags = kc.get("diagnostics") or []
    err_diags = [d for d in diags if d.get("severity") == "error"]
    codes = {d.get("code") for d in diags}
    timed_out = bool(codes & TIMEOUT_CODES)
    incomplete = bool(codes & INCOMPLETE_CODES)
    values = {
        m["name"]: m["value"]
        for m in kc.get("measurements") or []
        if m.get("value") is not None
    }
    checks, checks_ok = evaluate(exp, values)
    status = kc.get("status")
    ok = (
        status in ("pass", "fail")
        and not err_diags
        and not timed_out
        and not incomplete
        and checks_ok
    )
    failure = None
    if timed_out:
        failure = "TIMEOUT -- the engine/job budget expired (" + _diag_summary(err_diags or diags) + ")"
    elif incomplete:
        failure = "batch job result never observed (" + _diag_summary(diags) + ")"
    elif status not in ("pass", "fail"):
        failure = f"klt corner status {status!r}: " + _diag_summary(diags)
    elif err_diags:
        failure = _diag_summary(err_diags)
    return {
        "corner_id": corner.id,
        "process": corner.process,
        "temperature_c": corner.temp_c,
        "supply_v": corner.supply_v,
        # `klt sim` classifies from the ngspice log and does not report the
        # simulator's exit code or a killing signal (see sim/README.md,
        # "Batch backend": interface gap), so these are unknown, not zero.
        "ngspice_exit": None,
        "timed_out": timed_out,
        "killed_by_signal": None,
        "killed_by_signal_name": None,
        "elapsed_s": kc.get("runtime_s"),
        "timeout_s": timeout_s,
        "measurements": checks,
        "pass": ok,
        "log": log_rel,
        "batch": {
            "klt_status": status,
            "klt_corner_id": kc.get("corner_id"),
            "diagnostics": diags,
            "failure": failure,
            "job_id": job.get("job_id"),
        },
    }


def synthetic_failure(exp, corner, timeout_s: int, reason: str, evaluate: Callable, job_id) -> dict:
    checks, _ = evaluate(exp, {})
    return {
        "corner_id": corner.id,
        "process": corner.process,
        "temperature_c": corner.temp_c,
        "supply_v": corner.supply_v,
        "ngspice_exit": None,
        "timed_out": False,
        "killed_by_signal": None,
        "killed_by_signal_name": None,
        "elapsed_s": None,
        "timeout_s": timeout_s,
        "measurements": checks,
        "pass": False,
        "log": None,
        "batch": {"klt_status": None, "klt_corner_id": None, "diagnostics": [],
                  "failure": reason, "job_id": job_id},
    }


def assemble(
    exp,
    matrix: list,
    outcomes: list[GroupOutcome],
    timeout_s: int,
    evaluate: Callable,
    *,
    local_lib_sha256: str,
    pin: dict,
) -> tuple[list[dict], list[str], dict]:
    """Return (results in matrix order, overall-blocking reasons, execution
    provenance). Pure function of the reports: unit-testable without klt."""
    blockers: list[str] = []
    by_key: dict[tuple, list[tuple[dict, Group, dict]]] = {}
    jobs_meta = []
    for o in outcomes:
        rep = o.report
        env = rep.get("environment") or {}
        remote = env.get("remote") or {}
        prov = rep.get("provenance") or {}
        corner_rt = [c.get("runtime_s") for c in rep["corners"] if c.get("runtime_s") is not None]
        job_elapsed = remote.get("elapsed_seconds")
        meta = {
            "supply_v": o.group.supply_v,
            "job_id": remote.get("job_id"),
            "submitted_at": o.submitted_at,
            "collected_at": o.collected_at,
            "submit_to_collect_wall_s": round(o.wall_s, 1),
            "job_elapsed_s": job_elapsed,
            "queue_provision_and_transfer_s": (
                round(o.wall_s - float(job_elapsed), 1) if _isnum(job_elapsed) else None
            ),
            "corner_runtime_sum_s": round(sum(corner_rt), 1),
            "corner_runtime_max_s": round(max(corner_rt), 1) if corner_rt else None,
            "corner_runtime_min_s": round(min(corner_rt), 1) if corner_rt else None,
            "corner_count": rep.get("corner_count"),
            "klt_status": rep.get("status"),
            "klt_exit_code": o.rc,
            "engine": env.get("engine"),
            "engine_version": env.get("engine_version"),
            "ngspice_binary": env.get("ngspice_binary"),
            "models_lib_sha256": env.get("models_lib_sha256"),
            "netlist_sha256": env.get("netlist_sha256"),
            "pdk_provenance": prov.get("pdk"),
            "klt_client_version": prov.get("klt_version"),
            "remote": remote,
            "report": str(o.report_path) if o.report_path else None,
        }
        jobs_meta.append(meta)
        remote_sha = env.get("models_lib_sha256")
        if remote_sha != local_lib_sha256:
            blockers.append(
                f"supply {o.group.supply_v:.2f} V: remote model library sha256 {remote_sha!r} "
                f"does not match the pinned local library {local_lib_sha256!r}; results from a "
                "different PDK build cannot be trusted"
            )
        if remote.get("runner_compatibility") not in (None, "match"):
            blockers.append(
                f"supply {o.group.supply_v:.2f} V: runner klt "
                f"{remote.get('runner_klt_version')!r} vs client "
                f"{remote.get('client_klt_version')!r} ({remote.get('runner_compatibility')})"
            )
        for kc in rep["corners"]:
            by_key.setdefault(_key(kc.get("process"), kc.get("temperature_c"), o.group.supply_v), []).append(
                (kc, o.group, meta)
            )

    expected = {_key(c.process, c.temp_c, c.supply_v) for c in matrix}
    for k in sorted(set(by_key) - expected):
        blockers.append(f"unexpected corner returned by the fleet: {k}")

    results = []
    for corner in matrix:
        k = _key(corner.process, corner.temp_c, corner.supply_v)
        hits = by_key.get(k, [])
        job_id = next((m["job_id"] for m in jobs_meta if m["supply_v"] == corner.supply_v), None)
        if not hits:
            blockers.append(f"{corner.id}: no result returned")
            results.append(synthetic_failure(exp, corner, timeout_s, "no result returned for this corner", evaluate, job_id))
        elif len(hits) > 1:
            blockers.append(f"{corner.id}: {len(hits)} duplicate results returned")
            results.append(synthetic_failure(
                exp, corner, timeout_s, f"{len(hits)} duplicate results returned; refusing to pick one",
                evaluate, job_id))
        else:
            kc, group, meta = hits[0]
            results.append(corner_result(exp, corner, kc, timeout_s, evaluate, meta, ""))
    for o in outcomes:
        rep = o.report
        if rep.get("corner_count") != len(o.group.corners) or len(rep["corners"]) != len(o.group.corners):
            blockers.append(
                f"supply {o.group.supply_v:.2f} V: expected {len(o.group.corners)} corners, "
                f"report says corner_count={rep.get('corner_count')} with {len(rep['corners'])} entries"
            )
    return results, blockers, {"jobs": jobs_meta}


def _isnum(v) -> bool:
    try:
        float(v)
        return v is not None
    except (TypeError, ValueError):
        return False


# --------------------------------------------------------------------------
# evidence files (raw logs, exact inputs)
# --------------------------------------------------------------------------


def _read(path) -> str | None:
    try:
        return Path(path).read_text(errors="replace")
    except (OSError, TypeError):
        return None


def write_corner_logs(
    results: list[dict], matrix: list, outcomes: list[GroupOutcome], corners_dir: Path, repo_root: Path
) -> None:
    """Per-corner `.log` in the local runner's layout, filled from klt's
    retained artifacts, plus the exact request/netlist/report per group."""
    corners_dir.mkdir(parents=True, exist_ok=True)
    arts: dict[tuple, dict] = {}
    for o in outcomes:
        for kc in o.report["corners"]:
            arts[_key(kc.get("process"), kc.get("temperature_c"), o.group.supply_v)] = kc
    for corner, res in zip(matrix, results):
        kc = arts.get(_key(corner.process, corner.temp_c, corner.supply_v))
        log_path = corners_dir / f"{corner.id}.log"
        deck = log = None
        if kc:
            a = kc.get("artifacts") or {}
            deck, log = _read(a.get("deck")), _read(a.get("log"))
        b = res["batch"]
        lines = [
            f"# corner: {corner.id}",
            f"# process={corner.process} temp={corner.temp_c:g}C supply={corner.supply_v:.2f}V",
            f"# executed on the batch fleet; job {b.get('job_id')}; klt corner status: {b.get('klt_status')}",
            "# ngspice exit code / signal: not exposed by klt sim (see sim/README.md)",
            f"# engine wall clock: {res['elapsed_s']}s (--timeout was {res['timeout_s']}s)",
            f"# result: {'PASS' if res['pass'] else 'FAIL'}"
            + (f" -- {b['failure']}" if b.get("failure") else ""),
            "",
            "# ==== deck (exact input given to ngspice, as retained by klt) ====",
            *([f"| {ln}" for ln in deck.splitlines()] if deck else ["(not retrieved)"]),
            "",
            "# ==== ngspice log (as retained by klt) ====",
            log.rstrip() if log else "(not retrieved)",
            "",
            "# ==== klt diagnostics ====",
            json.dumps(b.get("diagnostics"), indent=2),
            "",
        ]
        log_path.write_text("\n".join(lines))
        res["log"] = str(log_path.relative_to(repo_root))
    for o in outcomes:
        gdir = corners_dir / f"batch-v{o.group.supply_v:.2f}"
        gdir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(o.group.request_path, gdir / "request.json")
        shutil.copyfile(o.group.netlist_path, gdir / "netlist.cir")
        if o.report_path:
            shutil.copyfile(o.report_path, gdir / "klt-report.json")


# --------------------------------------------------------------------------
# the executor `sim_common.run_matrix_and_write_record()` calls
# --------------------------------------------------------------------------


def execute(
    exp,
    pin: dict,
    pdk,
    matrix: list,
    body: list[str],
    spiceinit_text: str,
    work_dir: Path,
    corners_dir: Path,
    repo_root: Path,
    timeout_s: int,
    evaluate: Callable,
    local_tools: dict,
    *,
    capacity_wait_s: float = 3600.0,
    runner_version_check: str = "enforce",
    poll_interval_s: float = 30.0,
    runner: Callable[[Group], GroupOutcome] = run_klt,
) -> tuple[list[dict], list[str], dict]:
    """Build, submit, collect and fold a batch run. Returns
    `(results, overall_blockers, record_extra)`; raises `BatchError` when no
    report could be obtained (nothing is then recorded or run locally)."""
    groups = build_groups(
        exp, pin, matrix, body, spiceinit_text, work_dir, timeout_s,
        capacity_wait_s=capacity_wait_s, runner_version_check=runner_version_check,
        poll_interval_s=poll_interval_s,
    )
    started, t0 = _now(), time.monotonic()
    outcomes = collect(groups, runner)
    total_wall = time.monotonic() - t0
    finished = _now()
    results, blockers, extra = assemble(
        exp, matrix, outcomes, timeout_s, evaluate,
        local_lib_sha256=sha256_file(pdk.lib_file), pin=pin,
    )
    write_corner_logs(results, matrix, outcomes, corners_dir, repo_root)

    jobs = extra["jobs"]
    versions = sorted({str(j["engine_version"]) for j in jobs})
    types = sorted({str(j["remote"].get("instance_type")) for j in jobs})
    amis = sorted({str(j["remote"].get("ami_id")) for j in jobs})
    runtimes = [r["elapsed_s"] for r in results if r["elapsed_s"] is not None]
    execution = {
        "backend": "batch",
        "mechanism": "klt sim --backend batch (2am EDA batch fleet, Spot)",
        "klt_client": local_tools.get("klt"),
        "submitted_at": started,
        "collected_at": finished,
        "submit_to_collect_wall_s": round(total_wall, 1),
        "jobs": jobs,
        "corner_runtime_sum_s": round(sum(runtimes), 1),
        "corner_runtime_min_s": round(min(runtimes), 1) if runtimes else None,
        "corner_runtime_max_s": round(max(runtimes), 1) if runtimes else None,
        "corner_runtime_median_s": round(sorted(runtimes)[len(runtimes) // 2], 1) if runtimes else None,
        "remote_engine_versions": versions,
        "remote_instance_types": types,
        "remote_ami_ids": amis,
        "local_pinned_lib_sha256": sha256_file(pdk.lib_file),
        "remote_pdk_matches_pin": not any("model library sha256" in b for b in blockers),
        "timing_note": (
            "elapsed_s per corner is the remote engine wall clock reported by klt "
            "(runtime_s). job_elapsed_s is the fleet harness's own job time. "
            "queue_provision_and_transfer_s = submit-to-collect wall minus job_elapsed_s "
            "(S3 upload, Spot acquisition/boot, polling granularity, download)."
        ),
        "blockers": blockers,
    }
    tools = dict(local_tools)
    tools["ngspice"] = (
        f"ngspice-{'/'.join(versions)} (remote, batch fleet {'/'.join(types)}; "
        "not the dispatch host's ngspice)"
    )
    record_extra = {"execution": execution, "tools": tools, "jobs": None}
    return results, blockers, record_extra
