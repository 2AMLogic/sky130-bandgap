#!/usr/bin/env python3
"""Derived DR-005 untrimmed-accuracy qualification from committed MC samples (issue #334).

`run_mc_untrimmed.py` grades each Monte Carlo point against a >= 50 % in-window
*sanity floor* (its own caveat says so: it is not the literal 3-sigma spec
threshold). DR-005's Output-reference row is "1.20 V +/-2 % untrimmed (3 sigma,
mismatch MC N>=300 + process corners, -40...125 C)". This script grades that
literal row from the SAME committed corner logs (the samples `emit_klt_yield.py`
already extracts), without any new simulation, and records three verdicts that
must not be conflated:

* ``evidence_existence`` -- the samples/envelope exist (what T1 item 6 means);
* ``harness_sanity``     -- the retained >= 50 % in-window floor, per temperature;
* ``spec``               -- DR-005: mean +/- 3 sigma inside [1.176, 1.224] V.

Statistical convention (stated in every record it mints)
--------------------------------------------------------
* mean and *sample* sigma (n-1 denominator) of the converged ``tt_mm``/``all``
  draws at each temperature; 3-sigma bounds mean +/- 3*sigma against the window,
  inclusive (a bound exactly on the limit passes);
* a 3-sigma calculation is a parametric statement (it presumes the draws are
  roughly normal), NOT an empirical confidence guarantee: the empirical in-window
  fraction with its Clopper-Pearson 95 % interval is reported next to it and the
  two are never merged into one number;
* ``tt_mm`` is *local mismatch at the nominal process point only*. It is not
  process-plus-mismatch coverage; the committed corner matrix (process corners,
  no mismatch) is deterministic and its extrema are NOT combined with the MC
  spread, because adding unrelated extrema is not a statistically supported claim.
  No joint process x mismatch evidence exists, so a spec PASS is unreachable and
  the best attainable spec verdict on this evidence is INSUFFICIENT_EVIDENCE;
* N: DR-005 requires N >= 300. The requirement is applied to *converged* draws
  (issue #10 startup non-convergences are not mismatch data). A temperature below
  300 converged draws can still FAIL (a violation is a violation) but can never
  PASS.

Verdict composition: any FAIL -> FAIL; else any INSUFFICIENT_EVIDENCE (short N,
missing temperature, unavailable joint coverage) -> INSUFFICIENT_EVIDENCE; else PASS.

Usage
-----
    sim/monte-carlo-untrimmed/qualify_dr005.py <record_id>

Writes ``records/<record_id>-dr005-qualification.{json,md}`` (append-only: refuses
to overwrite). Stdlib + the sibling ``emit_klt_yield`` sample loader only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE.parent
REPO_ROOT = SIM_DIR.parent
sys.path.insert(0, str(HERE))
import emit_klt_yield as eky  # noqa: E402

WINDOW_V = (1.176, 1.224)
N_REQUIRED = 300
SANITY_FLOOR = 0.50
CONFIDENCE = 0.95
SUFFIX = "dr005-qualification"
SIGMAS = 3.0


# --------------------------------------------------------------------------
# statistics
# --------------------------------------------------------------------------
def _log_binom_pmf(k: int, n: int, p: float) -> float:
    if p <= 0.0:
        return 0.0 if k == 0 else -math.inf
    if p >= 1.0:
        return 0.0 if k == n else -math.inf
    return (math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
            + k * math.log(p) + (n - k) * math.log1p(-p))


def _binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k)."""
    return min(1.0, sum(math.exp(_log_binom_pmf(i, n, p)) for i in range(0, k + 1)))


def clopper_pearson(k: int, n: int, confidence: float = CONFIDENCE) -> tuple[float, float]:
    """Exact two-sided binomial interval (stdlib bisection)."""
    if n <= 0:
        return (0.0, 1.0)
    a = (1.0 - confidence) / 2.0

    def bisect(f, lo=0.0, hi=1.0):
        for _ in range(100):
            mid = (lo + hi) / 2.0
            if f(mid):
                hi = mid
            else:
                lo = mid
        return (lo + hi) / 2.0

    low = 0.0 if k == 0 else bisect(lambda p: 1.0 - _binom_cdf(k - 1, n, p) >= a)
    high = 1.0 if k == n else bisect(lambda p: _binom_cdf(k, n, p) <= a, 0.0, 1.0)
    return (low, high)


def grade_temperature(temp_c: float, requested: int | None, samples: list[float] | None, *,
                      window=WINDOW_V, n_required: int = N_REQUIRED) -> dict:
    """Grade one temperature. ``samples`` are the *converged* vout draws."""
    lo, hi = window
    out: dict = {"temperature_c": temp_c, "requested_n": requested,
                 "converged_n": len(samples) if samples is not None else 0}
    if not samples or len(samples) < 2:
        out.update(mean_v=None, sigma_v=None, lower_3sigma_v=None, upper_3sigma_v=None,
                   three_sigma_inside_window=None, yield_empirical=None, yield_ci95=None,
                   harness_sanity="INSUFFICIENT_EVIDENCE", spec="INSUFFICIENT_EVIDENCE",
                   n_sufficient=False,
                   reason="no usable converged samples at this temperature")
        return out
    n = len(samples)
    mean = statistics.fmean(samples)
    sigma = statistics.stdev(samples)  # sample sigma, n-1
    lower, upper = mean - SIGMAS * sigma, mean + SIGMAS * sigma
    inside = lower >= lo and upper <= hi
    k = sum(1 for v in samples if lo <= v <= hi)
    ci = clopper_pearson(k, n)
    n_ok = n >= n_required
    sanity = "PASS" if k / n >= SANITY_FLOOR else "FAIL"
    if not inside:
        spec, reason = "FAIL", "mean +/- 3 sigma extends outside the window"
    elif not n_ok:
        spec, reason = "INSUFFICIENT_EVIDENCE", f"{n} converged draws < required {n_required}"
    else:
        spec, reason = "PASS", "mean +/- 3 sigma inside the window with sufficient converged N"
    out.update(mean_v=mean, sigma_v=sigma, lower_3sigma_v=lower, upper_3sigma_v=upper,
               three_sigma_inside_window=inside,
               margin_lower_mv=(lower - lo) * 1e3, margin_upper_mv=(hi - upper) * 1e3,
               in_window_n=k, yield_empirical=k / n, yield_ci95=list(ci),
               sample_min_v=min(samples), sample_max_v=max(samples),
               harness_sanity=sanity, spec=spec, n_sufficient=n_ok, reason=reason)
    return out


def qualify(per_temp: list[dict], *, joint_process_mismatch_available: bool = False,
            expected_temps=tuple(eky.TEMPS_C), window=WINDOW_V,
            n_required: int = N_REQUIRED) -> dict:
    """``per_temp``: dicts with ``temperature_c``, ``requested_n``, ``samples``."""
    by_t = {float(p["temperature_c"]): p for p in per_temp}
    rows = []
    for t in expected_temps:
        p = by_t.get(float(t))
        rows.append(grade_temperature(float(t), p.get("requested_n") if p else None,
                                      p.get("samples") if p else None,
                                      window=window, n_required=n_required))
    specs = [r["spec"] for r in rows]
    sanities = [r["harness_sanity"] for r in rows]
    if "FAIL" in specs:
        spec = "FAIL"
    elif "INSUFFICIENT_EVIDENCE" in specs or not joint_process_mismatch_available:
        spec = "INSUFFICIENT_EVIDENCE"
    else:
        spec = "PASS"
    if "FAIL" in sanities:
        sanity = "FAIL"
    elif "INSUFFICIENT_EVIDENCE" in sanities:
        sanity = "INSUFFICIENT_EVIDENCE"
    else:
        sanity = "PASS"
    return {
        "verdicts": {
            "evidence_existence": "PRESENT" if all(r["converged_n"] > 0 for r in rows) else "INCOMPLETE",
            "harness_sanity": sanity,
            "spec": spec,
        },
        "window_v": list(window), "sigmas": SIGMAS, "n_required_converged": n_required,
        "sanity_floor": SANITY_FLOOR, "confidence": CONFIDENCE,
        "joint_process_mismatch_available": joint_process_mismatch_available,
        "temperatures": rows,
    }


# --------------------------------------------------------------------------
# record minting
# --------------------------------------------------------------------------
def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(p: Path) -> str:
    return str(p.resolve().relative_to(REPO_ROOT))


def collect(record_id: str) -> tuple[list[dict], dict]:
    src = HERE / "records" / f"{record_id}.json"
    if not src.is_file():
        raise SystemExit(f"error: no such record: {src}")
    rec = json.loads(src.read_text())
    reqs = {}
    for pt in rec["points"]:
        if pt.get("config") == "all" and pt.get("section") == "tt_mm" and "seed_b" not in pt["corner_id"] \
                and pt.get("role") == "mismatch":
            reqs[float(pt["temperature_c"])] = pt.get("requested_samples")
    per_temp = []
    logs = {}
    for t in eky.TEMPS_C:
        log = HERE / "corners" / record_id / f"{eky.corner_id_for(t)}.log"
        per_temp.append({"temperature_c": t, "requested_n": reqs.get(t),
                         "samples": eky.load_vout_samples(log)})
        logs[eky.corner_id_for(t)] = {"path": _rel(log), "sha256": _sha(log)}
    return per_temp, {"source_record": _rel(src), "source_sha256": _sha(src), "logs": logs}


def render_md(rec: dict) -> str:
    q = rec["qualification"]
    v = q["verdicts"]
    L = [f"# Record {rec['record_id']}", "",
         f"- **Record ID**: {rec['record_id']}",
         "- **Experiment**: `monte-carlo-untrimmed` -- derived DR-005 untrimmed-accuracy qualification (issue #334)",
         f"- **Claim**: grade the literal DR-005 Output-reference row (1.20 V +/-2 %, 3 sigma, mismatch MC N>=300) from "
         f"the committed samples of record `{rec['source']['record_id']}`, separately from that record's >=50 % harness "
         "sanity floor and from T1 item 6's evidence-existence meaning. No new simulation was run.",
         f"- **Source**: `{rec['source']['source_record']}` (sha256 `{rec['source']['source_sha256']}`)",
         f"- **Repo state**: `{rec['git_sha']}`",
         f"- **Timestamp / author**: {rec['timestamp']}, {rec['author']}",
         "- **Supersedes**: (none -- first DR-005 3-sigma qualification of the untrimmed output)", "",
         "## Three separate verdicts", "",
         "| verdict | value | meaning |", "|---|---|---|",
         f"| evidence existence | **{v['evidence_existence']}** | committed samples and `klt yield` envelope exist (T1 item 6; says nothing about conformance) |",
         f"| harness sanity (>= {q['sanity_floor']:.0%} in-window floor) | **{v['harness_sanity']}** | `run_mc_untrimmed.py`'s own per-point gate; a sanity floor, not the 3-sigma threshold |",
         f"| **DR-005 spec (mean +/- 3 sigma in [{q['window_v'][0]}, {q['window_v'][1]}] V)** | **{v['spec']}** | the literal specification row, on the evidence available |",
         "", "## Per-temperature results (converged `tt_mm` all-family draws)", "",
         "| T (C) | requested N | converged N | mean (V) | sample sigma (mV) | mean-3s (V) | mean+3s (V) | 3-sigma in window | empirical yield | 95 % CP CI | sanity | spec |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in q["temperatures"]:
        if r["mean_v"] is None:
            L.append(f"| {r['temperature_c']:g} | {r['requested_n']} | {r['converged_n']} | -- | -- | -- | -- | -- | -- | -- | {r['harness_sanity']} | {r['spec']} |")
            continue
        L.append(f"| {r['temperature_c']:g} | {r['requested_n']} | {r['converged_n']} | {r['mean_v']:.6f} | "
                 f"{r['sigma_v']*1e3:.3f} | {r['lower_3sigma_v']:.6f} | {r['upper_3sigma_v']:.6f} | "
                 f"{'yes' if r['three_sigma_inside_window'] else 'NO'} (margins {r['margin_lower_mv']:+.1f} / {r['margin_upper_mv']:+.1f} mV) | "
                 f"{r['yield_empirical']:.2%} ({r['in_window_n']}/{r['converged_n']}) | "
                 f"[{r['yield_ci95'][0]:.2%}, {r['yield_ci95'][1]:.2%}] | {r['harness_sanity']} | {r['spec']} |")
    L += ["", "Per-temperature reasons:", ""]
    L += [f"- {r['temperature_c']:g} C: {r['spec']} -- {r['reason']}" for r in q["temperatures"]]
    L += ["", "## Statistical convention and coverage disclosure", ""]
    L += [f"- {s}" for s in rec["conventions"]]
    L += ["", "## Determination", "", rec["determination"], "",
          "Written by `sim/monte-carlo-untrimmed/qualify_dr005.py`. Append-only: never edit this file -- a correction "
          "is a new record with a `Supersedes` field (see `sim/README.md`).", ""]
    return "\n".join(L)


def conventions(q: dict) -> list[str]:
    return [
        "Mean and sample standard deviation (n-1) of the converged draws; 3-sigma bounds are mean +/- 3 sigma; "
        "a bound exactly on a window limit passes.",
        "A 3-sigma calculation is parametric (presumes near-normal draws). It is not an empirical confidence "
        "guarantee; the empirical in-window fraction and its exact Clopper-Pearson 95 % interval are reported "
        "beside it and are never merged with it. The two can disagree (yield above 50 % while mean +/- 3 sigma "
        "is outside the window).",
        "tt_mm is LOCAL MISMATCH at the nominal (tt) process point only. It is not full process-plus-mismatch "
        "coverage. The process-corner matrix (report row 1a) is deterministic, mismatch-free evidence; its "
        "extrema are not combined with the MC spread because summing unrelated extrema is not a supported "
        "statistical claim.",
        "Joint process x mismatch coverage is UNAVAILABLE in the committed evidence "
        f"(joint_process_mismatch_available = {q['joint_process_mismatch_available']}); a spec PASS is therefore "
        "unreachable on this evidence even if every temperature's 3-sigma bounds fit.",
        f"DR-005 requires N >= {q['n_required_converged']}; applied to CONVERGED draws (non-converged startup "
        "artifacts, issue #10, are not mismatch data). Short N cannot PASS but can FAIL.",
    ]


def determination(q: dict) -> str:
    v = q["verdicts"]["spec"]
    bad = [f"{r['temperature_c']:g} C" for r in q["temperatures"] if r["spec"] == "FAIL"]
    short = [f"{r['temperature_c']:g} C ({r['converged_n']})" for r in q["temperatures"] if not r["n_sufficient"]]
    s = f"DR-005 spec verdict on the committed evidence: **{v}**. "
    if bad:
        s += f"Mean +/- 3 sigma extends outside the window at {', '.join(bad)}. "
    if short:
        s += f"Below the required converged N: {', '.join(short)}. "
    s += ("The >=50 % harness sanity floor and the T1 item 6 evidence-existence verdict are unchanged and do not "
          "imply spec conformance. Circuit correction or broader Monte Carlo (joint process x mismatch, more "
          "converged draws) is separate follow-up work; DR-005 is not relaxed by this record.")
    return s


def mint(record_id: str, author: str = "loom-builder (issue #334)") -> tuple[Path, Path]:
    out_json = HERE / "records" / f"{record_id}-{SUFFIX}.json"
    out_md = out_json.with_suffix(".md")
    for p in (out_json, out_md):
        if p.exists():
            raise SystemExit(f"error: {_rel(p)} exists; records/* is append-only (sim/README.md)")
    per_temp, src = collect(record_id)
    src["record_id"] = record_id
    ky = HERE / "records" / "20260923-062524-1e38c62-klt-yield-input.json"
    if ky.is_file():
        src["klt_yield_input"] = {"path": _rel(ky), "sha256": _sha(ky)}
    q = qualify(per_temp)
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                         cwd=REPO_ROOT).stdout.strip()
    rec = {"record_id": f"{record_id}-{SUFFIX}", "kind": "derived-qualification", "author": author,
           "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "git_sha": sha,
           "supersedes": None, "source": src, "qualification": q,
           "conventions": conventions(q), "determination": determination(q)}
    out_json.write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n")
    out_md.write_text(render_md(rec))
    return out_md, out_json


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("record_id")
    ap.add_argument("--author", default="loom-builder (issue #334)")
    a = ap.parse_args(argv)
    md, js = mint(a.record_id, a.author)
    print(f"wrote {_rel(md)}\nwrote {_rel(js)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
