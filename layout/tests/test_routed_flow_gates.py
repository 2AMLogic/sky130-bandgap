#!/usr/bin/env python3
"""Unit coverage for the routed-flow's own gates (issue #62).

`layout/bin/run-bandgap-routed-flow.sh` decides pass/fail on four checks
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
3. **The coverage-scoring check** -- `layout_common.schematic_net_coverage()`.
   Scores acceptance criterion 1 against `design/bandgap_core.sch`'s own
   inter-block node list rather than against the flow's own `connectivity[]`
   declaration, so a net the flow simply forgot to declare still shows up as
   a miss. It also drives the router's ordering search, so a scoring bug
   silently changes which layout gets drawn.
4. **The split-node check** -- `met1_bus.Met1Bus.components()` scored by
   `gen_bandgap_routed.split_routed_nets()`. The exact inverse of check 1: a
   node this router reports as fully routed whose own met1 is still in two
   pieces that never touch. Invisible to all three checks above and to DRC --
   `klt extract` just emits two anonymous nets, and check 3 scores the
   router's hop bookkeeping rather than the geometry, so it would still call
   the node drawn (issue #72).

Until now all of them were exercised only end-to-end, by a flow run that needs
a `klt` install and a ~1 GB PDK and takes minutes -- so their *failure*
paths (the ones that matter) were never exercised at all, because a passing
run by construction never reaches them. These tests exercise both paths in
milliseconds with no PDK, and are wired into `npm run check:ci`.

The router's own internals and drawn geometry moved to sibling files so
this one stays about the gates (issue #556): `test_bus_routing.py` holds
the finger-bus/gate-contact geometry and the open-channel router
(including the repair pass driven through the real router),
`test_met2_escape.py` the met2 escape plane, and
`test_ladder_geometry.py` the resistor-ladder scoreboard helpers.

Standard library only (`unittest`), matching every other script under
`layout/`. Run directly, or via:

    npm run test:unit
    python3 -m unittest discover --start-directory layout/tests
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "layout" / "bin"))

import gen_bandgap_routed  # noqa: E402  -- resolved from layout/bin, above
import layout_common  # noqa: E402
import met1_bus  # noqa: E402
import bus_routing  # noqa: E402  -- issue #221: split out of gen_bandgap_routed.py


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
        bus.hseg(0.0, 5.0, 0.0)
        bus.vseg(5.0, 0.0, 5.0)
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


class TestComponentsGate(unittest.TestCase):
    """`Met1Bus.components()` -- the matching safety net to `conflicts()`
    (issue #72's port from the closed `feature/issue-62` branch,
    `git show 91996e0045d2ce783483ebc790ffcfdc4d99ae1c:layout/bin/met1_bus.py`).

    `conflicts()` catches two *different* nodes' metal touching; this catches
    the opposite failure -- one node's own wiring drawn as two pieces that
    never touch, which nothing downstream reports (`klt extract` just sees
    two anonymous nets with no error). A component count of 1 means the
    wiring this flow drew for that node is genuinely one conductor.
    """

    def test_empty_bus_has_no_components(self) -> None:
        """No met1 drawn at all -- an empty result, not a KeyError or a
        spurious zero-count entry for a net nobody touched."""
        bus = met1_bus.Met1Bus()
        self.assertEqual(bus.components(), {})

    def test_single_connected_run_is_one_component(self) -> None:
        """A bus is a chain of touching same-net rectangles by construction
        -- an elbow's two segments share a corner, and a via's landing pad
        sits under the wire that reaches it. Real bussing must read as 1."""
        bus = met1_bus.Met1Bus()
        bus.net("VSS")
        bus.via(0.0, 0.0)
        bus.hseg(0.0, 5.0, 0.0)
        bus.vseg(5.0, 0.0, 5.0)
        bus.via(5.0, 5.0)
        self.assertEqual(bus.components(), {"VSS": 1})

    def test_disjoint_pieces_of_one_net_are_separate_components(self) -> None:
        """The core case: one electrical node drawn as two met1 islands that
        never touch. `conflicts()` reports nothing here (there is only one
        net, so there is no *different*-net pair to flag) -- this is the
        check that catches it instead."""
        bus = met1_bus.Met1Bus()
        bus.net("D2")
        bus.hseg(0.0, 1.0, 0.0)
        bus.hseg(100.0, 101.0, 100.0)  # far away, same net, unconnected
        self.assertEqual(bus.components(), {"D2": 2})

    def test_touching_rectangles_merge_into_one_component(self) -> None:
        """Two same-net rectangles that only share an edge (no area overlap)
        still count as one conductor -- a shared edge is a real connection
        on a single metal layer."""
        bus = met1_bus.Met1Bus()
        bus.net("VOUT")
        bus.hseg(0.0, 1.0, 0.0)
        bus.vseg(1.0, -1.0, 1.0)  # touches the hseg's right edge at x=1.0
        self.assertEqual(bus.components(), {"VOUT": 1})

    def test_multiple_nets_are_scored_independently(self) -> None:
        """One net's split pieces must not affect another net's count, even
        when their geometry is interleaved in the drawing order -- this is
        the synthetic reconstruction of the historical finding that
        motivated this port (four nodes, several still split as two or
        three pieces): `{"D2": 3, "VB": 2, "VOUT": 2, "VSS": 3}`."""
        bus = met1_bus.Met1Bus()
        bus.net("D2")
        bus.hseg(0.0, 1.0, 0.0)
        bus.hseg(10.0, 11.0, 0.0)
        bus.hseg(20.0, 21.0, 0.0)
        bus.net("VB")
        bus.hseg(0.0, 1.0, 10.0)
        bus.hseg(10.0, 11.0, 10.0)
        bus.net("VOUT")
        bus.hseg(0.0, 1.0, 20.0)
        bus.hseg(10.0, 11.0, 20.0)
        bus.net("VSS")
        bus.hseg(0.0, 1.0, 30.0)
        bus.hseg(10.0, 11.0, 30.0)
        bus.hseg(20.0, 21.0, 30.0)
        self.assertEqual(
            bus.components(), {"D2": 3, "VB": 2, "VOUT": 2, "VSS": 3}
        )

    def test_components_spans_the_grid_index_cell_boundary(self) -> None:
        """Two rectangles that touch exactly at a `GRID_UM` cell boundary
        must still merge -- `components()` shares the same spatial index
        `met1_near`/`conflicts` use, and a bucketing bug there would split a
        real connection at every cell edge."""
        bus = met1_bus.Met1Bus()
        bus.net("VDD")
        x = met1_bus.GRID_UM  # exactly on a cell boundary
        bus.hseg(x - 1.0, x, 0.0)
        bus.hseg(x, x + 1.0, 0.0)
        self.assertEqual(bus.components(), {"VDD": 1})


class TestSplitRoutedNetsGate(unittest.TestCase):
    """`split_routed_nets()` is what turns `Met1Bus.components()` from a
    number in a JSON file into the flow's fourth pass/fail gate (issue #72).

    A node this router reports as fully `routed` whose met1 is still in two
    pieces is a bug in the router's own bookkeeping, and nothing else in the
    flow can see it: DRC passes (two legal wires), `klt extract` emits two
    anonymous nets with nothing in `warnings[]`, `conflicts()` finds nothing
    (there is only one net, so no *different*-net pair), and
    `schematic_net_coverage()` scores the hop records rather than the
    geometry, so it would still call the node drawn.
    """

    def test_a_routed_net_in_one_piece_is_not_reported(self) -> None:
        """The normal case. Every routed node is one conductor, so the gate
        has nothing to say."""
        routes = [{"net": "VDD", "routed": True}, {"net": "TAIL", "routed": True}]
        self.assertEqual(
            gen_bandgap_routed.split_routed_nets(routes, {"VDD": 1, "TAIL": 1}), {}
        )

    def test_a_routed_net_in_two_pieces_is_reported_with_its_count(self) -> None:
        """The bug the gate exists for -- and the count is carried through so
        a failing run says how badly, not only that."""
        routes = [{"net": "VDD", "routed": True}]
        self.assertEqual(
            gen_bandgap_routed.split_routed_nets(routes, {"VDD": 3}), {"VDD": 3}
        )

    def test_an_unrouted_net_in_two_pieces_is_not_reported(self) -> None:
        """Load-bearing exclusion: a node that came up a hop short is
        *supposed* to be in more than one piece. Gating on it would fire on
        every partial run and would only restate the coverage table."""
        routes = [{"net": "VSS", "routed": False}]
        self.assertEqual(gen_bandgap_routed.split_routed_nets(routes, {"VSS": 2}), {})

    def test_only_the_offending_nets_are_reported(self) -> None:
        """A mixed run: one clean routed node, one split routed node, one
        split unrouted node."""
        routes = [
            {"net": "TAIL", "routed": True},
            {"net": "VDD", "routed": True},
            {"net": "VSS", "routed": False},
        ]
        self.assertEqual(
            gen_bandgap_routed.split_routed_nets(
                routes, {"TAIL": 1, "VDD": 2, "VSS": 4}
            ),
            {"VDD": 2},
        )

    def test_a_net_with_no_drawn_met1_at_all_is_not_reported(self) -> None:
        """`components()` only has an entry for nets that drew met1. A routed
        node missing from it must read as "nothing to report", not as a
        KeyError that takes the whole flow down at the last step."""
        routes = [{"net": "GDRV", "routed": True}]
        self.assertEqual(gen_bandgap_routed.split_routed_nets(routes, {}), {})

    def test_end_to_end_against_real_drawn_geometry(self) -> None:
        """The two halves wired together on a real `Met1Bus`, not on a hand-
        written component map: one node drawn as a connected elbow, one drawn
        as two islands, and only the second is reported."""
        bus = met1_bus.Met1Bus()
        bus.net("TAIL")
        bus.hseg(0.0, 5.0, 0.0)
        bus.vseg(5.0, 0.0, 5.0)
        bus.net("VDD")
        bus.hseg(20.0, 21.0, 20.0)
        bus.hseg(80.0, 81.0, 80.0)  # never reaches the first piece
        routes = [{"net": "TAIL", "routed": True}, {"net": "VDD", "routed": True}]
        self.assertEqual(
            gen_bandgap_routed.split_routed_nets(routes, bus.components()),
            {"VDD": 2},
        )


class TestBulkTapTerminals(unittest.TestCase):
    """`bulk_terminal()` offers every guard-ring tap of a MOS group as a
    routing candidate rather than pinning the node to `TAP_S` (issue #72).

    This is the fix for the 0/0 LVS correspondence regression: with `TAP_S`
    hardcoded, the `VDD` trunk could not reach `core_mirror`'s or
    `amp_input_pair`'s n-well tap, so both PMOS groups' body terminals
    extracted onto anonymous floating nets instead of onto `VDD`, and
    `NetlistComparer` could not seed a single device or net correspondence
    from a netlist whose PMOS bulks are all on nets the reference does not
    contain.
    """

    @staticmethod
    def _report(**ports: tuple[float, float]) -> dict[str, object]:
        return {
            "ports": [
                {
                    "name": name,
                    "x_um": x,
                    "y_um": y,
                    "width_um": 0.5,
                    "direction_deg": 270,
                    "layer": {"layer": 67, "datatype": 20, "name": None},
                }
                for name, (x, y) in ports.items()
            ]
        }

    def test_every_tap_of_the_ring_is_offered(self) -> None:
        """Not one tap, and not a tap chosen here: the whole set, so which one
        is taken stays a routing decision."""
        terminal = bus_routing.bulk_terminal("core_mirror")
        self.assertEqual(terminal["block"], "core_mirror")
        self.assertEqual(terminal["ports"], list(bus_routing.BULK_TAP_PORTS))
        self.assertNotIn("port", terminal, "a single pinned tap is the bug")

    def test_the_offered_set_is_the_generators_own_tap_names(self) -> None:
        """`klt gen diff_pair` reports its ring taps as `TAP_N`/`TAP_S`/
        `TAP_E`; a typo here would silently drop a candidate."""
        self.assertEqual(
            set(bus_routing.BULK_TAP_PORTS), {"TAP_N", "TAP_S", "TAP_E"}
        )

    def test_no_escape_stub(self) -> None:
        """A ring tap already sits on the block's outer edge facing open
        floorplan, so the router leaves from the pad itself."""
        self.assertFalse(bus_routing.bulk_terminal("amp_pmirr")["escape"])

    def test_every_bulk_terminal_names_a_real_block(self) -> None:
        """The declared inter-block table is hand-written; a bulk terminal on
        a block that is not placed would raise deep inside the router."""
        block_ids = {b["id"] for b in gen_bandgap_routed.BLOCKS}
        for spec in bus_routing.INTER_BLOCK_MET1:
            for terminal in spec["terminals"]:
                if "ports" in terminal:
                    with self.subTest(net=spec["net"], block=terminal["block"]):
                        self.assertIn(terminal["block"], block_ids)

    def test_the_router_resolves_a_ports_terminal_to_one_of_its_taps(self) -> None:
        """The `ports` terminal shape end to end: `_route_one_net` turns it
        into candidates, picks one, claims exactly that pad, and names it
        `<block>.<port>` -- the form the route summary's `terminals[]`
        entries carry."""
        reports = {
            "blk": self._report(
                TAP_S=(10.0, 0.0), TAP_N=(10.0, 40.0), TAP_E=(20.0, 20.0)
            ),
            "other": self._report(TAP_S=(10.0, 100.0)),
        }
        origins = {"blk": {"x": 0.0, "y": 0.0}, "other": {"x": 0.0, "y": 0.0}}
        specs = {
            "VDD": {
                "net": "VDD",
                "schematic": "two ring taps",
                "terminals": [
                    bus_routing.bulk_terminal("blk"),
                    bus_routing.bulk_terminal("other"),
                ],
            }
        }
        used: set[tuple[str, str]] = set()
        route = bus_routing._route_one_net(
            met1_bus.Met1Bus(), "VDD", specs, reports, origins, {}, {}, used, {}
        )
        self.assertTrue(route["routed"], route)
        self.assertEqual(sorted(route["blocks"]), ["blk", "other"])
        for name in route["terminals"]:
            block, _, port = name.partition(".")
            self.assertIn(port, bus_routing.BULK_TAP_PORTS)
            self.assertIn((block, port), used)
        # One pad per block, not one per offered candidate.
        self.assertEqual(len(used), 2)

    def test_an_already_claimed_tap_is_not_offered_again(self) -> None:
        """Pad claims are shared with the pin selector, so a tap another node
        already took must drop out of the candidate set rather than be
        double-booked."""
        reports = {
            "blk": self._report(TAP_S=(10.0, 0.0), TAP_N=(10.0, 40.0)),
            "other": self._report(TAP_S=(10.0, 100.0)),
        }
        origins = {"blk": {"x": 0.0, "y": 0.0}, "other": {"x": 0.0, "y": 0.0}}
        specs = {
            "VDD": {
                "net": "VDD",
                "schematic": "two ring taps",
                "terminals": [
                    bus_routing.bulk_terminal("blk"),
                    bus_routing.bulk_terminal("other"),
                ],
            }
        }
        used = {("blk", "TAP_S")}
        route = bus_routing._route_one_net(
            met1_bus.Met1Bus(), "VDD", specs, reports, origins, {}, {}, used, {}
        )
        self.assertIn("blk.TAP_N", route["terminals"])
        self.assertNotIn("blk.TAP_S", route["terminals"])

    def test_a_block_with_no_free_tap_raises_rather_than_routing_nowhere(
        self,
    ) -> None:
        """Silently dropping the terminal would leave the group's bulk
        floating again -- the exact regression this change fixes -- with the
        route still reported as `routed`."""
        reports = {"blk": self._report(TAP_S=(10.0, 0.0))}
        origins = {"blk": {"x": 0.0, "y": 0.0}}
        specs = {
            "VDD": {
                "net": "VDD",
                "schematic": "one ring tap",
                "terminals": [bus_routing.bulk_terminal("blk")],
            }
        }
        with self.assertRaises(KeyError):
            bus_routing._route_one_net(
                met1_bus.Met1Bus(), "VDD", specs, reports, origins, {}, {},
                {("blk", "TAP_S")}, {},
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

    # -- extract.json view: the headless pin for store-backed records -----
    # Every record from here on is store-backed (issue #440 ruling), so in
    # the no-broker CI job the current-record tripwire reads the record's
    # committed extract.json instead of the netlist bytes. These pin that
    # view against the same defect the netlist scan catches (issue #671).
    def test_extract_view_reports_merged_name_in_nets(self) -> None:
        extract = {
            "merged_net_labels": [],
            "nets": [{"name": "VDD"}, {"name": "TAIL|VOUT"}],
        }
        self.assertEqual(
            gen_bandgap_routed.merged_pin_names_from_extract(extract),
            ["TAIL|VOUT"],
        )

    def test_extract_view_reports_nonempty_merged_net_labels(self) -> None:
        extract = {"merged_net_labels": ["TAIL", "VOUT"], "nets": []}
        self.assertEqual(
            gen_bandgap_routed.merged_pin_names_from_extract(extract),
            ["TAIL", "VOUT"],
        )

    def test_extract_view_clean_dict_returns_empty(self) -> None:
        extract = {
            "merged_net_labels": [],
            "nets": [{"name": "VDD"}, {"name": "VSS"}],
        }
        self.assertEqual(
            gen_bandgap_routed.merged_pin_names_from_extract(extract), []
        )

    def test_extract_view_reads_legacy_schema_without_merged_net_labels(self) -> None:
        """Records from before `merged_net_labels` existed still get the
        `nets[].name` scan. (The one such record in tree,
        `20260804-012421-1a97bf5`, lists anonymous `$N` nets there, which
        is why the historical positive case is pinned on the netlist
        below rather than here.)"""
        legacy = {"nets": [{"name": "VA"}, {"name": "VB"}]}
        self.assertEqual(
            gen_bandgap_routed.merged_pin_names_from_extract(legacy), []
        )
        collided = {"nets": [{"name": "VA"}, {"name": "TAIL|VOUT"}]}
        self.assertEqual(
            gen_bandgap_routed.merged_pin_names_from_extract(collided),
            ["TAIL|VOUT"],
        )

    def test_extract_view_without_any_signal_raises(self) -> None:
        """An extract from an unknown schema fails the gate rather than
        silently passing it."""
        with self.assertRaises(ValueError):
            gen_bandgap_routed.merged_pin_names_from_extract(
                {"schema_version": 0, "status": "ok"}
            )

    def test_store_backed_fallback_fails_without_extract_json(self) -> None:
        """A store-backed record with no committed extract.json cannot be
        pinned headless -- that is a failure, not a pass."""
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(AssertionError):
                self._assert_store_backed_record_is_clean(Path(tmp))

    # -- regression corpus: the flow's own append-only evidence -------------
    # These read the checked-in records rather than a synthetic fixture, so
    # the gate is pinned against the exact netlists it was written to judge.
    def test_flags_the_historical_collision_the_gate_was_written_for(self) -> None:
        """Record `20260804-012421-1a97bf5` is the run whose `VOUT` label
        landed on `core_mirror.M2_1_D` -- MPAMP's drain, the pad the drawn
        `TAIL` net already contacted -- because the flow's pin labelling and
        its router kept separate "already used" sets. The trim-tap labels
        collided the same way. This is the real defect, from the real
        evidence trail, not an invented one."""
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
        latest_id = (reports / "LATEST").read_text().strip()
        latest = reports / latest_id
        netlist = latest / "bandgap_core_routed.extract.spice"
        if not netlist.is_file():
            # Store-backed record (issue #440 ruling): the bytes live in the
            # fleet artifact store and git keeps the manifest. With a broker
            # the full netlist check still runs, resolved exactly the way
            # the flow's own evidence index documents. Headless (the CI
            # job's environment) there are no netlist bytes to scan, but
            # the record's committed extract.json carries the same
            # label-collision traces -- assert on those instead of
            # skipping, so this tripwire never depends on a `klt` install
            # (issue #671).
            if shutil.which("klt") and os.environ.get("KLT_ARTIFACT_BROKER"):
                netlist = self._fetch_from_artifact_store(latest_id, netlist)
            else:
                self._assert_store_backed_record_is_clean(latest)
                return
        self.assertEqual(gen_bandgap_routed.assert_no_merged_pin_names(netlist), [])

    def _assert_store_backed_record_is_clean(self, record: Path) -> None:
        """Headless pin for a store-backed record: the label-collision
        traces in the record's committed `extract.json` must be clean."""
        extract_json = record / "extract.json"
        self.assertTrue(
            extract_json.is_file(),
            f"store-backed record {record.name} has no committed extract.json "
            f"at {extract_json} to pin the label-collision gate against",
        )
        self.assertEqual(
            gen_bandgap_routed.merged_pin_names_from_extract(
                json.loads(extract_json.read_text())
            ),
            [],
        )

    def _fetch_from_artifact_store(
        self, record_id: str, in_tree: Path
    ) -> Path:
        manifest = (
            REPO_ROOT
            / "manifests/artifacts"
            / f"layout-bandgap-core-{record_id}.manifest.json"
        )
        self.assertTrue(
            manifest.is_file(),
            f"no extracted netlist in {in_tree.parent} and no artifact manifest "
            f"at {manifest}",
        )
        wanted = (
            f"layout/bandgap-core/staging/{record_id}/"
            "bandgap_core_routed.extract.spice"
        )
        entries = json.loads(manifest.read_text()).get("entries", [])
        names = [e.get("name") for e in entries if e.get("name") == wanted]
        self.assertEqual(
            names,
            [wanted],
            f"no '{wanted}' entry in {manifest.name} to resolve the extract "
            "netlist from",
        )
        dest = Path(tempfile.mkdtemp(prefix="label-collision-")) / "extract.spice"
        proc = subprocess.run(
            ["klt", "artifact", "get", f"{manifest.relative_to(REPO_ROOT)}#{wanted}",
             "-o", str(dest)],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=300,
        )
        self.assertEqual(
            proc.returncode,
            0,
            f"klt artifact get failed for '{wanted}': {proc.stderr.strip()}",
        )
        self.addCleanup(shutil.rmtree, dest.parent, True)
        return dest


class TestRectsSnapToMfgGrid(unittest.TestCase):
    """Every drawn vertex lands on the 5 nm manufacturing grid (the sky130
    `*.ongrid.1` rules), even for off-grid route coordinates."""

    def test_off_grid_coordinates_are_snapped(self) -> None:
        bus = met1_bus.Met1Bus()
        bus.net("N")
        bus.via(84.78666666, 65.78666667)
        bus.vseg(68.325, 55.66666667, 69.6)
        self.assertTrue(bus.shapes)
        for shape in bus.shapes:
            for value in shape["rect_um"]:
                self.assertEqual(round(value * 1000) % 5, 0, shape)

    def test_via_pad_width_is_preserved(self) -> None:
        bus = met1_bus.Met1Bus()
        bus.via(84.78666666, 65.78666667)
        for shape in bus.shapes:
            x0, y0, x1, y1 = shape["rect_um"]
            self.assertEqual(round((x1 - x0) * 1000), round((y1 - y0) * 1000))


class TestFlowFailsClosedWithoutArtifactStore(unittest.TestCase):
    """Issue #426: with no `$KLT_ARTIFACT_BROKER` the routed flow must exit
    non-zero before creating `staging/` or `reports/<record-id>/`."""

    def test_broker_unset_writes_nothing(self) -> None:
        cell = REPO_ROOT / "layout/bandgap-core"
        before = sorted(p.name for p in (cell / "reports").iterdir())
        env = {k: v for k, v in os.environ.items() if k != "KLT_ARTIFACT_BROKER"}
        proc = subprocess.run(
            ["bash", str(REPO_ROOT / "layout/bin/run-bandgap-routed-flow.sh")],
            capture_output=True, text=True, env=env,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("KLT_ARTIFACT_BROKER", proc.stderr)
        self.assertFalse((cell / "staging").exists())
        self.assertEqual(sorted(p.name for p in (cell / "reports").iterdir()), before)


class TestInnerComposeRequest(unittest.TestCase):
    """The inner compose request `compose_inner()` serializes (issue #628).

    The retired MOS-gate label selector -- the `CORE_PIN_LABELS` table, the
    port-candidate search and the claimed-pad collection that fed `pins[]` --
    is gone: every gate node is drawn metal carrying its own schematic name
    now, so a second label on its pad would be the exact `A|B` rename the
    label-collision gate catches after extraction. What is contract-worthy
    after that retirement is the request file the flow hands `klt
    gen-compose`, so these tests pin it directly, with the external `klt`
    process stubbed out (the same shape the flow's own end-to-end run
    exercises, without the ~1 GB PDK).
    """

    def _compose(self, out_dir: Path):
        """Run `compose_inner()` against a stubbed `run_klt_json`.

        Returns `(request, returned, klt_calls, response)`; the two blocks'
        ports are irrelevant now (nothing consults them), so the inputs are
        just ids and origins.
        """
        calls = []
        response = {
            "schema": "stub.response/1",
            "cell_name": "probe_inner",
            "gds_path": str(out_dir / "probe_inner.gds"),
            "pdk": {"variant": "sky130A"},
            "bbox_um": {"x0": 0.0, "y0": 0.0, "x1": 4.0, "y1": 8.0},
        }

        def fake_run_klt_json(klt, *args, allow_exit=(0,)):
            calls.append({"args": list(args), "allow_exit": list(allow_exit)})
            return response

        real = gen_bandgap_routed.run_klt_json
        gen_bandgap_routed.run_klt_json = fake_run_klt_json
        try:
            returned = gen_bandgap_routed.compose_inner(
                "klt",
                out_dir,
                "sky130A",
                "probe_inner",
                ["blk_a", "blk_b"],
                {"blk_a": {"x": 1.5, "y": 2.5}, "blk_b": {"x": 0.0, "y": 40.0}},
            )
        finally:
            gen_bandgap_routed.run_klt_json = real
        request = json.loads((out_dir / "compose.inner.request.json").read_text())
        return request, returned, calls, response

    def test_pins_and_connectivity_are_deliberately_empty(self) -> None:
        """`pins[]` is empty because every gate node's own schematic name is
        drawn in metal by the bus overlay -- a label here renames a pad the
        route already owns. `connectivity[]` stays empty for the met1-vs-li1
        reasons in `compose_inner`'s docstring. A future edit that silently
        reintroduces either one changes the composed layout's meaning."""
        with tempfile.TemporaryDirectory() as tmp:
            request, _, _, _ = self._compose(Path(tmp))
        self.assertEqual(request["schema"], "klt.gen_compose.request/1")
        self.assertEqual(request["pins"], [])
        self.assertEqual(request["connectivity"], [])

    def test_placement_and_routing_are_carried_verbatim(self) -> None:
        """The request must state placement and routing exactly as the flow
        computed them: explicit strategy, the block order, the origins dict
        unchanged, and the met1 route width from the flow's own constant --
        any transform here would move geometry silently."""
        origins = {"blk_a": {"x": 1.5, "y": 2.5}, "blk_b": {"x": 0.0, "y": 40.0}}
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            request, _, _, _ = self._compose(out_dir)
            self.assertEqual(
                request["blocks"],
                [
                    {
                        "id": bid,
                        "generator_report": str(
                            (out_dir / f"{bid}.gen.json").resolve()
                        ),
                    }
                    for bid in ["blk_a", "blk_b"]
                ],
            )
        self.assertEqual(
            request["placement"],
            {"strategy": "explicit", "order": ["blk_a", "blk_b"], "origins_um": origins},
        )
        self.assertEqual(
            request["routing"],
            {"layer_role": "metal", "width_um": gen_bandgap_routed.ROUTE_WIDTH_UM},
        )
        self.assertEqual(request["pdk"], {"variant": "sky130A"})
        self.assertEqual(
            request["options"]["output"], str((out_dir / "probe_inner.gds").resolve())
        )

    def test_returns_the_compose_response_directly(self) -> None:
        """The retired empty label-list second return value is gone:
        `compose_inner()` returns the compose response itself, invokes
        `gen-compose` once on the serialized request path with exit 3
        allowed (partial success is a recorded result), and writes the
        response back as `compose.inner.json`."""
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            request, returned, calls, response = self._compose(out_dir)
            self.assertEqual(returned, response)
            self.assertEqual(len(calls), 1)
            self.assertEqual(
                calls[0]["args"][:2],
                ["gen-compose", str(out_dir / "compose.inner.request.json")],
            )
            self.assertEqual(calls[0]["allow_exit"], [0, 3])
            written = json.loads((out_dir / "compose.inner.json").read_text())
            self.assertEqual(written, response)


# ---------------------------------------------------------------------------
# Gate 3: the coverage-scoring check (schematic_net_coverage)
# ---------------------------------------------------------------------------
class TestCoverageScoringGate(unittest.TestCase):
    """`schematic_net_coverage()` scores acceptance criterion 1. It must never
    credit a node with connectivity that is not drawn -- that would turn the
    scoreboard from evidence into a claim.
    """

    def _row(self, routes: list[dict], net: str) -> dict:
        rows = layout_common.schematic_net_coverage(routes)
        self.assertEqual(
            len(rows),
            len(layout_common.SCHEMATIC_INTER_BLOCK_NETS),
            "every schematic inter-block node must be scored, drawn or not",
        )
        return next(row for row in rows if row["net"] == net)

    def test_no_routes_means_no_credit_anywhere(self) -> None:
        """The floorplan-skeleton baseline: a layout with zero drawn metal
        must score zero, with every block listed as missing."""
        rows = layout_common.schematic_net_coverage([])
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
                for spec in layout_common.SCHEMATIC_INTER_BLOCK_NETS
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
        for spec in layout_common.SCHEMATIC_INTER_BLOCK_NETS:
            for block in spec["blocks"]:
                self.assertIn(block, known, f"{spec['net']} names unknown block {block}")


# ---------------------------------------------------------------------------
# Gate 5 (issue #620): the MOS flavour gate -- the raw, pre-translation
# output of a PDK-bound extraction must bind every schematic MOS finger to
# the 5 V thick-oxide wrapper of its polarity.
# ---------------------------------------------------------------------------
class TestMosFlavourGate(unittest.TestCase):
    """`check_mos_flavour()` scores the raw PDK-bound netlist against the
    finger counts summed out of `reference.spice`. The layout could bind a
    thin-oxide card for every device and the curated-deck LVS path would
    never see it -- the curated deck maps both flavours to one generic
    class -- so this census is the only place the oxide flavour is
    observable, and it must fail on a single wrong card.
    """

    EXPECTED = {"nfet": 19, "pfet": 54}

    def test_reference_spice_sums_to_the_schematic_fingers(self) -> None:
        """The expectation is derived, not asserted: summing `m=` over the
        committed reference's MOS cards gives 19 NFET / 54 PFET fingers
        (16 of the PFET fingers are MMCC, the compensation cap)."""
        reference = (
            REPO_ROOT / "layout/bandgap-core/reference.spice"
        ).read_text()
        self.assertEqual(
            gen_bandgap_routed.expected_mos_fingers(reference),
            self.EXPECTED,
        )

    def test_m_multiplier_defaults_to_one(self) -> None:
        """A card with no `m=` is one finger, not zero or an error."""
        self.assertEqual(
            gen_bandgap_routed.expected_mos_fingers(
                "MMPC2 NG NG NC1 VDD pfet L=20U W=1U\n"
            ),
            {"nfet": 0, "pfet": 1},
        )

    def test_non_mos_cards_are_ignored(self) -> None:
        """Q cards, R cards, comments and continuations carry no finger."""
        self.assertEqual(
            gen_bandgap_routed.expected_mos_fingers(
                "* comment\n"
                "Q$1 (C=VSS,B=VSS,E=VA) PNP\n"
                "XR2A VA VOUT VSS sky130_fd_pr__res_high_po w=1.05 l=255\n"
                "+ N=49\n"
            ),
            {"nfet": 0, "pfet": 0},
        )

    @staticmethod
    def _raw_netlist(nfet_hvi: int, pfet_hvi: int, extra: str = "") -> str:
        lines = [
            "* extracted by klt extract --deck sky130",
            "",
            f".SUBCKT bandgap_core_routed VDD VSS VOUT",
        ]
        lines += [
            f"X$N{i} VSS GDRV VSS VSS sky130_fd_pr__nfet_g5v0d10v5 L=0.5 W=10"
            for i in range(nfet_hvi)
        ]
        lines += [
            f"X$P{i} VDD GDRV VDD VDD sky130_fd_pr__pfet_g5v0d10v5 L=20 W=30"
            for i in range(pfet_hvi)
        ]
        lines.append(extra)
        lines.append(".ENDS bandgap_core_routed")
        return "\n".join(lines) + "\n"

    def test_all_fingers_on_the_5v_wrappers_passes(self) -> None:
        verdict = gen_bandgap_routed.check_mos_flavour(
            self._raw_netlist(19, 54), self.EXPECTED
        )
        self.assertTrue(verdict["clean"], verdict)
        self.assertEqual(
            verdict["observed"],
            {"nfet": 19, "pfet": 54},
        )

    def test_a_single_thin_oxide_card_fails_twice_over(self) -> None:
        """The mixed-flavour negative control: total NFET/PFET counts held
        constant, exactly one card swapped to its thin-oxide counterpart.
        The gate must fail, naming both the short count and the unexpected
        model -- 'the rest bind correctly' must not be enough."""
        netlist = self._raw_netlist(
            18,
            54,
            extra=(
                "X$BAD VSS GDRV VSS VSS sky130_fd_pr__nfet_01v8 L=0.5 W=10"
            ),
        )
        verdict = gen_bandgap_routed.check_mos_flavour(netlist, self.EXPECTED)
        self.assertFalse(verdict["clean"])
        self.assertIn("nfet", verdict["mismatches"])
        self.assertEqual(verdict["mismatches"]["nfet"]["observed"], 18)
        self.assertEqual(
            verdict["unexpected_mos_models"],
            {"sky130_fd_pr__nfet_01v8": 1},
        )

    def test_one_missing_card_fails(self) -> None:
        """A gate that only checked 'no unexpected models' would pass a
        layout that simply dropped a device; the exact-count half catches
        it."""
        verdict = gen_bandgap_routed.check_mos_flavour(
            self._raw_netlist(18, 54), self.EXPECTED
        )
        self.assertFalse(verdict["clean"])
        self.assertEqual(verdict["mismatches"]["nfet"]["expected"], 19)

    def test_one_extra_card_fails(self) -> None:
        verdict = gen_bandgap_routed.check_mos_flavour(
            self._raw_netlist(20, 54), self.EXPECTED
        )
        self.assertFalse(verdict["clean"])

    def test_resistor_and_pnp_wrapper_cards_are_not_counted(self) -> None:
        """A PDK-bound extraction of this cell also emits X cards with
        empty/param models for resistors and PNPs; the census is a MOS-only
        census (`*fet*` match) and must not choke or count them."""
        counts = gen_bandgap_routed.raw_mos_card_counts(
            "X$1 VOUT TRIM_A VSS l=5 w=1.05 N=1\n"
            "+ sky130_fd_pr__res_high_po\n"
            "X$2 (C=VSS,B=VSS,E=VA) sky130_fd_pr__pnp_05v5_W0p68L0p68\n"
        )
        self.assertEqual(counts, {})

    # -- regression corpus: the original thin-oxide GDS ---------------------
    def test_fails_on_the_original_gds_raw_extraction(self) -> None:
        """The committed raw PDK-bound extraction of record
        `20260923-070209-dbd57a9`'s GDS (see
        `layout/tests/fixtures/README.md` for the byte-exact reproduction):
        19 + 54 thin-oxide `*_01v8` cards, zero 5 V cards. The gate this
        issue adds must fail on exactly the layout that motivated it."""
        netlist = (
            REPO_ROOT
            / "layout/tests/fixtures/20260923-070209-dbd57a9.pdk-extract.spice"
        ).read_text()
        verdict = gen_bandgap_routed.check_mos_flavour(netlist, self.EXPECTED)
        self.assertFalse(verdict["clean"])
        self.assertEqual(
            verdict["observed"], {"nfet": 0, "pfet": 0}
        )
        self.assertEqual(
            verdict["unexpected_mos_models"],
            {
                "sky130_fd_pr__nfet_01v8": 19,
                "sky130_fd_pr__pfet_01v8": 54,
            },
        )

    def test_every_hvi_block_declares_the_flavour(self) -> None:
        """Every MOS block (core, amplifier including the PMOS compensation
        capacitor, startup injector, both polarities) draws the thick-oxide
        flavour; a block added without it is a 1.8 V device in a 5 V
        schematic."""
        hvi = gen_bandgap_routed.mos_hvi_blocks()
        self.assertEqual(
            {b["id"] for b in hvi},
            {
                "core_mirror", "amp_input_pair", "amp_nload", "amp_pmirr",
                "amp_nmirr", "amp_cc", "su_clamp", "su_sense", "su_ref",
                "su_inj",
            },
        )
        for block in hvi:
            with self.subTest(block=block["id"]):
                self.assertIn(block["params"]["flavor"], ("nfet", "pfet"))


# ---------------------------------------------------------------------------
# Gate 6 (issue #620): the HV rule group of the pinned PDK's own source
# deck, zero applicable violations on the composed GDS.
# ---------------------------------------------------------------------------
class TestHvRuleScoring(unittest.TestCase):
    """`score_hv_rule_counts()` splits one DRC run's per-category counts
    into the HV group (gated) and the rest (reported), so a thick-oxide
    enclosure violation fails the flow while the same run's pre-existing
    non-HV FEOL findings stay evidence, not gate rows.
    """

    def test_su_inj_shaped_counts_are_not_clean(self) -> None:
        """The isolated injector control's own marker shape: three
        `hvdifftap.22` (hvi enclosure of diffusion) plus non-HV findings.
        This is the failing-enclosure shape the flow's negative control
        must produce from the raw generator output."""
        scored = gen_bandgap_routed.score_hv_rule_counts(
            {"hvdifftap.22": 3, "licon.15": 4}
        )
        self.assertFalse(scored["clean"])
        self.assertEqual(scored["hv_violation_count"], 3)
        self.assertEqual(scored["hv_violations"], {"hvdifftap.22": 3})
        self.assertEqual(scored["non_hv_violation_count"], 4)

    def test_non_hv_findings_alone_are_clean(self) -> None:
        """The composed cell's pre-existing FEOL/BEOL findings (licon,
        rpm, OFFGRID, ...) are the same findings the curated deck reports
        or the generator geometry triggers regardless of oxide flavour --
        they do not gate this check."""
        scored = gen_bandgap_routed.score_hv_rule_counts(
            {"licon.1": 2676, "rpm.2": 120, "ct_OFFGRID": 240}
        )
        self.assertTrue(scored["clean"])
        self.assertEqual(scored["non_hv_violation_count"], 3036)

    def test_every_hv_prefix_is_gated(self) -> None:
        """hvi.*, hvdifftap.*, hvnwell.*/hvnwel.*, hvpoly.*, hvntm.* --
        one marker in any of them is a violation."""
        for cat in (
            "hvi.1", "hvi.2", "hvdifftap.19", "hvnwell.8", "hvnwel.9",
            "hvpoly.13", "hvntm.3",
        ):
            with self.subTest(category=cat):
                self.assertFalse(
                    gen_bandgap_routed.score_hv_rule_counts({cat: 1})["clean"]
                )

    def test_empty_counts_are_clean(self) -> None:
        scored = gen_bandgap_routed.score_hv_rule_counts({})
        self.assertTrue(scored["clean"])
        self.assertEqual(scored["hv_violations"], {})


class TestWellBoxClassification(unittest.TestCase):
    """`classify_well_boxes()` assigns the composed GDS's merged n-wells to
    the tie nets that own them, for the ERC specs re-derived per run. A
    well matched by neither net (or both) is an error -- a tie declaration
    that guessed would silently under-report exactly the way the ERC
    negative control exists to catch."""

    BOXES = [
        {"bbox_um": [0.0, 0.0, 10.0, 10.0]},
        {"bbox_um": [20.0, 0.0, 30.0, 10.0]},
        {"bbox_um": [40.0, 0.0, 50.0, 10.0]},
    ]

    def test_vdd_and_vss_points_split_the_wells(self) -> None:
        assigned = gen_bandgap_routed.classify_well_boxes(
            self.BOXES,
            vdd_points=[(5.0, 5.0), (25.0, 5.0)],
            vss_points=[(45.0, 5.0)],
        )
        self.assertEqual(len(assigned["VDD"]), 2)
        self.assertEqual(len(assigned["VSS"]), 1)

    def test_a_well_matching_neither_net_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            gen_bandgap_routed.classify_well_boxes(
                self.BOXES, vdd_points=[(5.0, 5.0)], vss_points=[(25.0, 5.0)]
            )

    def test_a_well_matching_both_nets_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            gen_bandgap_routed.classify_well_boxes(
                self.BOXES,
                vdd_points=[(5.0, 5.0), (25.0, 5.0), (45.0, 5.0)],
                vss_points=[(5.0, 5.0), (25.0, 5.0), (45.0, 5.0)],
            )


# ---------------------------------------------------------------------------
# The gate composition itself
# ---------------------------------------------------------------------------
class TestFlowGate(unittest.TestCase):
    """`flow_gate()` is the flow's exit status. Its job is to fail on any one
    condition -- an "and" written as ten separate rows so a failing run can
    name which.
    """

    PASSING = {
        "drc_clean": True,
        "within_budget": True,
        "full_scale_ladder": True,
        "r2_leg_matches": True,
        "all_classes": True,
        "pin_count": 23,
        "met1_conflicts": [],
        "merged_pin_names": [],
        "split_routed": {},
        "met2_drc_clean": True,
        "mos_flavour_clean": True,
        "hv_drc_clean": True,
        "erc_supply_clean": True,
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
            # `full_scale_ladder` above is about the ladder's unit *count*;
            # this one is about the *length* those units add up to, which is
            # what design/bandgap_core.sch actually specifies and what sets
            # K = R2/R1. The 286-um-vs-270-um defect passed the count check
            # for nineteen increments (issue #91).
            "r2_leg_length_matches": {"r2_leg_matches": False},
            "device_classes_present": {"all_classes": False},
            "pins_promoted": {"pin_count": 0},
            "no_drawn_shorts": {"met1_conflicts": [{"nets": ["VDD", "VSS"]}]},
            "no_merged_pin_names": {"merged_pin_names": ["TAIL|VOUT"]},
            "no_split_routed_nets": {"split_routed": {"VDD": 2}},
            # The escape plane's own DRC. `drc_clean` above is `klt drc`'s
            # verdict; this row is the flow's independent cross-check of
            # the same rule set (`met2.area.1` included at the pinned 0.8.0)
            # at a stricter enclosure bar (0.085 um on every edge), plus the
            # orphan-via check `klt drc` passes clean -- so
            # a curated-deck regression on this hand-drawn plane still
            # fails the flow (layout/generator-notes.md#met2-escape-note).
            "met2_drc_clean": {"met2_drc_clean": False},
            # Issue #620: the schematic's MOS cards are all 5 V thick-oxide
            # devices -- one thin-oxide binding among 72 correct ones fails
            # this row, because the curated LVS path cannot see the
            # difference at all.
            "mos_flavour_bound": {"mos_flavour_clean": False},
            # The HV rule group of the pinned PDK's own source deck (FEOL
            # enabled, negative enclosure control included): the hvi/npc/
            # nwell enclosures the curated deck carries no rule for.
            "hv_drc_clean": {"hv_drc_clean": False},
            # Supply/tie ERC on the exact composed GDS, gated exactly like
            # run-erc-supply-flow.sh gates the committed records.
            "erc_supply_clean": {"erc_supply_clean": False},
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
