#!/usr/bin/env python3
"""The guard that stops a mixed-provenance startup bench from double-counting
the drawn startup injector (issue #285, follow-up #299).

`sim/startup-stability-post-layout/` and `sim/startup-ramp-post-layout/` wrap a
testbench that netlists `design/startup_injector.sym` instances of its own
alongside the extracted core, and that is only correct while the composed cell
draws NO injector. Since #285 it draws one. The failure mode if the guard is
missing is the dangerous kind: the run succeeds, produces plausible numbers,
and appends them to `sim/`'s append-only evidence -- the DUT instances quietly
carry two injectors and the bench's bare-core CONTROL instances quietly carry
one. Nothing in the output says so. So the refusal is asserted here rather
than left to a reviewer noticing.

Deliberately exercised against synthetic layout-record directories, not the
committed ones: the point is the decision function, and pinning it to whatever
`layout/bandgap-core/reports/LATEST` happens to say today would make this test
a restatement of the repo's current state instead of a check on the rule.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIM_DIR / "bin"))

import post_layout_common as plc  # noqa: E402

#: The six device cards `layout/bandgap-core/reference.spice` states for
#: `design/startup_injector.sch`, verbatim in the card order that file uses.
INJECTOR_CARDS = """\
MMPC1 NC1  NC1  GDRV VDD pfet L=20U  W=1U  m=1
MMPC2 NG   NG   NC1  VDD pfet L=20U  W=1U  m=1
MMNS  NG   VOUT NE   VSS nfet L=0.5U W=48U m=1
MMNI  GDRV NG   VSS  VSS nfet L=0.5U W=10U m=1
MMNC  VDD  VOUT GDRV VSS nfet L=1U   W=4U  m=1
QQS VSS VSS NE  pnp AE=3.6992P PE=21.76U NE=8
"""

#: A core-only reference, i.e. every pre-#285 layout record.
CORE_ONLY = """\
.subckt bandgap_core VOUT GDRV VDD VSS
MMPOUT VOUT GDRV VDD VDD pfet L=2U W=8U m=2
QQ1 VSS VSS VA  pnp AE=3.6992P PE=21.76U NE=8
.ends bandgap_core
"""


class TestLayoutRecordDrawsInjector(unittest.TestCase):
    def _record(self, reference_text: str | None) -> Path:
        tmp = Path(tempfile.mkdtemp())
        if reference_text is not None:
            (tmp / "reference.spice").write_text(reference_text)
        return tmp

    def test_core_only_record_does_not_draw_the_injector(self) -> None:
        self.assertFalse(plc.layout_record_draws_injector(self._record(CORE_ONLY)))

    def test_injector_inclusive_record_draws_it(self) -> None:
        text = CORE_ONLY.replace(".ends bandgap_core", INJECTOR_CARDS + ".ends bandgap_core")
        self.assertTrue(plc.layout_record_draws_injector(self._record(text)))

    def test_a_partial_transcription_is_not_treated_as_drawn(self) -> None:
        """All six cards or none: a reference carrying only some of them is a
        transcription in progress, and answering "yes, drawn" on it would let
        the guard fire on a cell whose injector is not actually complete."""
        partial = CORE_ONLY.replace(
            ".ends bandgap_core",
            "MMPC1 NC1  NC1  GDRV VDD pfet L=20U  W=1U  m=1\n.ends bandgap_core",
        )
        self.assertFalse(plc.layout_record_draws_injector(self._record(partial)))

    def test_a_card_name_appearing_only_as_a_substring_does_not_count(self) -> None:
        """`MMNC` must not be matched inside `MMNCX`, and a mention inside a
        comment must not count as a device card -- the match is anchored to
        the start of a line and requires the card's own trailing whitespace."""
        commented = CORE_ONLY.replace(
            ".ends bandgap_core",
            "* MMPC1 MMPC2 MMNS MMNI MMNC QQS are not drawn here\n.ends bandgap_core",
        )
        self.assertFalse(plc.layout_record_draws_injector(self._record(commented)))

    def test_a_record_with_no_reference_netlist_raises(self) -> None:
        with self.assertRaises(plc.PostLayoutError):
            plc.layout_record_draws_injector(self._record(None))


class TestRefuseIfLayoutDrawsInjector(unittest.TestCase):
    """The refusal itself, driven through a synthetic `reports/LATEST` tree."""

    def _layout_dir(self, reference_text: str) -> Path:
        root = Path(tempfile.mkdtemp())
        record = root / "reports" / "20260101-000000-abcdefg"
        record.mkdir(parents=True)
        (record / "reference.spice").write_text(reference_text)
        (record / "bandgap_core_routed.gds").write_bytes(b"")
        (root / "reports" / "LATEST").write_text("20260101-000000-abcdefg\n")
        return root

    def _run_against(self, reference_text: str):
        saved = plc.LAYOUT_BANDGAP_CORE_DIR
        plc.LAYOUT_BANDGAP_CORE_DIR = self._layout_dir(reference_text)
        try:
            return plc.refuse_if_layout_draws_injector("a-startup-bench")
        finally:
            plc.LAYOUT_BANDGAP_CORE_DIR = saved

    def test_pre_injector_layout_is_allowed_through(self) -> None:
        self.assertIsNone(self._run_against(CORE_ONLY))

    def test_injector_inclusive_layout_is_refused(self) -> None:
        text = CORE_ONLY.replace(".ends bandgap_core", INJECTOR_CARDS + ".ends bandgap_core")
        with self.assertRaises(plc.PostLayoutError) as caught:
            self._run_against(text)
        message = str(caught.exception)
        self.assertIn("a-startup-bench", message)
        self.assertIn("#299", message)
        self.assertIn("double-count", message)


if __name__ == "__main__":
    unittest.main()
