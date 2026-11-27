#!/usr/bin/env python3
"""Unit coverage for the ERC supply flow's own gate (issue #281, T1 item 11).

`layout/bin/run-erc-supply-flow.sh` produces the block's item-11 evidence, and
`layout/bin/erc_supply_record.py`'s ``gate_supply_report()`` is the only thing
that decides whether that evidence actually says what the committed
``record.md`` claims it says. Three failure modes matter, and all three look
exactly like a passing run if the gate is wrong:

1. **A report that does not describe the committed GDS.** `klt erc`'s
   ``provenance.input.content_hash`` is the only link between a JSON report and
   the stream it was run against. A stale report next to a regenerated layout is
   indistinguishable from a fresh one by eye — and it is the specific thing item
   11's acceptance criteria ask for ("input content-hash matching the committed
   GDS").
2. **A supply that was never checked.** ``erc.unconnected_net`` /
   ``erc.supply_short`` are only computed when ``nets[]`` declares the supply
   (`klayout-tools docs/cli/erc.md`: "Omitted entirely -> ... never computed").
   A spec that lost its ``nets[]`` block reports **zero** findings — the same
   zero a clean design reports. So the gate must require both supplies to appear
   in ``erc_coverage.checked``, never merely require the finding list to be
   empty. This is the same absence-of-evidence trap the empty ``ties[]`` /
   ``ties_disclosure`` situation documents for ``erc.missing_tie``.
3. **A finding that is present and ignored.** A split rail
   (``erc.unconnected_net`` with more than one island) or a rail-to-rail short
   (``erc.supply_short``) must fail the gate even though the report's overall
   ``status`` is not what item 11 grades on.

Every case is exercised in **both** directions — a compliant report must pass,
and a deliberately broken one must fail, with the failure named. Standard
library only, no PDK, no ``klt`` install, matching every other test under
``layout/tests/``.

Run directly, or via::

    npm run test:unit
    python3 -m unittest discover --start-directory layout/tests
"""

from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest import mock

_BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"
_REPO = _BIN.parent.parent
sys.path.insert(0, str(_REPO / "scripts" / "ci"))
from script_module import load_script_module  # noqa: E402

erc_supply_record = load_script_module(_BIN / "erc_supply_record.py", "erc_supply_record")

#: The newest checked-in item-11 record. Its envelopes are recorded evidence,
#: replayed read-only through the renderer's ``main()``; nothing here writes
#: into the evidence tree.
_RECORDED = _REPO / "layout" / "bandgap-core" / "erc" / "20261022-072429-9eb67913"

#: The confirmation prose the renderer emitted unconditionally until issue
#: #705, grouped by the gate leg whose failure disproves it, so a regression
#: reads as "the pass claims came back on a failing record", not as a bare
#: ``assertNotIn`` string. A leg that still passes keeps its true claims.
_COMPUTED_LEAD = "**`erc.missing_tie` is computed.**"
_TIE_EVIDENCE_CLAIMS = (
    "each in `erc_coverage.checked`",
    "with `erc_coverage.skipped` empty and no `ties_disclosure`",
    "Zero findings is therefore a result, not an absence",
)
_CONTROL_CLAIM = "the negative control below shows the declaration can fail"
_VERDICT_CLAIM = (
    "supply islands and n-well ties, both computed, with a negative control"
)
_TIE_CLAIMS = (_COMPUTED_LEAD,) + _TIE_EVIDENCE_CLAIMS
_PASS_CLAIMS = _TIE_CLAIMS + (_CONTROL_CLAIM, _VERDICT_CLAIM)


def clean_report(gds_sha: str) -> dict:
    """A minimal `klt erc` payload shaped like a passing supply run."""
    return {
        "schema_version": 1,
        "status": "clean",
        "erc_status": "clean",
        "erc_finding_count": 0,
        "erc_findings": [],
        "erc_coverage": {
            "checked": [
                'erc.floating_gate:["gate0"]',
                'erc.net_connectivity:["VDD"]',
                'erc.net_connectivity:["VSS"]',
                'erc.missing_tie:["nwell_tie_vdd"]',
                'erc.missing_tie:["nwell_tie_vss"]',
            ],
            "skipped": [],
            "inapplicable": [],
        },
        "provenance": {
            "klt_version": "0.7.0",
            "input": {"content_hash": f"sha256:{gds_sha}", "role": "layout"},
        },
    }


class ErcSupplyGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.gds = pathlib.Path(self._tmp.name) / "bandgap_core_routed.gds"
        self.gds.write_bytes(b"not a real GDS, but it has a stable sha256\n")
        self.sha = hashlib.sha256(self.gds.read_bytes()).hexdigest()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # --- 1. content-hash binding ------------------------------------------

    def test_matching_content_hash_passes(self) -> None:
        ok, reasons = erc_supply_record.gate_supply_report(
            clean_report(self.sha), self.gds
        )
        self.assertTrue(ok, reasons)
        self.assertEqual(reasons, [])

    def test_mismatched_content_hash_fails(self) -> None:
        report = clean_report("0" * 64)
        ok, reasons = erc_supply_record.gate_supply_report(report, self.gds)
        self.assertFalse(ok)
        self.assertTrue(
            any("content_hash" in r for r in reasons),
            f"expected a content-hash reason, got {reasons}",
        )

    def test_absent_provenance_input_fails(self) -> None:
        report = clean_report(self.sha)
        report["provenance"]["input"] = None
        ok, reasons = erc_supply_record.gate_supply_report(report, self.gds)
        self.assertFalse(ok)
        self.assertTrue(any("content_hash" in r for r in reasons), reasons)

    # --- 2. the check actually ran ----------------------------------------

    def test_unchecked_supply_fails_even_with_zero_findings(self) -> None:
        """The absence-of-evidence trap: no findings, because nothing was checked."""
        report = clean_report(self.sha)
        report["erc_coverage"]["checked"] = ['erc.floating_gate:["gate0"]']
        ok, reasons = erc_supply_record.gate_supply_report(report, self.gds)
        self.assertFalse(ok)
        self.assertEqual(report["erc_finding_count"], 0)
        for net in ("VDD", "VSS"):
            self.assertTrue(
                any(net in r and "erc_coverage.checked" in r for r in reasons),
                f"expected {net} to be named as unchecked, got {reasons}",
            )

    def test_one_unchecked_supply_fails(self) -> None:
        report = clean_report(self.sha)
        report["erc_coverage"]["checked"] = [
            x
            for x in report["erc_coverage"]["checked"]
            if 'erc.net_connectivity:["VSS"]' != x
        ]
        ok, reasons = erc_supply_record.gate_supply_report(report, self.gds)
        self.assertFalse(ok)
        self.assertEqual(len(reasons), 1)
        self.assertIn("VSS", reasons[0])

    # --- 3. findings are not ignored --------------------------------------

    def test_split_supply_rail_fails(self) -> None:
        report = clean_report(self.sha)
        report["erc_findings"] = [
            {
                "rule": "erc.unconnected_net",
                "description": "net 'VSS' resolves to 3 electrical islands",
                "net": "VSS",
                "other_net": None,
                "layer": None,
                "bbox": None,
            }
        ]
        report["erc_finding_count"] = 1
        ok, reasons = erc_supply_record.gate_supply_report(report, self.gds)
        self.assertFalse(ok)
        self.assertTrue(any("erc.unconnected_net" in r for r in reasons), reasons)

    def test_supply_short_fails_on_either_net_field(self) -> None:
        report = clean_report(self.sha)
        report["erc_findings"] = [
            {
                "rule": "erc.supply_short",
                "description": "supplies 'VDD' and 'VSS' are one island",
                "net": "VDD",
                "other_net": "VSS",
                "layer": None,
                "bbox": None,
            }
        ]
        report["erc_finding_count"] = 1
        ok, reasons = erc_supply_record.gate_supply_report(report, self.gds)
        self.assertFalse(ok)
        self.assertTrue(any("erc.supply_short" in r for r in reasons), reasons)

    def test_non_supply_findings_do_not_fail_the_gate(self) -> None:
        """Item 11's own rule: an antenna or floating-gate finding is a real
        defect but is not this item's subject (klayout-tools#1994)."""
        report = clean_report(self.sha)
        report["status"] = "violations"
        report["erc_status"] = "violations"
        report["erc_findings"] = [
            {
                "rule": "erc.floating_gate",
                "description": "gate net has no driver",
                "net": None,
                "other_net": None,
                "gate_id": "gate3",
                "layer": "poly",
                "bbox": None,
            },
            {
                "rule": "erc.unconnected_net",
                "description": "net 'VBQ' resolves to 2 electrical islands",
                "net": "VBQ",
                "other_net": None,
                "layer": None,
                "bbox": None,
            },
        ]
        report["erc_finding_count"] = 2
        ok, reasons = erc_supply_record.gate_supply_report(report, self.gds)
        self.assertTrue(ok, reasons)

    # --- every reason is reported, not just the first ---------------------

    def test_all_failures_are_reported_together(self) -> None:
        report = clean_report("f" * 64)
        report["erc_coverage"]["checked"] = []
        report["erc_findings"] = [
            {
                "rule": "erc.supply_short",
                "description": "shorted",
                "net": "VDD",
                "other_net": "VSS",
                "layer": None,
                "bbox": None,
            }
        ]
        ok, reasons = erc_supply_record.gate_supply_report(report, self.gds)
        self.assertFalse(ok)
        # 1 hash + 2 unchecked supplies + 1 short
        self.assertEqual(len(reasons), 4, reasons)

    def test_gate_does_not_mutate_the_report(self) -> None:
        report = clean_report(self.sha)
        before = copy.deepcopy(report)
        erc_supply_record.gate_supply_report(report, self.gds)
        self.assertEqual(report, before)


class ErcTieGateTest(unittest.TestCase):
    """The n-well tie gate: zero findings only counts when the rule actually ran."""

    def report(self) -> dict:
        return clean_report("0" * 64)

    def test_computed_clean_ties_pass(self) -> None:
        ok, reasons = erc_supply_record.gate_tie_report(self.report())
        self.assertTrue(ok, reasons)

    def test_uncomputed_ties_fail_even_with_zero_findings(self) -> None:
        report = self.report()
        report["erc_coverage"]["checked"] = [
            x for x in report["erc_coverage"]["checked"] if "missing_tie" not in x
        ]
        report["erc_coverage"]["inapplicable"] = [
            {"id": "erc.missing_tie:[]", "reason": "ties_disclosed_tool_limitation"}
        ]
        report["ties_disclosure"] = {"kind": "tool_limitation"}
        ok, reasons = erc_supply_record.gate_tie_report(report)
        self.assertFalse(ok)
        self.assertEqual(report["erc_finding_count"], 0)
        self.assertEqual(len(reasons), 3, reasons)

    def test_skipped_degenerate_selection_fails(self) -> None:
        report = self.report()
        report["erc_coverage"]["skipped"] = [
            {"id": 'erc.missing_tie:["nwell_tie_vss"]', "reason": "degenerate_well_selection"}
        ]
        ok, reasons = erc_supply_record.gate_tie_report(report)
        self.assertFalse(ok)
        self.assertTrue(any("skipped" in r for r in reasons), reasons)

    def test_missing_tie_finding_fails(self) -> None:
        report = self.report()
        report["erc_findings"] = [
            {"rule": "erc.missing_tie", "description": "tap not connected", "net": "VDD"}
        ]
        ok, reasons = erc_supply_record.gate_tie_report(report)
        self.assertFalse(ok)
        self.assertTrue(any("erc.missing_tie" in r for r in reasons), reasons)

    def test_negative_control_must_flag_every_well(self) -> None:
        finding = {"rule": "erc.missing_tie", "net": "VDD"}
        ok, _ = erc_supply_record.gate_negative_control({"erc_findings": [finding] * 8}, 8)
        self.assertTrue(ok)
        ok, reasons = erc_supply_record.gate_negative_control({"erc_findings": [finding] * 7}, 8)
        self.assertFalse(ok)
        ok, _ = erc_supply_record.gate_negative_control({"erc_findings": []}, 8)
        self.assertFalse(ok)


class CommittedRecordTest(unittest.TestCase):
    """The committed evidence must pass the committed gate.

    Guards the case where a future spec/flow change lands without re-running
    `layout/bin/run-erc-supply-flow.sh`, leaving a `record.md` that claims PASS
    over JSON that no longer does.
    """

    def test_every_committed_supply_report_passes_the_gate(self) -> None:
        import json

        cell = pathlib.Path(__file__).resolve().parent.parent / "bandgap-core"
        erc_dir = cell / "erc"
        reports = sorted(erc_dir.glob("*/erc.*.json"))
        # Newest record only: older records predate the n-well ties and carry
        # the superseded known-gap reports (append-only evidence).
        newest = sorted(p for p in erc_dir.iterdir() if p.is_dir())[-1]
        reports = [
            p
            for p in reports
            if p.parent == newest
            and "known-gap" not in p.name
            and "negative-control" not in p.name
        ]
        self.assertTrue(reports, f"no committed supply reports under {erc_dir}")
        for path in reports:
            with self.subTest(report=path.name):
                report = json.loads(path.read_text())
                # erc.<gds-record-id>.json -> the routed GDS it was run against
                gds_record = path.name[len("erc.") : -len(".json")]
                gds = cell / "reports" / gds_record / "bandgap_core_routed.gds"
                self.assertTrue(gds.is_file(), f"missing {gds}")
                ok, reasons = erc_supply_record.gate_supply_report(report, gds)
                self.assertTrue(ok, f"{path.name}: {reasons}")
                ok, reasons = erc_supply_record.gate_tie_report(report)
                self.assertTrue(ok, f"{path.name}: {reasons}")


class ErcSupplyRecordRenderTest(unittest.TestCase):
    """The rendered ``record.md`` must say what the gates said (issue #705).

    The three ``gate_*`` functions decide the exit status, but until #705
    ``main()`` rendered the confirmation prose -- ``erc.missing_tie`` is
    computed, zero findings is a result, the negative control shows the
    declaration can fail, both computed with a negative control -- whether or
    not those gates had passed, so a failing record contradicted its own
    table. This replays the newest committed record's envelopes through the
    renderer's real ``main()`` and breaks one gate leg at a time:

    * the recorded envelopes -- PASS, exit 0, byte-identical to the committed
      ``record.md`` (the passing wording must not change), with no ``--klt``
      on the command line;
    * each gate leg broken -- FAIL, exit 1, with every pass claim that leg
      disproves withdrawn and the gate's own reasons in its place, while the
      claims of the legs that still pass stay.

    Only ``sys.argv`` is stubbed; the record text is produced by the code
    under test from the envelopes on disk. Standard library only, no PDK, no
    ``klt`` install.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = pathlib.Path(self._tmp.name)
        for envelope in sorted(_RECORDED.glob("*.json")):
            shutil.copy(envelope, self.out_dir / envelope.name)
        (control,) = self.out_dir.glob("erc.negative-control-nwell-swapped.*.json")
        self.control = control.name
        self.newest = self.control[
            len("erc.negative-control-nwell-swapped.") : -len(".json")
        ]
        self.n_wells = len(json.loads(control.read_text())["erc_findings"])
        self.gds_records = sorted(
            p.name[len("erc.") : -len(".json")]
            for p in self.out_dir.glob("erc.*.json")
            if "negative-control" not in p.name and "known-gap" not in p.name
        )
        self.assertEqual(self.gds_records[-1], self.newest)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # --- harness ----------------------------------------------------------

    def _render(self, *extra_argv: str) -> tuple[int, str]:
        """Run the renderer's real ``main()`` over the copied envelopes."""
        argv = [
            "erc_supply_record.py",
            "--out-dir",
            str(self.out_dir),
            "--record-id",
            _RECORDED.name,
            "--repo-root",
            str(_REPO),
            "--gds-records",
            *self.gds_records,
            "--newest",
            self.newest,
            *extra_argv,
        ]
        with mock.patch.object(sys, "argv", argv), redirect_stdout(StringIO()):
            rc = erc_supply_record.main()
        return rc, (self.out_dir / "record.md").read_text()

    def _break(self, envelope: str, mutate) -> None:
        """Overwrite one copied envelope with ``mutate`` applied to its payload."""
        path = self.out_dir / envelope
        report = json.loads(path.read_text())
        mutate(report)
        path.write_text(json.dumps(report))

    def _line(self, md: str, prefix: str) -> str:
        for line in md.splitlines():
            if line.startswith(prefix):
                return line
        self.fail(f"no line starting {prefix!r} in:\n{md}")

    def _assert_no_pass_claims(self, md: str, *claims: str) -> None:
        for claim in claims:
            self.assertNotIn(claim, md)

    def _uncheck(self, *ids: str):
        """Return a mutation dropping ``ids`` from ``erc_coverage.checked``."""

        def mutate(report: dict) -> None:
            cov = report["erc_coverage"]
            cov["checked"] = [x for x in cov["checked"] if x not in ids]

        return mutate

    # --- the recorded PASS path -------------------------------------------

    def test_recorded_envelopes_render_the_committed_record(self) -> None:
        rc, md = self._render()
        self.assertEqual(rc, 0)
        self.assertEqual(md, (_RECORDED / "record.md").read_text())
        for claim in _PASS_CLAIMS:
            self.assertIn(claim, md)

    def test_cli_takes_no_klt_flag(self) -> None:
        """``--klt`` was required yet never read (#705); the version of record
        is the report's own ``provenance.klt_version``."""
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as caught:
            self._render("--klt", "/nonexistent/not-even-used")
        self.assertEqual(caught.exception.code, 2)

    # --- a failing gate leg withdraws the claims it disproves -------------

    def test_failing_tie_gate_renders_its_reasons_not_pass_claims(self) -> None:
        """The #705 reproduction: every tie-gate leg failing at once on the
        newest GDS, while the supply half and the control still pass."""

        def break_ties(report: dict) -> None:
            cov = report["erc_coverage"]
            cov["checked"] = [x for x in cov["checked"] if "missing_tie" not in x]
            cov["skipped"] = [
                {
                    "id": 'erc.missing_tie:["nwell_tie_vss"]',
                    "reason": "degenerate_well_selection",
                }
            ]
            report["ties_disclosure"] = {"kind": "tool_limitation"}
            report["erc_findings"] = report["erc_findings"] + [
                {
                    "rule": "erc.missing_tie",
                    "description": "tap not connected",
                    "net": "VDD",
                }
            ]

        self._break(f"erc.{self.newest}.json", break_ties)
        rc, md = self._render()
        self.assertEqual(rc, 1)
        row = self._line(md, f"| `{self.newest}` |")
        self.assertIn("0/2 / **1** | **FAIL** |", row)
        self._assert_no_pass_claims(md, *_TIE_CLAIMS, _VERDICT_CLAIM)
        self.assertIn(_CONTROL_CLAIM, md)
        summary = self._line(md, "**`erc.missing_tie` is")
        self.assertIn(f"`{self.newest}`", summary)
        for reason in (
            "erc.missing_tie for nwell_tie_vdd is not in erc_coverage.checked",
            "erc.missing_tie for nwell_tie_vss is not in erc_coverage.checked",
            "erc_coverage.skipped is not empty",
            "report still carries a ties_disclosure",
            "erc.missing_tie: tap not connected",
        ):
            self.assertIn(reason, summary)
        self.assertIn("**FAIL** — item 11's structural gate.", md)

    def test_older_gds_tie_failure_cannot_hide_behind_a_clean_newest(self) -> None:
        """The tie paragraph summarises every row of the table above it, so a
        failed older row must withdraw the confirmation as well."""
        oldest = self.gds_records[0]
        self._break(
            f"erc.{oldest}.json",
            self._uncheck('erc.missing_tie:["nwell_tie_vdd"]'),
        )
        rc, md = self._render()
        self.assertEqual(rc, 1)
        self._assert_no_pass_claims(md, *_TIE_CLAIMS, _VERDICT_CLAIM)
        self.assertIn(_CONTROL_CLAIM, md)
        summary = self._line(md, "**`erc.missing_tie` is")
        self.assertIn(f"`{oldest}`", summary)
        self.assertIn(
            "erc.missing_tie for nwell_tie_vdd is not in erc_coverage.checked", summary
        )
        self.assertIn("**FAIL** — item 11's structural gate.", md)

    def test_failing_negative_control_renders_its_reason_not_pass_claims(
        self,
    ) -> None:
        """The control flags all but one well: the tie gate still passes, so
        only the claim that leans on the control may be withdrawn."""

        def drop_one_flag(report: dict) -> None:
            report["erc_findings"] = report["erc_findings"][:-1]

        self._break(self.control, drop_one_flag)
        rc, md = self._render()
        self.assertEqual(rc, 1)
        flagged = self.n_wells - 1
        self.assertIn(f"Total `erc.missing_tie`: **{flagged}** of {self.n_wells}", md)
        self._assert_no_pass_claims(md, _COMPUTED_LEAD, _CONTROL_CLAIM, _VERDICT_CLAIM)
        for claim in _TIE_EVIDENCE_CLAIMS:
            self.assertIn(claim, md)
        self.assertIn(
            "the negative control below does not show the declaration can fail: "
            f"negative control reported {flagged} erc.missing_tie, "
            f"expected {self.n_wells}",
            md,
        )

    def test_failing_supply_gate_withdraws_the_verdicts_pass_wording(self) -> None:
        """Ties and control pass, so their paragraph stays true; only the
        verdict's "supply islands ... computed" must go."""
        self._break(
            f"erc.{self.newest}.json",
            self._uncheck('erc.net_connectivity:["VSS"]'),
        )
        rc, md = self._render()
        self.assertEqual(rc, 1)
        self._assert_no_pass_claims(md, _VERDICT_CLAIM)
        for claim in _TIE_CLAIMS + (_CONTROL_CLAIM,):
            self.assertIn(claim, md)
        verdict = self._line(md, "Item 11's structural half")
        self.assertIn(
            f"supply gate failed on 1 of {len(self.gds_records)} routed GDSs "
            f"(`{self.newest}`)",
            verdict,
        )
        self.assertIn("n-well tie gate passed on every routed GDS", verdict)
        self.assertIn("swapped-tie negative control passed", verdict)


if __name__ == "__main__":
    unittest.main()
