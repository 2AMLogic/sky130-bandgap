"""Shared helpers deduplicated out of the two psrr-injector scripts (issue #379).

Issue #511 added the run-orchestration half (the local deck, the per-point run,
`explore`'s print loop, and `verify`'s record skeleton and write tail), so the
second class below also pins the record KEY ORDER each bench writes against its
own newest committed record -- `sim/` is append-only evidence, and a dedup that
silently reshuffled a record's json would make new records non-comparable with
the committed ones no one can go back and fix.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SIM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM_DIR / "bin"))
import sim_common  # noqa: E402

RUNNERS = {
    "attribution": SIM_DIR / "psrr-injector-attribution" / "run_psrr_injector_attribution.py",
    "candidates": SIM_DIR / "psrr-injector-candidates" / "run_psrr_injector_candidates.py",
}


def load_runner(name: str):
    """Import one bench's runner under its own module name (these tests load
    both, and `test_psrr_attribution_batch.py` loads one of them too)."""
    mod_name = f"psrr_injector_shared_{name}"
    cached = sys.modules.get(mod_name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(mod_name, RUNNERS[name])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def newest_committed_record(name: str) -> dict:
    """The bench's most recent committed record json. Newest, not any: the
    `execution` key only exists from the batch-backend record (#398/#361) on."""
    records = sorted((RUNNERS[name].parent / "records").glob("*.json"))
    return json.loads(records[-1].read_text())


FAKE_PDK = SimpleNamespace(
    dir=Path("/pdk/sky130A"), installed_commit="deadbeef", variant="sky130A",
    matches_pin=True, lib_file=Path("/pdk/sky130A/sky130.lib.spice"),
)
FAKE_PIN = {"family": "sky130", "open_pdks_commit": "cafef00d"}


def fake_args(**kw):
    base = dict(backend="local", jobs=2, timeout=1800, author="t@example.com")
    base.update(kw)
    return SimpleNamespace(**base)


def fake_variant(name: str, what: str = "what"):
    return SimpleNamespace(name=name, what=what)


class SharedHelpersTest(unittest.TestCase):
    def test_corner_id_and_matrix(self):
        self.assertEqual(sim_common.corner_id("tt", 27, 1.8), "tt_27c_1.80v")
        self.assertEqual(
            sim_common.matrix(["tt", "ss"], [-40, 27], [1.7]),
            [("tt", -40, 1.7), ("tt", 27, 1.7), ("ss", -40, 1.7), ("ss", 27, 1.7)],
        )

    def test_band_min_by_corner(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            rec = tmp / "r.json"
            rec.write_text(json.dumps({"corners": [
                {"corner_id": "a", "measurements": [{"name": "psrr_band_min", "value": -41.5}]},
                {"corner_id": "b", "measurements": [{"name": "psrr_band_min", "value": None}]},
            ]}))
            self.assertEqual(sim_common.band_min_by_corner(rec, "rec"), {"a": -41.5})
            with self.assertRaises(sim_common._cr().HarnessError):
                sim_common.band_min_by_corner(tmp / "missing.json", "rec")

    def test_run_all_variants(self):
        def fake(v, p, t, s):
            cid = sim_common.corner_id(p, t, s)
            return {"variant": v, "corner_id": cid, "ngspice_exit": 0, "timed_out": False,
                    "measurements": {"psrr_band_min": -40.0} if v == "x" else {}}

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = sim_common.run_all_variants(fake, ["x", "y"], [("tt", 27, 1.8)], 2, 5)
        self.assertEqual(set(res), {("x", "tt_27c_1.80v"), ("y", "tt_27c_1.80v")})
        out = buf.getvalue()
        self.assertIn("[  1/2] x     tt_27c_1.80v", out)
        self.assertIn("NO MEASUREMENT (rc=0, timeout=False)", out)

    def test_write_batch_log_and_artifact_text(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            deck = tmp / "deck.cir"
            deck.write_text("R1 a b 1k\n")
            kcs = {"ac": {"artifacts": {"deck": str(deck)}, "diagnostics": []}}
            self.assertIsNone(sim_common.artifact_text(None, "deck"))
            self.assertEqual(sim_common.artifact_text(kcs["ac"], "deck"), "R1 a b 1k\n")
            sim_common.write_batch_log(tmp / "logs", "v__c", "rid", kcs)
            text = (tmp / "logs" / "v__c.log").read_text()
            self.assertIn("| R1 a b 1k", text)
            self.assertIn("(not retrieved)", text)  # no ngspice log artifact



class InjectorOrchestrationTest(unittest.TestCase):
    """The run-orchestration helpers shared by the two benches (issue #511)."""

    def test_parse_corner_spec(self):
        self.assertEqual(
            sim_common.parse_corner_spec("ff,125,3.63;tt,27,3.30"),
            [("ff", 125.0, 3.63), ("tt", 27.0, 3.3)],
        )
        with self.assertRaises(ValueError):
            sim_common.parse_corner_spec("ff,125")

    def test_injector_deck_head_control_and_op_readouts(self):
        deck = sim_common.injector_deck(
            "slug", "run.py", FAKE_PDK, fake_variant("v1", "a variant"), "ff", 125.0, 3.63,
            ["XR1 a b r"],
            deck_options=("wnflag=1", "reltol=1e-6"), ac_analysis="ac dec 10 0.1 1meg",
            ac_meas=(("psrr_dc", "e1"),), op_meas=(("v_vref", "v(vref)"), ("v_ng", "v(ng)")),
        )
        lines = deck.splitlines()
        self.assertEqual(lines[0], "* slug deck -- generated by sim/slug/run.py, do not edit")
        self.assertEqual(lines[1], "* variant: v1 (a variant)")
        self.assertEqual(lines[2], "* corner: ff_125c_3.63v")
        self.assertIn(".param vsup=3.63", lines)
        self.assertIn(".option wnflag=1", lines)
        self.assertIn(".temp 125", lines)
        self.assertIn('.lib "/pdk/sky130A/sky130.lib.spice" ff', lines)
        self.assertIn("XR1 a b r", lines)
        # the AC readouts are all printed BEFORE `op` re-points the plot
        self.assertLess(lines.index("print meas_psrr_dc"), lines.index("op"))
        self.assertLess(lines.index("op"), lines.index("let meas_v_vref = v(vref)"))
        self.assertEqual(lines[-3:], ["quit", ".endc", ".end"])

    def test_injector_deck_op_meas_is_the_callers_whole_list(self):
        """The attribution bench appends its variant's `op_extra`, the
        candidates bench does not -- the shared deck measures exactly what it
        is handed, and adds nothing of its own."""
        def deck_for(op_meas):
            return sim_common.injector_deck(
                "s", "r.py", FAKE_PDK, fake_variant("v"), "tt", 27.0, 3.3, [],
                deck_options=(), ac_analysis="ac dec 10 0.1 1meg", ac_meas=(),
                op_meas=op_meas)

        always = (("v_vref", "v(vref)"),)
        extra = (("v_ng", "v(xsu.ng)"),)
        self.assertNotIn("v_ng", deck_for(always))
        self.assertIn("print meas_v_ng", deck_for(always + extra))

    def test_injector_run_point_uses_one_run_dir_per_point(self):
        """`run_ngspice()` writes `.spiceinit` into its run dir, so two points
        running concurrently must never share one."""
        seen = []

        def fake_run_ngspice(run_dir, name, deck, timeout):
            seen.append((run_dir, name, deck, timeout))
            return "meas_psrr_band_min = -41.5\n", 0, False

        with tempfile.TemporaryDirectory() as d:
            build = Path(d) / "build"
            logs = Path(d) / "corners"
            with mock.patch.object(sim_common, "run_ngspice", fake_run_ngspice):
                rows = [
                    sim_common.injector_run_point(
                        FAKE_PDK, fake_variant("v1"), p, t, s, 60, logs, "rid",
                        build_dir=build, deck=f"* deck {p}")
                    for p, t, s in (("tt", 27.0, 3.3), ("ff", 125.0, 3.63))
                ]
            self.assertEqual([r[0] for r in seen], [
                build / "rid" / "v1__tt_27c_3.30v",
                build / "rid" / "v1__ff_125c_3.63v",
            ])
            self.assertEqual(rows[1], {
                "variant": "v1", "corner_id": "ff_125c_3.63v", "process": "ff",
                "temperature_c": 125.0, "supply_v": 3.63,
                "ngspice_exit": 0, "timed_out": False,
                "measurements": {"psrr_band_min": -41.5},
            })
            self.assertTrue((logs / "v1__ff_125c_3.63v.log").is_file())

    def test_injector_run_point_writes_no_log_without_a_corners_dir(self):
        """Explore mode passes `corners_dir=None` and must write nothing under
        `sim/<experiment>/`."""
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(sim_common, "run_ngspice",
                                   lambda *a: ("", 0, False)), \
                 mock.patch.object(sim_common, "write_log") as wl:
                sim_common.injector_run_point(
                    FAKE_PDK, fake_variant("v1"), "tt", 27.0, 3.3, 60, None, "explore",
                    build_dir=Path(d), deck="* deck")
            wl.assert_not_called()

    def test_injector_run_variants_dispatches_on_the_backend(self):
        local_results = {("v1", "tt_27c_3.30v"): {"measurements": {}}}
        batch_results = {("v1", "ff_125c_3.63v"): {"measurements": {}}}
        calls = []

        def run_all(pdk, base, variants, points, timeout, jobs, corners_dir, record_id):
            calls.append(("local", timeout, jobs, corners_dir, record_id))
            return local_results

        def run_all_batch(pdk, pin, base, variants, points, timeout, corners_dir, record_id,
                          args):
            calls.append(("batch", timeout, corners_dir, record_id))
            return batch_results, ["a blocker"], {"backend": "batch"}

        out = sim_common.injector_run_variants(
            fake_args(), FAKE_PDK, FAKE_PIN, [], ["v1"], [("tt", 27.0, 3.3)], None, "rid",
            run_all=run_all, run_all_batch=run_all_batch)
        self.assertEqual(out, (local_results, [], None))

        out = sim_common.injector_run_variants(
            fake_args(backend="batch"), FAKE_PDK, FAKE_PIN, [], ["v1"], [("tt", 27.0, 3.3)],
            None, "rid", run_all=run_all, run_all_batch=run_all_batch)
        self.assertEqual(out, (batch_results, ["a blocker"], {"backend": "batch"}))
        self.assertEqual([c[0] for c in calls], ["local", "batch"])

    def test_injector_explore_pads_the_label_column_and_prints_blockers(self):
        results = {
            ("ref3_ngclamp", "tt_27c_3.30v"): {"measurements": {
                "psrr_band_min": 61.5, "psrr_dc": 70.25, "v_vref": 1.2345, "v_ng": 0.0123}},
            ("base", "tt_27c_3.30v"): {"measurements": {}},
        }

        def run_all_batch(*a, **k):
            return results, ["one op result missing"], {"backend": "batch"}

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = sim_common.injector_explore(
                fake_args(backend="batch"), FAKE_PDK, FAKE_PIN, [], ["x"],
                [("tt", 27.0, 3.3)], base_snapshot=sim_common.REPO_DIR / "sim" / "snap.spice",
                label_width=13, run_all=None, run_all_batch=run_all_batch)
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("base body: sim/snap.spice", out)
        self.assertIn("(explore mode: nothing is written under sim/<experiment>/)", out)
        self.assertIn("  BLOCKER: one op result missing", out)
        self.assertIn("  tt_27c_3.30v     ref3_ngclamp  band_min=  61.500 dc=  70.250 "
                      "vref=1.23450 ng=0.0123", out)
        # a variant with no measurements still prints a row, as nan
        self.assertIn("  tt_27c_3.30v     base          band_min=     nan", out)
        # sorted by corner then variant
        self.assertLess(out.index(" base      "), out.index(" ref3_ngclamp "))

    def test_injector_banner_names_the_backend(self):
        def banner(args):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                sim_common.injector_banner(
                    args, FAKE_PDK, ["v1", "v2"], [("tt", 27.0, 3.3)], "rid",
                    slug="a-bench", base_snapshot=sim_common.REPO_DIR / "sim" / "snap.spice")
            return buf.getvalue()

        local = banner(fake_args())
        self.assertIn("experiment    : a-bench", local)
        self.assertIn("record id     : rid", local)
        self.assertIn("points        : 1 corners x 2 variants = 2 ngspice runs (jobs=2)", local)
        self.assertIn("= 2 ngspice runs (batch fleet)", banner(fake_args(backend="batch")))

    def test_batch_integrity_checks_are_failures_not_footnotes(self):
        self.assertEqual(sim_common.batch_integrity_checks([]), [])
        self.assertEqual(sim_common.batch_integrity_checks(["a", "b"]), [
            {"name": "batch_integrity[0]", "pass": False, "detail": "a"},
            {"name": "batch_integrity[1]", "pass": False, "detail": "b"},
        ])

    def test_new_record_id_is_date_time_sha(self):
        with mock.patch.object(sim_common._cr(), "git_state",
                               lambda: {"sha": "abc1234", "branch": "b", "dirty": False}):
            record_id, git_info, now = sim_common.new_record_id()
        self.assertEqual(record_id, f"{now:%Y%m%d}-{now:%H%M%S}-abc1234")
        self.assertEqual(git_info["sha"], "abc1234")

    def test_injector_links_splices_extra_after_cited_record(self):
        plain = sim_common.injector_links(
            sim_common.REPO_DIR / "sim" / "snap.spice", "sim/companion", "rid0", "slug", "run.py")
        self.assertEqual(list(plain),
                         ["base_snapshot", "cited_record", "companion_manifest", "runner"])
        self.assertEqual(plain["base_snapshot"], "sim/snap.spice")
        self.assertEqual(plain["cited_record"], "sim/companion/records/rid0.json")
        self.assertEqual(plain["runner"], "sim/slug/run.py")
        with_extra = sim_common.injector_links(
            sim_common.REPO_DIR / "sim" / "snap.spice", "sim/companion", "rid0", "slug",
            "run.py", {"ceiling_record": "x.json", "attribution": "y/"})
        self.assertEqual(list(with_extra), [
            "base_snapshot", "cited_record", "ceiling_record", "attribution",
            "companion_manifest", "runner"])

    def test_write_injector_record_publishes_before_writing(self):
        """A store failure must leave no record behind: `sim/` is append-only,
        so a record whose raw evidence was never published can never be fixed."""
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            record = {"record_id": "rid", "overall_pass": True, "checks": [], "_results": {}}
            with mock.patch.object(sim_common, "REPO_DIR", tmp), \
                 mock.patch.object(sim_common, "publish_run_evidence",
                                   side_effect=RuntimeError("store down")):
                with self.assertRaises(RuntimeError):
                    sim_common.write_injector_record(
                        record, tmp / "records", tmp / "corners", tmp / "records" / "rid.md",
                        tmp / "records" / "rid.json", render=lambda r: "md")
            self.assertFalse((tmp / "records").exists())

    def test_write_injector_record_drops_private_keys_and_returns_the_verdict(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            checks = [{"name": "ok", "pass": True, "detail": "-"},
                      {"name": "bad", "pass": False, "detail": "why"}]
            record = {"record_id": "rid", "checks": checks, "overall_pass": False,
                      "_results": {"x": 1}, "_points": []}
            buf = io.StringIO()
            with mock.patch.object(sim_common, "REPO_DIR", tmp), \
                 mock.patch.object(sim_common, "publish_run_evidence", lambda c: None), \
                 contextlib.redirect_stdout(buf):
                rc = sim_common.write_injector_record(
                    record, tmp / "records", tmp / "corners", tmp / "records" / "rid.md",
                    tmp / "records" / "rid.json", render=lambda r: f"md for {r['record_id']}")
            self.assertEqual(rc, 2)
            self.assertEqual((tmp / "records" / "rid.md").read_text(), "md for rid")
            written = json.loads((tmp / "records" / "rid.json").read_text())
            self.assertEqual(list(written), ["record_id", "checks", "overall_pass"])
            out = buf.getvalue()
            self.assertIn("record: records/rid.md", out)
            self.assertIn("Overall: FAIL", out)
            self.assertIn("  FAIL bad: why", out)
            self.assertNotIn("FAIL ok", out)

            record["overall_pass"] = True
            with mock.patch.object(sim_common, "REPO_DIR", tmp), \
                 mock.patch.object(sim_common, "publish_run_evidence", lambda c: None), \
                 contextlib.redirect_stdout(io.StringIO()):
                rc = sim_common.write_injector_record(
                    record, tmp / "records", tmp / "corners", tmp / "records" / "rid2.md",
                    tmp / "records" / "rid2.json", render=lambda r: "md")
            self.assertEqual(rc, 0)


class InjectorRecordSkeletonTest(unittest.TestCase):
    """`injector_record_head()` must reproduce, for EACH bench, the record key
    order that bench's committed records already carry (issue #511).

    This is the one thing the dedup could break invisibly: `sim/` records are
    append-only evidence, and a reordered or renamed key makes a new record
    non-comparable with the committed ones.
    """

    def head_for(self, name, extra_record, **over):
        R = load_runner(name)
        kw = dict(
            slug=R.SLUG, title=R.TITLE, base_snapshot=R.BASE_SNAPSHOT,
            wrapped_schematic=R.WRAPPED_SCHEMATIC,
            statistical_convention="N/A (test)",
            processes=R.PROCESSES, temps_c=R.TEMPS_C, supplies_v=R.SUPPLIES_V,
        )
        kw.update(over)
        return R, sim_common.injector_record_head(
            fake_args(), FAKE_PDK, FAKE_PIN, [fake_variant("base")], None,
            "20260101-000000-abc1234", sim_common.datetime(2026, 1, 1,
                                                           tzinfo=sim_common.timezone.utc),
            {"sha": "abc1234", "branch": "b", "dirty": False}, extra_record, **kw)

    def test_attribution_record_keys_match_its_newest_committed_record(self):
        _R, head = self.head_for("attribution", {"cited_record": "x.md", "cited": {}})
        committed = newest_committed_record("attribution")
        self.assertEqual(
            list(head) + ["points", "checks", "overall_pass", "links"], list(committed))

    def test_candidates_record_keys_match_its_newest_committed_record(self):
        _R, head = self.head_for("candidates", {
            "cited_record": "x.md", "cited": {},
            "ceiling_record": "y.md", "ceiling": {},
        })
        committed = newest_committed_record("candidates")
        self.assertEqual(
            list(head) + ["points", "checks", "overall_pass", "links"], list(committed))

    def test_nested_block_keys_match_the_committed_records(self):
        for name in ("attribution", "candidates"):
            extra = {"cited_record": "x.md", "cited": {}}
            if name == "candidates":
                extra |= {"ceiling_record": "y.md", "ceiling": {}}
            _R, head = self.head_for(name, extra)
            committed = newest_committed_record(name)
            for block in ("experiment", "pdk", "matrix"):
                with self.subTest(bench=name, block=block):
                    self.assertEqual(list(head[block]), list(committed[block]))

    def test_links_keys_match_the_committed_records(self):
        for name in ("attribution", "candidates"):
            R = load_runner(name)
            extra = None
            if name == "candidates":
                extra = {
                    "ceiling_record": f"{R.CEILING_BENCH}/records/{R.CEILING_RECORD_ID}.json",
                    "attribution": f"{R.ATTRIBUTION}/",
                }
            links = sim_common.injector_links(
                R.BASE_SNAPSHOT, R.COMPANION, R.CITED_RECORD_ID, R.SLUG, R.SCRIPT, extra)
            with self.subTest(bench=name):
                self.assertEqual(links, newest_committed_record(name)["links"])
                self.assertEqual(list(links), list(newest_committed_record(name)["links"]))

    def test_each_bench_keeps_its_own_statistical_convention_and_identity(self):
        for name, convention in (("attribution", "attribution"), ("candidates", "screen")):
            R, head = self.head_for(name, {}, statistical_convention=f"N/A (... {convention})")
            committed = newest_committed_record(name)
            with self.subTest(bench=name):
                self.assertEqual(head["experiment"]["slug"], committed["experiment"]["slug"])
                self.assertEqual(head["experiment"]["title"], committed["experiment"]["title"])
                self.assertEqual(head["experiment"]["provenance_source"],
                                 committed["experiment"]["provenance_source"])
                self.assertEqual(head["experiment"]["wrapped_schematic"],
                                 committed["experiment"]["wrapped_schematic"])
                self.assertEqual(head["matrix"], committed["matrix"])
                self.assertIn(convention, head["experiment"]["statistical_convention"])
                self.assertEqual(head["jobs"], 2)
                self.assertIsNone(head["execution"])
                del R

    def test_runner_verify_passes_its_own_statistical_convention(self):
        """The one `experiment` field the shared skeleton cannot derive: each
        runner must still hand in the convention its committed records use."""
        for name in ("attribution", "candidates"):
            R = load_runner(name)
            source = RUNNERS[name].read_text()
            convention = newest_committed_record(name)["experiment"]["statistical_convention"]
            with self.subTest(bench=name):
                self.assertIn(f'statistical_convention="{convention}"', source)
                del R


if __name__ == "__main__":
    unittest.main()
