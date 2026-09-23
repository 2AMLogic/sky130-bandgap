#!/usr/bin/env python3
"""Unit coverage for `layout/bin/measure_combine_devices_determinism.py` (#288).

The harness exists to answer one question that a signoff claim rests on: does
this block's committed `klt lvs` request reproduce the *same* verdict on
repeated runs of the same build? Two parts of it are this file's business,
because both can be wrong in a way that looks like a clean answer:

1. **The isolating variant must differ from the baseline in exactly one
   field.** `max_attempts_1` is only a control if it carries the committed
   request's `options.combine_devices`, `hints`, `engine` and tops through
   unchanged and adds only `combine_devices_max_attempts`. A variant that
   quietly dropped `combine_devices` would compare two different questions and
   the harness would still print a tidy table.

2. **The rendered conclusion must be derived from this run's tallies.** A
   fixed narrative ("still nondeterministic") would outlive the upstream fix
   and become a false claim in a committed evidence record -- the same
   discipline `measure_fixed_offset_variants.py` adopted after its own verdict
   changed once.

`klayout_tools` is imported lazily inside the harness's measurement functions,
so this file runs on a plain interpreter with no layout venv and no `klt` --
same convention as `test_mim_overlay_feasibility.py`.

    python3 -m unittest discover --start-directory layout/tests
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "layout" / "bin"))

import measure_combine_devices_determinism as cdt  # noqa: E402

COMMITTED_REQUEST = {
    "schema": "klt.lvs.request/1",
    "engine": "klayout",
    "layout": {"netlist": "cell.extract.spice", "top": "cell"},
    "reference": {"netlist": "reference.spice", "top": "cell_ref"},
    "hints": {"same_nets": []},
    "options": {"combine_devices": True},
}


def _row(label, *, supported=True, tally=None, trials=100, detail=None):
    if not supported:
        return {"variant": label, "supported": False, "detail": detail, "trials": 0}
    counts = dict(tally or {})
    total = sum(counts.values())
    return {
        "variant": label,
        "supported": True,
        "trials": trials,
        "deterministic": len(counts) == 1,
        "mismatch_counts": counts,
        "statuses": {},
        "category_totals": {},
        "clean_fraction": counts.get("0", 0) / total if total else None,
    }


def _payload(rows):
    return {
        "record_id": "r",
        "source_record": "layout/bandgap-core/reports/r",
        "request": "layout/bandgap-core/reports/r/lvs.combined.request.json",
        "repo_sha": "0" * 40,
        "klt_pin": "klayout-tools @ git+https://example.invalid@deadbeef",
        "klt_version": {"version": "0.0.0", "module_location": "x", "lvs_module_sha256": "y"},
        "python_version": "3.12.0",
        "trials": 100,
        "variants": rows,
    }


class VariantRequestIsAControl(unittest.TestCase):
    def _build(self, max_attempts):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            record = work / "record"
            record.mkdir()
            path = cdt._variant_request(
                COMMITTED_REQUEST, record, max_attempts, work, "v"
            )
            return json.loads(path.read_text()), record

    def test_carries_every_other_field_through_verbatim(self):
        built, _record = self._build(1)
        self.assertEqual(built["schema"], COMMITTED_REQUEST["schema"])
        self.assertEqual(built["engine"], COMMITTED_REQUEST["engine"])
        self.assertEqual(built["hints"], COMMITTED_REQUEST["hints"])
        self.assertEqual(built["layout"]["top"], COMMITTED_REQUEST["layout"]["top"])
        self.assertEqual(
            built["reference"]["top"], COMMITTED_REQUEST["reference"]["top"]
        )
        self.assertIs(
            built["options"]["combine_devices"],
            True,
            "the variant dropped options.combine_devices -- it would then measure "
            "a different question than the committed request",
        )

    def test_adds_only_the_retry_budget(self):
        built, _record = self._build(1)
        self.assertEqual(
            set(built["options"]) - set(COMMITTED_REQUEST["options"]),
            {"combine_devices_max_attempts"},
        )
        self.assertEqual(built["options"]["combine_devices_max_attempts"], 1)

    def test_omits_the_budget_when_none_requested(self):
        built, _record = self._build(None)
        self.assertNotIn("combine_devices_max_attempts", built["options"])

    def test_netlist_paths_are_absolute_against_the_record(self):
        """A copy written outside the record cannot keep relative netlist paths."""
        built, record = self._build(1)
        for side in ("layout", "reference"):
            netlist = Path(built[side]["netlist"])
            self.assertTrue(netlist.is_absolute())
            self.assertEqual(netlist.parent, record.resolve())

    def test_does_not_mutate_the_committed_request(self):
        before = json.dumps(COMMITTED_REQUEST, sort_keys=True)
        self._build(1)
        self.assertEqual(json.dumps(COMMITTED_REQUEST, sort_keys=True), before)


class ConclusionIsDerivedNotAsserted(unittest.TestCase):
    def test_flaky_build_is_reported_as_not_deterministic(self):
        text = " ".join(
            cdt._conclusion_lines(
                _payload(
                    [
                        _row("as_committed", tally={"0": 76, "12": 24}),
                        _row("max_attempts_1", tally={"0": 100}),
                    ]
                )
            )
        )
        self.assertIn("not deterministic", text)
        self.assertIn("76.0% clean", text)
        self.assertIn("restores determinism", text)

    def test_a_fixed_build_does_not_leave_a_stale_broken_claim(self):
        """The reason this harness renders prose instead of asserting it."""
        text = " ".join(
            cdt._conclusion_lines(
                _payload(
                    [
                        _row("as_committed", tally={"0": 100}),
                        _row("max_attempts_1", tally={"0": 100}),
                    ]
                )
            )
        )
        self.assertIn("**deterministic**", text)
        self.assertNotIn("not deterministic", text)
        self.assertIn("not perturbing this compare", text)

    def test_unsupported_isolating_variant_is_disclosed_not_dropped(self):
        text = " ".join(
            cdt._conclusion_lines(
                _payload(
                    [
                        _row("as_committed", tally={"0": 100}),
                        _row(
                            "max_attempts_1",
                            supported=False,
                            detail="this build predates the retry entirely",
                        ),
                    ]
                )
            )
        )
        self.assertIn("predates the retry entirely", text)

    def test_still_flaky_with_the_budget_pinned_reopens_the_question(self):
        """The isolating control failing to isolate must not read as success."""
        text = " ".join(
            cdt._conclusion_lines(
                _payload(
                    [
                        _row("as_committed", tally={"0": 70, "12": 30}),
                        _row("max_attempts_1", tally={"0": 70, "12": 30}),
                    ]
                )
            )
        )
        self.assertIn("also** nondeterministic", text)
        self.assertNotIn("restores determinism", text)


class RenderedRecordSurfacesTheTally(unittest.TestCase):
    def test_table_marks_a_nondeterministic_variant(self):
        text = cdt._render_record(
            _payload(
                [
                    _row("as_committed", tally={"0": 76, "12": 24}),
                    _row("max_attempts_1", tally={"0": 100}),
                ]
            )
        )
        self.assertIn("| `as_committed` | build default | **NO** | 76x `0`, 24x `12` |", text)
        self.assertIn("| `max_attempts_1` | 1 | **yes** | 100x `0` |", text)

    def test_unsupported_variant_renders_as_unsupported(self):
        text = cdt._render_record(
            _payload(
                [
                    _row("as_committed", tally={"0": 100}),
                    _row("max_attempts_1", supported=False, detail="no retry budget"),
                ]
            )
        )
        self.assertIn("unsupported by this build", text)


class ProvenanceRecordsIdentityNotLocation(unittest.TestCase):
    """`design-evidence-tiers.md`: repo-relative paths only, never absolute."""

    def test_committed_records_name_no_absolute_module_path(self):
        root = REPO_ROOT / "layout" / "bandgap-core" / "combine-determinism"
        records = sorted(root.glob("*/determinism*.json"))
        self.assertTrue(records, "no committed combine-determinism records found")
        for record in records:
            with self.subTest(record=record.name):
                location = json.loads(record.read_text())["klt_version"]["module_location"]
                self.assertFalse(
                    Path(location).is_absolute(),
                    "a machine-local absolute path was recorded into permanent "
                    "evidence; record identity (lvs_module_sha256) instead",
                )


if __name__ == "__main__":
    unittest.main()
