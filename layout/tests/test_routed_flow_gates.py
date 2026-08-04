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
        # Whatever VSS's declared block list is, the two islands above credit
        # exactly one of them -- derived from the table rather than a literal,
        # so a future scope change to the node does not silently turn this
        # into a test of nothing.
        declared = len(
            next(
                spec["blocks"]
                for spec in gen_bandgap_routed.SCHEMATIC_INTER_BLOCK_NETS
                if spec["net"] == "VSS"
            )
        )
        self.assertEqual(len(row["missing"]), declared - 2)

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


# ---------------------------------------------------------------------------
# The MOS gate contact + finger-bus geometry (added with the post-#461 pin)
# ---------------------------------------------------------------------------
class TestGateContact(unittest.TestCase):
    """`met1_bus.Met1Bus.gate_contact()` is the stack upstream
    2AMLogic/klayout-tools#461 (merged via #474) made legal: a licon on the
    generator's poly landing pad plus an li1 riser down to a bus track inside
    the device row. It is hand-placed geometry, so its sizing has to hold to
    the deck's own thresholds without a DRC run to catch it.
    """

    def _shapes(self, bus: met1_bus.Met1Bus, layer: list[int]):
        return [s["rect_um"] for s in bus.shapes if s["layer"] == layer]

    def test_draws_a_licon_on_the_pad_and_an_li1_riser_to_the_track(self) -> None:
        bus = met1_bus.Met1Bus()
        bus.net("D1").gate_contact(10.0, 8.21, 4.0)
        licons = self._shapes(bus, met1_bus.LICON_LAYER)
        risers = self._shapes(bus, met1_bus.LI1_LAYER)
        self.assertEqual(len(licons), 1)
        self.assertEqual(len(risers), 1)
        # The licon is centred on the reported gate-port position...
        x0, y0, x1, y1 = licons[0]
        self.assertAlmostEqual((x0 + x1) / 2, 10.0)
        self.assertAlmostEqual((y0 + y1) / 2, 8.21)
        self.assertAlmostEqual(x1 - x0, met1_bus.LICON_UM)
        # ...and the riser spans pad to track, covering it at both ends.
        rx0, ry0, rx1, ry1 = risers[0]
        self.assertLessEqual(ry0, 4.0)
        self.assertGreaterEqual(ry1, 8.21)
        self.assertLessEqual(rx0, x0)
        self.assertGreaterEqual(rx1, x1)

    def test_riser_encloses_both_the_licon_under_it_and_the_mcon_on_it(self) -> None:
        """The riser is the only conductor joining gate poly to the met1
        trunk, so it has to cover the licon below and the mcon above. A riser
        narrower than either would be an open circuit that no gate in this
        flow reports -- `klt drc` models no li1 enclosure of mcon on sky130."""
        self.assertGreaterEqual(met1_bus.GATE_LI1_UM, met1_bus.LICON_UM)
        self.assertGreaterEqual(met1_bus.GATE_LI1_UM, met1_bus.VIA_UM)
        # ...and is at least the deck's own li1 minimum width.
        self.assertGreaterEqual(met1_bus.GATE_LI1_UM, 0.17)

    def test_counts_are_speculation_safe(self) -> None:
        """A gate contact drawn inside a rolled-back routing attempt must
        leave nothing behind -- the same invariant `mark`/`restore` already
        holds for wires and vias."""
        bus = met1_bus.Met1Bus()
        mark = bus.mark()
        bus.net("D1").gate_contact(10.0, 8.21, 4.0)
        self.assertEqual(bus.gate_contact_count, 1)
        bus.restore(mark)
        self.assertEqual(bus.gate_contact_count, 0)
        self.assertEqual(bus.shapes, [])
        self.assertEqual(bus.li1_rects, [])

    def test_two_nodes_risers_too_close_are_a_conflict(self) -> None:
        """li1 is the layer every device pad already lives on, so two gate
        risers of different nodes that come within `li1.space.1` are a short
        exactly as two met1 wires would be. Reported under its own layer key
        so a failing run says which conductor."""
        bus = met1_bus.Met1Bus()
        bus.net("D1").gate_contact(10.0, 8.21, 4.0)
        bus.net("D2").gate_contact(10.0 + met1_bus.GATE_LI1_UM + 0.10, 8.21, 4.0)
        found = [c for c in bus.conflicts() if c.get("layer") == "li1"]
        self.assertEqual(len(found), 1)
        self.assertEqual(sorted(found[0]["nets"]), ["D1", "D2"])

    def test_two_nodes_risers_at_the_deck_threshold_are_clean(self) -> None:
        bus = met1_bus.Met1Bus()
        bus.net("D1").gate_contact(10.0, 8.21, 4.0)
        bus.net("D2").gate_contact(
            10.0 + met1_bus.GATE_LI1_UM + met1_bus.LI1_SPACE_UM, 8.21, 4.0
        )
        self.assertEqual([c for c in bus.conflicts() if c.get("layer") == "li1"], [])


class TestMet1ProximityIndex(unittest.TestCase):
    """`met1_near()` is a pure speed-up of the drawn-short test the router
    runs on every candidate path, so it has to return exactly what a full
    scan would. A stale index would silently hide a drawn short -- the one
    failure mode this whole file exists to make impossible.
    """

    def _brute(self, bus: met1_bus.Met1Bus, box, clearance):
        x0, y0, x1, y1 = box
        return sorted(
            r
            for r in bus.met1_rects
            if x0 - clearance < r[3]
            and r[1] - clearance < x1
            and y0 - clearance < r[4]
            and r[2] - clearance < y1
        )

    def _bus(self) -> met1_bus.Met1Bus:
        bus = met1_bus.Met1Bus()
        for i in range(40):
            bus.net(f"N{i % 5}")
            bus.hseg(i * 1.7, i * 1.7 + 30.0, i * 0.9)
            bus.vseg(i * 2.3, -5.0, 40.0)
            bus.via(i * 3.1, i * 1.3)
        return bus

    def test_matches_a_full_scan(self) -> None:
        bus = self._bus()
        for box in ((0.0, 0.0, 1.0, 1.0), (20.0, 10.0, 21.0, 30.0), (-9.0, -9.0, -8.0, -8.0)):
            self.assertEqual(
                sorted(bus.met1_near(*box, 0.14)),
                self._brute(bus, box, 0.14),
                box,
            )

    def test_truncation_unindexes(self) -> None:
        """`truncate_met1` is how a rolled-back path leaves the index. If it
        left entries behind, every later route would be tested against
        geometry that is not in the emitted layout."""
        bus = self._bus()
        keep = 20
        bus.truncate_met1(keep)
        self.assertEqual(len(bus.met1_rects), keep)
        box = (0.0, -10.0, 60.0, 40.0)
        self.assertEqual(
            sorted(bus.met1_near(*box, 0.14)), self._brute(bus, box, 0.14)
        )


class TestMosCombPlan(unittest.TestCase):
    """The declarative half of the MOS finger bus: every schematic device
    terminal in `BLOCKS`' `mos_comb` specs has to resolve through
    `MOS_HALVES`, and the per-block net set has to be exactly the set of
    schematic nodes that block participates in. A typo here is a topology
    error neither DRC nor the drawn-short check can see -- the same class of
    defect MOS_HALF_NOTE was written for.
    """

    def _combs(self):
        return {
            block["id"]: block["bus"]
            for block in gen_bandgap_routed.BLOCKS
            if block.get("bus", {}).get("kind") == "mos_comb"
        }

    def test_every_terminal_names_a_device_the_half_table_binds(self) -> None:
        for bid, spec in self._combs().items():
            devices = gen_bandgap_routed.MOS_HALVES[bid]["devices"]
            for entry in spec["nets"]:
                for device, terminal in entry["terminals"]:
                    self.assertIn(device, devices, f"{bid}.{device}")
                    self.assertIn(terminal, ("drain", "source", "gate"))

    def test_every_device_terminal_is_assigned_exactly_once(self) -> None:
        """A finger left off the comb is a floating terminal; a finger on two
        combs is a drawn short. Both are silent."""
        for bid, spec in self._combs().items():
            seen: list[tuple[str, str]] = []
            for entry in spec["nets"]:
                seen.extend(tuple(t) for t in entry["terminals"])
            self.assertEqual(len(seen), len(set(seen)), f"{bid}: repeated terminal")
            expected = {
                (device, terminal)
                for device in gen_bandgap_routed.MOS_HALVES[bid]["devices"]
                for terminal in ("drain", "source", "gate")
            }
            self.assertEqual(set(seen), expected, bid)

    def test_every_comb_net_is_a_declared_inter_block_node(self) -> None:
        declared = {spec["net"] for spec in gen_bandgap_routed.INTER_BLOCK_MET1}
        for bid, spec in self._combs().items():
            for entry in spec["nets"]:
                self.assertIn(entry["net"], declared, f"{bid}:{entry['net']}")

    def test_every_inter_block_comb_terminal_exists_in_its_block(self) -> None:
        """The reverse direction: a route asking for a comb point the block
        never built would raise deep inside the router, mid-run."""
        combs = self._combs()
        for spec in gen_bandgap_routed.INTER_BLOCK_MET1:
            for terminal in spec["terminals"]:
                if "comb" not in terminal:
                    continue
                bid, net = terminal["comb"]
                self.assertIn(bid, combs)
                self.assertIn(
                    net, {e["net"] for e in combs[bid]["nets"]}, f"{bid}:{net}"
                )

    def test_the_spine_side_escape_goes_to_the_outermost_node_only(self) -> None:
        """Only the last group in a block's list may escape on the spine
        side -- every inner one is walled in by the outer spines. The order
        is therefore load-bearing, and this asserts the block tables put a
        node whose partners lie on the spine side there."""
        for bid, spec in self._combs().items():
            self.assertIn(spec["spine_side"], ("W", "E"), bid)
            self.assertGreaterEqual(len(spec["nets"]), 2, bid)

    def test_band_index_places_gates_with_their_own_row(self) -> None:
        """A gate port sits above its row's diffusion, below the next row's.
        Getting that wrong would bus a gate onto the *other* device row's
        track -- legal geometry, wrong transistor."""
        bands = [(0.0, 8.0), (8.82, 16.82)]
        self.assertEqual(gen_bandgap_routed._band_index(bands, 4.0), 0)
        self.assertEqual(gen_bandgap_routed._band_index(bands, 8.21), 0)
        self.assertEqual(gen_bandgap_routed._band_index(bands, 12.82), 1)
        self.assertEqual(gen_bandgap_routed._band_index(bands, 17.03), 1)


class TestChannelTracks(unittest.TestCase):
    """`free_channels()` decides where the open-channel router may cross the
    floorplan. It returned a set with no usable track at all in a first cut
    (every survivor of its "fewest blocks crossed" ranking was outside the
    whole cell), which reported six schematic nets unroutable without any
    tool gap behind it -- so the property worth asserting is that the
    placement channels *between* neighbours are represented.
    """

    REPORTS = {
        "a": {"bbox_um": {"x0": 0.0, "y0": 0.0, "x1": 10.0, "y1": 10.0}},
        "b": {"bbox_um": {"x0": 30.0, "y0": 0.0, "x1": 40.0, "y1": 10.0}},
        # Overlaps both in x, as a second-row block does on the real
        # floorplan -- this is what a union-of-spans approach collapses.
        "c": {"bbox_um": {"x0": 5.0, "y0": 40.0, "x1": 38.0, "y1": 50.0}},
    }
    ORIGINS = {k: {"x": 0.0, "y": 0.0} for k in REPORTS}

    def test_the_gap_between_two_neighbours_gets_tracks(self) -> None:
        lanes = gen_bandgap_routed.free_channels(self.REPORTS, self.ORIGINS)
        between = [t for t in lanes["x"] if 10.0 < t < 30.0]
        self.assertTrue(between, lanes["x"])

    def test_tracks_clear_the_comb_escape_stubs(self) -> None:
        """The nearest track to a block edge must sit outside that block's
        own escape fan, or every path through it is rejected on arrival."""
        self.assertGreater(
            gen_bandgap_routed.CHANNEL_TRACK_OFFSET_UM,
            max(gen_bandgap_routed.MOS_ESCAPE_UM),
        )

    def test_a_block_with_no_neighbour_still_gets_outside_tracks(self) -> None:
        lanes = gen_bandgap_routed.free_channels(self.REPORTS, self.ORIGINS)
        self.assertTrue([t for t in lanes["x"] if t < 0.0])
        self.assertTrue([t for t in lanes["x"] if t > 40.0])


# ---------------------------------------------------------------------------
# The open-channel router: _connect / _channel_paths / _chain_orders /
# _candidate_assignments (gen_bandgap_routed.py)
# ---------------------------------------------------------------------------
#
# Every one of these is exercised end-to-end by `run-bandgap-routed-flow.sh`
# on real block geometry, but none of them had unit coverage of their own --
# issue #62's routed record for `20260804-045058-649329e` (9/12 schematic
# nets, `mismatch_count=106`) names "this flow's own hand-written router
# running out of corridors in its own congestion" as the residual gap's
# dominant cause, which makes this exact code the highest-value place left to
# add regression coverage: a search-order or candidate-generation regression
# here would silently change which nodes route, with no DRC or LVS failure to
# catch it (a route that isn't attempted is indistinguishable from one that
# was tried and correctly rejected).
class TestConnectRouter(unittest.TestCase):
    """`_connect()` tries a direct elbow, then a floorplan channel path, then
    Z-detours, until one clears -- see its own docstring. These tests force
    each stage in turn by drawing an obstacle net only the earlier stages
    collide with.
    """

    def test_straight_elbow_succeeds_when_clear(self) -> None:
        bus = met1_bus.Met1Bus()
        result = gen_bandgap_routed._connect(bus, "N1", (0.0, 0.0), (10.0, 5.0))
        self.assertIsNotNone(result)
        self.assertEqual(result["detour_um"], 0.0)
        self.assertEqual(result["points"][0], [0.0, 0.0])
        self.assertEqual(result["points"][-1], [10.0, 5.0])
        # Both elbow segments actually landed on the bus.
        self.assertEqual(len(bus.met1_rects), 2)

    def test_falls_back_to_a_channel_path_when_the_direct_elbow_is_blocked(
        self,
    ) -> None:
        """Both two-segment elbows between (0, 0) and (10, 10) turn at
        (10, 0) or (0, 10) -- blocking a small box at each corner rejects
        both, without touching the interior track a channel path can still
        use."""
        bus = met1_bus.Met1Bus()
        bus.net("WALL")
        bus.hseg(9.85, 10.15, 0.0)
        bus.hseg(-0.15, 0.15, 10.0)
        a, b = (0.0, 0.0), (10.0, 10.0)
        # The direct elbows are provably blocked before the channel fallback
        # is even asked to resolve anything.
        self.assertIsNone(
            gen_bandgap_routed._connect_path(
                bus, "N1", [a, (b[0], a[1]), b]
            )
        )
        self.assertIsNone(
            gen_bandgap_routed._connect_path(
                bus, "N1", [a, (a[0], b[1]), b]
            )
        )
        result = gen_bandgap_routed._connect(
            bus, "N1", a, b, channels={"x": [3.0], "y": [5.0]}
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.get("via_channel"))
        self.assertEqual(result["points"][0], [0.0, 0.0])
        self.assertEqual(result["points"][-1], [10.0, 10.0])
        # The drawn-short check the whole flow gates on stays clean: the
        # channel path threaded between the two blockers, not through them.
        self.assertEqual(bus.conflicts(), [])

    def test_returns_none_and_leaves_no_residue_when_every_candidate_fails(
        self,
    ) -> None:
        """A hop that truly cannot be placed must report `None` rather than
        drawing a colliding path -- and must roll back every rectangle it
        speculatively drew while searching, or the next hop would be tested
        against phantom geometry."""
        bus = met1_bus.Met1Bus()
        bus.net("WALL")
        bus.hseg(9.85, 10.15, 0.0)
        bus.hseg(-0.15, 0.15, 10.0)
        rects_before = list(bus.met1_rects)
        shapes_before = list(bus.shapes)
        detours = gen_bandgap_routed.DETOUR_OFFSETS_UM
        gen_bandgap_routed.DETOUR_OFFSETS_UM = [0.0]
        try:
            result = gen_bandgap_routed._connect(
                bus, "N1", (0.0, 0.0), (10.0, 10.0), channels={}
            )
        finally:
            gen_bandgap_routed.DETOUR_OFFSETS_UM = detours
        self.assertIsNone(result)
        self.assertEqual(bus.met1_rects, rects_before)
        self.assertEqual(bus.shapes, shapes_before)


class TestChannelPaths(unittest.TestCase):
    """`_channel_paths()` is the shape a cross-floorplan hop needs that no
    elbow or single-jog Z can express -- see its own docstring. These check
    the geometric contract every caller relies on: every returned path is a
    legal orthogonal polyline, shortest first, and the double-dogleg variants
    genuinely use two different tracks (a same-track "dogleg" would just be
    a single-jog Z, already covered by the plain paths above it)."""

    CHANNELS = {"x": [2.0, 8.0, -5.0], "y": [3.0, 7.0, -4.0]}

    def test_every_path_is_orthogonal(self) -> None:
        paths = gen_bandgap_routed._channel_paths(
            (0.0, 0.0), (10.0, 10.0), self.CHANNELS
        )
        self.assertTrue(paths)
        for path in paths:
            for (x0, y0), (x1, y1) in zip(path, path[1:]):
                self.assertTrue(x0 == x1 or y0 == y1, path)

    def test_paths_are_sorted_shortest_first(self) -> None:
        paths = gen_bandgap_routed._channel_paths(
            (0.0, 0.0), (10.0, 10.0), self.CHANNELS
        )

        def length(path):
            return sum(
                abs(x0 - x1) + abs(y0 - y1)
                for (x0, y0), (x1, y1) in zip(path, path[1:])
            )

        lengths = [length(p) for p in paths]
        self.assertEqual(lengths, sorted(lengths))

    def test_double_dogleg_variants_use_two_different_tracks(self) -> None:
        """The double-dogleg family is what lets a hop leave on one track and
        arrive on a different one -- see the "D1 and D2" note in
        _channel_paths' own docstring. A same-track pair would degenerate to
        a plain single-jog Z, so every 6-point path here must actually use
        two distinct x (or y) tracks."""
        paths = gen_bandgap_routed._channel_paths(
            (0.0, 0.0), (10.0, 10.0), self.CHANNELS
        )
        six_point = [p for p in paths if len(p) == 6]
        self.assertTrue(six_point)
        for path in six_point:
            xs = {round(x, 6) for x, _ in path}
            ys = {round(y, 6) for _, y in path}
            # A double-dogleg varies exactly one axis across its two middle
            # legs (x for the x-band family, y for the y-band family); the
            # other axis only ever takes the two endpoints' own values.
            self.assertTrue(len(xs) >= 3 or len(ys) >= 3, path)

    def test_empty_channels_yield_no_paths(self) -> None:
        """No tracks to offer means no channel path is even attempted --
        `_connect` then falls straight through to its Z-detour stage."""
        self.assertEqual(
            gen_bandgap_routed._channel_paths((0.0, 0.0), (10.0, 10.0), {}), []
        )


class TestChainOrders(unittest.TestCase):
    """`_chain_orders()` supplies the visit-order candidates a multi-terminal
    node's hops are drawn in -- see its own docstring for why the order
    itself is load-bearing (a zig-zag chain asks the router for corridors a
    friendlier order never needs)."""

    def _pt(self, x: float, y: float) -> dict[str, float]:
        return {"x": x, "y": y}

    def test_two_terminal_net_never_costs_more_than_the_two_directions(self) -> None:
        """A 2-point chain has exactly one hop to draw either way it is
        walked -- forward or reversed -- so the dedup step must collapse
        every one of the (up to four) generator strategies down to at most
        those two orderings, never re-trying the same forward or the same
        reversed walk twice."""
        points = [self._pt(0.0, 0.0), self._pt(5.0, 5.0)]
        orders = gen_bandgap_routed._chain_orders(points)
        self.assertLessEqual(len(orders), 2)
        for order in orders:
            self.assertEqual(len(order), 2)
            self.assertEqual(set(id(p) for p in order), set(id(p) for p in points))

    def test_identical_generator_strategies_collapse_to_one_order(self) -> None:
        """When every strategy (column-major, row-major, nearest-neighbour
        from either start) agrees on the same walk, the dedup step must
        actually collapse them -- three axis-aligned points in a row leave
        no ambiguity for any of the four generators to disagree on."""
        points = [self._pt(0.0, 0.0), self._pt(1.0, 0.0), self._pt(2.0, 0.0)]
        orders = gen_bandgap_routed._chain_orders(points)
        self.assertEqual(len(orders), 3)

    def test_column_and_row_major_orders_are_both_present(self) -> None:
        points = [self._pt(5.0, 0.0), self._pt(0.0, 5.0), self._pt(5.0, 5.0)]
        orders = gen_bandgap_routed._chain_orders(points)
        by_xy = sorted(points, key=lambda p: (p["x"], p["y"]))
        by_yx = sorted(points, key=lambda p: (p["y"], p["x"]))
        self.assertIn(by_xy, orders)
        self.assertIn(by_yx, orders)

    def test_every_point_appears_as_a_nearest_neighbour_start(self) -> None:
        points = [
            self._pt(0.0, 0.0),
            self._pt(10.0, 0.0),
            self._pt(10.0, 10.0),
            self._pt(0.0, 10.0),
        ]
        orders = gen_bandgap_routed._chain_orders(points)
        starts = {id(order[0]) for order in orders}
        self.assertEqual(starts, {id(p) for p in points})
        # Every candidate order is a permutation of the same terminal set --
        # a chain that dropped or duplicated a terminal would leave one node
        # unrouted or shorted without either check noticing.
        for order in orders:
            self.assertEqual(sorted(id(p) for p in order), sorted(id(p) for p in points))

    def test_nearest_neighbour_chain_visits_the_closer_point_first(self) -> None:
        """From a given start, the manhattan-nearest remaining point is
        picked at each step -- so a chain starting at the origin with one
        very close neighbour and one far one must visit the close one
        second, not third."""
        near = self._pt(1.0, 0.0)
        far = self._pt(100.0, 0.0)
        start = self._pt(0.0, 0.0)
        orders = gen_bandgap_routed._chain_orders([start, far, near])
        nn_from_start = next(o for o in orders if o[0] is start)
        self.assertIs(nn_from_start[1], near)
        self.assertIs(nn_from_start[2], far)


class TestCandidateAssignments(unittest.TestCase):
    """`_candidate_assignments()` enumerates which pad/escape each terminal
    of a node takes -- see its own docstring for why centroid-nearest alone
    left real routes unroutable (PN/GDRV/etc.) while a perfectly good path
    existed off a different candidate of the same terminal."""

    def test_fixed_points_pass_through_unchanged(self) -> None:
        fixed = {"block": "b", "name": "b.PORT", "x": 1.0, "y": 2.0, "via": True}
        assignments = gen_bandgap_routed._candidate_assignments([fixed], 0.0, 0.0)
        self.assertEqual(len(assignments), 1)
        resolved, claims = assignments[0]
        self.assertEqual(resolved, [fixed])
        self.assertEqual(claims, [])

    def test_nearest_candidate_is_tried_first(self) -> None:
        point = {
            "block": "b",
            "via": True,
            "candidates": [("far", 100.0, 0.0), ("near", 1.0, 0.0)],
        }
        assignments = gen_bandgap_routed._candidate_assignments([point], 0.0, 0.0)
        resolved, claims = assignments[0]
        self.assertEqual(resolved[0]["name"], "b.near")
        self.assertEqual(claims, [("b", "near")])

    def test_result_count_is_bounded_by_candidate_assignments(self) -> None:
        point_a = {
            "block": "a",
            "via": True,
            "candidates": [(f"a{i}", float(i), 0.0) for i in range(5)],
        }
        point_b = {
            "block": "b",
            "via": True,
            "candidates": [(f"b{i}", float(i), 10.0) for i in range(5)],
        }
        assignments = gen_bandgap_routed._candidate_assignments(
            [point_a, point_b], 2.0, 5.0
        )
        self.assertLessEqual(
            len(assignments), gen_bandgap_routed.CANDIDATE_ASSIGNMENTS
        )
        # Every offered option is drawn from each terminal's own nearest
        # CANDIDATES_PER_TERMINAL -- the two farthest of the five never
        # appear, at either terminal, in any returned assignment.
        seen_a = {resolved[0]["name"] for resolved, _ in assignments}
        seen_b = {resolved[1]["name"] for resolved, _ in assignments}
        self.assertFalse(seen_a & {"a.a3", "a.a4"})
        self.assertFalse(seen_b & {"b.b3", "b.b4"})

    def test_claims_pad_false_leaves_the_name_unprefixed_and_unclaimed(
        self,
    ) -> None:
        """A `comb` terminal's escape point is already on drawn metal with no
        pad of its own (MOS_COMB_NOTE) -- claiming it would falsely reserve a
        pad no other net could then legally use."""
        point = {
            "block": "b",
            "via": False,
            "claims_pad": False,
            "candidates": [("escape", 3.0, 4.0)],
        }
        assignments = gen_bandgap_routed._candidate_assignments([point], 0.0, 0.0)
        resolved, claims = assignments[0]
        self.assertEqual(resolved[0]["name"], "escape")
        self.assertEqual(claims, [])


# ---------------------------------------------------------------------------
# PR #73's rip-up-and-reroute repair pass (issue #62, fifth increment) --
# `_route_one_net`'s `skip_first` parameter and `_repair_unrouted_hops`/
# `_replay_tail`.
#
# SEE ALSO `layout/tests/test_route_repair.py`, which PR #73 shipped
# alongside the mechanism itself and which already unit-covers these same
# three functions. That file is the primary coverage: it isolates the repair
# pass's *control flow* (targeting, bounded retries, revert-on-no-improvement,
# "a later net named as blocker is never rolled back") by replacing
# `_route_one_net` with a scripted mock, and covers `skip_first` candidate
# selection against hand-built li1 block ports.
#
# The classes below are deliberately complementary, not a replacement, and do
# not originate coverage of this mechanism:
#   * They drive the *real*, non-mocked router end to end -- `skip_first` and
#     `_repair_unrouted_hops` acting on actually-drawn met1 geometry, with
#     `bus.mark()`/`bus.conflicts()` as the assertions -- so a geometry-level
#     regression that a scripted mock cannot see (the mock never draws
#     anything) still fails here.
#   * They reach `_route_one_net` through a different terminal-resolution
#     path: `trunk`/`comb` terminals, which need no `klt gen` block report,
#     versus `test_route_repair.py`'s `block`/li1-port terminals.
#   * They live in the file issue #62's own Test Plan names ("extend
#     layout/tests/test_routed_flow_gates.py ... for any new gate logic a
#     further increment adds"), next to this repo's other router-internal
#     gate tests.
#
# The synthetic floorplans here (minimal `trunk`/`comb` fixtures) exercise the
# three outcomes the real record (`bus-summary.json`,
# `layout/matching-plan.md` Section 7c) and this mechanism's own docstring
# describe: a rip-up that finds a genuinely clear alternate and frees the hop;
# a rip-up that tries a real alternate and it still blocks, so the change is
# reverted (the `D1`/`VSS` case); and a hop whose blocker cannot be attributed
# to any rippable net at all (the `VDD` case, no valid target).
# ---------------------------------------------------------------------------
class TestRouteOneNetSkipFirst(unittest.TestCase):
    """`_route_one_net(..., skip_first=N)` must pass over its own first `N`
    fully-*routed* attempts and commit to the next one -- the exact question
    `_repair_unrouted_hops` asks a blocker: "what is your next-best routing
    against the same geometry?" (Section 7c of `layout/matching-plan.md`).

    A 2-terminal net has exactly two chain-visit orders (forward and
    reverse) and they draw identical geometry -- so the first `skip_first`
    slot is always spent on that duplicate before a genuinely different
    candidate is tried; `skip_first=2` is what actually reaches the second
    `comb` candidate below. This is a real, load-bearing property of the
    search, not a test artefact -- `TestRepairUnroutedHops` below uses a
    3-terminal net specifically to avoid it, the same way a real multi-pad
    inter-block node does.

    Complements (does not replace) the same-named
    `test_route_repair.TestRouteOneNetSkipFirst`, which covers `skip_first`
    candidate *ranking* through `block`/li1-port terminals; this class covers
    it through `trunk`/`comb` terminals, where the reversed-duplicate quirk
    above is visible.
    """

    def _specs(self) -> dict[str, dict[str, object]]:
        return {
            "A": {
                "net": "A",
                "schematic": "test net",
                "terminals": [{"trunk": ("L", "A")}, {"comb": ("R", "A")}],
            }
        }

    def test_skip_first_zero_takes_the_nearest_candidate(self) -> None:
        bus = met1_bus.Met1Bus()
        trunks = {("L", "A"): (0.0, 0.0)}
        combs = {("R", "A"): [("near", 10.0, 0.0), ("far", 50.0, 0.0)]}
        result = gen_bandgap_routed._route_one_net(
            bus, "A", self._specs(), {}, {}, trunks, combs, set(), {},
            skip_first=0,
        )
        self.assertTrue(result["routed"])
        self.assertIn("near", result["terminals"])
        self.assertNotIn("far", result["terminals"])

    def test_skip_first_past_the_reversed_duplicate_reaches_the_next_candidate(
        self,
    ) -> None:
        bus = met1_bus.Met1Bus()
        trunks = {("L", "A"): (0.0, 0.0)}
        combs = {("R", "A"): [("near", 10.0, 0.0), ("far", 50.0, 0.0)]}
        result = gen_bandgap_routed._route_one_net(
            bus, "A", self._specs(), {}, {}, trunks, combs, set(), {},
            skip_first=2,
        )
        self.assertTrue(result["routed"])
        self.assertIn("far", result["terminals"])
        self.assertNotIn("near", result["terminals"])

    def test_skip_first_past_every_candidate_still_reports_a_result(self) -> None:
        """Asking to skip past every fully-routed candidate must not raise --
        `_route_one_net` falls back to redrawing its own best-scoring attempt
        (see its own "if not routed" tail), the same fallback a real deadlock
        (no candidate left to try) hits."""
        bus = met1_bus.Met1Bus()
        trunks = {("L", "A"): (0.0, 0.0)}
        combs = {("R", "A"): [("near", 10.0, 0.0), ("far", 50.0, 0.0)]}
        result = gen_bandgap_routed._route_one_net(
            bus, "A", self._specs(), {}, {}, trunks, combs, set(), {},
            skip_first=99,
        )
        self.assertIn("net", result)
        self.assertIn("hops", result)


class TestRepairUnroutedHops(unittest.TestCase):
    """`_repair_unrouted_hops()` rolls back to just before a blocking net,
    forces it past its own next-best solution, and keeps the result only if
    it strictly improves -- see the function's own docstring and
    `layout/matching-plan.md` Section 7c for the real-floorplan record this
    mirrors.

    Complements (does not replace) the same-named
    `test_route_repair.TestRepairUnroutedHops`, which covers this function's
    control flow with `_route_one_net` replaced by a scripted mock. Here
    `_route_one_net` is the real one and really draws met1, so these tests
    additionally pin the *geometric* outcome (`bus.mark()` equality on the
    revert/no-op paths, `bus.conflicts()` on the kept path) that a mocked
    router cannot observe.

    Fixture: net `A` is a 3-terminal net (`L`, `R`, `M`, all fixed `trunk`
    points -- deliberately not collinear, and scaled up so the widest
    candidate geometry's extent comfortably exceeds every offset
    `DETOUR_OFFSETS_UM` tries). A 3-terminal net's chain-visit orders are
    *not* all mutual reversals of one another (unlike the 2-terminal case
    `TestRouteOneNetSkipFirst` documents above): `skip_first=1` alone lands
    on a genuinely different pair of drawn segments, which is what lets a
    single repair attempt (`_repair_unrouted_hops` only ever tries one
    `skip_first` increment per blocker/failing-net pair before giving up)
    matter at all. `B` is a 2-terminal vertical hop with no channels
    declared, so its only route is the direct vertical elbow.
    """

    _K = 60.0
    L_TRUNK = (11.4 * _K, -7.9 * _K)
    R_TRUNK = (-0.9 * _K, 3.3 * _K)
    M_TRUNK = (16.3 * _K, 0.2 * _K)

    def _specs(self) -> dict[str, dict[str, object]]:
        return {
            "A": {
                "net": "A",
                "schematic": "test blocker net",
                "terminals": [
                    {"trunk": ("L", "A")},
                    {"trunk": ("R", "A")},
                    {"trunk": ("M", "A")},
                ],
            },
            "B": {
                "net": "B",
                "schematic": "test failing net",
                "terminals": [{"trunk": ("X", "B")}, {"trunk": ("Y", "B")}],
            },
        }

    def _trunks(
        self, x_y: tuple[float, float], y_y: tuple[float, float]
    ) -> dict[tuple[str, str], tuple[float, float]]:
        return {
            ("L", "A"): self.L_TRUNK,
            ("R", "A"): self.R_TRUNK,
            ("M", "A"): self.M_TRUNK,
            ("X", "B"): x_y,
            ("Y", "B"): y_y,
        }

    def _run_forward_pass(self, x_y: tuple[float, float], y_y: tuple[float, float]):
        bus = met1_bus.Met1Bus()
        specs = self._specs()
        trunks = self._trunks(x_y, y_y)
        channels: dict[str, list[float]] = {}
        used_ports: set[tuple[str, str]] = set()
        sequence = ["A", "B"]
        marks = []
        port_snapshots = []
        results = []
        for net_name in sequence:
            marks.append(bus.mark())
            port_snapshots.append(set(used_ports))
            results.append(
                gen_bandgap_routed._route_one_net(
                    bus, net_name, specs, {}, {}, trunks, {}, used_ports,
                    channels,
                )
            )
        return bus, specs, trunks, channels, used_ports, sequence, marks, \
            port_snapshots, results

    def test_repair_reroutes_the_blocker_and_frees_the_hop(self) -> None:
        """`B`'s vertical hop at x=5 crosses `A`'s greedy-first geometry (a
        segment at y=198, drawn between `R` and `L`) but not its `skip_first=1`
        alternate (a segment at y=12, drawn between `L` and `M`) -- so ripping
        `A` up and forcing it past its first pick frees `B`."""
        bus, specs, trunks, channels, used_ports, sequence, marks, \
            port_snapshots, results = self._run_forward_pass(
                (5.0, 150.0), (5.0, 250.0)
            )

        self.assertTrue(results[0]["routed"])
        self.assertFalse(results[1]["routed"])
        self.assertEqual(results[1]["hops"][0]["blocked_by"], "A")
        original_terminals = list(results[0]["terminals"])

        gen_bandgap_routed._repair_unrouted_hops(
            bus, sequence, specs, {}, {}, trunks, {}, used_ports, channels,
            marks, port_snapshots, results,
        )

        self.assertTrue(results[0]["routed"])
        self.assertTrue(results[1]["routed"], results[1])
        # `A` was genuinely ripped up and redrawn -- not left as the forward
        # pass's own pick.
        self.assertNotEqual(results[0]["terminals"], original_terminals)
        self.assertEqual(bus.conflicts(), [])

    def test_repair_is_a_noop_when_the_blocker_is_outside_the_sequence(
        self,
    ) -> None:
        """Mirrors `VDD`'s recorded finding (PR #73): a hop whose blocker
        cannot be attributed to any net this repair pass could rip up (here,
        pre-existing bus geometry from outside `sequence` entirely) must be
        left exactly as the forward pass drew it -- no attempt, no change."""
        bus = met1_bus.Met1Bus()
        bus.net("WALL")
        # A long horizontal wall at y=5, wide enough that every x-offset
        # Z-detour DETOUR_OFFSETS_UM tries still crosses it (max offset is
        # bounded, see that constant's own docstring).
        bus.hseg(-150.0, 300.0, 5.0)
        specs = {
            "B": {
                "net": "B",
                "schematic": "test failing net",
                "terminals": [{"trunk": ("X", "B")}, {"trunk": ("Y", "B")}],
            }
        }
        trunks = {("X", "B"): (5.0, 0.0), ("Y", "B"): (5.0, 10.0)}
        channels: dict[str, list[float]] = {}
        used_ports: set[tuple[str, str]] = set()
        sequence = ["B"]
        marks = [bus.mark()]
        port_snapshots = [set(used_ports)]
        results = [
            gen_bandgap_routed._route_one_net(
                bus, "B", specs, {}, {}, trunks, {}, used_ports, channels,
            )
        ]
        self.assertFalse(results[0]["routed"])
        self.assertEqual(results[0]["hops"][0]["blocked_by"], "WALL")

        mark_before_repair = bus.mark()
        gen_bandgap_routed._repair_unrouted_hops(
            bus, sequence, specs, {}, {}, trunks, {}, used_ports, channels,
            marks, port_snapshots, results,
        )

        self.assertFalse(results[0]["routed"])
        self.assertEqual(bus.mark(), mark_before_repair)

    def test_repair_reverts_when_no_alternate_improves(self) -> None:
        """Mirrors `D1`/`VSS`'s recorded finding (PR #73): `B`'s hop spans
        wide enough (x=5, y 0..250) to cross both `A`'s greedy-first geometry
        *and* its `skip_first=1` alternate, so ripping `A` up finds a real,
        different, legitimate rip-up target and it still does not free the
        hop -- the repair must leave the layout exactly as the forward pass
        drew it (`"kept": false` in the real record's `bus-summary.json`),
        not a half-reverted mutation."""
        bus, specs, trunks, channels, used_ports, sequence, marks, \
            port_snapshots, results = self._run_forward_pass(
                (5.0, 0.0), (5.0, 250.0)
            )

        self.assertTrue(results[0]["routed"])
        self.assertFalse(results[1]["routed"])
        original_terminals = list(results[0]["terminals"])
        mark_before_repair = bus.mark()

        gen_bandgap_routed._repair_unrouted_hops(
            bus, sequence, specs, {}, {}, trunks, {}, used_ports, channels,
            marks, port_snapshots, results,
        )

        self.assertFalse(results[1]["routed"])
        self.assertEqual(results[0]["terminals"], original_terminals)
        self.assertEqual(bus.mark(), mark_before_repair)
        self.assertEqual(bus.conflicts(), [])
