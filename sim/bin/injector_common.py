#!/usr/bin/env python3
"""Shared helpers for the two psrr-injector benches,
`sim/psrr-injector-attribution/run_psrr_injector_attribution.py` and
`sim/psrr-injector-candidates/run_psrr_injector_candidates.py`
(issues #379, #410, #511; split out of `sim_common.py` by issue #557).

The two benches are variant-sweeps over the same base body: both build one
local deck per (variant, PVT corner), run the cross product locally or on the
batch fleet, and write the SAME record skeleton. These are the helpers they
share -- the sweep drivers (`run_all_variants` / `run_all_batch`), the local
deck, the per-point run, `explore`'s print loop, and `verify`'s record
skeleton and write tail -- in a sibling module of their own, the same shape
the post-layout family established with `sim/bin/post_layout_common.py`
(issue #16).

What stays per-bench, deliberately: `variant_body()` (different substitution
models -- device removal vs. card retarget/clone/insert), `evaluate()` and
`render_record()` (the per-experiment judgement, as #410 specified),
`parse_args()`, and the early exits each `verify()`/`explore()` owns (the
attribution bench's `--dry-run`, the candidates bench's ceiling load).

What this module needs from `sim_common` it imports rather than copies
(`_cr`, `REPO_DIR`, `corner_id`, `parse_measurements`, `run_ngspice`,
`write_log`, `publish_run_evidence`); the generic batch-request builders
(`batch_netlist`, `build_batch_groups`) stay in `sim_common` (issue #557
scoped the move out) -- these two injector benches are their only callers;
the Monte Carlo runners' same-named `batch_netlist` / `build_batch_groups`
are independent locals with different signatures, not users of these.
For the history of which issue added which helper, see
`git log -p -- sim/bin/injector_common.py sim/bin/sim_common.py`.
"""

from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from sim_common import (  # noqa: E402  (importers put sim/bin on sys.path first)
    REPO_DIR,
    _cr,
    corner_id,
    parse_measurements,
    publish_run_evidence,
    run_ngspice,
    write_log,
)


def band_min_by_corner(path: Path, label: str) -> dict[str, float]:
    """Per-corner `psrr_band_min` values from an existing record json (issue #379)."""
    cr = _cr()
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


def run_all_variants(
    run_point, variants, points, jobs: int, label_width: int
) -> dict[tuple[str, str], dict]:
    """Run `run_point(variant, process, temp_c, supply_v)` over variants x points.

    Prints a `[done/total]` progress line per result, with the variant name
    padded to `label_width`, and returns `{(variant, corner_id): result}`
    (issue #379).
    """
    work = [(v, p, t, s) for v in variants for (p, t, s) in points]
    total = len(work)
    results: dict[tuple[str, str], dict] = {}
    done = 0

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for res in pool.map(lambda item: run_point(*item), work):
            done += 1
            band = res["measurements"].get("psrr_band_min")
            print(f"[{done:3d}/{total}] {res['variant']:{label_width}s} {res['corner_id']:16s} "
                  + (f"psrr_band_min={band:8.3f} dB" if band is not None
                     else f"NO MEASUREMENT (rc={res['ngspice_exit']}, "
                          f"timeout={res['timed_out']})"),
                  flush=True)
            results[(res["variant"], res["corner_id"])] = res
    return results


def artifact_text(kc: dict | None, which: str) -> str | None:
    try:
        return Path((kc.get("artifacts") or {}).get(which)).read_text(errors="replace")
    except (OSError, TypeError, AttributeError):
        return None


def write_batch_log(corners_dir: Path, name: str, record_id: str, kcs: dict) -> None:
    corners_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"# point: {name}", f"# record: {record_id}",
             "# executed on the batch fleet via klt sim; ngspice exit code not exposed by klt", ""]
    for kind, kc in kcs.items():
        lines += [f"# ==== {kind}: deck (as retained by klt) ====",
                  *[f"| {ln}" for ln in (artifact_text(kc, "deck") or "(not retrieved)").splitlines()],
                  "", f"# ==== {kind}: ngspice log (as retained by klt) ====",
                  (artifact_text(kc, "log") or "(not retrieved)").rstrip(), "",
                  f"# ==== {kind}: klt diagnostics ====",
                  json.dumps(kc.get("diagnostics"), indent=2), ""]
    (corners_dir / f"{name}.log").write_text("\n".join(lines))


def batch_tools(execution: dict | None) -> dict:
    cr = _cr()
    tools = cr.tool_versions()
    if execution is not None:
        tools["klt"] = cr.first_line(["klt", "--version"])
        tools["ngspice"] = (
            f"ngspice-{'/'.join(execution['remote_engine_versions'])} (remote, batch fleet "
            f"{'/'.join(execution['remote_instance_types'])}; not this host's ngspice)"
        )
    return tools


def run_all_batch(
    pdk, pin, base_body, variants, points, timeout, corners_dir, record_id, args, runner,
    *, batch_sim, run_dir: Path, kinds, build_groups,
):
    """Run every (variant, point) on the batch fleet. Returns `(results,
    blockers, execution)`; `results` has the shape of a local `run_all()`'s.
    `build_groups(pin, base_body, variants, points, run_dir, timeout, args)`
    builds the requests; `kinds` names the analyses per point."""
    cr = _cr()
    supplies = list(dict.fromkeys(s for _p, _t, s in points))
    try:
        groups = build_groups(pin, base_body, variants, points, run_dir, timeout, args)
        # Each request is sharded over `remote.hosts` fleet jobs; divide the
        # job budget so shard jobs in flight stay within --batch-max-jobs.
        hosts = max((g.request["remote"]["hosts"] for g in groups), default=1)
        request_workers = max(1, args.batch_max_jobs // hosts)
        print(f"batch         : {len(groups)} klt sim requests "
              f"({len(variants)} variants x {len(supplies)} supplies x {len(kinds)} analyses), "
              f"{request_workers} at a time x {hosts} shard job(s) each")
        outcomes = batch_sim.collect(groups, runner, max_workers=request_workers)
    except batch_sim.BatchError as err:
        raise cr.HarnessError(str(err)) from err
    lib_sha = batch_sim.sha256_file(pdk.lib_file)
    values, klt_corners, blockers, jobs = batch_sim.collect_values(outcomes, lib_sha)

    results: dict[tuple[str, str], dict] = {}
    for v in variants:
        for p, t, s in points:
            cid = corner_id(p, t, s)
            meas: dict[str, float] = {}
            kcs, timed_out = {}, False
            for kind in kinds:
                key = batch_sim._key(p, t, s) + (f"{v.name}-{kind}-v{s:.2f}",)
                kc = klt_corners.get(key)
                if kc is None:
                    blockers.append(f"{v.name}/{cid}: no {kind} result returned")
                    continue
                kcs[kind] = kc
                meas.update(values[key])
                diags = kc.get("diagnostics") or []
                timed_out |= bool({d.get("code") for d in diags} & batch_sim.TIMEOUT_CODES)
                errs = [d for d in diags if d.get("severity") == "error"]
                if errs:
                    blockers.append(f"{v.name}/{cid} [{kind}]: " + batch_sim._diag_summary(errs))
            results[(v.name, cid)] = {
                "variant": v.name, "corner_id": cid, "process": p, "temperature_c": t,
                "supply_v": s, "ngspice_exit": None, "timed_out": timed_out,
                "measurements": meas,
                "batch": {k: {"klt_status": kc.get("status"), "klt_corner_id": kc.get("corner_id"),
                              "diagnostics": kc.get("diagnostics") or []} for k, kc in kcs.items()},
            }
            if corners_dir is not None:
                write_batch_log(corners_dir, f"{v.name}__{cid}", record_id, kcs)
    if corners_dir is not None:
        for o in outcomes:
            gdir = corners_dir / f"batch-{o.group.label}"
            gdir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(o.group.request_path, gdir / "request.json")
            shutil.copyfile(o.group.netlist_path, gdir / "netlist.cir")
            if o.report_path:
                shutil.copyfile(o.report_path, gdir / "klt-report.json")
    worker_environments = batch_sim.hoist_worker_environments(jobs)
    versions = sorted({str(j["engine_version"]) for j in jobs})
    execution = {
        "backend": "batch",
        "mechanism": "klt sim --backend batch (2am EDA batch fleet, Spot)",
        "requests": len(groups),
        "max_concurrent_requests": request_workers,
        "jobs": jobs,
        batch_sim.WORKER_ENVIRONMENTS_TABLE: worker_environments,
        "remote_engine_versions": versions,
        "remote_instance_types": sorted({str(j["remote"].get("instance_type")) for j in jobs}),
        "local_pinned_lib_sha256": lib_sha,
        "remote_pdk_matches_pin": not any("model library sha256" in b for b in blockers),
        "blockers": blockers,
    }
    for (_v, cid), res in sorted(results.items()):
        band = res["measurements"].get("psrr_band_min")
        print(f"  {res['variant']:13s} {cid:16s} "
              + (f"psrr_band_min={band:8.3f} dB" if band is not None else "NO MEASUREMENT"),
              flush=True)
    return results, blockers, execution


def parse_corner_spec(spec: str) -> list[tuple[str, float, float]]:
    """`"ff,125,3.63;tt,27,3.30"` -> `[("ff", 125.0, 3.63), ("tt", 27.0, 3.3)]`.

    The `--corners` explore-mode spec both psrr-injector benches accept.
    """
    points = [tuple(pt.split(",")) for pt in spec.split(";")]
    return [(p, float(t), float(s)) for p, t, s in points]


def injector_deck(
    slug: str, script: str, pdk, variant, process: str, temp_c: float, supply_v: float,
    body: list[str], *, deck_options, ac_analysis: str, ac_meas, op_meas,
) -> str:
    """The local ngspice deck for one (variant, PVT corner): head, the already-
    substituted `body`, then the AC sweep followed by the operating point.

    `op_meas` is the full operating-point readout list for THIS variant -- the
    attribution bench passes `OP_ALWAYS + tuple(variant.op_extra)`, the
    candidates bench passes `OP_ALWAYS` (its variants carry no `op_extra`).
    """
    cr = _cr()
    head = [
        f"* {slug} deck -- generated by sim/{slug}/{script}, do not edit",
        f"* variant: {variant.name} ({variant.what})",
        f"* corner: {corner_id(process, temp_c, supply_v)}",
        f".param vsup={supply_v}",
    ]
    head += [f".option {opt}" for opt in deck_options]
    head += [f".temp {cr.fmt_temp(temp_c)}", f'.lib "{pdk.lib_file}" {process}']

    ctrl = [".control", "save all", ac_analysis]
    ctrl += [f"let meas_{n} = {e}" for n, e in ac_meas]
    ctrl += [f"print meas_{n}" for n, _ in ac_meas]
    # `op` re-points the current plot, so every AC readout above is already
    # printed by the time the operating point is solved.
    ctrl += ["op"]
    ctrl += [f"let meas_{n} = {e}" for n, e in op_meas]
    ctrl += [f"print meas_{n}" for n, _ in op_meas]
    ctrl += ["quit", ".endc", ".end", ""]
    return "\n".join(head + body + ctrl)


def injector_run_point(
    pdk, variant, process: str, temp_c: float, supply_v: float, timeout: int,
    corners_dir: Path | None, record_id: str, *, build_dir: Path, deck: str,
) -> dict:
    """Run one (variant, corner) deck locally and return its result row.

    `deck` is the caller's `build_deck(...)` output -- the per-bench deck
    constants stay in the calling script. Writes the per-corner log under
    `corners_dir` when one is given (explore mode passes `None`).
    """
    cid = corner_id(process, temp_c, supply_v)
    name = f"{variant.name}__{cid}"
    # One run dir per point: `run_ngspice()` writes `.spiceinit` into it, so
    # sharing a dir across concurrent points would race on that file.
    run_dir = build_dir / record_id / name
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


def injector_run_variants(
    args, pdk, pin, base_body, variants, points, corners_dir: Path | None, record_id: str,
    *, run_all, run_all_batch,
):
    """Dispatch a (variants x points) run to the backend `args.backend` names.

    Returns `(results, blockers, execution)` for either backend: the local path
    has no blockers and no `execution` block. `run_all` / `run_all_batch` are
    the calling script's own thin wrappers (they bind its `BUILD_DIR` and
    progress-label width).
    """
    if args.backend == "batch":
        return run_all_batch(pdk, pin, base_body, variants, points, args.timeout,
                             corners_dir, record_id, args)
    results = run_all(pdk, base_body, variants, points, args.timeout, args.jobs,
                      corners_dir, record_id)
    return results, [], None


def injector_explore(
    args, pdk, pin, base_body, variants, points, *, base_snapshot: Path, label_width: int,
    run_all, run_all_batch,
) -> int:
    """`--explore`'s body: run the selected variants/corners and print one line
    per result, writing NOTHING under `sim/<experiment>/`.

    `label_width` pads the variant-name column (the benches' longest variant
    names differ). Always returns 0 -- explore mode makes no claim to fail.
    """
    print(f"PDK: {pdk.dir} (open_pdks {pdk.installed_commit})")
    print(f"base body: {base_snapshot.relative_to(REPO_DIR)}")
    print("(explore mode: nothing is written under sim/<experiment>/)")
    results, blockers, _execution = injector_run_variants(
        args, pdk, pin, base_body, variants, points, None, "explore",
        run_all=run_all, run_all_batch=run_all_batch)
    for b in blockers:
        print(f"  BLOCKER: {b}")
    print()
    for (v, cid), res in sorted(results.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        m = res["measurements"]
        print(f"  {cid:16s} {v:{label_width}s} "
              f"band_min={m.get('psrr_band_min', float('nan')):8.3f} "
              f"dc={m.get('psrr_dc', float('nan')):8.3f} "
              f"vref={m.get('v_vref', float('nan')):.5f} "
              f"ng={m.get('v_ng', float('nan')):.4f}")
    return 0


def new_record_id() -> tuple[str, dict, datetime]:
    """`(record_id, git_info, now)` -- the `<date>-<time>-<sha>` id both
    psrr-injector benches stamp a record with, and the git state and timestamp
    that id is derived from (both land in the record itself)."""
    git_info = _cr().git_state()
    now = datetime.now(timezone.utc)
    return f"{now:%Y%m%d}-{now:%H%M%S}-{git_info['sha']}", git_info, now


def injector_banner(
    args, pdk, variants, points, record_id: str, *, slug: str, base_snapshot: Path
) -> None:
    """`verify`'s what-is-about-to-run header, printed before the first run."""
    print(f"experiment    : {slug}")
    print(f"record id     : {record_id}")
    print(f"PDK           : {pdk.dir} (open_pdks {pdk.installed_commit})")
    print(f"base body     : {base_snapshot.relative_to(REPO_DIR)}")
    print(f"points        : {len(points)} corners x {len(variants)} variants "
          f"= {len(points) * len(variants)} ngspice runs "
          + ("(batch fleet)" if args.backend == "batch" else f"(jobs={args.jobs})"))


def batch_integrity_checks(blockers) -> list[dict]:
    """One failing `batch_integrity[i]` check per fleet blocker: an
    untrustworthy fleet run must read as a failing record, not a footnote."""
    return [{"name": f"batch_integrity[{i}]", "pass": False, "detail": b}
            for i, b in enumerate(blockers)]


def injector_record_head(
    args, pdk, pin, variants, execution, record_id: str, now: datetime, git_info: dict,
    extra_record: dict, *, slug: str, title: str, base_snapshot: Path,
    wrapped_schematic: str, statistical_convention: str, processes, temps_c, supplies_v,
) -> dict:
    """The record keys both psrr-injector benches write identically, in the
    order they write them: identity, `experiment`, `pdk`, `tools`, `git`,
    `matrix`, `variants`, then `jobs` / `execution`.

    `extra_record` is spliced in between `variants` and `jobs` -- that is where
    each bench's own mid-record keys sit (`cited_record` / `cited`, and the
    candidates bench's `ceiling_record` / `ceiling`), so sharing the skeleton
    does not reorder a record's json. The caller appends its `points` /
    `checks` / `overall_pass` / `links` tail.
    """
    cr = _cr()
    batch = args.backend == "batch"
    return {
        "record_id": record_id,
        "timestamp": now.isoformat(),
        "author": args.author or cr.default_author(),
        "experiment": {
            "slug": slug, "title": title,
            "provenance": "schematic",
            "provenance_source": str(base_snapshot.relative_to(REPO_DIR)),
            "wrapped_schematic": wrapped_schematic,
            "statistical_convention": statistical_convention,
        },
        "pdk": {
            "family": pin["family"], "variant": pdk.variant, "dir": str(pdk.dir),
            "installed_commit": pdk.installed_commit,
            "pinned_commit": pin["open_pdks_commit"],
            "matches_pin": pdk.matches_pin,
            "lib_file": str(pdk.lib_file),
        },
        "tools": batch_tools(execution),
        "git": git_info,
        "matrix": {
            "process": list(processes), "temperature_c": list(temps_c),
            "supply_v": list(supplies_v), "is_subset": False,
        },
        "variants": [v.name for v in variants],
        **extra_record,
        "jobs": None if batch else args.jobs,
        "execution": execution,
    }


def injector_links(
    base_snapshot: Path, companion: str, cited_record_id: str, slug: str, script: str,
    extra: dict | None = None,
) -> dict:
    """The record's `links` block. `extra` is spliced in after `cited_record`,
    where the candidates bench puts its `ceiling_record` / `attribution`
    entries, so the key order of an existing record is preserved."""
    return {
        "base_snapshot": str(base_snapshot.relative_to(REPO_DIR)),
        "cited_record": f"{companion}/records/{cited_record_id}.json",
        **(extra or {}),
        "companion_manifest": f"{companion}/experiment.json",
        "runner": f"sim/{slug}/{script}",
    }


def write_injector_record(
    record: dict, records_dir: Path, corners_dir: Path, record_md: Path, record_json: Path,
    *, render,
) -> int:
    """Publish the run's raw evidence, write the record md+json, print the
    verdict, and return `verify`'s exit code (0 PASS / 2 FAIL).

    `publish_run_evidence()` runs FIRST so a store failure leaves no record.
    `_`-prefixed keys (the in-memory `_results` / `_points` the renderer uses)
    are dropped from the json.
    """
    publish_run_evidence(corners_dir)
    records_dir.mkdir(parents=True, exist_ok=True)
    record_md.write_text(render(record))
    record_json.write_text(json.dumps(
        {k: v for k, v in record.items() if not k.startswith("_")}, indent=2) + "\n")
    print(f"\nrecord: {record_md.relative_to(REPO_DIR)}")
    overall = record["overall_pass"]
    print(f"Overall: {'PASS' if overall else 'FAIL'}")
    for c in record["checks"]:
        if not c["pass"]:
            print(f"  FAIL {c['name']}: {c['detail']}")
    return 0 if overall else 2
