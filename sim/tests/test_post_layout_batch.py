#!/usr/bin/env python3
"""Coverage for the post-layout benches' `--backend batch` path (issue #396):
`batch_sim.build_groups(..., gate_slug=<post-layout slug>)` and the
`post_layout_common` flag set. Needs no PDK, ngspice, klt or network: the
requests are built from each bench's manifest and a stand-in extracted body.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIM_DIR / "bin"))

import batch_sim  # noqa: E402
import post_layout_common as plc  # noqa: E402
import sim_common  # noqa: E402

cr = sim_common.load_corner_run()
PIN = json.loads((SIM_DIR / "pdk.json").read_text())
SPICEINIT = (SIM_DIR / "spiceinit").read_text()
BODY = ["V1 VDD 0 'vsup'", "XBG VREF GDRV VDD 0 bandgap_core", ".subckt bandgap_core a b c d", ".ends"]

# slug -> the manifest directory its runner wraps (or owns)
MANIFEST = {
    "psrr-dc-post-layout": "psrr-dc",
    "quiescent-current-post-layout": "quiescent-current",
    "startup-stability-post-layout": "startup-stability-post-layout",
    "startup-ramp-post-layout": "startup-ramp-post-layout",
    "startup-time-post-layout": "startup-time",
    "line-regulation-post-layout": "line-regulation",
    "output-voltage-tc-post-layout": "output-voltage-tc",
}


def matrix(exp):
    c = exp.raw["corners"]
    return [
        cr.Corner(p, float(t), float(v))
        for p in c["process"]
        for t in c["temperature_c"]
        for v in c["supply_v"]
    ]


class PostLayoutBatchRequests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def groups(self, slug):
        exp = cr.load_experiment(SIM_DIR / MANIFEST[slug])
        return exp, batch_sim.build_groups(
            exp, PIN, matrix(exp), BODY, SPICEINIT, self.tmp / slug, 60,
            capacity_wait_s=60, runner_version_check="enforce", poll_interval_s=30,
            gate_slug=slug,
        )

    def test_enabled_benches_build_one_request_per_supply(self):
        """Every enabled post-layout bench builds real (non-dry-run) requests.

        Since issue #510 that is all seven, including the four whose `meas`
        cards make the request a single `analysis_steps[]` step -- so the
        measurement list is read from whichever of the two shapes the request
        carries.
        """
        for slug in sorted(batch_sim.POST_LAYOUT_BATCH_ENABLED_SLUGS):
            with self.subTest(slug=slug):
                exp, groups = self.groups(slug)
                self.assertEqual(
                    sorted(g.supply_v for g in groups),
                    sorted({c.supply_v for c in matrix(exp)}),
                )
                self.assertEqual(sum(len(g.corners) for g in groups), len(matrix(exp)))
                stepped = slug in batch_sim.POST_LAYOUT_STEP_REQUEST_SLUGS
                for g in groups:
                    self.assertEqual(g.request["backend"], "batch")
                    if stepped:
                        (step,) = g.request["analysis_steps"]
                        self.assertNotIn("analysis", g.request)
                        # the manifest's own measurements ride along with the
                        # translated `meas` cards, in manifest order
                        names = [m["name"] for m in step["measurements"]]
                        self.assertEqual(
                            [n for n in names if n in {m.name for m in exp.measurements}],
                            [m.name for m in exp.measurements],
                        )
                    else:
                        self.assertEqual(
                            [m["name"] for m in g.request["measurements"]],
                            [m.name for m in exp.measurements],
                        )
                    text = g.netlist_path.read_text()
                    self.assertIn(f".param vsup={g.supply_v}", text)
                    self.assertIn("XBG VREF GDRV VDD 0 bandgap_core", text)
                    self.assertNotIn(".lib", text)  # klt adds it per process corner

    def test_analysis_kinds(self):
        kinds = {
            "psrr-dc-post-layout": "ac",
            "quiescent-current-post-layout": "op",
            "startup-stability-post-layout": "dc",
            "startup-ramp-post-layout": "tran",
            "startup-time-post-layout": "tran",
            "line-regulation-post-layout": "dc",
            "output-voltage-tc-post-layout": "dc",
        }
        self.assertEqual(set(kinds), set(batch_sim.POST_LAYOUT_BATCH_ENABLED_SLUGS))
        for slug, kind in kinds.items():
            with self.subTest(slug=slug):
                _exp, groups = self.groups(slug)
                request = groups[0].request
                analysis = (
                    request["analysis_steps"][0]["analysis"]
                    if "analysis_steps" in request
                    else request["analysis"]
                )
                self.assertEqual(analysis["kind"], kind)

    def test_meas_benches_are_enabled_for_real_runs(self):
        """Issue #510: the four `analysis_steps` benches run for real.

        They needed `allow_step_requests=True` (i.e. `--dry-run`) while the
        fleet runner rejected the shape; a real run must now pass the gate
        without it, and the request must still be the single-step form.
        """
        for slug in sorted(batch_sim.POST_LAYOUT_STEP_REQUEST_SLUGS):
            with self.subTest(slug=slug):
                batch_sim.require_batch_enabled(slug, batch_sim.POST_LAYOUT_BATCH_ENABLED_SLUGS)
                _exp, groups = self.groups(slug)  # no allow_step_requests
                for g in groups:
                    self.assertEqual(len(g.request["analysis_steps"]), 1)
                    self.assertEqual(g.request["analysis_steps"][0]["name"], batch_sim.STEP_NAME)

    def test_the_refusal_mechanism_is_kept_but_empty(self):
        """The mechanism stays for the next unsupported request shape (#510),
        with no entries: a refused slug is still named with its reason and
        still admitted by `--dry-run`."""
        self.assertEqual(batch_sim.POST_LAYOUT_BATCH_REFUSALS, {})
        patched = {"made-up-post-layout": "the runner cannot do X yet"}
        with unittest.mock.patch.object(batch_sim, "POST_LAYOUT_BATCH_REFUSALS", patched):
            with self.assertRaises(batch_sim.BatchError) as cm:
                batch_sim.require_batch_enabled(
                    "made-up-post-layout", batch_sim.POST_LAYOUT_BATCH_ENABLED_SLUGS
                )
            self.assertIn("the runner cannot do X yet", str(cm.exception))
            batch_sim.require_batch_enabled(
                "made-up-post-layout",
                batch_sim.POST_LAYOUT_BATCH_ENABLED_SLUGS,
                dry_run=True,
            )

    def test_meas_benches_dry_run_as_one_analysis_step(self):
        for slug in sorted(batch_sim.POST_LAYOUT_STEP_REQUEST_SLUGS):
            with self.subTest(slug=slug):
                exp = cr.load_experiment(SIM_DIR / MANIFEST[slug])
                groups = batch_sim.build_groups(
                    exp, PIN, matrix(exp), BODY, SPICEINIT, self.tmp / slug, 60,
                    capacity_wait_s=60, runner_version_check="enforce", poll_interval_s=30,
                    gate_slug=slug, allow_step_requests=True,
                )
                self.assertEqual(
                    sorted(g.supply_v for g in groups), sorted({c.supply_v for c in matrix(exp)})
                )
                for g in groups:
                    self.assertNotIn("analysis", g.request)
                    (step,) = g.request["analysis_steps"]
                    spice = [m["name"] for m in step["measurements"] if "spice" in m]
                    self.assertEqual(
                        spice,
                        [e.split()[2] for e in exp.raw["deck"]["analyses"] if e.startswith("meas ")],
                    )
                    self.assertTrue(
                        {m.name for m in exp.measurements}
                        <= {m["name"] for m in step["measurements"]}
                    )

    def test_every_post_layout_bench_is_enabled_or_refused(self):
        self.assertEqual(
            set(MANIFEST),
            batch_sim.POST_LAYOUT_BATCH_ENABLED_SLUGS | set(batch_sim.POST_LAYOUT_BATCH_REFUSALS),
        )
        # Issue #510: nothing is refused any more, and the step-request set is
        # a request-shape marker, not a hold-back list.
        self.assertEqual(set(batch_sim.POST_LAYOUT_BATCH_REFUSALS), set())
        self.assertLessEqual(
            batch_sim.POST_LAYOUT_STEP_REQUEST_SLUGS, batch_sim.POST_LAYOUT_BATCH_ENABLED_SLUGS
        )
        self.assertEqual(set(MANIFEST), set(batch_sim.POST_LAYOUT_BATCH_ENABLED_SLUGS))

    def test_unknown_post_layout_slug_is_refused(self):
        with self.assertRaises(batch_sim.BatchError):
            batch_sim.require_batch_enabled("nope-post-layout", batch_sim.POST_LAYOUT_BATCH_ENABLED_SLUGS)

    def test_gate_slug_none_keeps_the_pre_layout_gate(self):
        exp = cr.load_experiment(SIM_DIR / "error-amp-loop")
        with self.assertRaises(batch_sim.BatchError):
            batch_sim.build_groups(
                exp, PIN, matrix(exp), BODY, SPICEINIT, self.tmp / "x", 60,
                capacity_wait_s=60, runner_version_check="enforce", poll_interval_s=30,
            )


class PostLayoutArgs(unittest.TestCase):
    def test_default_backend_is_local_with_300s_timeout(self):
        a = plc.parse_post_layout_args([])
        self.assertEqual((a.backend, a.timeout), ("local", 300))

    def test_batch_backend_defaults_to_the_post_layout_fleet_timeout(self):
        """Issue #510: the post-layout path has its own fleet budget. The
        pre-layout `DEFAULT_BATCH_TIMEOUT_S` (10 800 s, sized for a ~6.4 ks
        homotopy DC corner in #320) cannot fit the fleet's whole-job ceiling at
        any shard count, so it is not the default here."""
        a = plc.parse_post_layout_args(["--backend", "batch"])
        self.assertEqual(a.timeout, batch_sim.POST_LAYOUT_BATCH_TIMEOUT_S)
        self.assertLess(a.timeout, batch_sim.DEFAULT_BATCH_TIMEOUT_S)
        self.assertLessEqual(
            batch_sim.job_bound_s(1, a.timeout), batch_sim.FLEET_JOB_CEILING_S
        )

    def test_explicit_timeout_wins(self):
        a = plc.parse_post_layout_args(["--backend", "batch", "--timeout", "90"])
        self.assertEqual(a.timeout, 90)


class PostLayoutJobCeiling(unittest.TestCase):
    """Issue #510: a post-layout batch request's job bound must fit the fleet's
    `max_job_seconds`, and a `--timeout` that cannot be made to fit must fail
    loudly instead of riding klt's warning into a job that is killed at the
    ceiling with every unit reported `batch_job_timeout`."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def build(self, slug, timeout_s, **kw):
        exp = cr.load_experiment(SIM_DIR / MANIFEST[slug])
        return batch_sim.build_groups(
            exp, PIN, matrix(exp), BODY, SPICEINIT, self.tmp / slug, timeout_s,
            capacity_wait_s=60, runner_version_check="enforce", poll_interval_s=30,
            gate_slug=slug, **kw,
        )

    def test_full_matrix_requests_fit_the_ceiling_at_the_default_timeout(self):
        for slug in sorted(batch_sim.POST_LAYOUT_BATCH_ENABLED_SLUGS):
            with self.subTest(slug=slug):
                groups = self.build(
                    slug, batch_sim.POST_LAYOUT_BATCH_TIMEOUT_S, enforce_job_ceiling=True
                )
                for g in groups:
                    units = len(g.corners)
                    hosts = g.request["remote"]["hosts"]
                    self.assertLessEqual(hosts, units)  # klt rejects hosts > units
                    bound = batch_sim.job_bound_s(
                        units, g.request["options"]["timeout_s"], hosts
                    )
                    self.assertLessEqual(bound, batch_sim.FLEET_JOB_CEILING_S)

    def test_over_ceiling_timeout_is_refused(self):
        groups_err = None
        for timeout_s in (
            batch_sim.DEFAULT_BATCH_TIMEOUT_S,
            batch_sim.FLEET_JOB_CEILING_S - batch_sim.FLEET_JOB_OVERHEAD_S + 1,
        ):
            with self.subTest(timeout_s=timeout_s):
                with self.assertRaises(batch_sim.BatchError) as cm:
                    self.build("startup-time-post-layout", timeout_s, enforce_job_ceiling=True)
                groups_err = str(cm.exception)
                self.assertIn("whole-job ceiling", groups_err)
        self.assertIn(str(batch_sim.POST_LAYOUT_BATCH_TIMEOUT_S), groups_err)

    def test_the_largest_fitting_timeout_is_accepted(self):
        self.build(
            "startup-time-post-layout",
            batch_sim.FLEET_JOB_CEILING_S - batch_sim.FLEET_JOB_OVERHEAD_S,
            enforce_job_ceiling=True,
        )

    def test_dry_run_requests_are_checked_too(self):
        """A `--dry-run` that printed an over-ceiling request would present it
        as a valid request to submit by hand."""
        with self.assertRaises(batch_sim.BatchError):
            self.build(
                "startup-time-post-layout",
                batch_sim.DEFAULT_BATCH_TIMEOUT_S,
                allow_step_requests=True,
                enforce_job_ceiling=True,
            )

    def test_pre_layout_path_keeps_its_own_budget(self):
        """Out of scope for #510: the pre-layout benches' 10 800 s default was
        measured from a ~6.4 ks corner (#320) and is not ceiling-enforced."""
        exp = cr.load_experiment(SIM_DIR / "psrr-dc")
        batch_sim.build_groups(
            exp, PIN, matrix(exp), BODY, SPICEINIT, self.tmp / "pre",
            batch_sim.DEFAULT_BATCH_TIMEOUT_S,
            capacity_wait_s=60, runner_version_check="enforce", poll_interval_s=30,
        )

    def test_job_bound_matches_klts_serial_formula(self):
        # klt: timeout_s x ceil(units / hosts) + overhead
        self.assertEqual(batch_sim.job_bound_s(15, 600), 600 * 5 + 120)
        self.assertEqual(batch_sim.job_bound_s(15, 600, 1), 600 * 15 + 120)
        self.assertEqual(batch_sim.job_bound_s(1, 10800), 10800 + 120)
        self.assertEqual(batch_sim.shard_hosts(15, 600), 3)


if __name__ == "__main__":
    unittest.main()
