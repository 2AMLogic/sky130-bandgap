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
3. **The coverage-scoring check** -- `gen_bandgap_routed.schematic_net_coverage()`.
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

Standard library only (`unittest`), matching every other script under
`layout/`. Run directly, or via:

    npm run test:unit
    python3 -m unittest discover --start-directory layout/tests
"""

from __future__ import annotations

import contextlib
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "layout" / "bin"))

import gen_bandgap_routed  # noqa: E402  -- resolved from layout/bin, above
import met1_bus  # noqa: E402


@contextlib.contextmanager
def met1_only():
    """Disable `_connect`'s met2 escape for the duration of the block.

    The met2 escape plane (MET2_ESCAPE_NOTE) is a last-resort fallback that
    is available to essentially every hop, because met2 starts empty -- so
    with it on, "the met1 search ran out of options" and "the router gave
    up" stop being the same question. Every test below that asserts what the
    *met1* search does when it is boxed in wraps itself in this, so it keeps
    testing the thing it names. Tests of the escape itself do not.
    """
    previous = gen_bandgap_routed.MET2_ESCAPE_ENABLED
    gen_bandgap_routed.MET2_ESCAPE_ENABLED = False
    try:
        yield
    finally:
        gen_bandgap_routed.MET2_ESCAPE_ENABLED = previous


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
        terminal = gen_bandgap_routed.bulk_terminal("core_mirror")
        self.assertEqual(terminal["block"], "core_mirror")
        self.assertEqual(terminal["ports"], list(gen_bandgap_routed.BULK_TAP_PORTS))
        self.assertNotIn("port", terminal, "a single pinned tap is the bug")

    def test_the_offered_set_is_the_generators_own_tap_names(self) -> None:
        """`klt gen diff_pair` reports its ring taps as `TAP_N`/`TAP_S`/
        `TAP_E`; a typo here would silently drop a candidate."""
        self.assertEqual(
            set(gen_bandgap_routed.BULK_TAP_PORTS), {"TAP_N", "TAP_S", "TAP_E"}
        )

    def test_no_escape_stub(self) -> None:
        """A ring tap already sits on the block's outer edge facing open
        floorplan, so the router leaves from the pad itself."""
        self.assertFalse(gen_bandgap_routed.bulk_terminal("amp_pmirr")["escape"])

    def test_every_bulk_terminal_names_a_real_block(self) -> None:
        """The declared inter-block table is hand-written; a bulk terminal on
        a block that is not placed would raise deep inside the router."""
        block_ids = {b["id"] for b in gen_bandgap_routed.BLOCKS}
        for spec in gen_bandgap_routed.INTER_BLOCK_MET1:
            for terminal in spec["terminals"]:
                if "ports" in terminal:
                    with self.subTest(net=spec["net"], block=terminal["block"]):
                        self.assertIn(terminal["block"], block_ids)

    def test_the_router_resolves_a_ports_terminal_to_one_of_its_taps(self) -> None:
        """The `ports` terminal shape end to end: `_route_one_net` turns it
        into candidates, picks one, claims exactly that pad, and names it
        `<block>.<port>` -- the form `routed_ports()` parses."""
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
                    gen_bandgap_routed.bulk_terminal("blk"),
                    gen_bandgap_routed.bulk_terminal("other"),
                ],
            }
        }
        used: set[tuple[str, str]] = set()
        route = gen_bandgap_routed._route_one_net(
            met1_bus.Met1Bus(), "VDD", specs, reports, origins, {}, {}, used, {}
        )
        self.assertTrue(route["routed"], route)
        self.assertEqual(sorted(route["blocks"]), ["blk", "other"])
        for name in route["terminals"]:
            block, _, port = name.partition(".")
            self.assertIn(port, gen_bandgap_routed.BULK_TAP_PORTS)
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
                    gen_bandgap_routed.bulk_terminal("blk"),
                    gen_bandgap_routed.bulk_terminal("other"),
                ],
            }
        }
        used = {("blk", "TAP_S")}
        route = gen_bandgap_routed._route_one_net(
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
                "terminals": [gen_bandgap_routed.bulk_terminal("blk")],
            }
        }
        with self.assertRaises(KeyError):
            gen_bandgap_routed._route_one_net(
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
            # verdict, and the curated sky130 deck still carries no met2
            # min-area rule (`m2.6`, klayout-tools#513/#515 left it out) --
            # so without this row an undersized met2 area would pass the
            # whole flow (MET2_ESCAPE_NOTE).
            "met2_drc_clean": {"met2_drc_clean": False},
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
            with met1_only():
                result = gen_bandgap_routed._connect(
                    bus, "N1", (0.0, 0.0), (10.0, 10.0), channels={}
                )
        finally:
            gen_bandgap_routed.DETOUR_OFFSETS_UM = detours
        self.assertIsNone(result)
        self.assertEqual(bus.met1_rects, rects_before)
        self.assertEqual(bus.shapes, shapes_before)

    def test_blocker_counts_tally_every_distinct_veto_not_just_the_last(
        self,
    ) -> None:
        """`_LAST_BLOCKER` (used for `blocked_by`) is whichever candidate a
        search happened to check last -- issue #62's `matching-plan.md`
        Section 7g found that misleading on a hop contested by several
        already-drawn nets at once, not just one. `_BLOCKER_COUNTS` (surfaced
        by `_draw_chain` as `blocked_by_counts`) tallies every veto a single
        `_connect()` call sees, so the dominant contributor is visible even
        when it is not the last one checked."""
        bus = met1_bus.Met1Bus()
        bus.net("WALL_A")
        bus.hseg(9.85, 10.15, 0.0)
        bus.net("WALL_B")
        bus.hseg(-0.15, 0.15, 10.0)
        detours = gen_bandgap_routed.DETOUR_OFFSETS_UM
        gen_bandgap_routed.DETOUR_OFFSETS_UM = [0.0]
        try:
            with met1_only():
                result = gen_bandgap_routed._connect(
                    bus, "N1", (0.0, 0.0), (10.0, 10.0), channels={}
                )
        finally:
            gen_bandgap_routed.DETOUR_OFFSETS_UM = detours
        self.assertIsNone(result)
        # Both walls vetoed at least one candidate elbow (WALL_A the one that
        # turns first at x=10, WALL_B the one that turns first at y=10) --
        # both must be present, not just whichever was checked last.
        self.assertEqual(
            set(gen_bandgap_routed._BLOCKER_COUNTS), {"WALL_A", "WALL_B"}
        )
        self.assertGreater(gen_bandgap_routed._BLOCKER_COUNTS["WALL_A"], 0)
        self.assertGreater(gen_bandgap_routed._BLOCKER_COUNTS["WALL_B"], 0)

    def test_blocker_counts_reset_at_the_start_of_each_connect_call(
        self,
    ) -> None:
        """A tally left over from a previous hop's failed search must not
        leak into the next hop's `blocked_by_counts` -- each `_connect()`
        call reports only what *it* saw."""
        bus = met1_bus.Met1Bus()
        bus.net("WALL")
        bus.hseg(9.85, 10.15, 0.0)
        bus.hseg(-0.15, 0.15, 10.0)
        detours = gen_bandgap_routed.DETOUR_OFFSETS_UM
        gen_bandgap_routed.DETOUR_OFFSETS_UM = [0.0]
        try:
            gen_bandgap_routed._connect(
                bus, "N1", (0.0, 0.0), (10.0, 10.0), channels={}
            )
            self.assertIn("WALL", gen_bandgap_routed._BLOCKER_COUNTS)
            # A second, unrelated call that never collides with anything
            # must start from a clean tally.
            result = gen_bandgap_routed._connect(
                bus, "N2", (20.0, 20.0), (30.0, 25.0), channels={}
            )
        finally:
            gen_bandgap_routed.DETOUR_OFFSETS_UM = detours
        self.assertIsNotNone(result)
        self.assertEqual(dict(gen_bandgap_routed._BLOCKER_COUNTS), {})


class TestDrawChainBlockedByCounts(unittest.TestCase):
    """`_draw_chain()` is what a failed hop's report -- `blocked_by` and
    `blocked_by_counts` -- actually comes from; see TestConnectRouter above
    for `_connect()`/`_BLOCKER_COUNTS` itself."""

    def test_failed_hop_carries_both_the_last_blocker_and_the_full_breakdown(
        self,
    ) -> None:
        bus = met1_bus.Met1Bus()
        bus.net("WALL_A")
        bus.hseg(9.85, 10.15, 0.0)
        bus.net("WALL_B")
        bus.hseg(-0.15, 0.15, 10.0)
        detours = gen_bandgap_routed.DETOUR_OFFSETS_UM
        gen_bandgap_routed.DETOUR_OFFSETS_UM = [0.0]
        plan = [
            {"name": "P0", "pad": (0.0, 0.0), "via": False},
            {"name": "P1", "pad": (10.0, 10.0), "via": False},
        ]
        try:
            with met1_only():
                hops, routed = gen_bandgap_routed._draw_chain(bus, "N1", plan)
        finally:
            gen_bandgap_routed.DETOUR_OFFSETS_UM = detours
        self.assertFalse(routed)
        self.assertEqual(len(hops), 1)
        hop = hops[0]
        self.assertFalse(hop["routed"])
        self.assertIn(hop["blocked_by"], {"WALL_A", "WALL_B"})
        self.assertEqual(set(hop["blocked_by_counts"]), {"WALL_A", "WALL_B"})
        # Most-frequent first: both walls are vetoed at least once here, but
        # the ordering contract (descending count) must hold regardless of
        # which two nets a real floorplan's congestion names.
        counts = list(hop["blocked_by_counts"].values())
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_successful_hop_carries_no_blocker_fields(self) -> None:
        bus = met1_bus.Met1Bus()
        plan = [
            {"name": "P0", "pad": (0.0, 0.0), "via": False},
            {"name": "P1", "pad": (10.0, 5.0), "via": False},
        ]
        hops, routed = gen_bandgap_routed._draw_chain(bus, "N1", plan)
        self.assertTrue(routed)
        self.assertEqual(len(hops), 1)
        self.assertNotIn("blocked_by", hops[0])
        self.assertNotIn("blocked_by_counts", hops[0])


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
        # met1-only: this fixture's whole point is that `B` is boxed in on
        # met1 and only a rip-up of `A` frees it. With the met2 escape on,
        # `B` simply hops over `A` and the repair pass has nothing to repair
        # -- a real and desirable property of the router, but not the one
        # these tests are about (see met1_only()).
        with met1_only():
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

        with met1_only():
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
        with met1_only():
            results = [
                gen_bandgap_routed._route_one_net(
                    bus, "B", specs, {}, {}, trunks, {}, used_ports, channels,
                )
            ]
        self.assertFalse(results[0]["routed"])
        self.assertEqual(results[0]["hops"][0]["blocked_by"], "WALL")

        mark_before_repair = bus.mark()
        with met1_only():
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

        with met1_only():
            gen_bandgap_routed._repair_unrouted_hops(
                bus, sequence, specs, {}, {}, trunks, {}, used_ports, channels,
                marks, port_snapshots, results,
            )

        self.assertFalse(results[1]["routed"])
        self.assertEqual(results[0]["terminals"], original_terminals)
        self.assertEqual(bus.mark(), mark_before_repair)
        self.assertEqual(bus.conflicts(), [])


class TestMet2DrcCoverageNote(unittest.TestCase):
    """`gen_bandgap_routed.met2_drc_coverage_note()` -- record.md's prose on
    whether `klt drc` itself checked the escape plane, issue #62's
    twenty-sixth increment.

    Extracted from an inline block that used to hardcode "`klt drc` does not
    check any of this geometry" unconditionally, one sentence before quoting
    the run's own `coverage.layers_in_stream_without_rules` list -- which,
    once klayout-tools#513 (merged via #515) added the met2/via1 DRC rules,
    started naming *neither* escape-plane layer as unchecked, so the record
    contradicted itself in the same paragraph. This function makes the claim
    track the measured `coverage` list instead of a fixed increment-era fact,
    and these tests exercise both branches directly -- something the old
    inline form, buried in `main()`'s klt-and-PDK-dependent flow, could not
    be given without a full flow run.
    """

    def test_both_escape_layers_unchecked_reports_the_gap(self) -> None:
        note = gen_bandgap_routed.met2_drc_coverage_note(["68/44", "69/20"])
        self.assertIn("does not fully check", note)
        self.assertIn("68/44, 69/20", note)

    def test_one_escape_layer_unchecked_is_still_reported_as_a_gap(self) -> None:
        """Partial coverage (e.g. a `klt` regression that drops just the via
        rule) must not read as fully clean."""
        note = gen_bandgap_routed.met2_drc_coverage_note(["68/44"])
        self.assertIn("does not fully check", note)
        self.assertIn("**68/44**", note)
        self.assertNotIn("69/20**", note)

    def test_neither_escape_layer_unchecked_reports_current_coverage(self) -> None:
        """The state as of klayout-tools#513/#515: `coverage` no longer
        names either escape-plane layer, so the note must say `klt drc` now
        checks them (not the removed "does not check any" claim) and must
        still name the one rule (`m2.6`) neither `klt drc` nor this
        function's own claim of "checked" covers."""
        note = gen_bandgap_routed.met2_drc_coverage_note(
            ["64/20", "65/44", "66/13", "68/5", "82/44", "83/20", "86/20", "94/20"]
        )
        self.assertIn("now checks most", note)
        self.assertNotIn("does not fully check", note)
        self.assertIn("m2.6", note)

    def test_empty_unchecked_list_still_names_the_m2_6_gap(self) -> None:
        note = gen_bandgap_routed.met2_drc_coverage_note([])
        self.assertIn("now checks most", note)
        self.assertIn("m2.6", note)
        self.assertIn("`--`", note)  # the empty coverage list itself is quoted


# ---------------------------------------------------------------------------
# The met2 escape plane (issue #62's eighteenth increment).
#
# This is the mechanism that closed acceptance criterion 1 after PRs #75-#88
# exhausted every met1-side lever, so its own failure modes need the same
# unit coverage the met1 gates have. Two of them are silent in exactly the
# way this file exists to catch:
#
#   * a met2 wire drawn across another node's met2 is a short that `klt drc`
#     cannot see -- its met2 rules (klayout-tools#513/#515) are geometric,
#     not net-aware, so two touching nets are not a spacing violation
#     (MET2_ESCAPE_NOTE);
#   * a via1 stack that misses its own met1 leaves the node in two floating
#     pieces while every per-plane component count still reads 1.
# ---------------------------------------------------------------------------
class TestMet2Escape(unittest.TestCase):
    """`_connect_met2()` -- the last-resort lift onto met2."""

    def _boxed_in(self) -> met1_bus.Met1Bus:
        """A bus whose met1 is walled off at both ends of the hop, so no met1
        form can clear (the same fixture `TestConnectRouter`'s "every
        candidate fails" test uses)."""
        bus = met1_bus.Met1Bus()
        bus.net("WALL")
        bus.hseg(9.85, 10.15, 0.0)
        bus.hseg(-0.15, 0.15, 10.0)
        return bus

    def test_met1_is_tried_first_and_met2_is_not_touched_when_it_clears(
        self,
    ) -> None:
        """The escape must stay an escape. A hop with a clear met1 path draws
        no via1 and no met2 -- otherwise every hop would migrate onto the one
        plane `klt drc` does not check."""
        bus = met1_bus.Met1Bus()
        result = gen_bandgap_routed._connect(
            bus, "N1", (0.0, 0.0), (10.0, 5.0), channels={}
        )
        self.assertIsNotNone(result)
        self.assertNotIn("met2", result)
        self.assertEqual(bus.met2_rects, [])
        self.assertEqual(bus.via1_count, 0)

    def test_a_hop_met1_cannot_clear_escapes_onto_met2(self) -> None:
        bus = self._boxed_in()
        detours = gen_bandgap_routed.DETOUR_OFFSETS_UM
        gen_bandgap_routed.DETOUR_OFFSETS_UM = [0.0]
        try:
            result = gen_bandgap_routed._connect(
                bus, "N1", (0.0, 0.0), (10.0, 10.0), channels={}
            )
        finally:
            gen_bandgap_routed.DETOUR_OFFSETS_UM = detours
        self.assertIsNotNone(result)
        self.assertTrue(result["met2"])
        self.assertEqual(len(result["via1_drops"]), 2)
        # One via1 stack per end, and met2 wire between them.
        self.assertEqual(bus.via1_count, 2)
        self.assertTrue(bus.met2_rects)
        # And the escape did not itself short anything on either plane.
        self.assertEqual(bus.conflicts(), [])

    def test_the_escaped_node_is_one_conductor_across_both_planes(self) -> None:
        """The whole point: `components()` must see the met1 stub, the met2
        wire and the via1 stacks as ONE piece. If it counted planes
        separately a met2 escape would score 2 and trip the split-node gate;
        if it ignored met2 entirely it would score 2 as well, and the flow
        would report a routed node it had actually drawn in two halves."""
        bus = self._boxed_in()
        detours = gen_bandgap_routed.DETOUR_OFFSETS_UM
        gen_bandgap_routed.DETOUR_OFFSETS_UM = [0.0]
        try:
            gen_bandgap_routed._connect(
                bus, "N1", (0.0, 0.0), (10.0, 10.0), channels={}
            )
        finally:
            gen_bandgap_routed.DETOUR_OFFSETS_UM = detours
        self.assertEqual(bus.components()["N1"], 1)

    def test_a_via1_that_misses_its_met1_is_reported_as_a_split_node(
        self,
    ) -> None:
        """The inverse, drawn by hand: met2 wire and met1 stub of one node
        with the via1 stack somewhere else entirely. Per-plane counting would
        say 1 for each plane; the cross-plane graph must say 2."""
        bus = met1_bus.Met1Bus()
        bus.net("N1")
        bus.hseg(0.0, 5.0, 0.0)  # met1 stub
        bus.hseg2(20.0, 30.0, 20.0)  # met2 wire, nowhere near it
        self.assertEqual(bus.components()["N1"], 2)

    def test_two_nodes_met2_crossing_is_a_conflict_klt_drc_cannot_see(
        self,
    ) -> None:
        """`conflicts()` must score met2 as well as met1. Nothing downstream
        does: `klt drc`'s curated met2 rules (klayout-tools#513/#515) are
        geometric spacing/width/enclosure checks, not net-aware -- two
        different nets' met2 that actually touch have no gap to measure, so
        no spacing rule fires -- and `klt extract` would read the short as
        connectivity."""
        bus = met1_bus.Met1Bus()
        bus.net("A")
        bus.hseg2(0.0, 10.0, 0.0)
        bus.net("B")
        bus.vseg2(5.0, -5.0, 5.0)
        found = [c for c in bus.conflicts() if c.get("layer") == "met2"]
        self.assertEqual(len(found), 1)
        self.assertEqual(set(found[0]["nets"]), {"A", "B"})

    def test_two_nodes_via1_cuts_too_close_is_a_conflict(self) -> None:
        """sky130 `via.2` is 0.17 um. Two different nodes' cuts inside that
        are effectively a short and are invisible to the curated deck."""
        bus = met1_bus.Met1Bus()
        bus.net("A")
        bus.via1(0.0, 0.0)
        bus.net("B")
        bus.via1(0.2, 0.0)  # 0.05 um edge-to-edge, well under via.2
        via_conflicts = [c for c in bus.conflicts() if "via_a" in c]
        self.assertTrue(via_conflicts)

    def test_met2_and_met1_of_different_nodes_may_overlap_freely(self) -> None:
        """The reason the escape works at all: met2 crossing over another
        node's met1 is ordinary routing, not a short, and `conflicts()` must
        not confuse the two planes."""
        bus = met1_bus.Met1Bus()
        bus.net("A")
        bus.hseg(0.0, 10.0, 0.0)
        bus.net("B")
        bus.hseg2(0.0, 10.0, 0.0)  # exactly on top, different plane
        self.assertEqual(bus.conflicts(), [])

    def test_a_failed_met2_escape_leaves_no_residue(self) -> None:
        """Same contract as `_connect`'s met1 rollback: a met2 escape that
        cannot be placed must restore every plane it speculatively drew on,
        or the next hop is searched against phantom geometry."""
        bus = met1_bus.Met1Bus()
        bus.net("WALL")
        bus.hseg(9.85, 10.15, 0.0)
        bus.hseg(-0.15, 0.15, 10.0)
        # Box the met1 drop points in too, so no via1 landing pad fits at
        # either end and the escape cannot even be entered.
        bus.net("PADWALL")
        for dx in (-2.0, -1.6, -1.2, -0.8, -0.4, 0.0, 0.4, 0.8, 1.2, 1.6, 2.0):
            bus.hseg(dx - 0.2, dx + 0.2, 0.4)
            bus.hseg(dx - 0.2, dx + 0.2, -0.4)
        mark = bus.mark()
        detours = gen_bandgap_routed.DETOUR_OFFSETS_UM
        gen_bandgap_routed.DETOUR_OFFSETS_UM = [0.0]
        try:
            result = gen_bandgap_routed._connect(
                bus, "N1", (0.0, 0.0), (10.0, 10.0), channels={}
            )
        finally:
            gen_bandgap_routed.DETOUR_OFFSETS_UM = detours
        if result is None:
            self.assertEqual(bus.mark(), mark)
        else:
            # If it did find room, it must at least still be short-free.
            self.assertEqual(bus.conflicts(), [])

    def test_mark_and_restore_cover_the_met2_accumulators(self) -> None:
        bus = met1_bus.Met1Bus()
        bus.net("N1")
        mark = bus.mark()
        bus.via1(0.0, 0.0)
        bus.hseg2(0.0, 5.0, 0.0)
        self.assertTrue(bus.met2_rects)
        self.assertEqual(bus.via1_count, 1)
        bus.restore(mark)
        self.assertEqual(bus.met2_rects, [])
        self.assertEqual(bus.via1_xy, [])
        self.assertEqual(bus.via1_count, 0)
        self.assertEqual(bus.shapes, [])
        # And the de-dup ledger was rolled back too, so the same via can be
        # drawn again rather than silently vanishing.
        bus.via1(0.0, 0.0)
        self.assertEqual(bus.via1_count, 1)

    def test_met2_wire_count_is_tracked_separately_from_met1(self) -> None:
        """Issue #93: `hseg2()`/`vseg2()` used to bump the shared
        `wire_count`, so the emitted `met1_wire_count` silently tallied met2
        segments too. `met2_wire_count` must count only met2 segments, and
        `wire_count` (emitted as `met1_wire_count`) must stay met1-only."""
        bus = met1_bus.Met1Bus()
        bus.net("N1")
        bus.hseg(0.0, 5.0, 0.0)  # met1
        bus.vseg(5.0, 0.0, 5.0)  # met1
        bus.hseg2(0.0, 5.0, 10.0)  # met2
        self.assertEqual(bus.wire_count, 2)
        self.assertEqual(bus.met2_wire_count, 1)

    def test_mark_and_restore_cover_met2_wire_count(self) -> None:
        bus = met1_bus.Met1Bus()
        bus.net("N1")
        bus.hseg2(0.0, 5.0, 0.0)
        mark = bus.mark()
        bus.hseg2(10.0, 15.0, 0.0)
        self.assertEqual(bus.met2_wire_count, 2)
        bus.restore(mark)
        self.assertEqual(bus.met2_wire_count, 1)

    def test_met2_drop_backtracks_off_a_foreign_met2_wire_with_no_met1_nearby(
        self,
    ) -> None:
        """Issue #93: `_met2_drop()` used to check only the met1 landing pad
        against a foreign node, so a foreign met2 wire with no met1 anywhere
        near the drop point sailed straight through -- the met1 check saw
        nothing to object to, and the via1 stack landed right on top of it.
        `conflicts()` catches the resulting met2 short today (this cannot
        ship), but only after the fact; this asserts the search itself now
        keeps walking the offset ladder past the blocked point instead of
        committing to it."""
        bus = met1_bus.Met1Bus()
        # A foreign met2 wire straddling the origin, with no met1 anywhere
        # near it -- isolates the met2-landing-pad half of the guard.
        bus.net("F").hseg2(-1.0, 1.0, 0.0)
        drop = gen_bandgap_routed._met2_drop(bus, "N1", 0.0, 0.0)
        self.assertIsNotNone(drop)
        self.assertNotEqual(drop, (0.0, 0.0))
        self.assertEqual(bus.conflicts(), [])

    def test_met2_drop_backtracks_off_a_same_node_notch(self) -> None:
        """Issue #91's re-run. `_met2_drop()` rejected only *foreign* metal
        under its landing pad, so a pad could land 0.12 um from a wire of its
        **own** node and notch it. `met1.space.1` does not exempt same-node
        edges -- only touching ones -- and the pad is 0.32 um where the stub
        reaching it is 0.24, so the pad overhangs its own stub by 0.04 um on
        each side and that overhang is what lands in the gap. Invisible to
        `conflicts()`, which compares different nets only; `klt drc` was the
        only thing that saw it. Here the drop must walk past the notching
        point rather than commit to it."""
        bus = met1_bus.Met1Bus()
        # This net's own wire, its top edge 0.12 um below the pad the natural
        # (0, 0) drop would place (pad spans y -0.16..+0.16 about the query
        # point) -- close enough to notch, far enough not to touch. It runs
        # well past every x offset in both directions, so sliding along x
        # cannot dodge it: the walk has to leave in y.
        bus.net("N1").hseg(-20.0, 20.0, -0.4)
        drop = gen_bandgap_routed._met2_drop(bus, "N1", 0.0, 0.0)
        self.assertIsNotNone(drop)
        assert drop is not None
        self.assertNotEqual(drop, (0.0, 0.0))
        # And the committed pad genuinely clears the notch: it stands a full
        # met1.space.1 above its own wire's top edge (the only other legal
        # outcome, touching it, is not reachable from this geometry).
        half = met1_bus.MET1_VIA1_LANDING_UM / 2.0
        self.assertGreaterEqual(
            drop[1] - half, -0.28 + 0.14 - 1e-9,
            f"pad at {drop} still notches its own wire",
        )

    def test_met2_drop_still_lands_on_its_own_wire_when_it_touches(
        self,
    ) -> None:
        """The negative control for the check above: a pad *overlapping* its
        own node's wire is the ordinary case (that is how the stack connects
        at all) and must not be rejected as a notch."""
        bus = met1_bus.Met1Bus()
        bus.net("N1").hseg(-2.0, 2.0, 0.0)
        drop = gen_bandgap_routed._met2_drop(bus, "N1", 0.0, 0.0)
        self.assertEqual(drop, (0.0, 0.0))

    def test_met2_drop_backtracks_off_a_foreign_via1_stack(self) -> None:
        """The same guard against a full foreign via1 stack (met1 pad, via1
        cut and met2 pad all at once), placed close enough to the query
        point to foul the natural (0, 0) offset but far enough that the
        search stub can still depart in the opposite direction -- a via1
        stack coincident with the query point makes every direction
        unroutable regardless of this guard (a pre-existing, unrelated
        property of the offset walk), so that placement would not isolate
        anything this fix changed."""
        bus = met1_bus.Met1Bus()
        bus.net("F").via1(0.3, 0.0)
        drop = gen_bandgap_routed._met2_drop(bus, "N1", 0.0, 0.0)
        self.assertIsNotNone(drop)
        self.assertNotEqual(drop, (0.0, 0.0))
        self.assertEqual(bus.conflicts(), [])


class TestR2LegLength(unittest.TestCase):
    """`r2_leg_length()` states the drawn-vs-specified R2 divider leg length
    from the flow's own constants, so any regression in either constant is in
    every record whether or not `klt lvs` reaches those devices -- see
    RES_TRIM_LENGTH_NOTE."""

    def test_reports_the_schematic_value_from_core_params(self) -> None:
        report = gen_bandgap_routed.r2_leg_length()
        self.assertEqual(report["spec_um"], 250.0)  # r_lseg=5 * n_r2=50

    def test_drawn_length_counts_the_trim_ladder_because_it_is_in_series(
        self,
    ) -> None:
        report = gen_bandgap_routed.r2_leg_length()
        self.assertEqual(
            report["drawn_um"], report["coarse_um"] + report["trim_um"]
        )

    def test_the_drawn_leg_is_the_specified_leg_at_dr002_code_0(self) -> None:
        """Issue #91. The layout used to draw 286 um -- a full-length 270 um
        coarse leg with a 16 um trim ladder wired in series after it, i.e.
        DR-002 trim code +16, a direction DR-002 rejects outright. The leg is
        now decomposed rather than extended, so code 0 is exactly the
        schematic's own length and this test catches any silent return of
        either the sign or the magnitude."""
        report = gen_bandgap_routed.r2_leg_length()
        self.assertTrue(report["matches"])
        self.assertEqual(report["delta_um"], 0.0)
        self.assertEqual(report["effective_trim_code"], 0)

    def test_the_split_is_coarse_plus_fine_not_coarse_plus_extra(self) -> None:
        """The specific decomposition matters, not just the total: the fine
        ladder has to be long enough to reach DR-002's -16 code from inside
        the 250 um (issue #112's re-partition, forced by DR-002's revised
        `r_lseg_trim=0.5`, of issue #108's 46/20 decomposition -- which was
        itself issue #108's resize of issue #91's decomposition), which is
        what rules out e.g. 49 coarse + 15 fine (also totals 250 um but only
        reaches code -15 at the halved fine-unit length)."""
        report = gen_bandgap_routed.r2_leg_length()
        self.assertEqual(report["coarse_um"], 240.0)
        self.assertEqual(report["trim_um"], 10.0)
        self.assertGreaterEqual(
            gen_bandgap_routed.N_R2_TRIM_UNITS,
            gen_bandgap_routed.N_R2_TRIM_CODES,
            "the fine ladder cannot express DR-002's full downward range",
        )

    def test_the_blocks_draw_the_counts_the_length_claims(self) -> None:
        """`r2_leg_length()` reads the constants; the gate is only honest if
        `BLOCKS` draws those same constants (two legs of each)."""
        params = {b["id"]: b["params"] for b in gen_bandgap_routed.BLOCKS}
        self.assertEqual(
            params["res_r2"]["num"], 2 * gen_bandgap_routed.N_R2_COARSE
        )
        self.assertEqual(
            params["res_trim"]["num"], 2 * gen_bandgap_routed.N_R2_TRIM_UNITS
        )
        self.assertEqual(
            params["res_r2"]["length_um"], gen_bandgap_routed.R_LSEG_UM
        )
        self.assertEqual(
            params["res_trim"]["length_um"], gen_bandgap_routed.R_LSEG_TRIM_UM
        )


class TestTrimTapLadder(unittest.TestCase):
    """The trim ladder's *direction*, from the block's own reported ports.

    DR-002 certifies codes 0..-16 and rejects every positive one, so it is
    not enough that the leg is 250 um at code 0 (issue #91's decomposition,
    re-transcribed to the resized n_r2=50 sizing by issue #108): selecting a
    tap has to make the leg shorter, monotonically, one um per code. Before
    issue #91 the ladder was wired after a full-length leg and every tap
    made it longer.
    """

    #: A `res_array` report stub carrying exactly the ports the real block
    #: reports for `2 * N_R2_TRIM_UNITS` interdigitated fine units.
    def _reports(self, num: int | None = None) -> dict[str, dict[str, object]]:
        if num is None:
            num = 2 * gen_bandgap_routed.N_R2_TRIM_UNITS
        return {
            "res_trim": {
                "ports": [
                    {"name": f"R{i}_{end}"}
                    for i in range(num)
                    for end in ("A", "B")
                ]
            }
        }

    def test_code_0_yields_the_schematic_leg_length(self) -> None:
        rows = gen_bandgap_routed.trim_tap_ladder(self._reports())
        code0 = [row for row in rows if row["code"] == 0]
        self.assertEqual(len(code0), 1)
        self.assertEqual(
            code0[0]["leg_um"], gen_bandgap_routed.r2_leg_length()["spec_um"]
        )

    def test_every_certified_code_subtracts_exactly_r_lseg_trim_um(
        self,
    ) -> None:
        """Acceptance criterion 3 of issue #91, stated as an assertion:
        selecting tap k yields `spec_um - k*R_LSEG_TRIM_UM` um for k in 0..16
        (spec_um is 250 since issue #108's resize; R_LSEG_TRIM_UM is 0.5
        since issue #112's propagation of DR-002's revision -- was 1.0 um
        per code before, 270 um spec before #108)."""
        rows = {row["code"]: row for row in gen_bandgap_routed.trim_tap_ladder(
            self._reports()
        )}
        spec_um = gen_bandgap_routed.r2_leg_length()["spec_um"]
        step_um = gen_bandgap_routed.R_LSEG_TRIM_UM
        for k in range(gen_bandgap_routed.N_R2_TRIM_CODES + 1):
            with self.subTest(code=-k):
                self.assertEqual(rows[-k]["leg_um"], spec_um - k * step_um)
                self.assertTrue(rows[-k]["certified"])

    def test_no_tap_is_longer_than_the_specified_leg(self) -> None:
        """The whole defect, as one assertion: a positive code (a leg longer
        than the schematic's) must not be expressible by any drawn tap."""
        spec_um = gen_bandgap_routed.r2_leg_length()["spec_um"]
        for row in gen_bandgap_routed.trim_tap_ladder(self._reports()):
            with self.subTest(code=row["code"]):
                self.assertLessEqual(row["leg_um"], spec_um)
                self.assertLessEqual(row["code"], 0)

    def test_taps_past_dr002s_range_are_drawn_but_flagged(self) -> None:
        """The 48/20 split (issue #112's re-partition of issue #108's 46/20
        split, itself issue #108's resize of issue #91's 50/20) draws four
        taps past DR-002's certified -16. They exist in metal (a
        metal-option ladder's taps always do), so they are reported --
        explicitly marked out of certified range, not silently offered as
        valid codes."""
        rows = gen_bandgap_routed.trim_tap_ladder(self._reports())
        uncertified = [row["code"] for row in rows if not row["certified"]]
        self.assertEqual(uncertified, [-17, -18, -19, -20])
        self.assertEqual(
            min(row["code"] for row in rows),
            -gen_bandgap_routed.N_R2_TRIM_UNITS,
        )

    def test_the_two_legs_interdigitate_by_segment_parity(self) -> None:
        """Leg A owns even segment indices, leg B odd -- the arrangement
        `bus_res_series` chains and matching-plan Section 3 asks for. A tap
        that named the wrong parity would address the other leg."""
        for row in gen_bandgap_routed.trim_tap_ladder(self._reports()):
            with self.subTest(code=row["code"]):
                for leg, name in ((0, "A"), (1, "B")):
                    port = row["ports"][name]
                    index = int(port[1:].split("_")[0])
                    self.assertEqual(index % 2, leg)

    def test_a_count_change_fails_loudly_instead_of_mislabelling(self) -> None:
        """The ports are validated against the block's own report, so a
        constant change that the generator did not follow raises here rather
        than silently naming a tap that is not drawn."""
        with self.assertRaises(KeyError):
            gen_bandgap_routed.trim_tap_ladder(self._reports(num=4))

    def test_the_wired_low_end_of_each_leg_is_the_code_0_tap(self) -> None:
        """INTER_BLOCK_MET1 joins `VA`/`VB` to a specific `res_trim` port.
        That port must be the code-0 tap, or the drawn cell sits at a code
        the record does not report."""
        wired = {
            spec["net"]: [
                terminal["port"]
                for terminal in spec["terminals"]
                if terminal.get("block") == "res_trim"
            ]
            for spec in gen_bandgap_routed.INTER_BLOCK_MET1
            if spec["net"] in ("VA", "VB")
        }
        self.assertEqual(wired["VA"], [gen_bandgap_routed.trim_tap_port(0, 0)])
        self.assertEqual(wired["VB"], [gen_bandgap_routed.trim_tap_port(1, 0)])

    def test_the_coarse_leg_hands_off_to_the_head_of_the_fine_chain(
        self,
    ) -> None:
        """`TRIM_A`/`TRIM_B` join `res_r2`'s tail to `res_trim`'s head, so the
        coarse and fine parts are in series and the whole 250 um (issue
        #108's resize of issue #91's 270 um) is one device per leg."""
        trims = {
            spec["net"]: {t["block"]: t["port"] for t in spec["terminals"]}
            for spec in gen_bandgap_routed.INTER_BLOCK_MET1
            if spec["net"] in ("TRIM_A", "TRIM_B")
        }
        coarse = 2 * gen_bandgap_routed.N_R2_COARSE
        self.assertEqual(trims["TRIM_A"]["res_r2"], f"R{coarse - 2}_B")
        self.assertEqual(trims["TRIM_A"]["res_trim"], "R0_A")
        self.assertEqual(trims["TRIM_B"]["res_r2"], f"R{coarse - 1}_B")
        self.assertEqual(trims["TRIM_B"]["res_trim"], "R1_A")

    def test_a_positive_code_is_not_addressable_at_all(self) -> None:
        with self.assertRaises(ValueError):
            gen_bandgap_routed.trim_tap_port(0, 1)
        with self.assertRaises(ValueError):
            gen_bandgap_routed.trim_tap_port(
                0, -(gen_bandgap_routed.N_R2_TRIM_UNITS + 1)
            )


class TestInternalNetLabelling(unittest.TestCase):
    """A net declared `internal` to a schematic device must not be labelled.

    A labelled met1 net becomes a top-level pin, and `combine_devices` will
    not fold a series chain through a pinned node -- so labelling a node
    interior to R2A/R2B splits that device into unpairable pieces. See
    INTERNAL_NODE_LABEL_NOTE.
    """

    def _spec(self, internal: str | None) -> dict[str, dict[str, object]]:
        spec: dict[str, object] = {
            "net": "T",
            "schematic": "test net",
            "terminals": [{"trunk": ("L", "T")}, {"trunk": ("R", "T")}],
        }
        if internal:
            spec["internal"] = internal
        return {"T": spec}

    def _route(self, internal: str | None) -> met1_bus.Met1Bus:
        bus = met1_bus.Met1Bus()
        trunks = {("L", "T"): (0.0, 0.0), ("R", "T"): (10.0, 5.0)}
        gen_bandgap_routed._route_one_net(
            bus, "T", self._spec(internal), {}, {}, trunks, {}, set(), {},
        )
        return bus

    def test_an_ordinary_net_is_labelled(self) -> None:
        self.assertEqual(
            [label["text"] for label in self._route(None).labels], ["T"]
        )

    def test_an_internal_net_is_not_labelled(self) -> None:
        self.assertEqual(self._route("R2A").labels, [])

    def test_the_declared_trim_nets_are_the_internal_ones(self) -> None:
        """The two nets that were splitting R2A/R2B are declared internal in
        INTER_BLOCK_MET1 itself, so this cannot silently regress by someone
        re-adding a label at the call site."""
        internal = {
            spec["net"]: spec["internal"]
            for spec in gen_bandgap_routed.INTER_BLOCK_MET1
            if spec.get("internal")
        }
        self.assertEqual(internal, {"TRIM_A": "R2A", "TRIM_B": "R2B"})
