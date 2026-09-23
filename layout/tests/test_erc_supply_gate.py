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
import importlib.util
import pathlib
import tempfile
import unittest

_BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"
_SPEC = importlib.util.spec_from_file_location(
    "erc_supply_record", _BIN / "erc_supply_record.py"
)
assert _SPEC is not None and _SPEC.loader is not None
erc_supply_record = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(erc_supply_record)


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
            ],
            "skipped": [],
            "inapplicable": [
                {
                    "id": "erc.missing_tie:[]",
                    "reason": "ties_disclosed_tool_limitation",
                }
            ],
        },
        "provenance": {
            "klt_version": "0.6.0",
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
        reports = [p for p in reports if "known-gap" not in p.name]
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


if __name__ == "__main__":
    unittest.main()
