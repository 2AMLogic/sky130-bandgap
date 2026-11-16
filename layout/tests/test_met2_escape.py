#!/usr/bin/env python3
"""Unit coverage for the met2 escape plane (issue #62).

`_connect_met2()` is the last-resort lift onto met2 that closed acceptance
criterion 1 after the met1-side levers were exhausted, and two of its failure
modes are silent in exactly the way this suite exists to catch: a met2 wire
drawn across another node's met2 is a short `klt drc` cannot see (its met2
rules are geometric, not net-aware), and a via1 stack that misses its own
met1 leaves the node in two floating pieces while every per-plane component
count still reads 1. Also here: the met2 half of the shared met1/met2
proximity index (`met2_near()`), and
`gen_bandgap_routed.met2_drc_coverage_note()`, which keeps the flow's record
claiming only what `klt drc` actually covers instead of a fixed
increment-era fact.

SEE ALSO `layout/tests/test_met2_drc.py` -- the `klt`-side checker for the
same geometry -- and `layout/tests/test_bus_routing.py`, which owns the
`wall_bus` / `zero_detour` fixtures imported below.

Standard library only (`unittest`), matching every other script under
`layout/`. Run directly, or via:

    npm run test:unit
    python3 -m unittest discover --start-directory layout/tests
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "layout" / "bin"))

import gen_bandgap_routed  # noqa: E402  -- resolved from layout/bin, above
import met1_bus  # noqa: E402
import bus_routing  # noqa: E402

from test_bus_routing import wall_bus, zero_detour  # noqa: E402  -- shared router fixtures


class TestMet2ProximityIndex(unittest.TestCase):
    """`met2_near()` is `met1_near()`'s counterpart for the met2 escape
    plane -- both now share one `_PlaneIndex` implementation
    (`layout/bin/met1_bus.py`), so this mirrors `TestMet1ProximityIndex`
    exactly to prove the met2 instance of that shared index is exercised
    directly too, not only through higher-level routing tests.
    """

    def _brute(self, bus: met1_bus.Met1Bus, box, clearance):
        x0, y0, x1, y1 = box
        return sorted(
            r
            for r in bus.met2_rects
            if x0 - clearance < r[3]
            and r[1] - clearance < x1
            and y0 - clearance < r[4]
            and r[2] - clearance < y1
        )

    def _bus(self) -> met1_bus.Met1Bus:
        bus = met1_bus.Met1Bus()
        for i in range(40):
            bus.net(f"N{i % 5}")
            bus.hseg2(i * 1.7, i * 1.7 + 30.0, i * 0.9)
            bus.vseg2(i * 2.3, -5.0, 40.0)
            bus.via1(i * 3.1, i * 1.3)
        return bus

    def test_matches_a_full_scan(self) -> None:
        bus = self._bus()
        for box in ((0.0, 0.0, 1.0, 1.0), (20.0, 10.0, 21.0, 30.0), (-9.0, -9.0, -8.0, -8.0)):
            self.assertEqual(
                sorted(bus.met2_near(*box, 0.14)),
                self._brute(bus, box, 0.14),
                box,
            )

    def test_truncation_unindexes(self) -> None:
        """`truncate_met2` is how a rolled-back met2 escape leaves the index.
        If it left entries behind, every later route would be tested against
        geometry that is not in the emitted layout."""
        bus = self._bus()
        keep = 20
        bus.truncate_met2(keep)
        self.assertEqual(len(bus.met2_rects), keep)
        box = (0.0, -10.0, 60.0, 40.0)
        self.assertEqual(
            sorted(bus.met2_near(*box, 0.14)), self._brute(bus, box, 0.14)
        )


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

    def test_met1_is_tried_first_and_met2_is_not_touched_when_it_clears(
        self,
    ) -> None:
        """The escape must stay an escape. A hop with a clear met1 path draws
        no via1 and no met2 -- otherwise every hop would migrate onto the one
        plane `klt drc` does not check."""
        bus = met1_bus.Met1Bus()
        result = bus_routing._connect(
            bus, "N1", (0.0, 0.0), (10.0, 5.0), channels={}
        )
        self.assertIsNotNone(result)
        self.assertNotIn("met2", result)
        self.assertEqual(bus.met2_rects, [])
        self.assertEqual(bus.via1_count, 0)

    def test_a_hop_met1_cannot_clear_escapes_onto_met2(self) -> None:
        bus = wall_bus("WALL")
        with zero_detour():
            result = bus_routing._connect(
                bus, "N1", (0.0, 0.0), (10.0, 10.0), channels={}
            )
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
        bus = wall_bus("WALL")
        with zero_detour():
            bus_routing._connect(
                bus, "N1", (0.0, 0.0), (10.0, 10.0), channels={}
            )
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
        with zero_detour():
            result = bus_routing._connect(
                bus, "N1", (0.0, 0.0), (10.0, 10.0), channels={}
            )
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
        drop = bus_routing._met2_drop(bus, "N1", 0.0, 0.0)
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
        drop = bus_routing._met2_drop(bus, "N1", 0.0, 0.0)
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
        drop = bus_routing._met2_drop(bus, "N1", 0.0, 0.0)
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
        drop = bus_routing._met2_drop(bus, "N1", 0.0, 0.0)
        self.assertIsNotNone(drop)
        self.assertNotEqual(drop, (0.0, 0.0))
        self.assertEqual(bus.conflicts(), [])


if __name__ == "__main__":
    unittest.main()
