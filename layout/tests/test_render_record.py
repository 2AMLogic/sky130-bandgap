#!/usr/bin/env python3
"""Replay coverage for the trivial-cell record renderer (issue #636).

``layout/bin/render-record.py`` decides a record's four-verdict PASS/FAIL
from the six JSON envelopes ``run-trivial-cell-flow.sh`` leaves in a record
directory. Until #636 it also rendered a second, hardcoded answer about the
good-reference LVS run: a narrative paragraph that unconditionally described
every mismatch entry as ``severity: "warning"`` with zero errors, then
appended a correction when the entries said otherwise -- so on the failure
path one report claimed "all 34 entries are warnings (0 errors)" and "31
error entries were present" at the same time. #636 retired that narrative:
the results table (read from the envelopes) is the per-run summary, the raw
``lvs*.json`` entries carry the detail, and the standing explanation of the
expected warning categories lives in `layout/README.md`'s "Expected LVS
warnings on the trivial cell" section, linked from the record.

This module replays the recorded envelopes from
``layout/trivial-cell/reports/20260806-055840-3a4293a`` through the
renderer's own ``main()``, stubbing only the three environment lookups a
replay cannot reproduce (``klt --version``, ``klt pdk find``, git state),
and exercises both verdict paths the issue names:

* the recorded good inputs -- PASS, exit 0;
* the #636 reproduction -- the recorded ``lvs.broken-device.json``
  envelope copied over the good-reference ``lvs.json``, which must render
  FAIL, exit 1, with a table that agrees with its input.

In both directions it checks the same four things: the overall verdict,
the per-row statuses and mismatch counts against the JSON actually fed in,
the process exit code, and the absence of any self-contradicting severity
classification. The four verdict checks themselves are asserted intact on
both paths -- the renderer's real gate must keep failing loudly when a
verdict flips.

Standard library only, no PDK, no ``klt`` install, matching every other
test under ``layout/tests/``. Run directly, or via::

    npm run test:unit
    python3 -m unittest discover --start-directory layout/tests
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock

_REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "scripts" / "ci"))
from script_module import load_script_module  # noqa: E402

render_record = load_script_module(
    _REPO / "layout" / "bin" / "render-record.py", "render_record"
)

#: The current checked-in record's envelopes (the one `layout/README.md`
#: names via `trivial-cell/reports/LATEST`). Recorded evidence, replayed
#: read-only; nothing here writes into the reports tree.
_RECORDED = _REPO / "layout" / "trivial-cell" / "reports" / "20260806-055840-3a4293a"

_ENVELOPES = (
    "gen.json",
    "drc.json",
    "extract.json",
    "lvs.json",
    "lvs.broken-device.json",
    "lvs.broken-topology.json",
)

_README_SECTION_LINK = (
    "../../../README.md#expected-lvs-warnings-on-the-trivial-cell"
)

#: Stubs of the retired narrative's failure-path fingerprints, so a
#: regression reads as "the two-answers paragraph came back", not as a
#: bare ``assertNotIn`` string.
_RETIRED_CLAIMS = (
    # "all N entries are severity warning (0 at severity error)"
    '(0 at `severity: "error"`',
    # the appended contradiction on the failure path
    "NOT a clean match",
)


class RenderRecordReplayTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = pathlib.Path(self._tmp.name)
        for name in _ENVELOPES:
            shutil.copy(_RECORDED / name, self.out_dir / name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # --- harness -----------------------------------------------------------

    def _render(self) -> tuple[int, str]:
        """Run the renderer's real main() over the prepared out_dir.

        Only the environment lookups are stubbed: klt version, the
        `klt pdk find` metadata call, and the git provenance stamp. The
        record text itself -- verdicts, table, links -- is produced by the
        code under test from the envelopes on disk.
        """
        argv = [
            "render-record.py",
            "--out-dir",
            str(self.out_dir),
            "--record-id",
            "replay-636",
            "--repo-root",
            str(_REPO),
            "--klt",
            "klt-not-required-in-replay",
            "--pdk-variant",
            "sky130A",
        ]
        stdout = StringIO()
        patches = (
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(
                render_record, "klt_version", lambda klt: "klt replay-stub"
            ),
            mock.patch.object(
                render_record,
                "run_klt_json",
                lambda klt, *a: {"variant": "sky130A", "version": "replay-stub"},
            ),
            mock.patch.object(
                render_record,
                "git_repo_state",
                lambda root: ("0" * 40, "replay", False),
            ),
        )
        with redirect_stdout(stdout):
            for p in patches:
                p.start()
            try:
                rc = render_record.main()
            finally:
                for p in reversed(patches):
                    p.stop()
        return rc, stdout.getvalue()

    def _row(self, md: str, prefix: str) -> str:
        for line in md.splitlines():
            if line.startswith(prefix):
                return line
        self.fail(f"no results-table row starting {prefix!r} in:\n{md}")

    def _assert_row_agrees(
        self, md: str, prefix: str, envelope: dict, count_field: str = "mismatch_count"
    ) -> None:
        """The summary must say what the input envelope says: status and
        the row's count field verbatim, from the same fields main() read
        (LVS rows carry mismatch_count; DRC's is violation_count)."""
        row = self._row(md, prefix)
        self.assertIn(f"| {envelope.get('status')} |", row)
        self.assertIn(f"{count_field}={envelope.get(count_field)}", row)

    # --- the recorded PASS path ---------------------------------------------

    def test_pass_path_matches_recorded_inputs(self) -> None:
        rc, md = self._render()
        self.assertEqual(rc, 0)
        self.assertIn("## Overall verdict: PASS", md)
        for desc in (
            "DRC on trivial_mos_array is clean",
            "LVS matches the known-good reference",
            "LVS negative control (device-parameter corruption) reports mismatch",
            "LVS negative control (topology corruption) reports mismatch",
        ):
            self.assertIn(f"- [x] {desc}", md)

        envelopes = {
            name: json.loads((self.out_dir / name).read_text())
            for name in _ENVELOPES
        }
        self._assert_row_agrees(md, "| DRC |", envelopes["drc.json"],
                                count_field="violation_count")
        self._assert_row_agrees(md, "| LVS (good reference) |", envelopes["lvs.json"])
        self._assert_row_agrees(
            md, "| LVS negative control: device parameter |",
            envelopes["lvs.broken-device.json"],
        )
        self._assert_row_agrees(
            md, "| LVS negative control: topology (shorted net) |",
            envelopes["lvs.broken-topology.json"],
        )
        # the good row also carries the category counts it summarizes
        good = envelopes["lvs.json"]
        self.assertIn(f"category_counts={good.get('category_counts')}", md)
        # and every entry behind that "match" really is a warning, so the
        # README section the record links to is the right reading of it
        self.assertTrue(
            good["mismatches"], "recorded good lvs.json has no mismatch entries"
        )
        self.assertTrue(
            all(m.get("severity") == "warning" for m in good["mismatches"])
        )

    # --- the #636 failure path -----------------------------------------------

    def test_broken_good_reference_fails_without_contradicting_itself(self):
        """The issue's reproduction: the recorded broken-device envelope
        (34 entries, 31 at severity error) copied over the good-reference
        input. The renderer must report exactly one answer -- FAIL, with a
        table that agrees with the envelope -- never a table that says
        `mismatch` next to prose that says all entries were warnings."""
        shutil.copy(
            _RECORDED / "lvs.broken-device.json", self.out_dir / "lvs.json"
        )
        rc, md = self._render()
        self.assertEqual(rc, 1)
        self.assertIn("## Overall verdict: FAIL", md)
        self.assertIn("- [ ] LVS matches the known-good reference", md)
        # the other three verdicts are untouched by this corruption
        self.assertIn("- [x] DRC on trivial_mos_array is clean", md)
        self.assertIn(
            "- [x] LVS negative control (device-parameter corruption) "
            "reports mismatch",
            md,
        )
        self.assertIn(
            "- [x] LVS negative control (topology corruption) reports mismatch",
            md,
        )

        envelope = json.loads((self.out_dir / "lvs.json").read_text())
        self.assertEqual(envelope["status"], "mismatch")
        errors = sum(
            1 for m in envelope["mismatches"] if m.get("severity") == "error"
        )
        self.assertEqual(errors, 31)  # the recorded 34-entries/31-errors shape
        self._assert_row_agrees(md, "| LVS (good reference) |", envelope)
        for claim in _RETIRED_CLAIMS:
            self.assertNotIn(claim, md)

    # --- the narrative stays retired on both paths ---------------------------

    def test_no_hardcoded_severity_claims_on_either_path(self) -> None:
        """The two-answers bug was path-independent prose; its retirement
        must hold on the PASS path too, and the record must point at the
        raw envelopes and the README section instead."""
        for _label in ("pass", "fail"):
            if _label == "fail":
                shutil.copy(
                    _RECORDED / "lvs.broken-device.json",
                    self.out_dir / "lvs.json",
                )
            _, md = self._render()
            for claim in _RETIRED_CLAIMS:
                self.assertNotIn(claim, md)
            self.assertIn(_README_SECTION_LINK, md)
            self.assertIn("[`lvs.json`](lvs.json)", md)
            self.assertIn(
                "[`lvs.broken-device.json`](lvs.broken-device.json)", md
            )
            self.assertIn(
                "[`lvs.broken-topology.json`](lvs.broken-topology.json)", md
            )


if __name__ == "__main__":
    unittest.main()
