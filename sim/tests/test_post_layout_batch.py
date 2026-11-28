#!/usr/bin/env python3
"""Coverage for the post-layout benches' `--backend batch` path (issue #396):
`batch_sim.build_groups(..., gate_slug=<post-layout slug>)` and the
`post_layout_common` flag set. Needs no PDK, ngspice, klt or network: the
requests are built from each bench's manifest and a stand-in extracted body.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

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


class PostLayoutBatchWiring(unittest.TestCase):
    """`run_post_layout_experiment()` under `--backend batch`, end to end with
    the layout inputs stubbed (issue #720). The dry-run preview is the shared
    printer's output and nothing else, and a real run hands
    `run_matrix_and_write_record()` the shared executor
    (`batch_sim.make_matrix_executor()`) wired to this path's own policy: the
    variant-resolved pin, the bench's gate slug and the job ceiling -- the
    arguments the private closure passed, so the record is unchanged.

    The runner resolves everything under its module-level `SIM_DIR` /
    `REPO_ROOT`, so the test stands a scratch tree in for them: the wrapped
    manifest is reached through a symlink, which keeps the record's
    repo-relative paths computable without writing under the real `sim/`.
    """

    SLUG = "psrr-dc-post-layout"
    WRAPPED = "psrr-dc"
    WRAPPED_SCHEMATIC = "sim/psrr-dc/testbench/tb_vref_psrr.sch"
    CLAIM_TAIL = "Measures the fixture claim against the routed layout."
    LAYOUT_PROVENANCE = {
        "layout_record_id": "20260101-000000-abcdef12",
        "layout_gds_source": {"kind": "fixture"},
        "layout_gds": "layout/fixture.gds",
        "parasitics_snapshot": {"source": "fixture"},
        "layout_lvs": {},
    }

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sim = self.tmp / "sim"
        self.sim.mkdir()
        (self.sim / self.WRAPPED).symlink_to(SIM_DIR / self.WRAPPED, target_is_directory=True)
        shutil.copyfile(SIM_DIR / "spiceinit", self.sim / "spiceinit")
        self.here = self.sim / self.SLUG
        self.here.mkdir()
        self.pdk = SimpleNamespace(
            matches_pin=True, variant="sky130A", dir=self.tmp / "pdk" / "sky130A",
            installed_commit=PIN["open_pdks_commit"],
        )
        self.out = io.StringIO()
        self.captured = {}
        self.calls = []

        def fake_record(module, **kwargs):
            self.captured["module"] = module
            self.captured["kwargs"] = kwargs
            return {}, True

        def fake_execute(*args, **kwargs):
            self.calls.append((args, kwargs))
            return ([], [], {})

        for patcher in (
            mock.patch.object(plc, "SIM_DIR", self.sim),
            mock.patch.object(plc, "REPO_ROOT", self.tmp),
            mock.patch.object(plc, "shutil", SimpleNamespace(
                which=lambda name: f"/fixture/bin/{name}", copyfile=shutil.copyfile,
            )),
            mock.patch.object(plc, "build_extracted_body", lambda *a, **k: (BODY, self.LAYOUT_PROVENANCE)),
            mock.patch.object(cr, "resolve_pdk", lambda pin: self.pdk),
            mock.patch.object(cr, "git_state", lambda: {"sha": "abc1234", "branch": "t", "dirty": False}),
            mock.patch.object(cr, "tool_versions", lambda: {"ngspice": "fixture"}),
            mock.patch.object(cr, "first_line", lambda cmd: f"fixture {cmd[0]}"),
            mock.patch.object(sim_common, "run_matrix_and_write_record", fake_record),
            mock.patch.object(batch_sim, "execute", fake_execute),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_bench(self, argv):
        with contextlib.redirect_stdout(self.out):
            return plc.run_post_layout_experiment(
                cr, here=self.here, slug=self.SLUG, wrapped_experiment=self.WRAPPED,
                wrapped_schematic=self.WRAPPED_SCHEMATIC, claim_tail=self.CLAIM_TAIL,
                argv=argv, temp_override=None, subset_reason="",
            )

    def run_dir(self):
        record_id = re.search(r"^record id\s+: (\S+)$", self.out.getvalue(), re.M).group(1)
        return self.sim / "build" / self.SLUG / record_id

    def test_dry_run_prints_the_shared_preview_and_writes_nothing_under_the_bench(self):
        seen = {}
        real = batch_sim.print_batch_dry_run

        def spy(groups):
            seen["groups"] = groups
            real(groups)

        with mock.patch.object(batch_sim, "print_batch_dry_run", spy):
            self.assertEqual(self.run_bench(["--backend", "batch", "--dry-run"]), 0)
        run_dir = self.run_dir()
        supplies = list(dict.fromkeys(c.supply_v for c in matrix(cr.load_experiment(self.sim / self.WRAPPED))))
        self.assertEqual(
            [g.request_path for g in seen["groups"]],
            [run_dir / "batch" / f"v{v:.2f}" / "request.json" for v in supplies],
        )
        # the dry-run request keeps this path's own gate and ceiling checks
        for g in seen["groups"]:
            self.assertEqual(g.request["backend"], "batch")
        _head, marker, preview = self.out.getvalue().partition("\n-- batch requests")
        self.assertTrue(marker)
        expected = io.StringIO()
        with contextlib.redirect_stdout(expected):
            real(seen["groups"])
        self.assertEqual(marker + preview, expected.getvalue())
        self.assertEqual(list(self.here.iterdir()), [])
        self.assertEqual(self.calls, [])
        self.assertNotIn("execute_matrix", self.captured)

    def test_a_real_run_hands_run_matrix_the_shared_executor_on_this_paths_inputs(self):
        self.assertEqual(self.run_bench(["--backend", "batch"]), 0)
        self.assertIs(self.captured["module"], cr)
        exp = cr.load_experiment(self.sim / self.WRAPPED)
        corners_dir = self.here / "corners" / self.run_dir().name
        self.assertEqual(self.calls, [])
        self.assertEqual(self.captured["kwargs"]["execute_matrix"](matrix(exp), corners_dir), ([], [], {}))
        self.assertEqual(self.calls, [((
            exp, {**PIN, "variant": "sky130A"}, self.pdk, matrix(exp), BODY, SPICEINIT,
            self.run_dir() / "batch", corners_dir, self.tmp,
            batch_sim.POST_LAYOUT_BATCH_TIMEOUT_S, cr.evaluate_measurements,
            {"ngspice": "fixture", "klt": "fixture klt"},
        ), {
            "capacity_wait_s": sim_common.DEFAULT_BATCH_CAPACITY_WAIT_S,
            "runner_version_check": sim_common.DEFAULT_BATCH_RUNNER_VERSION_CHECK,
            "gate_slug": self.SLUG, "enforce_job_ceiling": True,
        })])
        # the record still names the variant-resolved pin's unresolved twin
        self.assertEqual(self.captured["kwargs"]["pin"], PIN)
        self.assertEqual(self.captured["kwargs"]["args"].timeout, batch_sim.POST_LAYOUT_BATCH_TIMEOUT_S)


if __name__ == "__main__":
    unittest.main()
