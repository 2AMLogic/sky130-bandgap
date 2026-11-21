#!/usr/bin/env python3
"""Direct coverage for the shared resistor-chain substitution loop
(`sim_common.substitute_chained_arrays`).

The loop is the single replacement engine behind the resistor-array resize
bench and the head-resistance bench (via the `substitute_arrays()` sizing
entry point and explicit segment lists respectively). Until now every
consolidation step was validated by a transient old-vs-new byte comparison
at review time; this module is the committed regression (#624).

Pinned:

  * The full ordered output for a synthetic body: each `XR1`/`XR2A`/`XR2B`
    card becomes the `chain_lines()` expansion at the given segment lists,
    non-target lines pass through unchanged and in order (whitespace
    included). The input cards are literals, not `TARGET_LINES` lookups, so
    drift in `TARGET_LINES` itself trips the missing-card diagnostic here.
  * Both diagnostics: a duplicated card names that card; a removed card
    names the card and the `base_snapshot` the caller passed.
  * `substitute_arrays()` delegates to `substitute_chained_arrays()`: the
    sizing wrapper and the equivalent explicit segment lists produce the
    same output on the committed core-body snapshot the benches reuse.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIM_DIR / "bin"))

import sim_common  # noqa: E402

# The typed exception the loop raises: `_cr()` is the same idempotent module
# load the loop itself uses, so this is the identical class object.
HarnessError = sim_common._cr().HarnessError

# The committed core-body snapshot the benches substitute into -- the real
# input for the wrapper-vs-explicit equivalence check, so the test cannot
# agree with itself about what a base body contains.
BASE_SNAPSHOT = (
    SIM_DIR / "trim-range-monotonicity" / "netlist-snapshots"
    / "20260803-170704-b976d0f.spice"
)

# The diagnostics only echo the path, so a nonexistent one suffices for the
# synthetic bodies.
SYNTHETIC_SNAPSHOT = Path("synthetic/base.spice")

# Literal copies of TARGET_LINES' cards: if TARGET_LINES drifts, these
# literals stop matching and the substitution raises below.
XR2A_CARD = (
    "XR2A VA VOUT VSS sky130_fd_pr__res_high_po W='r_w' "
    "L='r_lseg*n_r2+r_lseg_trim*n_r2_trim' mult=1 m=1"
)
XR2B_CARD = (
    "XR2B VB VOUT VSS sky130_fd_pr__res_high_po W='r_w' "
    "L='r_lseg*n_r2+r_lseg_trim*n_r2_trim' mult=1 m=1"
)
XR1_CARD = "XR1 VBQ VB VSS sky130_fd_pr__res_high_po W='r_w' L='r_lseg*n_r1' mult=1 m=1"

R1_SEG = [5.0, 2.5]
R2_SEG = [5.0, 1.0, 1.0, 0.5]

XQ1_LINE = (
    "XQ1 VSS VSS VA sky130_fd_pr__pnp_05v5_W0p68L0p68 m='n_pnp_ctat' "
    "mult='n_pnp_ctat'"
)
# Leading whitespace must survive substitution untouched.
XQ2_LINE = (
    "  XQ2 VSS VSS VBQ sky130_fd_pr__pnp_05v5_W3p40L3p40 m='n_pnp_ptat' "
    "mult='n_pnp_ptat'"
)

SYNTHETIC_BODY = [
    "* bespoke chained-array body",
    XR2A_CARD,
    XQ1_LINE,
    XR2B_CARD,
    XR1_CARD,
    XQ2_LINE,
]

# The chain_lines() expansions the cards above must become -- written out,
# not computed, so a change to chain_lines()'s emitted line shape fails here.
R2A_CHAIN = [
    "XR2A_0 VA R2A_n1 VSS sky130_fd_pr__res_high_po W=1.0 L=5.0 mult=1 m=1",
    "XR2A_1 R2A_n1 R2A_n2 VSS sky130_fd_pr__res_high_po W=1.0 L=1.0 mult=1 m=1",
    "XR2A_2 R2A_n2 R2A_n3 VSS sky130_fd_pr__res_high_po W=1.0 L=1.0 mult=1 m=1",
    "XR2A_3 R2A_n3 VOUT VSS sky130_fd_pr__res_high_po W=1.0 L=0.5 mult=1 m=1",
]
R2B_CHAIN = [
    "XR2B_0 VB R2B_n1 VSS sky130_fd_pr__res_high_po W=1.0 L=5.0 mult=1 m=1",
    "XR2B_1 R2B_n1 R2B_n2 VSS sky130_fd_pr__res_high_po W=1.0 L=1.0 mult=1 m=1",
    "XR2B_2 R2B_n2 R2B_n3 VSS sky130_fd_pr__res_high_po W=1.0 L=1.0 mult=1 m=1",
    "XR2B_3 R2B_n3 VOUT VSS sky130_fd_pr__res_high_po W=1.0 L=0.5 mult=1 m=1",
]
R1_CHAIN = [
    "XR1_0 VBQ R1_n1 VSS sky130_fd_pr__res_high_po W=1.0 L=5.0 mult=1 m=1",
    "XR1_1 R1_n1 VB VSS sky130_fd_pr__res_high_po W=1.0 L=2.5 mult=1 m=1",
]

EXPECTED_SUBSTITUTED = [
    "* bespoke chained-array body",
    *R2A_CHAIN,
    XQ1_LINE,
    *R2B_CHAIN,
    *R1_CHAIN,
    XQ2_LINE,
]


class OrderingAndPassThrough(unittest.TestCase):
    def test_full_ordered_output_for_synthetic_body(self):
        out = sim_common.substitute_chained_arrays(
            SYNTHETIC_BODY, R1_SEG, R2_SEG, base_snapshot=SYNTHETIC_SNAPSHOT
        )
        self.assertEqual(out, EXPECTED_SUBSTITUTED)


class DuplicateCardDiagnostics(unittest.TestCase):
    def test_duplicate_card_raises_naming_that_card(self):
        for card in (XR2A_CARD, XR2B_CARD, XR1_CARD):
            name = card.split()[0]
            with self.subTest(card=name):
                body = list(SYNTHETIC_BODY)
                body.insert(body.index(card) + 1, card)
                with self.assertRaises(HarnessError) as ctx:
                    sim_common.substitute_chained_arrays(
                        body, R1_SEG, R2_SEG, base_snapshot=SYNTHETIC_SNAPSHOT
                    )
                self.assertIn(name, str(ctx.exception))
                self.assertIn("more than once", str(ctx.exception))


class MissingCardDiagnostics(unittest.TestCase):
    def test_missing_card_raises_naming_card_and_snapshot(self):
        for card in (XR2A_CARD, XR2B_CARD, XR1_CARD):
            name = card.split()[0]
            with self.subTest(card=name):
                body = [line for line in SYNTHETIC_BODY if line != card]
                with self.assertRaises(HarnessError) as ctx:
                    sim_common.substitute_chained_arrays(
                        body, R1_SEG, R2_SEG, base_snapshot=SYNTHETIC_SNAPSHOT
                    )
                self.assertIn(name, str(ctx.exception))
                self.assertIn(str(SYNTHETIC_SNAPSHOT), str(ctx.exception))


class SizingWrapperDelegation(unittest.TestCase):
    def test_substitute_arrays_equals_explicit_segments_on_committed_snapshot(self):
        # The benches' own read path (strips the trailing `.end`); the
        # `.param` drift guard is load_base_body's concern, not this loop's.
        body = sim_common.load_base_body(BASE_SNAPSHOT, set())
        sized = sim_common.substitute_arrays(
            body, 7, 51, -1, 0.5, base_snapshot=BASE_SNAPSHOT
        )
        explicit = sim_common.substitute_chained_arrays(
            body,
            sim_common.r1_segments_um(7, 5.0),
            sim_common.r2_segments_um(51, -1, 0.5),
            base_snapshot=BASE_SNAPSHOT,
        )
        self.assertEqual(sized, explicit)
        # Non-vacuous: the single-device cards really were replaced.
        self.assertNotEqual(sized, body)
        for card in (XR2A_CARD, XR2B_CARD, XR1_CARD):
            self.assertNotIn(card, sized)


if __name__ == "__main__":
    unittest.main()
