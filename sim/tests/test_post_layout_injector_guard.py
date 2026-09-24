#!/usr/bin/env python3
"""The guard that keeps the two post-layout startup benches pointed at the DUT
they claim to measure (issue #285, restructured by issue #299).

`sim/startup-stability-post-layout/` and `sim/startup-ramp-post-layout/` are
claims about the COMPOSED cell -- core + startup injector as drawn. Since #299
they instantiate `design/bandgap_core.sym` ALONE and rely on the extracted body
to supply the injector, so the dangerous direction is running them against a
layout record that does NOT draw it: the run would succeed, produce plausible
numbers on an unprotected core, and append them to `sim/`'s append-only
evidence as the composed cell's. `require_layout_draws_injector()` is the
structural precondition that refuses instead -- and it is also what replaced
the bare-core CONTROL instances those benches carried before #299, which the
drawn cell cannot express any more.

It is the mirror image of the pre-#299 `refuse_if_layout_draws_injector()`
guard, which existed for the opposite hazard: back when those benches wrapped
a testbench that netlisted its own `design/startup_injector.sym` instances,
running against an injector-drawing layout record would have double-counted
the injector on the DUT instances and silently made the controls
injector-equipped. Both guards exist for the same reason -- the failure they
catch is invisible in the output -- so the refusal is asserted here rather
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


INJECTOR_INCLUSIVE = CORE_ONLY.replace(
    ".ends bandgap_core", INJECTOR_CARDS + ".ends bandgap_core"
)


class TestRequireLayoutDrawsInjector(unittest.TestCase):
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
            return plc.require_layout_draws_injector("a-startup-bench")
        finally:
            plc.LAYOUT_BANDGAP_CORE_DIR = saved

    def test_injector_inclusive_layout_is_allowed_through(self) -> None:
        self.assertIsNone(self._run_against(INJECTOR_INCLUSIVE))

    def test_core_only_layout_is_refused(self) -> None:
        """The post-#299 hazard: these benches instantiate the core symbol
        alone and expect the extracted body to supply the injector, so a
        core-only layout record would be measured -- and recorded -- as the
        composed cell."""
        with self.assertRaises(plc.PostLayoutError) as caught:
            self._run_against(CORE_ONLY)
        message = str(caught.exception)
        self.assertIn("a-startup-bench", message)
        self.assertIn("#299", message)
        self.assertIn("20260101-000000-abcdefg", message)

    def test_the_pre_299_guard_is_gone(self) -> None:
        """The two guards are mutually exclusive by construction -- one refuses
        exactly the layout records the other requires -- so leaving both on the
        module invites a bench calling the wrong one and refusing every layout
        record in existence."""
        self.assertFalse(hasattr(plc, "refuse_if_layout_draws_injector"))


if __name__ == "__main__":
    unittest.main()
