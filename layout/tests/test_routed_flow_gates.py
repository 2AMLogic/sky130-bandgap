#!/usr/bin/env python3
"""Unit coverage for the routed-flow's own gates (issue #62).

`layout/bin/run-bandgap-routed-flow.sh` decides pass/fail on three checks
that no external tool performs for it:

1. **The drawn-short check** -- `met1_bus.Met1Bus.conflicts()`. Every met1
   rectangle the flow hand-draws carries the electrical node it belongs to,
   so two nodes' wires touching is detectable here. It has to be: a drawn
   short reads as *connectivity* to `klt extract`, i.e. as a better LVS
   result, which is precisely the false evidence this repo's "verification
   is the product" rule exists to prevent.
2. **The label-collision check** -- `gen_bandgap_routed.assert_no_merged_pin_names()`.
   A `pins[]` label is drawn on a pad; a label landing on a pad some other
   node's metal already contacts renames *that* node, and `klt extract`
   silently emits the result as a single `A|B` net
   (2AMLogic/klayout-tools#470, open). Invisible to DRC and to check 1 --
   the shapes are legal and well separated, it is the labels that collide.
3. **The coverage-scoring check** -- `gen_bandgap_routed.schematic_net_coverage()`.
   Scores acceptance criterion 1 against `design/bandgap_core.sch`'s own
   inter-block node list rather than against the flow's own `connectivity[]`
   declaration, so a net the flow simply forgot to declare still shows up as
   a miss. It also drives the router's ordering search, so a scoring bug
   silently changes which layout gets drawn.

Until now all three were exercised only end-to-end, by a flow run that needs
a `klt` install and a ~1 GB PDK and takes minutes -- so their *failure*
paths (the ones that matter) were never exercised at all, because a passing
run by construction never reaches them. These tests exercise both paths in
milliseconds with no PDK, and are wired into `npm run check:ci`.

Standard library only (`unittest`), matching every other script under
`layout/`. Run directly, or via:

    npm run test:unit
    python3 -m unittest discover --start-directory layout/tests
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "layout" / "bin"))

import gen_bandgap_routed  # noqa: E402  -- resolved from layout/bin, above
import met1_bus  # noqa: E402


# ---------------------------------------------------------------------------
# Gate 1: the drawn-short check (met1_bus.Met1Bus.conflicts)
# ---------------------------------------------------------------------------
class TestDrawnShortGate(unittest.TestCase):
    """`conflicts()` must report every different-net met1 pair that touches,
    overlaps, or violates the sky130 deck's `met1.space.1` (0.14 um) spacing
    -- and must report nothing for same-net geometry, which is what a bus is
    made of.
    """

    #: Two horizontal met1 wires WIRE_WIDTH_UM apart in y have a metal-to-metal
    #: gap of (dy - WIRE_WIDTH_UM), so these two y offsets bracket the 0.14 um
    #: `met1.space.1` threshold exactly.
    Y_AT_THRESHOLD = met1_bus.WIRE_WIDTH_UM + 0.14  # 0.38 -> gap exactly 0.14
    Y_INSIDE_THRESHOLD = met1_bus.WIRE_WIDTH_UM + 0.12  # 0.36 -> gap 0.12

    def test_same_net_overlap_is_not_a_conflict(self) -> None:
        """A bus is overlapping same-net metal by construction: every elbow's
        two segments share a corner, and every via's landing pad sits under
        the wire that reaches it. If those registered, the gate would fire on
        every real run and be useless."""
        bus = met1_bus.Met1Bus()
        bus.net("VSS")
        bus.elbow(0.0, 0.0, 5.0, 5.0)
        bus.via(0.0, 0.0)
        bus.via(5.0, 5.0)
        bus.hseg(0.0, 5.0, 0.0)  # deliberately retraced over the elbow's leg
        self.assertEqual(bus.conflicts(), [])

    def test_different_net_overlap_is_a_conflict(self) -> None:
        """The core case: two electrical nodes' wires crossing. `klt extract`
        would report this as one net -- i.e. as connectivity the schematic
        does not contain."""
        bus = met1_bus.Met1Bus()
        bus.net("VDD").hseg(0.0, 10.0, 0.0)
        bus.net("VSS").vseg(5.0, -10.0, 10.0)
        found = bus.conflicts()
        self.assertEqual(len(found), 1)
        self.assertEqual(sorted(found[0]["nets"]), ["VDD", "VSS"])
        # Rectangle conflicts carry both offending rectangles, so a failing
        # run can be debugged from the JSON alone.
        self.assertIn("a", found[0])
        self.assertIn("b", found[0])

    def test_different_net_spacing_at_the_deck_threshold_is_clean(self) -> None:
        """Exactly `met1.space.1` apart is legal. The check's 1e-9 epsilon
        exists so float noise in a derived coordinate cannot turn a legal
        wire pair into a spurious flow failure."""
        bus = met1_bus.Met1Bus()
        bus.net("VDD").hseg(0.0, 10.0, 0.0)
        bus.net("VSS").hseg(0.0, 10.0, self.Y_AT_THRESHOLD)
        self.assertEqual(bus.conflicts(), [])

    def test_different_net_spacing_inside_the_deck_threshold_is_a_conflict(self) -> None:
        """Closer than `met1.space.1` but not touching. This is the case DRC
        would also catch -- the gate agreeing with the deck here is what makes
        its verdict on the cases DRC does *not* model trustworthy."""
        bus = met1_bus.Met1Bus()
        bus.net("VDD").hseg(0.0, 10.0, 0.0)
        bus.net("VSS").hseg(0.0, 10.0, self.Y_INSIDE_THRESHOLD)
        self.assertEqual(len(bus.conflicts()), 1)

    def test_clearance_is_a_parameter_not_a_constant(self) -> None:
        """A future deck (or a future sky130 revision) can raise the spacing
        rule; the gate takes it as an argument rather than baking 0.14 in."""
        bus = met1_bus.Met1Bus()
        bus.net("VDD").hseg(0.0, 10.0, 0.0)
        bus.net("VSS").hseg(0.0, 10.0, self.Y_AT_THRESHOLD)
        self.assertEqual(bus.conflicts(), [])
        self.assertEqual(len(bus.conflicts(clearance_um=0.20)), 1)

    def test_via_spacing_between_different_nets_is_checked_separately(self) -> None:
        """`mcon.space.1` (0.19 um) is a stricter, separate rule from met1
        spacing, so vias get their own pass. Two mcons that close are very
        nearly a short even when the metal above them is legal."""
        bus = met1_bus.Met1Bus()
        bus.net("VDD").via(0.0, 0.0)
        bus.net("VSS").via(0.30, 0.0)
        via_conflicts = [c for c in bus.conflicts() if "via_a" in c]
        self.assertEqual(len(via_conflicts), 1)
        self.assertEqual(sorted(via_conflicts[0]["nets"]), ["VDD", "VSS"])

    def test_well_separated_vias_of_different_nets_are_clean(self) -> None:
        """Both the via rule and the landing pads' met1 spacing have to clear.
        A landing pad is LANDING_UM wide, so pad spacing is the binding
        constraint at 0.24 + 0.14 = 0.38 um centre-to-centre."""
        bus = met1_bus.Met1Bus()
        bus.net("VDD").via(0.0, 0.0)
        bus.net("VSS").via(met1_bus.LANDING_UM + 0.14, 0.0)
        self.assertEqual(bus.conflicts(), [])

    def test_repeated_via_at_one_position_is_drawn_once(self) -> None:
        """Two coincident mcons are one via drawn twice -- and would trip the
        deck's own `mcon.space.1` rule as a zero-spacing pair. The bus
        de-duplicates so a bus routine may contact a pad unconditionally."""
        bus = met1_bus.Met1Bus()
        bus.net("VSS").via(1.0, 2.0)
        bus.net("VSS").via(1.0, 2.0)
        self.assertEqual(bus.via_count, 1)
        self.assertEqual(bus.conflicts(), [])

    def test_zero_length_segments_draw_nothing(self) -> None:
        """A degenerate segment is a geometry-derived no-op (two ports at the
        same coordinate), not a zero-area rectangle for the checker to reason
        about."""
        bus = met1_bus.Met1Bus()
        bus.net("VSS")
        bus.hseg(3.0, 3.0, 0.0)
        bus.vseg(0.0, 3.0, 3.0)
        self.assertEqual(bus.wire_count, 0)
        self.assertEqual(bus.shapes, [])

    def test_conflicts_reports_every_offending_pair(self) -> None:
        """Not just the first. The flow prints the count into record.md, and
        "1 conflict" vs "3 conflicts" is the difference between a stray wire
        and a systematically mis-planned net."""
        bus = met1_bus.Met1Bus()
        bus.net("VDD").hseg(0.0, 10.0, 0.0)
        bus.net("VSS").vseg(2.0, -5.0, 5.0)
        bus.net("VOUT").vseg(6.0, -5.0, 5.0)
        found = bus.conflicts()
        self.assertEqual(len(found), 2)
        self.assertEqual(
            sorted(sorted(c["nets"]) for c in found),
            [["VDD", "VOUT"], ["VDD", "VSS"]],
        )


class TestBusSpeculation(unittest.TestCase):
    """`mark()`/`restore()` is what lets the router *try* a whole multi-hop net
    against real drawn geometry and take it back when it does not route. If a
    rejected attempt left anything behind, the drawn-short gate would be
    checking geometry that is not in the emitted layout -- either failing the
    flow over a wire nobody drew, or (worse) passing it while the emitted
    cell holds shapes the checker never saw.
    """

    def test_restore_undoes_every_accumulator(self) -> None:
        bus = met1_bus.Met1Bus()
        bus.net("VSS").hseg(0.0, 5.0, 0.0)
        bus.via(0.0, 0.0)
        bus.label("VSS", 0.0, 0.0)
        before = (
            list(bus.shapes),
            list(bus.met1_rects),
            list(bus.via_xy),
            list(bus.labels),
            bus.via_count,
            bus.wire_count,
        )

        mark = bus.mark()
        bus.net("VDD").hseg(0.0, 5.0, 0.0)  # a drawn short, if kept
        bus.via(0.0, 0.0)
        bus.label("VDD", 0.0, 0.0)
        self.assertNotEqual(bus.conflicts(), [])

        bus.restore(mark)
        self.assertEqual(
            (
                bus.shapes,
                bus.met1_rects,
                bus.via_xy,
                bus.labels,
                bus.via_count,
                bus.wire_count,
            ),
            before,
        )
        self.assertEqual(bus.conflicts(), [])

    def test_restore_releases_the_via_dedup_key(self) -> None:
        """A speculative via that was rolled back must be re-drawable. The
        de-dup set is keyed on (net, x, y), so forgetting to discard it on
        restore would silently drop the via when the same net is retried in a
        different order -- an open circuit that no gate would report."""
        bus = met1_bus.Met1Bus()
        mark = bus.mark()
        bus.net("VSS").via(1.0, 2.0)
        self.assertEqual(bus.via_count, 1)
        bus.restore(mark)
        self.assertEqual(bus.via_count, 0)
        bus.net("VSS").via(1.0, 2.0)
        self.assertEqual(bus.via_count, 1)


# ---------------------------------------------------------------------------
# Gate 2: the label-collision check (assert_no_merged_pin_names)
# ---------------------------------------------------------------------------
class TestLabelCollisionGate(unittest.TestCase):
    """`assert_no_merged_pin_names()` returns the offending `A|B` names;
    empty is the only acceptable result.
    """

    def _check(self, netlist_text: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cell.extract.spice"
            path.write_text(netlist_text)
            return gen_bandgap_routed.assert_no_merged_pin_names(path)

    CLEAN_NETLIST = """* extracted by klt extract --deck sky130

* cell bandgap_core_routed
* pin VDD
* pin VSS
* pin VOUT
.subckt bandgap_core_routed VDD VSS VOUT
  Q$1 (C=VSS,B=VSS,E=VA) PNP
  R$1 (A=VOUT,B=TRIM_A) RES_GENERIC_PO
  M$1 (S=VDD,G=GDRV,D=VOUT,B=VDD) PFET
.ends
"""

    def test_clean_netlist_passes(self) -> None:
        self.assertEqual(self._check(self.CLEAN_NETLIST), [])

    def test_merged_net_name_is_reported(self) -> None:
        """KLayout's notation for "two labels, one net". The layout is
        asserting an equality between two schematic nodes that the schematic
        does not contain."""
        netlist = self.CLEAN_NETLIST.replace("D=VOUT", "D=TAIL|VOUT")
        self.assertEqual(self._check(netlist), ["TAIL|VOUT"])

    def test_every_distinct_merged_name_is_reported_once_and_sorted(self) -> None:
        """A pin selector that shares no state with the router produces these
        in batches, not singly -- the record has to list all of them, and a
        name repeated on N device terminals is still one defect."""
        netlist = self.CLEAN_NETLIST.replace("E=VA", "E=TRIM_A_CODE_MINUS16|VA")
        netlist = netlist.replace("A=VOUT,B=TRIM_A", "A=TAIL|VOUT,B=TRIM_A")
        netlist = netlist.replace("D=VOUT", "D=TAIL|VOUT")
        self.assertEqual(
            self._check(netlist), ["TAIL|VOUT", "TRIM_A_CODE_MINUS16|VA"]
        )

    def test_klayout_dollar_named_nets_are_scanned_too(self) -> None:
        """Unlabelled nets come back as `$N`. One label landing on an
        otherwise-unnamed net still merges, and the token has to be caught
        even though it does not start with a letter."""
        netlist = self.CLEAN_NETLIST.replace("G=GDRV", "G=$3|GDRV")
        self.assertEqual(self._check(netlist), ["$3|GDRV"])

    # -- regression corpus: the flow's own append-only evidence -------------
    # These read the checked-in records rather than a synthetic fixture, so
    # the gate is pinned against the exact netlists it was written to judge.
    def test_flags_the_historical_collision_the_gate_was_written_for(self) -> None:
        """Record `20260804-012421-1a97bf5` is the run whose `VOUT` label
        landed on `core_mirror.M2_1_D` -- MPAMP's drain, the pad the drawn
        `TAIL` net already contacted -- because the pin selector and the
        router kept separate "already used" sets (see `routed_ports`'s
        docstring). The trim-tap labels collided the same way. This is the
        real defect, from the real evidence trail, not an invented one."""
        netlist = (
            REPO_ROOT
            / "layout/bandgap-core/reports/20260804-012421-1a97bf5"
            / "bandgap_core_routed.extract.spice"
        )
        self.assertEqual(
            gen_bandgap_routed.assert_no_merged_pin_names(netlist),
            ["TAIL|VOUT", "TRIM_A_CODE_MINUS16|VA", "TRIM_B_CODE_MINUS16|VB"],
        )

    def test_passes_the_current_record(self) -> None:
        """And the fix holds: the record `LATEST` points at is clean. A future
        increment that reintroduces the shared-pad bug fails here without
        needing a `klt` install to notice."""
        reports = REPO_ROOT / "layout/bandgap-core/reports"
        latest = reports / (reports / "LATEST").read_text().strip()
        netlist = latest / "bandgap_core_routed.extract.spice"
        self.assertTrue(netlist.is_file(), f"no extracted netlist in {latest}")
        self.assertEqual(gen_bandgap_routed.assert_no_merged_pin_names(netlist), [])


class TestRoutedPortClaims(unittest.TestCase):
    """`routed_ports()` is the *prevention* half of the label-collision gate:
    the set of pads the drawn metal already owns, which the pin selector must
    not label. The gate above catches the failure after extraction; this is
    what stops it being drawn in the first place.
    """

    def test_claims_every_terminal_of_every_route(self) -> None:
        summary = {
            "_inter_block": [
                {"net": "TAIL", "terminals": ["core_mirror.M2_1_D", "amp_input_pair.M1_S"]},
                {"net": "VSS", "terminals": ["amp_nload.M1_S"]},
            ]
        }
        self.assertEqual(
            gen_bandgap_routed.routed_ports(summary),
            {
                ("core_mirror", "M2_1_D"),
                ("amp_input_pair", "M1_S"),
                ("amp_nload", "M1_S"),
            },
        )

    def test_ignores_terminals_with_no_port_part(self) -> None:
        """A bare block id claims nothing -- claiming the whole block would
        starve the pin selector of every pad on it."""
        summary = {"_inter_block": [{"net": "VSS", "terminals": ["amp_nload"]}]}
        self.assertEqual(gen_bandgap_routed.routed_ports(summary), set())

    def test_empty_summary_claims_nothing(self) -> None:
        self.assertEqual(gen_bandgap_routed.routed_ports({}), set())


# ---------------------------------------------------------------------------
# Gate 3: the coverage-scoring check (schematic_net_coverage)
# ---------------------------------------------------------------------------
class TestCoverageScoringGate(unittest.TestCase):
    """`schematic_net_coverage()` scores acceptance criterion 1. It must never
    credit a node with connectivity that is not drawn -- that would turn the
    scoreboard from evidence into a claim.
    """

    def _row(self, routes: list[dict], net: str) -> dict:
        rows = gen_bandgap_routed.schematic_net_coverage(routes)
        self.assertEqual(
            len(rows),
            len(gen_bandgap_routed.SCHEMATIC_INTER_BLOCK_NETS),
            "every schematic inter-block node must be scored, drawn or not",
        )
        return next(row for row in rows if row["net"] == net)

    def test_no_routes_means_no_credit_anywhere(self) -> None:
        """The floorplan-skeleton baseline: a layout with zero drawn metal
        must score zero, with every block listed as missing."""
        rows = gen_bandgap_routed.schematic_net_coverage([])
        self.assertTrue(all(row["status"] == "labelled only" for row in rows))
        for row in rows:
            self.assertEqual(row["joined"], [])
            self.assertEqual(row["missing"], sorted(row["blocks"]))

    def test_two_block_net_joined_end_to_end_is_drawn(self) -> None:
        routes = [
            {
                "net": "VBQ",
                "hops": [{"from": "res_r1.R53_B", "to": "pnp_ptat.Q4_E", "routed": True}],
            }
        ]
        row = self._row(routes, "VBQ")
        self.assertEqual(row["status"], "drawn")
        self.assertEqual(row["missing"], [])

    def test_an_unrouted_hop_earns_nothing(self) -> None:
        """The hop is declared and its endpoints are known, but no metal was
        drawn. Scoring the declaration rather than the geometry is exactly the
        failure this function exists to avoid.

        `status` is the authoritative field, and only it is asserted here: an
        unrouted hop leaves each endpoint as its own single-block component,
        so the cosmetic `joined`/`missing` split of a "labelled only" row can
        still name one endpoint block. No connectivity is credited either
        way -- a status below "partial" is the statement that nothing is
        joined."""
        routes = [
            {
                "net": "VBQ",
                "hops": [
                    {"from": "res_r1.R53_B", "to": "pnp_ptat.Q4_E", "routed": False}
                ],
            }
        ]
        row = self._row(routes, "VBQ")
        self.assertEqual(row["status"], "labelled only")
        self.assertLess(len(row["joined"]), 2)

    def test_chained_hops_through_a_shared_endpoint_join_into_one_node(self) -> None:
        """A three-block node is drawn as two hops meeting on one pad. The
        union-find over hop endpoints is what recognises them as one piece of
        metal rather than two disconnected pairs."""
        routes = [
            {
                "net": "VA",
                "hops": [
                    {"from": "pnp_ctat.Q0_E", "to": "res_trim.R0_B", "routed": True},
                    {
                        "from": "res_trim.R0_B",
                        "to": "amp_input_pair.M2_1_G",
                        "routed": True,
                    },
                ],
            }
        ]
        row = self._row(routes, "VA")
        self.assertEqual(row["status"], "drawn")

    def test_a_chain_broken_in_the_middle_scores_partial(self) -> None:
        """Criterion 1 is PARTIAL while any node is short. The blocker here is
        the MOS gate-contact gap (klayout-tools#461): the metal reaches the
        trim taps but cannot land on the amp's input gate."""
        routes = [
            {
                "net": "VA",
                "hops": [
                    {"from": "pnp_ctat.Q0_E", "to": "res_trim.R0_B", "routed": True},
                    {
                        "from": "res_trim.R0_B",
                        "to": "amp_input_pair.M2_1_G",
                        "routed": False,
                    },
                ],
            }
        ]
        row = self._row(routes, "VA")
        self.assertEqual(row["status"], "partial")
        self.assertEqual(row["joined"], ["pnp_ctat", "res_trim"])
        self.assertEqual(row["missing"], ["amp_input_pair"])

    def test_disjoint_pieces_are_not_summed(self) -> None:
        """Two separate two-block fragments of the VSS trunk are not a
        four-block node. Only the largest connected component counts --
        summing them would claim a trunk that is drawn as two islands is one
        net, which is the single easiest way to overstate this criterion."""
        routes = [
            {
                "net": "VSS",
                "hops": [
                    {"from": "amp_nload.M1_S", "to": "amp_nmirr.M3_S", "routed": True},
                    {"from": "pnp_ctat.Q0_B", "to": "pnp_ptat.Q0_B", "routed": True},
                ],
            }
        ]
        row = self._row(routes, "VSS")
        self.assertEqual(row["status"], "partial")
        self.assertEqual(len(row["joined"]), 2, row["joined"])
        self.assertEqual(len(row["missing"]), 5)

    def test_separate_pads_on_one_block_do_not_bridge_two_fragments(self) -> None:
        """Two hops landing on *different* pads of the same block are not
        connected: nothing in the layout ties those pads together. The
        endpoint key is the pad, not the block, precisely so this cannot be
        mistaken for a join."""
        routes = [
            {
                "net": "VA",
                "hops": [
                    {"from": "pnp_ctat.Q0_E", "to": "res_trim.R0_B", "routed": True},
                    {
                        "from": "res_trim.R7_A",
                        "to": "amp_input_pair.M2_1_G",
                        "routed": True,
                    },
                ],
            }
        ]
        row = self._row(routes, "VA")
        self.assertEqual(row["status"], "partial")
        self.assertEqual(len(row["joined"]), 2)

    def test_a_node_split_across_two_declared_nets_is_scored_as_one(self) -> None:
        """`TRIM` is one schematic device per leg that the layout splits into
        ladder + DR-002 trim taps, so it is carried by two declared met1 nets
        (`TRIM_A`, `TRIM_B`). Coverage aggregates every hop-net named in the
        schematic table, not just one with a matching name."""
        routes = [
            {
                "net": "TRIM_B",
                "hops": [{"from": "res_r2.R1_B", "to": "res_trim.R1_A", "routed": True}],
            }
        ]
        row = self._row(routes, "TRIM")
        self.assertEqual(row["status"], "drawn")

    def test_blocks_outside_the_schematic_node_earn_no_credit(self) -> None:
        """Routing `VBQ` from R1 to a block the schematic never puts on that
        node is not progress toward the node. `want & have` keeps the score
        measured against `design/bandgap_core.sch`, not against wherever the
        router happened to reach."""
        routes = [
            {
                "net": "VBQ",
                "hops": [{"from": "res_r1.R53_B", "to": "core_mirror.M1_D", "routed": True}],
            }
        ]
        row = self._row(routes, "VBQ")
        self.assertEqual(row["status"], "labelled only")
        self.assertEqual(row["joined"], ["res_r1"])

    def test_block_id_is_parsed_from_either_endpoint_form(self) -> None:
        """Endpoint names appear both as `block.PORT` and, for a bus-internal
        node, as `block:tag.PORT`."""
        routes = [
            {
                "net": "VBQ",
                "hops": [
                    {"from": "res_r1:tail.R53_B", "to": "pnp_ptat:bus.Q4_E", "routed": True}
                ],
            }
        ]
        self.assertEqual(self._row(routes, "VBQ")["status"], "drawn")

    def test_every_scored_net_names_real_blocks(self) -> None:
        """The schematic table is hand-maintained against `BLOCKS`; a renamed
        block would otherwise turn into a permanently-unreachable row that
        quietly caps criterion 1 below 100%."""
        known = {block["id"] for block in gen_bandgap_routed.BLOCKS}
        for spec in gen_bandgap_routed.SCHEMATIC_INTER_BLOCK_NETS:
            for block in spec["blocks"]:
                self.assertIn(block, known, f"{spec['net']} names unknown block {block}")


# ---------------------------------------------------------------------------
# The gate composition itself
# ---------------------------------------------------------------------------
class TestFlowGate(unittest.TestCase):
    """`flow_gate()` is the flow's exit status. Its job is to fail on any one
    condition -- an "and" written as seven separate rows so a failing run can
    name which.
    """

    PASSING = {
        "drc_clean": True,
        "within_budget": True,
        "full_scale_ladder": True,
        "all_classes": True,
        "pin_count": 23,
        "met1_conflicts": [],
        "merged_pin_names": [],
        "poly_conflicts": [],
    }

    def test_all_conditions_met_passes(self) -> None:
        gate = gen_bandgap_routed.flow_gate(**self.PASSING)
        self.assertTrue(all(gate.values()), gate)

    def test_each_condition_can_fail_the_flow_on_its_own(self) -> None:
        """Table-driven so a newly added gate row cannot be left unexercised:
        the failing-value map below is checked for completeness against
        `flow_gate`'s own output keys."""
        failures = {
            "drc_clean": {"drc_clean": False},
            "within_budget": {"within_budget": False},
            "full_scale_ladder": {"full_scale_ladder": False},
            "device_classes_present": {"all_classes": False},
            "pins_promoted": {"pin_count": 0},
            "no_drawn_shorts": {"met1_conflicts": [{"nets": ["VDD", "VSS"]}]},
            "no_merged_pin_names": {"merged_pin_names": ["TAIL|VOUT"]},
            "no_poly_shorts": {
                "poly_conflicts": [{"nets": ["D1", "D2"], "a": [0, 0, 1, 1]}]
            },
        }
        self.assertEqual(
            set(failures), set(gen_bandgap_routed.flow_gate(**self.PASSING)),
            "a gate condition was added or renamed without a failure case here",
        )
        for name, override in failures.items():
            with self.subTest(condition=name):
                gate = gen_bandgap_routed.flow_gate(**{**self.PASSING, **override})
                self.assertFalse(gate[name])
                failed = [key for key, passed in gate.items() if not passed]
                self.assertEqual(failed, [name])

    def test_lvs_and_coverage_are_recorded_but_not_gated(self) -> None:
        """Deliberate, and load-bearing: both are blocked on open upstream
        `klt` gaps (klayout-tools#463 for the resistor bulk terminal; #461's
        gate-contact fix has landed but is not yet picked up by this repo's
        pin). Gating on them would stop the flow producing the very record
        that measures how far short it falls -- and the record's own
        scoreboard, not the exit status, is the evidence."""
        gate = gen_bandgap_routed.flow_gate(**self.PASSING)
        self.assertNotIn("lvs_clean", gate)
        self.assertNotIn("full_connectivity", gate)


if __name__ == "__main__":
    unittest.main()
