#!/usr/bin/env python3
"""`post_layout_common.translate_extracted_netlist()` -- resistor card
dialect coverage across klt versions (issue #540).

`klt extract --parasitics` has now written the SAME `res_high_po` device
three different ways, and the shared translator has to recognise every shape
that a COMMITTED snapshot under `sim/*/parasitics-snapshot/` actually uses:

  * klt 0.5.0 (and 0.2.0):  `R$n <a> <b> <bulk> <value> res_high_po [L=.. W=..]`
    -- what `sim/startup-time-post-layout/`'s committed snapshot carries (the
    only 0.5.0 consumer left: issue #560 re-ran the other five onto the 0.8.0
    extraction on 2026-11-15; startup-time resolves its own local snapshot at
    step 1 and is disclosed in its README, not moved).
  * klt 0.8.0 (issue #540): `X$n <a> <b> <bulk> res_high_po r=<value> [L=.. W=..]`
    -- what `sim/output-voltage-tc-post-layout/`'s snapshot carries, and what
    the five re-run benches' snapshots resolve to since issue #560.
  * klt 0.8.0 with `--pdk` (issue #614): the device comes out already BOUND
    to the PDK subcircuit, `X$n <a> <b> <bulk> sky130_fd_pr__res_high_po
    l=5 w=1`, and is passed through unchanged (no fixed-value rewrite) --
    what the `20260923-070209-dbd57a9-pdk` snapshot carries and what the
    post-layout path resolves since #614. `PdkBoundDialects` below covers it.

All are live simultaneously: `SNAPSHOT_050`, `SNAPSHOT_080` and
`SNAPSHOT_PDK` below all resolve under the snapshot resolution, so a
regression on any dialect silently zeroes that bench's resistor coverage.
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

# The PDK-BOUND dialect (issue #614): `klt extract --parasitics --pdk sky130A`
# writes each device already bound to its PDK subcircuit. Cards below are
# copied verbatim out of the committed bound snapshot for the same layout
# record -- same devices, now temperature-behaved vendor models instead of
# hand-written fixed cards.
RES_CARD_BOUND = r"X$98 VOUT__t0 \$7__t0 VSS__t24 sky130_fd_pr__res_high_po l=5 w=1"
PNP_CARD_BOUND_SMALL = r"X$74 VSS__t0 VSS__t188 VA__t0 sky130_fd_pr__pnp_05v5_W0p68L0p68"
PNP_CARD_BOUND_LARGE = r"X$82 VSS__t16 VSS__t189 VBQ__t0 sky130_fd_pr__pnp_05v5_W3p40L3p40"
MOS_CARD_BOUND = (
    "X$1 VSS__t190 D1__t5 D1__t10 VSS__t169 sky130_fd_pr__nfet_01v8 "
    "L=20 W=8 AS=3.36 AD=3.36 PS=16.84 PD=16.84"
)
# The bound MOS card is the one class still rewritten: the layout draws no
# `hvi` marker, so klt binds the thin-oxide `_01v8` pair while the design
# instantiates `g5v0d10v5` -- see post_layout_common's `_X_BOUND_RES_RE`
# block comment for the full story.
MOS_CARD_BOUND_TRANSLATED = (
    "X$1 VSS__t190 D1__t5 D1__t10 VSS__t169 sky130_fd_pr__nfet_g5v0d10v5 "
    "L=20 W=8 AS=3.36 AD=3.36 PS=16.84 PD=16.84 "
    "nrd=0.036250 nrs=0.036250 nf=1 mult=1 sa=0 sb=0 sd=0"
)

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
SNAPSHOT_PDK = (
    SIM_DIR
    / "output-voltage-tc-post-layout"
    / "parasitics-snapshot"
    / "20260923-070209-dbd57a9-pdk"
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


class PdkBoundDialects(unittest.TestCase):
    """The `--pdk`-bound card dialect (issue #614): resistors and PNPs pass
    through as the PDK model calls klt wrote (temperature-behaved, bulk
    terminal and geometry intact); only the MOS class is rewritten, to the
    flavour the design actually draws."""

    def test_bound_resistor_passes_through_unchanged(self):
        text, counts = plc.translate_extracted_netlist(RES_CARD_BOUND + "\n")
        self.assertEqual(counts, {"mos": 0, "pnp": 0, "res": 1})
        self.assertIn(RES_CARD_BOUND, text)
        self.assertNotIn("R$98 ", text)  # no fixed-value card standing in

    def test_bound_pnp_passes_through_unchanged(self):
        for card in (PNP_CARD_BOUND_SMALL, PNP_CARD_BOUND_LARGE):
            text, counts = plc.translate_extracted_netlist(card + "\n")
            self.assertEqual(counts["pnp"], 1)
            self.assertIn(card, text)

    def test_bound_mos_is_rewritten_to_the_designs_flavour(self):
        text, counts = plc.translate_extracted_netlist(MOS_CARD_BOUND + "\n")
        self.assertEqual(counts["mos"], 1)
        self.assertIn(MOS_CARD_BOUND_TRANSLATED, text)
        self.assertNotIn("_01v8", text)

    def test_bound_pfet_too(self):
        card = (
            "X$40 VA__t1 VB__t2 GDRV__t1 VDD__t3 sky130_fd_pr__pfet_01v8 "
            "L=10 W=20 AS=8.4"
        )
        text, counts = plc.translate_extracted_netlist(card + "\n")
        self.assertEqual(counts["mos"], 1)
        self.assertIn("sky130_fd_pr__pfet_g5v0d10v5", text)
        self.assertIn("nrd=0.014500 nrs=0.014500", text)  # 0.29 / W=20

    def test_bound_mos_unit_suffixes_are_stripped(self):
        card = (
            "X$1 a b c d sky130_fd_pr__nfet_01v8 L=20U W=8U AS=3.36P"
        )
        text, counts = plc.translate_extracted_netlist(card + "\n")
        self.assertEqual(counts["mos"], 1)
        self.assertIn("L=20 W=8 AS=3.36", text)

    def test_bound_dialect_is_mutually_exclusive_with_legacy(self):
        """Neither the legacy resistor patterns nor the bound patterns may
        claim the other dialect's card, or a snapshot would double-count and
        trip the coverage guard."""
        self.assertIsNone(plc._R_RE.match(RES_CARD_BOUND))
        self.assertIsNone(plc._R_SUBCKT_RE.match(RES_CARD_BOUND))
        self.assertIsNone(plc._X_BOUND_RES_RE.match(R_CARD_080))
        self.assertIsNone(plc._X_BOUND_RES_RE.match(R_CARD_050))
        # A subckt call whose model merely CONTAINS the class name (the legacy
        # `res_high_po r=` shape vs the bound `sky130_fd_pr__res_high_po l=`)
        # must not cross-match either way.
        self.assertIsNone(plc._M_RE.match(MOS_CARD_BOUND))
        self.assertIsNone(plc._X_BOUND_M_RE.match("M$1 a b c d nfet L=20U W=8U"))

    def test_unknown_bound_pnp_macro_is_left_alone(self):
        """The bound PNP pattern whitelists the two macros this design draws;
        any other macro must fall through (and trip the coverage guard at run
        time) rather than pass an unknown subckt silently."""
        card = "X$9 a b c sky130_fd_pr__pnp_05v5_W5p00L5p00"
        text, counts = plc.translate_extracted_netlist(card + "\n")
        self.assertEqual(counts["pnp"], 0)
        self.assertIn(card, text)

    def test_committed_bound_snapshot_translates_at_full_coverage(self):
        """The committed bound snapshot must translate every device its own
        JSON summary declares, with the PDK binding recorded in provenance."""
        import json

        self.assertTrue(SNAPSHOT_PDK.is_file(), f"missing snapshot {SNAPSHOT_PDK}")
        summary = json.loads(
            SNAPSHOT_PDK.with_name("bandgap_core_routed.pex.json").read_text()
        )
        self.assertEqual(summary["provenance"]["klt_version"], "0.8.0")
        self.assertEqual(summary["provenance"]["pdk"]["name"], "sky130A")
        declared = summary["device_counts"]
        text, counts = plc.translate_extracted_netlist(SNAPSHOT_PDK.read_text())
        self.assertEqual(
            (counts["mos"], counts["pnp"], counts["res"]),
            (
                declared.get("nfet", 0) + declared.get("pfet", 0),
                declared.get("pnp", 0),
                declared.get("res_high_po", 0),
            ),
        )

    def test_committed_bound_snapshot_emits_no_fixed_resistor_card(self):
        """Issue #614's acceptance: the simulated extracted netlist contains
        no fixed-value `R` card standing in for a `res_high_po` device, and
        keeps all 145 bound cards."""
        text, counts = plc.translate_extracted_netlist(SNAPSHOT_PDK.read_text())
        self.assertEqual(counts["res"], 145)
        self.assertEqual(
            [l for l in text.splitlines() if l.startswith("R$")],
            [],
        )
        self.assertEqual(
            sum("sky130_fd_pr__res_high_po" in l for l in text.splitlines()),
            145,
        )

    def test_bound_snapshot_keeps_the_same_parasitic_network(self):
        """Binding changes only the DEVICE cards: the bound snapshot's plain
        parasitic `R`/`C` cards must be identical to the unbound 0.8.0
        snapshot's (same layout record, same klt version)."""
        def parasitic_lines(path):
            return [
                l
                for l in path.read_text().splitlines()
                if l.startswith(("R", "C")) and "$" not in l.split()[0]
            ]

        self.assertEqual(
            parasitic_lines(SNAPSHOT_PDK), parasitic_lines(SNAPSHOT_080)
        )


if __name__ == "__main__":
    unittest.main()
