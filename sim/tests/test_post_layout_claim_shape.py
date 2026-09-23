#!/usr/bin/env python3
"""`post_layout_common.resolve_record_claim_and_title()` -- the rule deciding
what `claim`/`title` an `extracted`-provenance record carries (issue #299).

Every branch of that function is a MISLABELING guard, and mislabeling is the
exact failure issue #16's own history warns against: a "post-layout" record
that is really a relabeled schematic run. The guards therefore have to be
exercisable without a PDK, ngspice or `klt` on PATH -- not first met at the
moment a record is being written into `sim/`'s append-only evidence.

Two manifest shapes exist:

  * WRAPPING -- the post-layout bench reuses its schematic-level sibling's
    manifest unchanged, so that manifest's own provenance sentence has to be
    split off and replaced. Five of the seven post-layout benches.
  * OWN-MANIFEST (issue #299) -- the post-layout bench carries its own
    `experiment.json`, already written for the extracted DUT, because its
    schematic-level sibling's measurement set cannot be reused at all.
    `sim/startup-stability-post-layout/` and `sim/startup-ramp-post-layout/`.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIM_DIR / "bin"))

import post_layout_common as plc  # noqa: E402


class _Boom(RuntimeError):
    """Stand-in for `cr.HarnessError`, which needs `corner-run.py` loaded."""


WRAPPED_RAW = {
    "title": "Startup: supply-ramp transient startup time",
    "claim": (
        "spec/topology-survey.md Startup row -- the startup-TIME half. Measures "
        "design/bandgap_core.sch + design/startup_injector.sch ..."
    ),
    "provenance": "schematic",
}

OWN_RAW = {
    "title": "Startup: ... of the COMPOSED LAYOUT CELL -- POST-LAYOUT (extracted netlist)",
    "claim": "spec/topology-survey.md Startup row ... the ROUTED, LVS-clean layout ...",
    "provenance": "extracted",
}


def resolve(**kwargs):
    base = dict(
        slug="a-post-layout",
        wrapped_experiment="a-post-layout",
        raw=OWN_RAW,
        fallback_title="a-post-layout",
        claim_tail=None,
        claim_split=None,
        error=_Boom,
    )
    base.update(kwargs)
    return plc.resolve_record_claim_and_title(**base)


class TestWrappingShape(unittest.TestCase):
    def test_the_schematic_provenance_tail_is_replaced(self) -> None:
        claim, title, owns = resolve(
            slug="startup-ramp-post-layout",
            wrapped_experiment="startup-ramp",
            raw=WRAPPED_RAW,
            claim_tail="Measures the ROUTED layout ...",
        )
        self.assertFalse(owns)
        self.assertNotIn("design/bandgap_core.sch", claim)
        self.assertTrue(claim.endswith("Measures the ROUTED layout ..."))
        self.assertTrue(claim.startswith("spec/topology-survey.md Startup row"))
        self.assertTrue(title.endswith("-- POST-LAYOUT (extracted netlist)"))

    def test_a_claim_split_that_does_not_occur_is_refused(self) -> None:
        with self.assertRaises(_Boom) as caught:
            resolve(
                slug="startup-ramp-post-layout",
                wrapped_experiment="startup-ramp",
                raw=WRAPPED_RAW,
                claim_tail="...",
                claim_split="Substantiates that ",
            )
        self.assertIn("schematic-level provenance sentence verbatim", str(caught.exception))


class TestOwnManifestShape(unittest.TestCase):
    def test_claim_and_title_are_used_verbatim(self) -> None:
        claim, title, owns = resolve()
        self.assertTrue(owns)
        self.assertEqual(claim, OWN_RAW["claim"])
        self.assertEqual(title, OWN_RAW["title"])

    def test_no_post_layout_suffix_is_appended_twice(self) -> None:
        _claim, title, _owns = resolve()
        self.assertEqual(title.count("POST-LAYOUT (extracted netlist)"), 1)

    def test_wrapping_somebody_elses_manifest_verbatim_is_refused(self) -> None:
        """The whole point of the own-manifest shape is that the claim is
        already written for the extracted DUT. Using another bench's claim
        verbatim would put its schematic-level sentence into an
        extracted-provenance record -- the mislabeling issue #16 guards
        against."""
        with self.assertRaises(_Boom) as caught:
            resolve(slug="startup-ramp-post-layout", wrapped_experiment="startup-ramp")
        self.assertIn("supply a claim_tail instead", str(caught.exception))

    def test_a_schematic_provenance_manifest_is_refused(self) -> None:
        with self.assertRaises(_Boom) as caught:
            resolve(raw=WRAPPED_RAW | {"title": "x"})
        self.assertIn("provenance", str(caught.exception))

    def test_claim_split_with_no_claim_tail_is_refused(self) -> None:
        with self.assertRaises(_Boom) as caught:
            resolve(claim_split="Measures ")
        self.assertIn("meaningless", str(caught.exception))


class TestTheTwoRestructuredBenchesUseTheOwnManifestShape(unittest.TestCase):
    """A committed-state check, deliberately: issue #299's whole point is that
    these two benches must NOT reuse their schematic-level sibling's manifest,
    and must NOT instantiate a separate `design/startup_injector.sym` alongside
    an extracted body that already contains one."""

    BENCHES = ("startup-stability-post-layout", "startup-ramp-post-layout")

    def test_each_carries_its_own_extracted_provenance_manifest(self) -> None:
        for slug in self.BENCHES:
            with self.subTest(slug=slug):
                raw = json.loads((SIM_DIR / slug / "experiment.json").read_text())
                self.assertEqual(raw["slug"], slug)
                self.assertEqual(raw["provenance"], "extracted")

    def test_no_testbench_instantiates_a_separate_startup_injector(self) -> None:
        for slug in self.BENCHES:
            with self.subTest(slug=slug):
                raw = json.loads((SIM_DIR / slug / "experiment.json").read_text())
                sch = (SIM_DIR / slug / raw["schematic"]).read_text()
                instances = [
                    ln for ln in sch.splitlines() if ln.startswith("C {design/")
                ]
                self.assertTrue(instances, "testbench instantiates no design/ symbol")
                self.assertTrue(
                    all("design/bandgap_core.sym" in ln for ln in instances),
                    f"{slug}: only design/bandgap_core.sym may be instantiated; "
                    "the extracted composed cell already contains the injector",
                )

    def test_no_control_dependent_measurement_survives(self) -> None:
        """The six stability + two ramp measurements that are differences
        against a bare-core control instance. The drawn cell has an injector,
        so none of them has a post-layout meaning -- see either manifest's own
        'DROPPED MEASUREMENTS' note for where those claims still live."""
        dropped = {
            "imin_off_bare",
            "i_off_bare",
            "ncross_bare",
            "dvref",
            "i_standing",
            "i_su_standing",
            "vref_n",
            "gn_n",
        }
        for slug in self.BENCHES:
            with self.subTest(slug=slug):
                raw = json.loads((SIM_DIR / slug / "experiment.json").read_text())
                names = {m["name"] for m in raw["measurements"]}
                self.assertEqual(names & dropped, set())


if __name__ == "__main__":
    unittest.main()
