#!/usr/bin/env python3
"""Coverage for `sim/bin/mc_common.py` -- shared Monte Carlo runner
orchestration and record boilerplate (issue #722).

Pins the four blocks lifted out of `run_amp_offset_mc.py`,
`run_mc_untrimmed.py`, and (for `## Checks` / footer) `run_pnp_mismatch.py`:
- `handle_mc_dry_run()` (batch via `batch_sim.print_mc_batch_dry_run`, local
  deck-head + control-block preview with per-bench 8/10-line head counts)
- `run_local_mc_point()` / `collect_operating_samples()` (batch vs local
  dispatch, exit/timeout/empty-parse/<2-converged `HarnessError` guards,
  optional `enrich` hook, operating-window partitioning)
- `write_mc_record()` / `run_cli()` (publish-before-write order, exit codes)
- `render_mc_checks()` / `render_mc_footer()` (section/footer formatting and
  delegation across all three MC runners)
"""

from __future__ import annotations

import contextlib
import inspect
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SIM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIM_DIR / "bin"))
sys.path.insert(0, str(SIM_DIR.parent / "scripts" / "ci"))

import batch_sim  # noqa: E402
import mc_common  # noqa: E402
import sim_common  # noqa: E402
from script_module import load_script_module  # noqa: E402

cr = sim_common.load_corner_run()

AMP = load_script_module(
    SIM_DIR / "error-amp-offset-mc" / "run_amp_offset_mc.py", "run_amp_offset_mc_mc_common"
)
UNTRIMMED = load_script_module(
    SIM_DIR / "monte-carlo-untrimmed" / "run_mc_untrimmed.py", "run_mc_untrimmed_mc_common"
)
PNP = load_script_module(
    SIM_DIR / "pnp-mismatch" / "run_pnp_mismatch.py", "run_pnp_mismatch_mc_common"
)


def _point(cid: str = "tt_mm_27c_3.30v", *, role: str = "mismatch") -> SimpleNamespace:
    return SimpleNamespace(
        corner_id=cid,
        section="tt_mm",
        temp_c=27.0,
        seed=20260803,
        samples=10,
        role=role,
        purpose="unit test point",
    )


class HandleMcDryRunTests(unittest.TestCase):
    """Batch and local `--dry-run` short-circuits."""

    def test_returns_false_and_does_nothing_when_dry_run_is_false(self) -> None:
        args = SimpleNamespace(dry_run=False, backend="local")
        build_groups = mock.Mock()
        build_deck = mock.Mock()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            handled = mc_common.handle_mc_dry_run(
                args,
                slug="error-amp-offset-mc",
                pin={},
                pdk=SimpleNamespace(),
                body=[],
                points=[_point()],
                build_dir=Path("/tmp/unused"),
                build_batch_groups=build_groups,
                build_deck=build_deck,
                control_block=lambda p: ".control",
                deck_head_lines=8,
            )
        self.assertFalse(handled)
        build_groups.assert_not_called()
        build_deck.assert_not_called()
        self.assertEqual(buf.getvalue(), "")

    def test_batch_dry_run_builds_groups_and_delegates_to_shared_printer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            req_path = tmp_path / "req.json"
            req_path.write_text('{"backend": "batch"}\n')
            group = SimpleNamespace(
                label="tt_mm_27c_3.30v",
                request_path=req_path,
                request={"monte_carlo": {"n": 10, "seed": 20260803, "vary": "mismatch"}},
            )
            seen = {}

            def fake_build_groups(pin, body, points, spiceinit, batch_dir, args):
                seen["pin"] = pin
                seen["body"] = body
                seen["points"] = points
                seen["spiceinit"] = spiceinit
                seen["batch_dir"] = batch_dir
                seen["args"] = args
                return [group]

            args = SimpleNamespace(dry_run=True, backend="batch")
            pts = [_point()]
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                handled = mc_common.handle_mc_dry_run(
                    args,
                    slug="error-amp-offset-mc",
                    pin={"family": "sky130"},
                    pdk=SimpleNamespace(),
                    body=["* body"],
                    points=pts,
                    build_dir=tmp_path,
                    build_batch_groups=fake_build_groups,
                    build_deck=mock.Mock(side_effect=AssertionError("should not build local deck")),
                    control_block=mock.Mock(side_effect=AssertionError("should not build control")),
                    deck_head_lines=8,
                )
            self.assertTrue(handled)
            self.assertEqual(seen["batch_dir"], tmp_path / "batch")
            self.assertEqual(seen["spiceinit"], sim_common.SPICEINIT_FILE.read_text())
            out = buf.getvalue()
            self.assertIn("-- batch requests (one klt sim Monte Carlo request per point) --", out)
            self.assertIn("-- request for tt_mm_27c_3.30v --", out)
            self.assertIn("(dry run: nothing submitted, nothing written under sim/error-amp-offset-mc/)", out)

    def test_local_dry_run_preserves_deck_head_line_count(self) -> None:
        deck_lines = [f"* line {i}" for i in range(1, 15)]
        deck_text = "\n".join(deck_lines)
        for head_lines, slug in ((8, "error-amp-offset-mc"), (10, "monte-carlo-untrimmed")):
            with self.subTest(head_lines=head_lines, slug=slug):
                args = SimpleNamespace(dry_run=True, backend="local")
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    handled = mc_common.handle_mc_dry_run(
                        args,
                        slug=slug,
                        pin={},
                        pdk=SimpleNamespace(),
                        body=[],
                        points=[_point()],
                        build_dir=Path("/tmp/unused"),
                        build_batch_groups=mock.Mock(side_effect=AssertionError("no batch")),
                        build_deck=lambda pdk, pt, body: deck_text,
                        control_block=lambda pt: ".control\nquit\n.endc",
                        deck_head_lines=head_lines,
                    )
                self.assertTrue(handled)
                expected = "\n".join([
                    "",
                    "-- deck head + control block for the first point --",
                    *deck_lines[:head_lines],
                    "...",
                    ".control",
                    "quit",
                    ".endc",
                    f"(dry run: nothing written under sim/{slug}/)",
                    "",
                ])
                self.assertEqual(buf.getvalue(), expected)


class CollectOperatingSamplesTests(unittest.TestCase):
    """Per-point batch/local collection, enrichment, windowing, and error paths."""

    WINDOW = (0.8, 1.6)

    def test_local_streaming_enrichment_and_window_partitioning(self) -> None:
        pts = [_point("p1"), _point("p2")]
        events: list[str] = []

        def run_local(pt):
            events.append(f"run:{pt.corner_id}")
            raw = (
                "vout = 1.20\nrra = 10.0\nrrb = 2.0\n"
                "vout = 1.21\nrra = 12.0\nrrb = 3.0\n"
                "vout = 0.05\nrra = 8.0\nrrb = 0.0\n"
            )
            return raw, 0, False, Path(f"/tmp/{pt.corner_id}.log")

        def enrich(parsed):
            for s in parsed:
                s["rratio"] = s["rra"] / s["rrb"] if s["rrb"] else float("nan")

        execution, stream = mc_common.collect_operating_samples(
            pts,
            batch=False,
            collect_batch=mock.Mock(side_effect=AssertionError("not batch")),
            run_local_point=run_local,
            vectors=("vout", "rra", "rrb"),
            operating_window=self.WINDOW,
            enrich=enrich,
        )
        self.assertIsNone(execution)
        self.assertEqual(events, [])  # lazy until iterated

        collected = []
        for idx, pt, samples, excluded in stream:
            events.append(f"got:{pt.corner_id}")
            collected.append((idx, pt.corner_id, samples, excluded))

        # Local points interleave run and yield so progress prints live.
        self.assertEqual(events, ["run:p1", "got:p1", "run:p2", "got:p2"])
        self.assertEqual([c[0] for c in collected], [1, 2])
        self.assertEqual(len(collected[0][2]), 2)
        self.assertEqual(len(collected[0][3]), 1)
        self.assertAlmostEqual(collected[0][2][0]["rratio"], 5.0)
        self.assertAlmostEqual(collected[0][2][1]["rratio"], 4.0)

    def test_batch_collects_up_front_and_returns_execution(self) -> None:
        pts = [_point("p1")]
        exec_block = {"backend": "batch", "requests": 1}
        batch_data = {"p1": [{"vout": 1.19}, {"vout": 1.21}, {"vout": 0.1}]}

        execution, stream = mc_common.collect_operating_samples(
            pts,
            batch=True,
            collect_batch=lambda: (batch_data, exec_block),
            run_local_point=mock.Mock(side_effect=AssertionError("not local")),
            vectors=("vout",),
            operating_window=self.WINDOW,
        )
        self.assertEqual(execution, exec_block)
        rows = list(stream)
        self.assertEqual(len(rows), 1)
        idx, pt, samples, excluded = rows[0]
        self.assertEqual((idx, pt.corner_id), (1, "p1"))
        self.assertEqual(len(samples), 2)
        self.assertEqual(len(excluded), 1)

    def test_local_nonzero_exit_and_timeout_raise_harness_error(self) -> None:
        pt = _point("tt_mm_27c_3.30v")
        log_in_repo = sim_common.REPO_DIR / "sim" / "error-amp-offset-mc" / "corners" / "r1" / f"{pt.corner_id}.log"

        for rc, timed_out, expect_substr in (
            (1, False, f"ngspice exit 1 for {pt.corner_id}; see sim/error-amp-offset-mc/corners/r1/{pt.corner_id}.log"),
            (0, True, f"ngspice exit 0 (timeout) for {pt.corner_id}; see sim/error-amp-offset-mc/corners/r1/{pt.corner_id}.log"),
        ):
            with self.subTest(rc=rc, timed_out=timed_out):
                _, stream = mc_common.collect_operating_samples(
                    [pt],
                    batch=False,
                    collect_batch=mock.Mock(),
                    run_local_point=lambda p, rc=rc, to=timed_out: ("", rc, to, log_in_repo),
                    vectors=("vout",),
                    operating_window=self.WINDOW,
                )
                with self.assertRaises(cr.HarnessError) as cm:
                    list(stream)
                self.assertEqual(str(cm.exception), expect_substr)

    def test_empty_parse_raises_harness_error(self) -> None:
        pt = _point("tt_mm_27c_3.30v")
        _, stream = mc_common.collect_operating_samples(
            [pt],
            batch=True,
            collect_batch=lambda: ({pt.corner_id: []}, {"backend": "batch"}),
            run_local_point=mock.Mock(),
            vectors=("vout",),
            operating_window=self.WINDOW,
        )
        with self.assertRaises(cr.HarnessError) as cm:
            list(stream)
        self.assertEqual(
            str(cm.exception),
            f"no Monte Carlo samples parsed for {pt.corner_id} \u2014 see the log",
        )

    def test_fewer_than_two_converged_draws_raises_harness_error(self) -> None:
        pt = _point("tt_mm_27c_3.30v")
        _, stream = mc_common.collect_operating_samples(
            [pt],
            batch=True,
            collect_batch=lambda: (
                {pt.corner_id: [{"vout": 1.20}, {"vout": 0.01}, {"vout": 0.02}]},
                {"backend": "batch"},
            ),
            run_local_point=mock.Mock(),
            vectors=("vout",),
            operating_window=self.WINDOW,
        )
        with self.assertRaises(cr.HarnessError) as cm:
            list(stream)
        self.assertEqual(
            str(cm.exception),
            f"only 1 of 3 draws for {pt.corner_id} converged to the operating solution "
            "\u2014 nothing to compute a sigma from; see the log",
        )

    def test_run_local_mc_point_wires_build_run_and_log(self) -> None:
        pt = _point("tt_mm_27c_3.30v")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            build_dir = tmp_path / "build"
            corners_dir = tmp_path / "corners"
            expected_log = corners_dir / f"{pt.corner_id}.log"
            seen = {}

            def fake_run_ngspice(run_dir, cid, deck, timeout):
                seen["run_dir"] = run_dir
                seen["cid"] = cid
                seen["deck"] = deck
                seen["timeout"] = timeout
                return "vout = 1.2\n", 0, False

            def fake_write_log(cdir, point, pdk, record_id, stamp, deck, raw, rc, timed_out):
                seen["log_args"] = (cdir, point, record_id, deck, raw, rc, timed_out)
                return expected_log

            with mock.patch.object(mc_common, "run_ngspice", fake_run_ngspice):
                raw, rc, timed_out, log_path = mc_common.run_local_mc_point(
                    pt,
                    pdk=SimpleNamespace(),
                    body=["* body"],
                    build_dir=build_dir,
                    corners_dir=corners_dir,
                    record_id="rec-1",
                    stamp="now",
                    timeout=123,
                    build_deck=lambda pdk, point, body: "* deck",
                    write_log=fake_write_log,
                )
            self.assertEqual((raw, rc, timed_out, log_path), ("vout = 1.2\n", 0, False, expected_log))
            self.assertEqual(seen["run_dir"], build_dir / "rec-1" / pt.corner_id)
            self.assertEqual(seen["timeout"], 123)


class WriteRecordAndCliTests(unittest.TestCase):
    """`write_mc_record()` publish-first order, outputs, and `run_cli()` error handling."""

    def test_write_mc_record_publishes_first_writes_pair_and_returns_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            corners_dir = tmp_path / "corners"
            records_dir = tmp_path / "records"
            rec_json = records_dir / "r1.json"
            rec_md = records_dir / "r1.md"
            order: list[str] = []

            def fake_publish(cdir):
                order.append("publish")
                self.assertEqual(cdir, corners_dir)
                self.assertFalse(rec_json.exists())
                self.assertFalse(rec_md.exists())

            def fake_render(rec):
                order.append("render")
                self.assertTrue(rec_json.exists())
                return "# record\n"

            for overall, expect_rc in ((True, 0), (False, 2)):
                order.clear()
                if rec_json.exists():
                    rec_json.unlink()
                if rec_md.exists():
                    rec_md.unlink()
                buf = io.StringIO()
                with mock.patch.object(mc_common, "publish_run_evidence", fake_publish), \
                     contextlib.redirect_stdout(buf):
                    rc = mc_common.write_mc_record(
                        {"record_id": "r1", "overall_pass": overall},
                        render_record=fake_render,
                        corners_dir=corners_dir,
                        records_dir=records_dir,
                        record_json=rec_json,
                        record_md=rec_md,
                        overall=overall,
                    )
                self.assertEqual(rc, expect_rc)
                self.assertEqual(order, ["publish", "render"])
                self.assertEqual(json.loads(rec_json.read_text()), {"record_id": "r1", "overall_pass": overall})
                self.assertTrue(rec_json.read_text().endswith("\n"))
                self.assertEqual(rec_md.read_text(), "# record\n")
                self.assertIn(f"\nrecord: {rec_md}\n", buf.getvalue())
                self.assertIn(f"        {rec_json}\n", buf.getvalue())

    def test_write_mc_record_leaves_no_record_if_publish_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            records_dir = tmp_path / "records"
            rec_json = records_dir / "r1.json"
            rec_md = records_dir / "r1.md"
            with mock.patch.object(
                mc_common, "publish_run_evidence", side_effect=cr.HarnessError("store failed")
            ):
                with self.assertRaises(cr.HarnessError):
                    mc_common.write_mc_record(
                        {"record_id": "r1"},
                        render_record=lambda r: "# md",
                        corners_dir=tmp_path / "corners",
                        records_dir=records_dir,
                        record_json=rec_json,
                        record_md=rec_md,
                        overall=True,
                    )
            self.assertFalse(rec_json.exists())
            self.assertFalse(rec_md.exists())

    def test_run_cli_propagates_return_code_and_formats_harness_error(self) -> None:
        with self.assertRaises(SystemExit) as ok:
            mc_common.run_cli(lambda argv: 2, ["foo"])
        self.assertEqual(ok.exception.code, 2)

        err_buf = io.StringIO()
        with contextlib.redirect_stderr(err_buf), self.assertRaises(SystemExit) as fail:
            mc_common.run_cli(mock.Mock(side_effect=cr.HarnessError("bad input")), [])
        self.assertEqual(fail.exception.code, 1)
        self.assertEqual(err_buf.getvalue(), "error: bad input\n")


class RenderChecksAndFooterTests(unittest.TestCase):
    """`render_mc_checks()` / `render_mc_footer()` formatting and runner delegation."""

    SAMPLE_RECORD = {
        "points": [
            {
                "corner_id": "tt_mm_27c_3.30v",
                "role": "mismatch",
                "config": "all",
                "pass": True,
                "checks": [
                    {"name": "sample_count", "pass": True, "detail": "parsed 300"},
                    {"name": "budget", "pass": False, "detail": "out of band"},
                ],
            }
        ],
        "cross_point_checks": [
            {"name": "seed_stability", "pass": True, "detail": "within tol"},
        ],
        "overall_pass": False,
        "links": {"testbench": "sim/x/tb.sch", "runner": "sim/x/run.py"},
        "timestamp": "2026-11-28T00:00:00Z",
        "author": "agent@example.com",
        "supersedes": None,
    }

    def test_render_mc_checks_default_and_custom_point_label(self) -> None:
        default_lines = mc_common.render_mc_checks(self.SAMPLE_RECORD)
        self.assertEqual(
            default_lines,
            [
                "## Checks",
                "",
                "- `tt_mm_27c_3.30v` (mismatch): **PASS**",
                "  - PASS `sample_count` \u2014 parsed 300",
                "  - FAIL `budget` \u2014 out of band",
                "- PASS `seed_stability` \u2014 within tol",
                "- **Overall: FAIL**",
                "",
            ],
        )
        labeled = mc_common.render_mc_checks(
            self.SAMPLE_RECORD, point_label=lambda p: f"{p['role']}, config=`{p['config']}`"
        )
        self.assertEqual(labeled[2], "- `tt_mm_27c_3.30v` (mismatch, config=`all`): **PASS**")

    def test_render_mc_footer_default_links_override_and_supersedes(self) -> None:
        lines = mc_common.render_mc_footer(
            self.SAMPLE_RECORD, runner_path="sim/x/run.py"
        )
        self.assertEqual(
            lines,
            [
                "- **Links**:",
                "  - testbench: `sim/x/tb.sch`",
                "  - runner: `sim/x/run.py`",
                "- **Timestamp / author**: 2026-11-28T00:00:00Z, agent@example.com",
                "- **Supersedes**: (none \u2014 first record for this claim)",
                "",
                "Written by `sim/x/run.py`. Append-only: never edit this "
                "file \u2014 a correction is a new record with a `Supersedes` field (see "
                "`sim/README.md`).",
                "",
            ],
        )
        rec_with_sup = {**self.SAMPLE_RECORD, "supersedes": "20260801-000000-abc1234"}
        merged = {**rec_with_sup["links"], "klt_yield_envelope": "sim/x/yield.json"}
        overridden = mc_common.render_mc_footer(
            rec_with_sup, links=merged, runner_path="sim/x/run.py"
        )
        self.assertIn("  - klt_yield_envelope: `sim/x/yield.json`", overridden)
        self.assertIn("- **Supersedes**: 20260801-000000-abc1234", overridden)

    def test_all_three_runners_delegate_shared_boilerplate_without_private_copies(self) -> None:
        for name, mod in (
            ("error-amp-offset-mc", AMP),
            ("monte-carlo-untrimmed", UNTRIMMED),
            ("pnp-mismatch", PNP),
        ):
            with self.subTest(runner=name):
                render_src = inspect.getsource(mod.render_record)
                self.assertIn("render_mc_checks", render_src)
                self.assertIn("render_mc_footer", render_src)
                full_src = inspect.getsource(mod)
                self.assertNotIn("Append-only: never", full_src)
                self.assertNotIn("(none \u2014 first record for this claim)", full_src)

        for name, mod, head_lines in (
            ("error-amp-offset-mc", AMP, 8),
            ("monte-carlo-untrimmed", UNTRIMMED, 10),
        ):
            with self.subTest(runner=name):
                main_src = inspect.getsource(mod.main)
                self.assertIn("handle_mc_dry_run", main_src)
                self.assertIn(f"deck_head_lines={head_lines}", main_src)
                self.assertIn("collect_operating_samples", main_src)
                self.assertIn("write_mc_record", main_src)
                full_src = inspect.getsource(mod)
                self.assertNotIn("-- deck head + control block for the first point --", full_src)
                self.assertNotIn("no Monte Carlo samples parsed for", full_src)
                self.assertNotIn("nothing to compute a sigma from", full_src)

    def test_committed_records_match_shared_checks_and_footer_byte_for_byte(self) -> None:
        benches = (
            (
                "error-amp-offset-mc",
                AMP,
                "sim/error-amp-offset-mc/run_amp_offset_mc.py",
                None,
                True,
            ),
            (
                "monte-carlo-untrimmed",
                UNTRIMMED,
                "sim/monte-carlo-untrimmed/run_mc_untrimmed.py",
                lambda p: f"{p['role']}, config=`{p['config']}`",
                True,
            ),
            (
                "pnp-mismatch",
                PNP,
                "sim/pnp-mismatch/run_pnp_mismatch.py",
                None,
                False,  # 20260731 JSON was written with sort_keys=True
            ),
        )
        seen = 0
        for slug, mod, runner_path, point_label, exact_md_footer in benches:
            rec_dir = SIM_DIR / slug / "records"
            for jf in sorted(rec_dir.glob("*.json")):
                if "-klt-yield" in jf.name or "-dr005-" in jf.name:
                    continue
                seen += 1
                with self.subTest(record=f"{slug}/{jf.name}"):
                    rec = json.loads(jf.read_text())
                    committed_md = jf.with_suffix(".md").read_text()
                    rendered = mod.render_record(rec)
                    checks_block = "\n".join(
                        mc_common.render_mc_checks(rec, point_label=point_label)
                    )
                    self.assertIn(checks_block, committed_md)
                    self.assertIn(checks_block, rendered)
                    footer_block = "\n".join(
                        mc_common.render_mc_footer(rec, runner_path=runner_path)
                    )
                    if exact_md_footer:
                        self.assertTrue(committed_md.endswith(footer_block))
                    self.assertTrue(rendered.endswith(footer_block))
        self.assertGreaterEqual(seen, 10)


if __name__ == "__main__":
    unittest.main()
