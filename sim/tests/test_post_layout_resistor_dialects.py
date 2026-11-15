#!/usr/bin/env python3
"""`post_layout_common.translate_extracted_netlist()` -- resistor card
dialect coverage across klt versions (issue #540).

`klt extract --parasitics` has now written the SAME `res_high_po` device
three different ways, and the shared translator has to recognise every shape
that a COMMITTED snapshot under `sim/*/parasitics-snapshot/` actually uses:

  * klt 0.5.0 (and 0.2.0):  `R$n <a> <b> <bulk> <value> res_high_po [L=.. W=..]`
    -- what the six other post-layout benches' committed snapshots carry.
  * klt 0.8.0 (issue #540): `X$n <a> <b> <bulk> res_high_po r=<value> [L=.. W=..]`
    -- what `sim/output-voltage-tc-post-layout/`'s snapshot carries.

Both are live simultaneously: issue #540 re-extracted ONE bench at the
pinned 0.8.0 while the other six keep reading their 0.5.0 snapshots, so a
regression on either dialect silently zeroes that bench's resistor coverage.
`build_extracted_body`'s `device_counts` cross-check turns that into a loud
abort rather than a wrong netlist -- these tests keep it from getting that
far, and pin the invariant that the two shapes translate to the SAME card.

Why this matters more than an ordinary parse test: an `X$n ... res_high_po
...` card with no `.SUBCKT res_high_po` in the file is valid SPICE for a
subcircuit instantiation, so an unrecognised 0.8.0 resistor does not fail to
parse -- it reaches ngspice as a call to an undefined subckt. Filed
generically upstream as 2AMLogic/klayout-tools#5741.

No PDK, ngspice or `klt` on PATH is needed.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIM_DIR / "bin"))
import post_layout_common as plc  # noqa: E402

# One real card per dialect, copied verbatim out of the two committed
# snapshots for layout record 20260923-070209-dbd57a9 (same device, same
# layout, same extracted value -- only the klt version differs).
R_CARD_050 = r"R$98 VOUT__t0 \$7__t0 VSS__t24 2003.841367 res_high_po L=5U W=1U"
R_CARD_080 = r"X$98 VOUT__t0 \$7__t0 VSS__t24 res_high_po r=2003.841367 L=5U W=1U"
# The translated form both must collapse to: a plain 2-terminal ngspice
# resistor at the extracted ohms, bulk terminal and L/W deliberately dropped.
R_TRANSLATED = r"R$98 VOUT__t0 \$7__t0 2003.841367"

SNAPSHOT_050 = (
    SIM_DIR
    / "startup-time-post-layout"
    / "parasitics-snapshot"
    / "20260923-070209-dbd57a9"
    / "bandgap_core_routed.pex.spice"
)
SNAPSHOT_080 = (
    SIM_DIR
    / "output-voltage-tc-post-layout"
    / "parasitics-snapshot"
    / "20260923-070209-dbd57a9"
    / "bandgap_core_routed.pex.spice"
)


class ResistorDialects(unittest.TestCase):
    def test_klt_050_card_translates(self):
        text, counts = plc.translate_extracted_netlist(R_CARD_050 + "\n")
        self.assertEqual(counts["res"], 1)
        self.assertIn(R_TRANSLATED, text)

    def test_klt_080_card_translates(self):
        text, counts = plc.translate_extracted_netlist(R_CARD_080 + "\n")
        self.assertEqual(counts["res"], 1)
        self.assertIn(R_TRANSLATED, text)

    def test_both_dialects_translate_to_the_same_card(self):
        """The 0.8.0 re-extraction must not change the DEVICE resistors --
        issue #540's whole premise is that only the PARASITIC network moved."""
        a, _ = plc.translate_extracted_netlist(R_CARD_050 + "\n")
        b, _ = plc.translate_extracted_netlist(R_CARD_080 + "\n")
        self.assertEqual(a, b)

    def test_dialects_are_mutually_exclusive(self):
        """Neither pattern may claim the other's card, or a snapshot carrying
        both shapes would double-count and trip the coverage guard."""
        self.assertIsNone(plc._R_RE.match(R_CARD_080))
        self.assertIsNone(plc._R_SUBCKT_RE.match(R_CARD_050))

    def test_080_pattern_accepts_exponent_form_value(self):
        card = r"X$7 A__t0 B__t0 VSS__t1 res_high_po r=1.5e+03 L=5U W=1U"
        text, counts = plc.translate_extracted_netlist(card + "\n")
        self.assertEqual(counts["res"], 1)
        self.assertIn(r"R$7 A__t0 B__t0 1.5e+03", text)

    def test_subckt_call_without_res_class_is_left_alone(self):
        """Only `res_high_po` cards are claimed -- a genuine subcircuit call
        must pass through untouched."""
        card = "X$5 A B C some_real_subckt r=1.0"
        text, counts = plc.translate_extracted_netlist(card + "\n")
        self.assertEqual(counts["res"], 0)
        self.assertIn(card, text)

    def test_committed_snapshots_translate_at_full_coverage(self):
        """Both committed snapshots for layout record 20260923-070209-dbd57a9
        must translate every device their own JSON summary declares -- the
        cross-check `build_extracted_body` enforces at run time."""
        import json

        for snap, klt_version in ((SNAPSHOT_050, "0.5.0"), (SNAPSHOT_080, "0.8.0")):
            with self.subTest(klt=klt_version):
                self.assertTrue(snap.is_file(), f"missing snapshot {snap}")
                summary = json.loads(
                    snap.with_name("bandgap_core_routed.pex.json").read_text()
                )
                self.assertEqual(summary["provenance"]["klt_version"], klt_version)
                declared = summary["device_counts"]
                _text, counts = plc.translate_extracted_netlist(snap.read_text())
                self.assertEqual(
                    (counts["mos"], counts["pnp"], counts["res"]),
                    (
                        declared.get("nfet", 0) + declared.get("pfet", 0),
                        declared.get("pnp", 0),
                        declared.get("res_high_po", 0),
                    ),
                )

    def test_committed_snapshots_agree_on_device_resistors(self):
        """The two klt versions' translated DEVICE resistor cards must be
        identical: issue #540's single variable is the parasitic network."""
        a, _ = plc.translate_extracted_netlist(SNAPSHOT_050.read_text())
        b, _ = plc.translate_extracted_netlist(SNAPSHOT_080.read_text())
        self.assertEqual(
            sorted(l for l in a.splitlines() if l.startswith("R$")),
            sorted(l for l in b.splitlines() if l.startswith("R$")),
        )


if __name__ == "__main__":
    unittest.main()
