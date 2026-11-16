#!/usr/bin/env python3
"""Coverage for the Spot-batch execution boundary (`sim/bin/batch_sim.py`,
`corner-run.py --backend batch`, issue #320). No fleet, AWS credentials,
ngspice or PDK needed: `klt sim` is replaced by a fake runner that returns
klt-shaped reports.

Properties pinned (the issue's test plan):

  * ordered aggregation despite shuffled report order;
  * missing / duplicate / unexpected corners block an overall PASS;
  * a simulation error, an engine timeout, an interrupted job and a failed
    submission can never report PASS, and none of them runs a corner locally;
  * the scientific content of the request (251-point sweep, measurement
    expressions, limits, pinned model, PVT axes) is the manifest's, unchanged;
  * a remote model library that is not the pinned one blocks PASS.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

SIM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIM_DIR / "bin"))

import batch_sim  # noqa: E402
import sim_common  # noqa: E402


# These tests exercise the record, not the artifact store (see test_artifact_store.py).
_publish_patch = mock.patch.object(sim_common, "publish_corner_evidence", return_value=None)


def setUpModule():
    _publish_patch.start()


def tearDownModule():
    _publish_patch.stop()

cr = sim_common.load_corner_run()
EXP_DIR = SIM_DIR / "startup-stability"
EXP = cr.load_experiment(EXP_DIR)
PIN = json.loads((SIM_DIR / "pdk.json").read_text())
LIB_SHA = "a" * 64
BODY = ["V1 VDDA 0 'vsup'", "VALPHA ALPHA 0 0"]


def full_matrix():
    c = EXP.raw["corners"]
    return [
        cr.Corner(p, float(t), float(v))
        for p in c["process"]
        for t in c["temperature_c"]
        for v in c["supply_v"]
    ]


def in_limits_values(index: int) -> dict[str, float]:
    """A value inside every limit, varying by corner so spread checks see
    corner sensitivity."""
    vals = {}
    for m in EXP.measurements:
        if m.min is not None and m.max is not None:
            v = (m.min + m.max) / 2
        elif m.min is not None:
            v = m.min * 10
        elif m.max is not None:
            v = m.max / 10
        else:
            v = 1.0
        vals[m.name] = v
    # tighten the ones whose sign conventions the generic rule above can miss
    vals["i_on_su"] = -1e-5
    vals["i_su_standing"] = 1e-7
    vals["vref_dut"] = 1.15 + 0.001 * (index % 30)
    vals["vgdrv_dut"] = 1.2 + 0.05 * (index % 30)
    return vals


def klt_corner(corner, index=0, *, status="pass", diags=None, values=None, runtime=100.0):
    vals = in_limits_values(index) if values is None else values
    return {
        "corner_id": f"{corner.process}/x/{corner.temp_c:g}C",
        "process": corner.process,
        "supply_v": {},
        "temperature_c": corner.temp_c,
        "status": status,
        "runtime_s": runtime,
        "measurements": [
            {"name": n, "value": v, "unit": "", "status": "pass", "margin": 0.0}
            for n, v in vals.items()
        ],
        "diagnostics": diags or [],
        "artifacts": {"log": None, "raw": None, "waveform": None, "deck": None},
        "monte_carlo": None,
    }


def worker_env(*, banner="ngspice-46", cpu="Intel(R) Xeon(R) Platinum 8488C"):
    """One `worker_environment` block, shaped like klt's own (issue #549): the
    ~1.4 kB of ngspice banner, PDK stamp, build comparison and CPU model klt
    attaches to *every* fleet job of a request."""
    return {
        "capture": "ok",
        "simulator": {
            "requested_binary": "ngspice", "binary_source": "PATH",
            "selected_path": "/usr/local/bin/ngspice", "version_probe": "ok",
            "version_banner": f"******\n** {banner} : Circuit level simulation program\n"
                              "** Compiled with KLU Direct Linear Solver\n" + "** pad\n" * 12,
        },
        "pdk": {
            "variant": "sky130A", "root": "/opt/pdk", "stamp_scheme": "sources-sha256",
            "stamp_sha256": "4" * 64,
            "stamp_text": "open_pdks f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7",
            "models_staged": False, "stamp_scope": "executed",
        },
        "cpu_model": cpu, "omp_num_threads": None, "image_manifest": None,
        "model_inputs": None, "diagnostics": [],
        "pdk_stamp_comparison": {"status": "not_comparable", "reason": "client_stamp_unavailable"},
        "engine_build_comparison": {"status": "match"},
    }


def shard_ids(group, job="klt-sim-test", shards=3):
    """The ids a `shards`-way sharded request reports, in report order."""
    return [f"{job}-{group.supply_v:.2f}-s{i}" for i in range(shards)]


def make_report(group, *, lib_sha=LIB_SHA, mutate=None, job="klt-sim-test", elapsed=500,
                shards=None, worker_envs=None):
    """`shards=N` gives the report the shape klt returns for a *sharded*
    request (issue #523): `environment.remote` carries a `fleet` list of
    per-shard entries and no top-level `job_id`, which is why every sharded
    request used to record `job_id: null`.

    `worker_envs` attaches klt's per-fleet-job `worker_environment` attestation
    (issue #549): a list of blocks, cycled over the fleet entries, so
    `[a]` gives every shard the same attestation and `[a, b]` alternates two.
    `None` leaves it off entirely -- the shape every test predating #549
    asserts on."""
    corners = [klt_corner(c, i) for i, c in enumerate(group.corners)]
    if mutate:
        corners = mutate(corners, group)
    if shards:
        ids = shard_ids(group, job, shards)
        remote = {
            "provider": "aws-batch-fleet",
            "runner_compatibility": "match",
            "fleet": [
                {"job_id": jid, "instance_type": "c7i.4xlarge", "ami_id": "ami-1",
                 "lifecycle": "spot",
                 **({"worker_environment": copy.deepcopy(worker_envs[i % len(worker_envs)])}
                    if worker_envs else {})}
                for i, jid in enumerate(ids)
            ],
        }
    else:
        remote = {
            "provider": "aws-batch-fleet",
            "job_id": f"{job}-{group.supply_v:.2f}",
            "instance_type": "c7i.4xlarge",
            "ami_id": "ami-1",
            "lifecycle": "spot",
            "elapsed_seconds": elapsed,
            "runner_compatibility": "match",
            **({"worker_environment": copy.deepcopy(worker_envs[0])} if worker_envs else {}),
        }
    return {
        "schema_version": 3,
        "status": "pass",
        "corner_count": len(group.corners),
        "corners": corners,
        "environment": {
            "engine": "ngspice",
            "engine_version": "46",
            "models_lib_sha256": lib_sha,
            "netlist_sha256": "b" * 64,
            "remote": remote,
        },
        "provenance": {"klt_version": "0.6.0", "pdk": None},
    }


def fake_runner(*, mutate=None, lib_sha=LIB_SHA, fail_supply=None, reverse=False, shards=None,
                worker_envs=None):
    def run(group):
        if fail_supply is not None and group.supply_v == fail_supply:
            return batch_sim.GroupOutcome(group, "t0", "t1", 1.0, 1, None, "klt sim exited 1: boom")
        rep = make_report(group, lib_sha=lib_sha, mutate=mutate, shards=shards,
                          worker_envs=worker_envs)
        if reverse:
            rep["corners"].reverse()
        (group.dir / "klt-report.json").write_text(json.dumps(rep))
        return batch_sim.GroupOutcome(group, "t0", "t1", 900.0, 0, rep, None, "", group.dir / "klt-report.json")

    return run


class _Env:
    """Throwaway work tree + a real-manifest batch run through fakes."""

    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup = None

    def execute(self, matrix=None, runner=None, timeout=3600):
        matrix = matrix or full_matrix()
        pdk = SimpleNamespace(lib_file=self.tmp / "sky130.lib.spice")
        pdk.lib_file.write_text("lib")
        sha = batch_sim.sha256_file(pdk.lib_file)
        runner = runner or fake_runner(lib_sha=sha)
        return batch_sim.execute(
            EXP, {**PIN}, pdk, matrix, BODY, (SIM_DIR / "spiceinit").read_text(),
            self.tmp / "work", self.tmp / "corners", self.tmp, timeout,
            cr.evaluate_measurements, {"xschem": "x", "platform": "p", "ngspice": "local"},
            runner=runner,
        ), sha


class RequestFidelity(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.groups = batch_sim.build_groups(
            EXP, PIN, full_matrix(), BODY, (SIM_DIR / "spiceinit").read_text(), self.tmp, 7200,
            capacity_wait_s=60, runner_version_check="enforce", poll_interval_s=30,
        )

    def test_three_supply_jobs_cover_the_full_45_corner_matrix_in_order(self):
        self.assertEqual([g.supply_v for g in self.groups], [2.97, 3.3, 3.63])
        self.assertEqual(sum(len(g.corners) for g in self.groups), 45)
        for g in self.groups:
            req = g.request
            self.assertEqual(req["corners"]["process"], EXP.raw["corners"]["process"])
            self.assertEqual(req["corners"]["temperature_c"], EXP.raw["corners"]["temperature_c"])
            self.assertNotIn("supply_v", req["corners"])  # vsup is a .param, pinned in the netlist
            self.assertIn(f".param vsup={g.supply_v}", g.netlist_path.read_text())

    def test_sweep_measurements_limits_and_model_pin_are_the_manifests(self):
        req = self.groups[0].request
        # the 251-point sweep is passed through verbatim, never shortened
        self.assertEqual(req["analysis"], {"kind": "dc", "args": "valpha 0 1 0.004"})
        self.assertEqual(req["backend"], "batch")
        self.assertEqual(req["engine"], "ngspice")
        self.assertEqual(req["models"], {"pdk": PIN["variant"], "lib": PIN["ngspice_lib"]})
        self.assertEqual([m["name"] for m in req["measurements"]], [m.name for m in EXP.measurements])
        for sent, m in zip(req["measurements"], EXP.measurements):
            self.assertEqual(sent.get("limits", {}).get("min"), m.min)
            self.assertEqual(sent.get("limits", {}).get("max"), m.max)
            # no intermediate vectors survive inlining
            for name in ("ifsu", "ifbare", "ssu", "sbare"):
                self.assertNotRegex(sent["expr"], rf"(?<![\w.]){name}(?![\w(])")
        self.assertTrue(req["options"]["keep_artifacts"])
        self.assertEqual(req["options"]["timeout_s"], 7200)
        init = req["options"]["ngspice_init"]
        self.assertIn("set ngbehavior=hsa", init)
        self.assertIn("option klu", init)
        self.assertTrue(all(";" not in line and not line.startswith("*") for line in init))

    def test_netlist_preamble_matches_the_local_decks_preamble(self):
        local = cr.build_deck(EXP, SimpleNamespace(lib_file=Path("/pdk/lib")), cr.Corner("tt", 27.0, 3.3), BODY)
        batch = self.groups[1].netlist_path.read_text()
        for line in local.splitlines():
            if line.startswith((".param", ".option")):
                self.assertIn(line, batch.splitlines())
        for line in BODY:
            self.assertIn(line, batch.splitlines())

    def test_inlined_expressions_compute_like_the_local_let_chain(self):
        ngspice = shutil.which("ngspice")
        if not ngspice:
            self.skipTest("ngspice not installed")
        analyses = EXP.raw["deck"]["analyses"]
        analysis, lets, _cards = batch_sim.split_analyses(analyses)
        # Stand-in circuit with the same probe sources and the same 251-point
        # sweep; only the circuit differs, the expressions are the manifest's.
        lines = [
            "inline-equivalence",
            "VALPHA c 0 0",
            "R1 c a 1k", "VPSW a 0 0",
            "R2 c b 2k", "VPSN b 0 0",
            "R3 c d 3k", "VPSU d 0 0",
            ".control", *analyses,
        ]
        probe_only = re.compile(r"^(?:[^v]|v(?!\())*$")  # no node voltages
        picked = [
            m for m in EXP.measurements
            if probe_only.match(m.expr) and not re.search(r"i\(v[12]\)", m.expr)
        ]
        self.assertGreaterEqual(len(picked), 8)  # every probe-current measurement, not a sample
        for m in picked:
            lines.append(f"let a_{m.name} = {m.expr}")
            lines.append(f"let b_{m.name} = {batch_sim.inline_lets(m.expr, lets)}")
            lines.append(f"print a_{m.name}")
            lines.append(f"print b_{m.name}")
        lines += ["quit", ".endc", ".end"]
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "d.spice").write_text("\n".join(lines))
        out = subprocess.run([ngspice, "-b", "d.spice"], cwd=tmp, capture_output=True, text=True).stdout
        self.assertIn("No. of Data Rows : 251", out)
        for m in picked:
            a = [ln for ln in out.splitlines() if ln.startswith(f"a_{m.name} =")]
            b = [ln for ln in out.splitlines() if ln.startswith(f"b_{m.name} =")]
            self.assertTrue(a and b, out[-800:])
            self.assertEqual(a[0].split("=")[1], b[0].split("=")[1], m.name)

    def test_klt_generated_deck_matches_the_local_deck(self):
        """Deck fidelity for one PVT corner: generate klt's own per-corner deck
        (its private `_write_corner_deck`, through the interpreter `klt` is
        installed in) and compare it with `corner-run.py::build_deck()`.
        Allowed differences: `.lib` quoting, `.temp` float formatting, the
        measurement `let`/`print` naming/inlining, and block order."""
        klt = shutil.which("klt")
        if not klt:
            self.skipTest("klt not installed")
        py = Path(klt).read_text(errors="replace").splitlines()[0].removeprefix("#!").strip()
        script = f"""
import json, sys
from pathlib import Path
from klayout_tools import sim
req = json.load(open({str(self.groups[0].request_path)!r}))
lib = '/PDK/' + req['models']['lib']
pt = sim.CornerPoint('ss', {{}}, -40.0)
sim._write_corner_deck(deck_path={str(self.tmp / 'klt.deck')!r}, netlist_path={str(self.groups[0].netlist_path)!r},
    models_lib=lib, point=pt, analysis=req['analysis'], measurements_spec=req['measurements'], raw_path=None)
"""
        proc = subprocess.run([py, "-c", script], capture_output=True, text=True)
        if proc.returncode != 0:
            self.skipTest(f"klt private deck writer unavailable: {proc.stderr[-200:]}")
        klt_deck = (self.tmp / "klt.deck").read_text().replace(
            f".include {self.groups[0].netlist_path}", self.groups[0].netlist_path.read_text()
        )
        corner = cr.Corner("ss", -40.0, 2.97)
        local = cr.build_deck(EXP, SimpleNamespace(lib_file=Path("/PDK/" + PIN["ngspice_lib"])), corner, BODY)
        self.assertEqual(
            [ln for ln in klt_deck.splitlines() if "valpha" in ln.lower() and ln.lower().startswith("dc")],
            [ln for ln in local.splitlines() if ln.lower().startswith("dc")],
        )

        def structural(text):
            out = set()
            for ln in text.splitlines():
                ln = ln.strip()
                if not ln or ln.startswith("*") or ln.startswith(("let ", "print ", ".end", ".control")):
                    continue
                ln = ln.replace('"', "").replace(".temp -40.0", ".temp -40")
                out.add(ln)
            return out

        self.assertEqual(structural(local), structural(klt_deck))
        self.assertIn("save all", klt_deck)
        self.assertIn("save all", local)
        _, lets, _cards = batch_sim.split_analyses(EXP.raw["deck"]["analyses"])
        for m in EXP.measurements:
            self.assertIn(f"let {m.name} = {batch_sim.inline_lets(m.expr, lets)}", klt_deck.splitlines())
            self.assertIn(f"let meas_{m.name} = {m.expr}", local.splitlines())

    def test_not_enabled_for_other_experiments(self):
        other = SimpleNamespace(slug="error-amp-loop", raw={}, measurements=[])
        with self.assertRaises(batch_sim.BatchError) as ctx:
            batch_sim.build_groups(other, PIN, full_matrix(), BODY, "", self.tmp / "o", 1,
                                   capacity_wait_s=0, runner_version_check="enforce", poll_interval_s=30)
        self.assertIn("analysis_steps", str(ctx.exception))  # the stated reason, not just "not enabled"

    def test_non_cross_product_subset_is_refused_not_widened(self):
        m = [cr.Corner("tt", 27.0, 3.3), cr.Corner("ss", -40.0, 3.3), cr.Corner("tt", -40.0, 3.3)]
        with self.assertRaises(batch_sim.BatchError):
            batch_sim.build_groups(EXP, PIN, m, BODY, "", self.tmp / "s", 1,
                                   capacity_wait_s=0, runner_version_check="enforce", poll_interval_s=30)


class ShardCount(unittest.TestCase):
    """`remote.hosts` keeps every shard's bound under the fleet job ceiling."""

    def test_fifteen_units_at_1800s_is_fifteen_hosts(self):
        self.assertEqual(batch_sim.shard_hosts(15, 1800), 15)

    def test_short_timeout_is_one_host(self):
        self.assertEqual(batch_sim.shard_hosts(15, 100), 1)

    def test_default_timeout_is_one_unit_per_shard(self):
        # 10800 s alone exceeds the ceiling; sharding cannot fix it, so the
        # finest split (one unit per shard, never more hosts than units).
        self.assertEqual(batch_sim.shard_hosts(15, batch_sim.DEFAULT_BATCH_TIMEOUT_S), 15)

    def test_partial_shards_round_up(self):
        # (3600 - 120) // 1000 = 3 units per job -> ceil(7 / 3)
        self.assertEqual(batch_sim.shard_hosts(7, 1000), 3)

    def test_mc_batch_default_packs_samples_into_shards(self):
        # The two MC benches' batch default: 300 samples at 240 s is 14 per
        # shard (22 hosts, bound 3 480 s), not one Spot host per sample (#528).
        self.assertEqual(batch_sim.shard_hosts(300, batch_sim.MC_BATCH_TIMEOUT_S), 22)
        self.assertEqual(batch_sim.shard_hosts(20, batch_sim.MC_BATCH_TIMEOUT_S), 2)
        self.assertLessEqual(
            batch_sim.job_bound_s(300, batch_sim.MC_BATCH_TIMEOUT_S),
            batch_sim.FLEET_JOB_CEILING_S,
        )

    def test_request_carries_the_shard_count(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        for timeout, hosts in ((1800, 15), (100, 1), (batch_sim.DEFAULT_BATCH_TIMEOUT_S, 15)):
            groups = batch_sim.build_groups(
                EXP, PIN, full_matrix(), BODY, (SIM_DIR / "spiceinit").read_text(), tmp, timeout,
                capacity_wait_s=60, runner_version_check="enforce", poll_interval_s=30,
            )
            for g in groups:
                self.assertEqual(g.request["remote"], {"hosts": hosts})


class MonteCarloGroupCeiling(unittest.TestCase):
    """`build_mc_group()` sizes `remote.hosts` from the sample count, and
    refuses a per-sample budget no split can bring under the fleet's whole-job
    ceiling -- before it writes anything (issue #528).

    An MC request's units are its `monte_carlo.n` draws, so the per-point
    budget the runners used locally is `n` times the bound klt enforces: at
    3600 s even one sample is over the ceiling, which is how three committed
    runs asked for 280 Spot hosts and lost ~175 shards each.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def build(self, timeout_s, samples=300, out=None):
        return batch_sim.build_mc_group(
            "mc-point", out or self.tmp, "* netlist\n", PIN, "tt_mm", 27.0, 3.3,
            samples, 20260803, [{"name": "vout", "expr": "v(vref)"}], "",
            timeout_s, capacity_wait_s=60, runner_version_check="enforce",
            poll_interval_s=30,
        )

    def test_sized_budget_shards_instead_of_one_host_per_sample(self):
        g = self.build(batch_sim.MC_BATCH_TIMEOUT_S)
        self.assertEqual(g.request["remote"]["hosts"], 22)
        self.assertEqual(g.request["monte_carlo"]["n"], 300)
        self.assertLessEqual(
            batch_sim.job_bound_s(300, batch_sim.MC_BATCH_TIMEOUT_S, 22),
            batch_sim.FLEET_JOB_CEILING_S,
        )

    def test_over_ceiling_budget_is_refused_naming_bound_ceiling_and_a_fit(self):
        for timeout_s in (3600, 7200, batch_sim.DEFAULT_BATCH_TIMEOUT_S):
            with self.subTest(timeout_s=timeout_s):
                with self.assertRaises(batch_sim.BatchError) as cm:
                    self.build(timeout_s)
                msg = str(cm.exception)
                self.assertIn("mc-point --timeout", msg)
                self.assertIn(f"{timeout_s + batch_sim.FLEET_JOB_OVERHEAD_S}s", msg)
                self.assertIn(f"{batch_sim.FLEET_JOB_CEILING_S}s", msg)
                self.assertIn("3480s", msg)

    def test_the_refusal_hint_names_the_mc_default_not_the_post_layout_one(self):
        with self.assertRaises(batch_sim.BatchError) as cm:
            self.build(3600)
        msg = str(cm.exception)
        self.assertIn(f"Monte Carlo batch default is {batch_sim.MC_BATCH_TIMEOUT_S}s", msg)
        self.assertNotIn("post-layout", msg)

    def test_nothing_is_written_when_the_budget_is_refused(self):
        out = self.tmp / "refused"
        with self.assertRaises(batch_sim.BatchError):
            self.build(3600, out=out)
        self.assertFalse(out.exists())

    def test_boundary_budget_is_accepted_and_one_second_over_is_not(self):
        limit = batch_sim.FLEET_JOB_CEILING_S - batch_sim.FLEET_JOB_OVERHEAD_S
        g = self.build(limit, out=self.tmp / "ok")
        self.assertEqual(g.request["remote"]["hosts"], 300)  # one sample per shard
        self.assertEqual(
            batch_sim.job_bound_s(300, limit, 300), batch_sim.FLEET_JOB_CEILING_S
        )
        with self.assertRaises(batch_sim.BatchError):
            self.build(limit + 1, out=self.tmp / "no")

    def test_a_small_sample_count_is_sized_too(self):
        g = self.build(batch_sim.MC_BATCH_TIMEOUT_S, samples=20, out=self.tmp / "small")
        self.assertEqual(g.request["remote"]["hosts"], 2)


class Aggregation(unittest.TestCase):
    def setUp(self):
        self.env = _Env()
        self.addCleanup(shutil.rmtree, self.env.tmp, True)

    def test_all_good_is_matrix_ordered_even_when_reports_are_shuffled(self):
        (self.env.tmp / "sky130.lib.spice").write_text("lib")
        (results, blockers, extra), sha = self.env.execute()
        self.assertEqual(blockers, [])
        self.assertEqual([r["corner_id"] for r in results], [c.id for c in full_matrix()])
        self.assertTrue(all(r["pass"] for r in results))
        # shuffled report order
        (results2, blockers2, _), _ = self.env.execute(runner=fake_runner(lib_sha=sha, reverse=True))
        self.assertEqual(blockers2, [])
        self.assertEqual([r["corner_id"] for r in results2], [c.id for c in full_matrix()])
        self.assertEqual(extra["execution"]["backend"], "batch")
        self.assertTrue(extra["execution"]["remote_pdk_matches_pin"])
        self.assertIsNone(extra["jobs"])

    def _run(self, mutate=None, **kw):
        (self.env.tmp / "sky130.lib.spice").write_text("lib")
        sha = batch_sim.sha256_file(self.env.tmp / "sky130.lib.spice")
        (res, blockers, extra), _ = self.env.execute(runner=fake_runner(mutate=mutate, lib_sha=kw.get("lib_sha", sha)))
        return res, blockers, extra

    def test_missing_corner_blocks_pass(self):
        res, blockers, _ = self._run(lambda cs, g: cs[:-1] if g.supply_v == 3.3 else cs)
        self.assertTrue(any("no result returned" in b for b in blockers))
        self.assertEqual(sum(1 for r in res if not r["pass"]), 1)

    def test_duplicate_corner_blocks_pass(self):
        res, blockers, _ = self._run(lambda cs, g: cs + [copy.deepcopy(cs[0])] if g.supply_v == 2.97 else cs)
        self.assertTrue(any("duplicate" in b for b in blockers))
        self.assertTrue(any("corner_count" in b for b in blockers))
        self.assertFalse(res[0]["pass"])

    def test_unexpected_corner_blocks_pass(self):
        def add(cs, g):
            extra = copy.deepcopy(cs[0])
            extra["process"] = "zz"
            return cs + [extra]
        _, blockers, _ = self._run(add)
        self.assertTrue(any("unexpected corner" in b for b in blockers))

    def test_engine_timeout_is_a_timeout_not_a_plain_failure(self):
        def mut(cs, g):
            if g.supply_v == 3.63:
                cs[0] = klt_corner(g.corners[0], values={}, status="error", runtime=3600.0, diags=[
                    {"severity": "error", "code": "timeout", "message": "ngspice did not complete within 3600s, killed"}])
            return cs
        res, _, _ = self._run(mut)
        bad = [r for r in res if not r["pass"]]
        self.assertEqual(len(bad), 1)
        self.assertTrue(bad[0]["timed_out"])
        self.assertIn("TIMEOUT", bad[0]["batch"]["failure"])
        self.assertIsNone(bad[0]["ngspice_exit"])  # not exposed by klt: unknown, never 0

    def test_simulation_error_is_a_failure_not_a_timeout(self):
        def mut(cs, g):
            if g.supply_v == 2.97:
                cs[1] = klt_corner(g.corners[1], values={}, status="error", diags=[
                    {"severity": "error", "code": "nonconvergence", "message": "gmin stepping failed"}])
            return cs
        res, _, _ = self._run(mut)
        bad = [r for r in res if not r["pass"]]
        self.assertEqual(len(bad), 1)
        self.assertFalse(bad[0]["timed_out"])
        self.assertIn("nonconvergence", bad[0]["batch"]["failure"])

    def test_interrupted_or_unobserved_job_never_passes(self):
        def mut(cs, g):
            return [klt_corner(c, values={}, status="error", diags=[
                {"severity": "error", "code": "batch_poll_timeout", "message": "job still running"}])
                for c in g.corners]
        res, _, _ = self._run(mut)
        self.assertFalse(any(r["pass"] for r in res))
        self.assertIn("never observed", res[0]["batch"]["failure"])

    def test_out_of_limit_value_fails_through_the_shared_evaluator(self):
        def mut(cs, g):
            vals = in_limits_values(0)
            vals["ncross_su"] = 3.0  # the very failure this bench exists to catch
            if g.supply_v == 3.3:
                cs[0] = klt_corner(g.corners[0], values=vals)
            return cs
        res, _, _ = self._run(mut)
        bad = [r for r in res if not r["pass"]]
        self.assertEqual(len(bad), 1)
        self.assertEqual([c["name"] for c in bad[0]["measurements"] if not c["pass"]], ["ncross_su"])

    def test_remote_model_library_that_is_not_the_pin_blocks_pass(self):
        _, blockers, extra = self._run(lib_sha="c" * 64)
        self.assertTrue(any("model library sha256" in b for b in blockers))
        self.assertFalse(extra["execution"]["remote_pdk_matches_pin"])

    def test_runner_version_skew_blocks_pass(self):
        (self.env.tmp / "sky130.lib.spice").write_text("lib")
        base = fake_runner(lib_sha=batch_sim.sha256_file(self.env.tmp / "sky130.lib.spice"))

        def skewed(group):
            out = base(group)
            out.report["environment"]["remote"]["runner_compatibility"] = "mismatch"
            return out
        (_, blockers, _), _ = self.env.execute(runner=skewed)
        self.assertTrue(any("runner klt" in b for b in blockers))

    def test_timings_separate_queue_overhead_from_compute(self):
        res, _, extra = self._run()
        job = extra["execution"]["jobs"][0]
        self.assertEqual(job["job_elapsed_s"], 500)
        self.assertEqual(job["queue_provision_and_transfer_s"], 400.0)  # 900 wall - 500 job
        self.assertEqual(extra["execution"]["corner_runtime_sum_s"], 4500.0)  # 45 x 100 s compute
        self.assertEqual(res[0]["elapsed_s"], 100.0)

    def test_evidence_files_are_written(self):
        self._run()
        corners = self.env.tmp / "corners"
        self.assertTrue((corners / "tt_-40c_2.97v.log").is_file())
        for v in ("2.97", "3.30", "3.63"):
            for name in ("request.json", "netlist.cir", "klt-report.json"):
                self.assertTrue((corners / f"batch-v{v}" / name).is_file(), (v, name))


class FleetJobIds(unittest.TestCase):
    """A sharded `klt sim` request reports its fleet job ids under
    `environment.remote.fleet[]` and leaves no top-level `job_id`, so reading
    `remote["job_id"]` alone records `null` for every sharded request and the
    one handle tying a record to its fleet jobs is lost (issue #523)."""

    def setUp(self):
        self.env = _Env()
        self.addCleanup(shutil.rmtree, self.env.tmp, True)

    # --- the read itself ------------------------------------------------

    def test_flat_remote_is_one_job_id(self):
        self.assertEqual(batch_sim.fleet_job_ids({"job_id": "klt-sim-a"}), ["klt-sim-a"])

    def test_sharded_remote_is_every_shard_id_in_report_order(self):
        remote = {"fleet": [{"job_id": "klt-sim-a"}, {"job_id": "klt-sim-b"},
                            {"job_id": "klt-sim-c"}]}
        self.assertEqual(batch_sim.fleet_job_ids(remote),
                         ["klt-sim-a", "klt-sim-b", "klt-sim-c"])

    def test_missing_or_empty_remote_is_no_ids_not_an_exception(self):
        for remote in (None, {}, {"fleet": []}, "not-a-dict"):
            with self.subTest(remote=remote):
                self.assertEqual(batch_sim.fleet_job_ids(remote), [])

    def test_fleet_entry_without_an_id_is_skipped_never_a_none(self):
        remote = {"fleet": [{"job_id": "klt-sim-a"}, {"instance_type": "c7i"},
                            {"job_id": None}, "junk"]}
        self.assertEqual(batch_sim.fleet_job_ids(remote), ["klt-sim-a"])

    # --- job_meta() -----------------------------------------------------

    def _execute(self, shards=None, mutate=None):
        (self.env.tmp / "sky130.lib.spice").write_text("lib")
        sha = batch_sim.sha256_file(self.env.tmp / "sky130.lib.spice")
        return self.env.execute(runner=fake_runner(lib_sha=sha, mutate=mutate, shards=shards))[0]

    def _jobs(self, shards=None):
        return self._execute(shards=shards)[2]["execution"]["jobs"]

    def test_job_meta_on_an_unsharded_report_keeps_one_id_in_both_fields(self):
        job = self._jobs()[0]
        self.assertEqual(job["job_id"], "klt-sim-test-2.97")
        self.assertEqual(job["job_ids"], ["klt-sim-test-2.97"])

    def test_job_meta_on_a_sharded_report_lists_every_shard(self):
        jobs = self._jobs(shards=3)
        for job, supply in zip(jobs, (2.97, 3.30, 3.63)):
            with self.subTest(supply=supply):
                # `job_id` deliberately keeps its old meaning -- the single id,
                # absent when klt sharded -- so record readers do not change shape.
                self.assertIsNone(job["job_id"])
                self.assertEqual(job["job_ids"],
                                 [f"klt-sim-test-{supply:.2f}-s{i}" for i in range(3)])

    # --- the consumers --------------------------------------------------

    def test_corner_log_header_names_the_shard_ids_not_none(self):
        self._execute(shards=3)
        header = (self.env.tmp / "corners" / "tt_-40c_2.97v.log").read_text().splitlines()[2]
        self.assertNotIn("None", header)
        for i in range(3):
            self.assertIn(f"klt-sim-test-2.97-s{i}", header)

    def test_corner_result_carries_the_shard_ids(self):
        res, _, _ = self._execute(shards=3)
        self.assertEqual(res[0]["batch"]["job_ids"],
                         [f"klt-sim-test-2.97-s{i}" for i in range(3)])

    def test_synthetic_failure_for_a_missing_corner_carries_the_shard_ids(self):
        def drop_first(corners, group):
            return corners[1:] if group.supply_v == 2.97 else corners
        res, blockers, _ = self._execute(shards=3, mutate=drop_first)
        missing = next(r for r in res if not r["measurements"] or r["batch"]["failure"])
        self.assertTrue(any("no result returned" in b for b in blockers))
        self.assertEqual(missing["batch"]["job_ids"],
                         [f"klt-sim-test-2.97-s{i}" for i in range(3)])

    def test_died_before_simulating_error_names_every_shard_id(self):
        """The fleet job died before simulating: the error is the only place
        the ids are reported (no record is minted), so `job None` there loses
        the handle entirely."""
        def dead(corners, group):
            return [klt_corner(c, values={}, status="error", diags=[{
                "severity": "error", "code": "batch_job_failed",
                "runner_code": "batch_runner_version_mismatch", "message": "skew"}])
                for c in group.corners]
        with self.assertRaises(batch_sim.BatchError) as cm:
            self._execute(shards=3, mutate=dead)
        msg = str(cm.exception)
        self.assertNotIn("job None", msg)
        for i in range(3):
            self.assertIn(f"klt-sim-test-2.97-s{i}", msg)

    # --- record prose ---------------------------------------------------

    def test_record_prose_renders_every_shard_id_and_pluralises(self):
        jobs = self._jobs(shards=3)
        line = batch_sim.md_job_ids(jobs[0])
        self.assertEqual(line, ", ".join(f"`klt-sim-test-2.97-s{i}`" for i in range(3)))
        self.assertEqual(batch_sim.md_job_ids({"job_id": "a"}), "`a`")
        self.assertEqual(batch_sim.md_job_ids({}), "(none reported)")
        self.assertEqual(
            batch_sim.md_fleet_job_ids([{"job_ids": ["a", "b"]}, {"job_id": "c"}]),
            "`a`, `b`, `c`")
        self.assertEqual(batch_sim.md_fleet_job_ids([]), "(none reported)")

    def test_corner_run_execution_prose_names_the_shards_never_none(self):
        res, blockers, extra = self._execute(shards=3)
        text = "\n".join(cr.render_execution(extra["execution"], blockers))
        self.assertNotIn("`None`", text)
        for supply in (2.97, 3.30, 3.63):
            for i in range(3):
                self.assertIn(f"`klt-sim-test-{supply:.2f}-s{i}`", text)
        self.assertIn("  - Jobs `klt-sim-test-2.97-s0`", text)

    def test_no_consumer_still_renders_a_single_job_id_into_prose(self):
        """The defect is one read repeated across benches, so the guard is
        structural: no record-prose site may format `job_id` directly again
        (issue #523). `batch_sim.job_meta()` keeps the field for record shape;
        `trim-lsb-chained` and `pex-native` read `environment.remote`
        themselves rather than `job_meta()` and are out of this issue's scope."""
        consumers = [
            SIM_DIR / "bin" / "corner-run.py",
            SIM_DIR / "psrr-injector-attribution" / "run_psrr_injector_attribution.py",
            SIM_DIR / "psrr-injector-candidates" / "run_psrr_injector_candidates.py",
        ]
        for path in consumers:
            with self.subTest(path=path.name):
                text = path.read_text()
                self.assertNotRegex(text, r"`\{j\['job_id'\]\}`")
                self.assertTrue(
                    any(f"batch_sim.{h}(" in text
                        for h in ("md_job_ids", "md_fleet_job_ids", "format_job_ids")),
                    f"{path.name} does not render job ids through batch_sim")

    def test_corner_run_execution_prose_is_unchanged_for_an_unsharded_run(self):
        res, blockers, extra = self._execute()
        text = "\n".join(cr.render_execution(extra["execution"], blockers))
        self.assertIn("  - Job `klt-sim-test-2.97` (supply 2.97 V): klt status pass", text)



class NoSilentLocalFallback(unittest.TestCase):
    def setUp(self):
        self.env = _Env()
        self.addCleanup(shutil.rmtree, self.env.tmp, True)
        (self.env.tmp / "sky130.lib.spice").write_text("lib")

    def test_failed_submission_raises_and_runs_nothing_locally(self):
        local_calls = []
        orig = sim_common._invoke_ngspice
        sim_common._invoke_ngspice = lambda *a, **k: local_calls.append(a) or ("", "", 0, False)
        orig_run_corner = cr.run_corner
        cr.run_corner = lambda *a, **k: local_calls.append(a)
        self.addCleanup(setattr, sim_common, "_invoke_ngspice", orig)
        self.addCleanup(setattr, cr, "run_corner", orig_run_corner)
        sha = batch_sim.sha256_file(self.env.tmp / "sky130.lib.spice")
        with self.assertRaises(batch_sim.BatchError) as ctx:
            self.env.execute(runner=fake_runner(lib_sha=sha, fail_supply=3.3))
        self.assertIn("nothing was run locally", str(ctx.exception))
        self.assertIn("3.30 V", str(ctx.exception))
        self.assertEqual(local_calls, [])

    def test_job_that_died_before_simulating_is_an_error_not_a_record(self):
        """E.g. the runner-image klt is older than the client: every corner
        comes back `batch_job_failed` with no measurements. That is an
        infrastructure fault; it must not become 45 FAIL rows about the design."""
        sha = batch_sim.sha256_file(self.env.tmp / "sky130.lib.spice")

        def mut(cs, g):
            return [klt_corner(c, values={}, status="error", diags=[{
                "severity": "error", "code": "batch_job_failed", "runner_code": "batch_runner_version_mismatch",
                "message": "the fleet runner runs klt 0.5.0 but the submitting client is 0.6.0"}])
                for c in g.corners]
        with self.assertRaises(batch_sim.BatchError) as ctx:
            self.env.execute(runner=fake_runner(lib_sha=sha, mutate=mut))
        self.assertIn("batch_runner_version_mismatch", str(ctx.exception))
        self.assertIn("before simulating", str(ctx.exception))

    def test_unusable_klt_binary_is_an_error(self):
        group = SimpleNamespace(dir=self.env.tmp, request_path=self.env.tmp / "r.json", supply_v=3.3)
        out = batch_sim.run_klt(group, klt="/nonexistent/klt")
        self.assertIsNone(out.report)
        self.assertIn("could not launch klt", out.error)

    def test_klt_error_exit_has_no_report(self):
        fake = self.env.tmp / "klt"
        fake.write_text("#!/bin/sh\necho 'error: no capacity' >&2\nexit 1\n")
        fake.chmod(0o755)
        group = SimpleNamespace(dir=self.env.tmp, request_path=self.env.tmp / "r.json", supply_v=3.3)
        out = batch_sim.run_klt(group, klt=str(fake))
        self.assertIsNone(out.report)
        self.assertIn("no capacity", out.error)

    def test_klt_exit_4_with_report_is_collected(self):
        fake = self.env.tmp / "klt"
        fake.write_text("#!/bin/sh\necho '{\"corners\": [], \"status\": \"error\"}'\nexit 4\n")
        fake.chmod(0o755)
        group = SimpleNamespace(dir=self.env.tmp, request_path=self.env.tmp / "r.json", supply_v=3.3)
        out = batch_sim.run_klt(group, klt=str(fake))
        self.assertEqual(out.rc, 4)
        self.assertEqual(out.report["status"], "error")


class RecordIntegration(unittest.TestCase):
    """`run_matrix_and_write_record(execute_matrix=...)`: blockers force FAIL
    even when every corner passed, and the record carries the execution block."""

    def _run(self, blockers):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        matrix = full_matrix()[:3]

        def execute_matrix(m, corners_dir):
            results = [{
                "corner_id": c.id, "process": c.process, "temperature_c": c.temp_c,
                "supply_v": c.supply_v, "ngspice_exit": None, "timed_out": False,
                "killed_by_signal": None, "killed_by_signal_name": None, "elapsed_s": 1.0,
                "timeout_s": 1, "measurements": [], "pass": True, "log": "x",
                "batch": {"failure": None},
            } for c in m]
            return results, blockers, {"execution": {"backend": "batch"}, "jobs": None}

        fake_cr = SimpleNamespace(
            REPO_ROOT=tmp, spread_checks=lambda e, r: [], default_author=lambda: "t",
            tool_versions=lambda: {"ngspice": "n", "xschem": "x", "platform": "p", "python": "3"},
            render_record=lambda r: "# r\n",
            unique_in_order=lambda v: list(dict.fromkeys(v)),
        )
        exp_dir = tmp / "sim" / "d"
        return sim_common.run_matrix_and_write_record(
            fake_cr, exp=SimpleNamespace(raw={}), matrix=matrix, is_subset=True, subset_reason="t",
            pdk=SimpleNamespace(root=tmp, variant="sky130A", installed_commit="d", matches_pin=True,
                                lib_file=tmp / "l"),
            pin={"open_pdks_commit": "d"}, body=["*"], run_dir=tmp / "b",
            corners_dir=exp_dir / "corners" / "r", records_dir=exp_dir / "records",
            record_md=exp_dir / "records" / "r.md", record_json=exp_dir / "records" / "r.json",
            snapshot=exp_dir / "snaps" / "r.spice", record_id="r",
            git_info={"sha": "a", "branch": "b", "dirty": False}, now=datetime.now(timezone.utc),
            args=SimpleNamespace(timeout=1, author="", supersedes="", jobs=1),
            experiment_fields={"slug": "d", "title": "d", "claim": "c", "provenance": "s",
                               "provenance_source": "s", "statistical_convention": "N/A"},
            links={"testbench": "t", "manifest": "m"}, execute_matrix=execute_matrix,
        )

    def test_clean_batch_passes(self):
        record, overall = self._run([])
        self.assertTrue(overall)
        self.assertEqual(record["overall_blockers"], [])
        self.assertEqual(record["execution"]["backend"], "batch")
        self.assertIsNone(record["jobs"])

    def test_blocker_forces_fail_even_if_every_corner_passed(self):
        record, overall = self._run(["x: no result returned"])
        self.assertFalse(overall)
        self.assertFalse(record["overall_pass"])


class ResolveXschemExprTests(unittest.TestCase):
    """xschem < 3.4.5 leaves `expr('...')` instance params unevaluated; the
    runner must produce the same netlist xschem 3.4.7 does (issue #320: the
    first live batch run failed every corner with `Undefined parameter [expr]`
    because the dispatch host has xschem 3.4.4)."""

    SNAP = EXP_DIR / "netlist-snapshots"

    def test_unevaluated_lines_match_the_3_4_7_netlist(self):
        raw = [
            "XM1 D G S B sky130_fd_pr__nfet_g5v0d10v5 L=2 W=8 nf=1 ad=expr('int((@nf + 1)/2) * @W / @nf",
            "+ * 0.29') as=expr('int((@nf + 2)/2) * @W / @nf * 0.29') pd=expr('2*int((@nf + 1)/2) * (@W / @nf + 0.29)') ps=expr('2*int((@nf",
            "+ + 2)/2) * (@W / @nf + 0.29)') nrd=expr('0.29 / @W ') nrs=expr('0.29 / @W ') sa=0 sb=0 sd=0 mult='m' m='m'",
            "R1 A B 1k",
        ]
        want = [
            "XM1 D G S B sky130_fd_pr__nfet_g5v0d10v5 L=2 W=8 nf=1 ad=2.32 as=2.32 pd=16.58 ps=16.58 "
            "nrd=0.03625 nrs=0.03625 sa=0 sb=0 sd=0 mult='m' m='m'",
            "R1 A B 1k",
        ]
        self.assertEqual(cr.resolve_xschem_expr(raw), want)

    def test_fifteen_digit_formatting(self):
        raw = ["XM1 D G S B m L=0.5 W=48 nf=1 nrd=expr('0.29 / @W ') sa=0"]
        self.assertIn("nrd=0.00604166666666667", cr.resolve_xschem_expr(raw)[0])

    def test_evaluated_netlist_is_a_noop(self):
        lines = (self.SNAP / "20260909-232410-e8e2e46.spice").read_text().splitlines()
        self.assertEqual(cr.resolve_xschem_expr(lines), lines)

    def test_unsupported_expression_is_loud(self):
        with self.assertRaises(cr.HarnessError):
            cr.resolve_xschem_expr(["X1 a b m W=1 p=expr('__import__(1)') q=0"])
        with self.assertRaises(cr.HarnessError):
            cr.resolve_xschem_expr(["X1 a b m W=1 p=expr('@missing * 2') q=0"])


class WorkerEnvironmentTable(unittest.TestCase):
    """klt attaches a full `worker_environment` attestation to *every* fleet
    job, so a sharded request re-serialized a byte-identical ~1.4 kB block
    once per shard: 1.4 MB of the committed records, 1-2 distinct values each
    (issue #549). The blocks now live once in a content-keyed
    `execution.worker_environments` table with each fleet entry referencing
    its own, and one reader resolves either shape -- committed records keep
    the inline form and must go on resolving identically."""

    def setUp(self):
        self.env = _Env()
        self.addCleanup(shutil.rmtree, self.env.tmp, True)
        self.a = worker_env()
        self.b = worker_env(banner="ngspice-45", cpu="AMD EPYC 9R14")

    def _execution(self, *, shards=3, worker_envs=None, mutate=None, lib_sha=None):
        (self.env.tmp / "sky130.lib.spice").write_text("lib")
        sha = lib_sha or batch_sim.sha256_file(self.env.tmp / "sky130.lib.spice")
        (_res, blockers, extra), _ = self.env.execute(runner=fake_runner(
            lib_sha=sha, shards=shards, worker_envs=worker_envs, mutate=mutate))
        return extra["execution"], blockers

    # --- the writer -----------------------------------------------------

    def test_a_repeated_attestation_is_stored_once_and_referenced_per_shard(self):
        """The headline case: 3 shards x 3 supplies that ran the same image
        used to write 9 copies of the block; now one table entry and 9 refs."""
        execution, _ = self._execution(worker_envs=[self.a])
        table = execution["worker_environments"]
        self.assertEqual(len(table), 1)
        self.assertEqual(list(table.values()), [self.a])
        key = next(iter(table))
        entries = [e for j in execution["jobs"] for e in batch_sim.fleet_jobs(j["remote"])]
        self.assertEqual(len(entries), 9)
        for entry in entries:
            self.assertNotIn("worker_environment", entry)
            self.assertEqual(entry["worker_environment_ref"], key)

    def test_a_shard_that_ran_a_different_environment_keeps_its_own_entry(self):
        """Dedup must never merge two attestations that differ -- that is the
        provenance the block exists to carry."""
        execution, _ = self._execution(worker_envs=[self.a, self.b])
        table = execution["worker_environments"]
        self.assertEqual(len(table), 2)
        self.assertEqual(sorted(table.values(), key=lambda w: w["cpu_model"]),
                         sorted([self.a, self.b], key=lambda w: w["cpu_model"]))
        # shards alternate a, b, a -- each entry must point at its own block.
        for job in execution["jobs"]:
            entries = batch_sim.fleet_jobs(job["remote"])
            resolved = [batch_sim.fleet_worker_environment(e, table) for e in entries]
            self.assertEqual(resolved, [self.a, self.b, self.a])

    def test_the_ref_sits_exactly_where_the_inline_block_sat(self):
        """Key order is part of what a reader of append-only evidence diffs,
        so the ref replaces the block in place rather than moving to the end."""
        raw = {"job_id": "s0", "worker_environment": self.a, "lifecycle": "spot"}
        jobs = [{"remote": {"fleet": [dict(raw)]}}]
        table = batch_sim.hoist_worker_environments(jobs)
        entry = jobs[0]["remote"]["fleet"][0]
        self.assertEqual(list(entry), ["job_id", "worker_environment_ref", "lifecycle"])
        self.assertEqual(entry["worker_environment_ref"], next(iter(table)))

    def test_an_unsharded_report_is_hoisted_the_same_way(self):
        """`fleet_jobs()` already unifies the two request shapes, so an
        unsharded run's single attestation goes through the same table rather
        than staying inline and splitting the reader's job in two."""
        execution, _ = self._execution(shards=None, worker_envs=[self.a])
        table = execution["worker_environments"]
        self.assertEqual(list(table.values()), [self.a])
        for job in execution["jobs"]:
            self.assertNotIn("worker_environment", job["remote"])
            self.assertEqual(job["remote"]["worker_environment_ref"], next(iter(table)))

    def test_a_run_with_no_attestation_gets_an_empty_table_and_no_rewrite(self):
        execution, _ = self._execution(worker_envs=None)
        self.assertEqual(execution["worker_environments"], {})
        for job in execution["jobs"]:
            for entry in batch_sim.fleet_jobs(job["remote"]):
                self.assertNotIn("worker_environment_ref", entry)

    def test_hoisting_leaves_the_klt_report_itself_inline(self):
        """The report is the fleet's own artifact, copied verbatim into
        `corners/<id>/batch-*/klt-report.json`; hoisting the record's copy must
        not reach back into it (or into the blocker checks reading it)."""
        self._execution(worker_envs=[self.a])
        report = json.loads(
            (self.env.tmp / "corners" / "batch-v2.97" / "klt-report.json").read_text())
        for entry in report["environment"]["remote"]["fleet"]:
            self.assertEqual(entry["worker_environment"], self.a)
            self.assertNotIn("worker_environment_ref", entry)

    # --- the round trip: resolved values, not the serialization ---------

    def test_resolved_attestations_are_exactly_the_inline_forms_set(self):
        """The issue's acceptance check: the record reports the same set of
        distinct attestations the inline shape would have carried."""
        for envs in ([self.a], [self.a, self.b]):
            with self.subTest(distinct=len(envs)):
                execution, _ = self._execution(worker_envs=envs)
                self.assertEqual(batch_sim.execution_worker_environments(execution), envs)

    def test_a_committed_inline_record_resolves_through_the_same_reader(self):
        """Records on disk predate the table and are append-only, so the
        reader must return their inline blocks with no table at all."""
        inline = {"execution": {"jobs": [{"remote": {"fleet": [
            {"job_id": "s0", "worker_environment": self.a},
            {"job_id": "s1", "worker_environment": self.b},
            {"job_id": "s2", "worker_environment": self.a},
        ]}}]}}
        self.assertEqual(
            batch_sim.execution_worker_environments(inline["execution"]), [self.a, self.b])
        entry = inline["execution"]["jobs"][0]["remote"]["fleet"][0]
        self.assertEqual(batch_sim.fleet_worker_environment(entry), self.a)
        self.assertEqual(batch_sim.fleet_worker_environment(entry, {}), self.a)

    def test_the_reader_needs_no_shape_check_at_the_call_site(self):
        """Same call, both shapes, same answer -- the point of the helper."""
        key = batch_sim.worker_environment_key(self.a)
        table = {key: self.a}
        self.assertEqual(
            batch_sim.fleet_worker_environment({"worker_environment": self.a}, table),
            batch_sim.fleet_worker_environment({"worker_environment_ref": key}, table))

    def test_an_entry_carrying_no_attestation_resolves_to_none(self):
        for entry in ({}, {"job_id": "s0"}, None, "junk", {"worker_environment": None}):
            with self.subTest(entry=entry):
                self.assertIsNone(batch_sim.fleet_worker_environment(entry, {}))

    def test_a_dangling_ref_is_loud_never_silently_absent(self):
        """A record claiming provenance it cannot produce is lost evidence;
        reading it as "absent" would hide that in an append-only tree."""
        for table in (None, {}, {"other": self.a}):
            with self.subTest(table=table):
                with self.assertRaises(batch_sim.BatchError) as cm:
                    batch_sim.fleet_worker_environment({"worker_environment_ref": "nope"}, table)
                self.assertIn("nope", str(cm.exception))
                self.assertIn("worker_environments", str(cm.exception))

    # --- the key --------------------------------------------------------

    def test_the_key_is_content_addressed_not_position_addressed(self):
        self.assertEqual(batch_sim.worker_environment_key(self.a),
                         batch_sim.worker_environment_key(copy.deepcopy(self.a)))
        self.assertNotEqual(batch_sim.worker_environment_key(self.a),
                            batch_sim.worker_environment_key(self.b))
        # insertion order is not content
        reordered = dict(reversed(list(self.a.items())))
        self.assertEqual(batch_sim.worker_environment_key(reordered),
                         batch_sim.worker_environment_key(self.a))

    def test_the_key_is_a_bare_sha256_from_the_one_hashing_module(self):
        key = batch_sim.worker_environment_key(self.a)
        self.assertRegex(key, r"^[0-9a-f]{64}$")

    # --- what must NOT change -------------------------------------------

    def test_a_mismatched_model_library_still_blocks_a_sharded_run(self):
        """Step 3 of the proposal: the blockers in `job_meta()` read the
        report, so hoisting the record's copy cannot soften them."""
        execution, blockers = self._execution(worker_envs=[self.a], lib_sha="f" * 64)
        self.assertTrue(any("model library sha256" in b for b in blockers), blockers)
        self.assertFalse(execution["remote_pdk_matches_pin"])
        # and the attestation is still recorded for the run that failed
        self.assertEqual(batch_sim.execution_worker_environments(execution), [self.a])

    def test_the_fleet_job_ids_and_instance_facts_survive_hoisting(self):
        execution, _ = self._execution(worker_envs=[self.a])
        for job, supply in zip(execution["jobs"], (2.97, 3.30, 3.63)):
            self.assertEqual(job["job_ids"],
                             [f"klt-sim-test-{supply:.2f}-s{i}" for i in range(3)])
        self.assertEqual(execution["remote_instance_types"], ["None"])  # sharded: no top-level
        self.assertNotIn("`None`", "\n".join(
            cr.render_execution(execution, execution["blockers"])))

    def test_the_table_removes_the_repetition_it_was_added_for(self):
        """The measurement, not just the shape: 9 shards sharing one block."""
        inline, _ = self._execution(worker_envs=None)
        hoisted, _ = self._execution(worker_envs=[self.a])
        # Reconstruct what the inline shape would have cost on the same run.
        inflated = copy.deepcopy(hoisted)
        del inflated["worker_environments"]
        for job in inflated["jobs"]:
            for entry in batch_sim.fleet_jobs(job["remote"]):
                entry.pop("worker_environment_ref", None)
                entry["worker_environment"] = self.a
        before = len(json.dumps(inflated))
        after = len(json.dumps(hoisted))
        self.assertLess(after, before)
        # 9 copies -> 1: the saving is at least 7 blocks' worth.
        self.assertGreater(before - after, 7 * len(json.dumps(self.a)))
        self.assertEqual(batch_sim.execution_worker_environments(inflated),
                         batch_sim.execution_worker_environments(hoisted))
        self.assertEqual(inline["worker_environments"], {})


class CommittedRecordsStillResolve(unittest.TestCase):
    """The records already on disk are append-only and keep the inline shape,
    so the reader has to go on reporting their provenance unchanged. This runs
    against the real evidence rather than a fixture of it (issue #549)."""

    @classmethod
    def setUpClass(cls):
        cls.records = []
        for path in sorted(SIM_DIR.glob("*/records/*.json")):
            text = path.read_text()
            if '"worker_environment"' not in text:
                continue
            cls.records.append((path, json.loads(text)))

    def test_every_committed_attestation_resolves_with_no_table(self):
        if not self.records:
            self.skipTest("no committed record carries fleet attestation")
        for path, record in self.records:
            execution = record.get("execution") or {}
            with self.subTest(record=path.name):
                resolved = batch_sim.execution_worker_environments(execution)
                self.assertTrue(resolved, f"{path}: attestation present but nothing resolved")
                inline = [e["worker_environment"]
                          for j in execution.get("jobs") or []
                          for e in batch_sim.fleet_jobs(j.get("remote"))
                          if isinstance(e.get("worker_environment"), dict)]
                distinct = []
                for block in inline:
                    if block not in distinct:
                        distinct.append(block)
                self.assertEqual(resolved, distinct)

    def test_hoisting_a_committed_record_preserves_its_resolved_provenance(self):
        """Proof the two shapes are interchangeable on real data: hoist a
        committed record's jobs and the resolved set is unchanged."""
        if not self.records:
            self.skipTest("no committed record carries fleet attestation")
        path, record = max(self.records, key=lambda pr: len(json.dumps(pr[1])))
        execution = copy.deepcopy(record["execution"])
        before = batch_sim.execution_worker_environments(execution)
        execution["worker_environments"] = batch_sim.hoist_worker_environments(execution["jobs"])
        self.assertEqual(batch_sim.execution_worker_environments(execution), before,
                         f"{path}: provenance changed under hoisting")
        self.assertEqual(len(execution["worker_environments"]), len(before))


if __name__ == "__main__":
    unittest.main()
