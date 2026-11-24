#!/usr/bin/env python3
"""Unit coverage for the bus router's drawn geometry and internals (issue #62).

The routed flow's four pass/fail gates live in `test_routed_flow_gates.py`;
this file holds what those gates score *with*: the finger-bus and gate-contact
geometry the flow hand-draws (`met1_bus.Met1Bus.gate_contact()`, the met1
proximity index behind `met1_near()`), the MOS-comb plan and its channel
tracks, the open-channel router's own functions (`_connect` /
`_channel_paths` / `_chain_orders` / `_candidate_assignments`), and PR #73's
rip-up-and-reroute repair pass driven through the real, non-mocked router --
so a geometry-level regression that a scripted mock cannot see still fails
here. Also the comb lane pitch, whose illegal spacing once read downstream as
*better* connectivity.

SEE ALSO `layout/tests/test_route_repair.py` -- the repair pass's control
flow, against a scripted mock -- and `layout/tests/test_routed_flow_gates.py`
(the gates themselves). The same-named `TestRouteOneNetSkipFirst` /
`TestRepairUnroutedHops` classes there and here are deliberate, documented
complements, not duplicates to collapse: that file isolates control flow,
this one exercises real geometry.

The `met1_only` / `zero_detour` / `wall_bus` fixtures defined here are
imported by `test_met2_escape.py`; keep them import-safe (no side effects at
module scope).

Standard library only (`unittest`), matching every other script under
`layout/`. Run directly, or via:

    npm run test:unit
    python3 -m unittest discover --start-directory layout/tests
"""

from __future__ import annotations

import contextlib
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "layout" / "bin"))

import gen_bandgap_routed  # noqa: E402  -- resolved from layout/bin, above
import met1_bus  # noqa: E402
import bus_routing  # noqa: E402  -- issue #221: split out of gen_bandgap_routed.py


@contextlib.contextmanager
def met1_only():
    """Disable `_connect`'s met2 escape for the duration of the block.

    The met2 escape plane (layout/generator-notes.md#met2-escape-note) is a
    last-resort fallback that
    is available to essentially every hop, because met2 starts empty -- so
    with it on, "the met1 search ran out of options" and "the router gave
    up" stop being the same question. Every test below that asserts what the
    *met1* search does when it is boxed in wraps itself in this, so it keeps
    testing the thing it names. Tests of the escape itself do not.
    """
    previous = bus_routing.MET2_ESCAPE_ENABLED
    bus_routing.MET2_ESCAPE_ENABLED = False
    try:
        yield
    finally:
        bus_routing.MET2_ESCAPE_ENABLED = previous


@contextlib.contextmanager
def zero_detour():
    """Force `_connect`'s Z-detour retry ladder down to a single try.

    `DETOUR_OFFSETS_UM` is the list of channel offsets `_connect` walks
    through before giving up on a hop; several failure-path tests below need
    that search to be exhausted in one attempt so a blocked hop fails
    deterministically rather than eventually clearing via some other offset.
    Same save/override/restore shape as `met1_only()` above, just for the
    other module-level toggle.
    """
    previous = bus_routing.DETOUR_OFFSETS_UM
    bus_routing.DETOUR_OFFSETS_UM = [0.0]
    try:
        yield
    finally:
        bus_routing.DETOUR_OFFSETS_UM = previous


def wall_bus(*nets: str) -> met1_bus.Met1Bus:
    """A bus whose met1 is walled off at both ends of a (0, 0)-(10, 10) hop,
    so no met1 form can clear. One net name walls both ends; two wall one
    end each (`WALL_A`/`WALL_B`), for tests that need each blocker counted
    separately."""
    bus = met1_bus.Met1Bus()
    if len(nets) == 1:
        (name,) = nets
        bus.net(name)
        bus.hseg(9.85, 10.15, 0.0)
        bus.hseg(-0.15, 0.15, 10.0)
    elif len(nets) == 2:
        first, second = nets
        bus.net(first)
        bus.hseg(9.85, 10.15, 0.0)
        bus.net(second)
        bus.hseg(-0.15, 0.15, 10.0)
    else:
        raise ValueError("wall_bus expects 1 or 2 net names")
    return bus


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
    defect layout/generator-notes.md#mos-half-note was written for.
    """

    def _combs(self):
        return {
            block["id"]: block["bus"]
            for block in gen_bandgap_routed.BLOCKS
            if block.get("bus", {}).get("kind") == "mos_comb"
        }

    def test_every_terminal_names_a_device_the_half_table_binds(self) -> None:
        for bid, spec in self._combs().items():
            devices = bus_routing.MOS_HALVES[bid]["devices"]
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
                for device in bus_routing.MOS_HALVES[bid]["devices"]
                for terminal in ("drain", "source", "gate")
            }
            self.assertEqual(set(seen), expected, bid)

    def test_every_comb_net_is_a_declared_inter_block_node(self) -> None:
        """...unless the block itself declares the node as block-internal.

        A comb net no inter-block route names is normally a typo -- the node
        would be drawn inside one block and joined to nothing. The one honest
        exception is a schematic node whose every terminal really is on that
        block, which `BLOCK_INTERNAL_COMB_NETS` has to say explicitly; an
        undeclared one still fails here.
        """
        declared = {spec["net"] for spec in bus_routing.INTER_BLOCK_MET1}
        for bid, spec in self._combs().items():
            internal = bus_routing.BLOCK_INTERNAL_COMB_NETS.get(bid, set())
            for entry in spec["nets"]:
                self.assertIn(
                    entry["net"], declared | internal, f"{bid}:{entry['net']}"
                )

    def test_block_internal_comb_nets_really_are_block_internal(self) -> None:
        """The exemption above must not become a way to hide an unrouted
        node: a net declared block-internal may not also appear in
        INTER_BLOCK_MET1, and must actually be a comb net of the block that
        declares it."""
        declared = {spec["net"] for spec in bus_routing.INTER_BLOCK_MET1}
        combs = self._combs()
        for bid, nets in bus_routing.BLOCK_INTERNAL_COMB_NETS.items():
            self.assertIn(bid, combs, bid)
            comb_nets = {e["net"] for e in combs[bid]["nets"]}
            for net in nets:
                self.assertIn(net, comb_nets, f"{bid}:{net}")
                self.assertNotIn(net, declared, f"{bid}:{net}")

    def test_every_inter_block_comb_terminal_exists_in_its_block(self) -> None:
        """The reverse direction: a route asking for a comb point the block
        never built would raise deep inside the router, mid-run."""
        combs = self._combs()
        for spec in bus_routing.INTER_BLOCK_MET1:
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
        self.assertEqual(bus_routing._band_index(bands, 4.0), 0)
        self.assertEqual(bus_routing._band_index(bands, 8.21), 0)
        self.assertEqual(bus_routing._band_index(bands, 12.82), 1)
        self.assertEqual(bus_routing._band_index(bands, 17.03), 1)


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
        lanes = bus_routing.free_channels(self.REPORTS, self.ORIGINS)
        between = [t for t in lanes["x"] if 10.0 < t < 30.0]
        self.assertTrue(between, lanes["x"])

    def test_tracks_clear_the_comb_escape_stubs(self) -> None:
        """The nearest track to a block edge must sit outside that block's
        own escape fan, or every path through it is rejected on arrival."""
        self.assertGreater(
            bus_routing.CHANNEL_TRACK_OFFSET_UM,
            max(bus_routing.MOS_ESCAPE_UM),
        )

    def test_a_block_with_no_neighbour_still_gets_outside_tracks(self) -> None:
        lanes = bus_routing.free_channels(self.REPORTS, self.ORIGINS)
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
        result = bus_routing._connect(bus, "N1", (0.0, 0.0), (10.0, 5.0))
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
        bus = wall_bus("WALL")
        a, b = (0.0, 0.0), (10.0, 10.0)
        # The direct elbows are provably blocked before the channel fallback
        # is even asked to resolve anything.
        self.assertIsNone(
            bus_routing._connect_path(
                bus, "N1", [a, (b[0], a[1]), b]
            )
        )
        self.assertIsNone(
            bus_routing._connect_path(
                bus, "N1", [a, (a[0], b[1]), b]
            )
        )
        result = bus_routing._connect(
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
        bus = wall_bus("WALL")
        rects_before = list(bus.met1_rects)
        shapes_before = list(bus.shapes)
        with zero_detour(), met1_only():
            result = bus_routing._connect(
                bus, "N1", (0.0, 0.0), (10.0, 10.0), channels={}
            )
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
        bus = wall_bus("WALL_A", "WALL_B")
        with zero_detour(), met1_only():
            result = bus_routing._connect(
                bus, "N1", (0.0, 0.0), (10.0, 10.0), channels={}
            )
        self.assertIsNone(result)
        # Both walls vetoed at least one candidate elbow (WALL_A the one that
        # turns first at x=10, WALL_B the one that turns first at y=10) --
        # both must be present, not just whichever was checked last.
        self.assertEqual(
            set(bus_routing._BLOCKER_COUNTS), {"WALL_A", "WALL_B"}
        )
        self.assertGreater(bus_routing._BLOCKER_COUNTS["WALL_A"], 0)
        self.assertGreater(bus_routing._BLOCKER_COUNTS["WALL_B"], 0)

    def test_blocker_counts_reset_at_the_start_of_each_connect_call(
        self,
    ) -> None:
        """A tally left over from a previous hop's failed search must not
        leak into the next hop's `blocked_by_counts` -- each `_connect()`
        call reports only what *it* saw."""
        bus = wall_bus("WALL")
        with zero_detour():
            bus_routing._connect(
                bus, "N1", (0.0, 0.0), (10.0, 10.0), channels={}
            )
            self.assertIn("WALL", bus_routing._BLOCKER_COUNTS)
            # A second, unrelated call that never collides with anything
            # must start from a clean tally.
            result = bus_routing._connect(
                bus, "N2", (20.0, 20.0), (30.0, 25.0), channels={}
            )
        self.assertIsNotNone(result)
        self.assertEqual(dict(bus_routing._BLOCKER_COUNTS), {})


class TestDrawChainBlockedByCounts(unittest.TestCase):
    """`_draw_chain()` is what a failed hop's report -- `blocked_by` and
    `blocked_by_counts` -- actually comes from; see TestConnectRouter above
    for `_connect()`/`_BLOCKER_COUNTS` itself."""

    def test_failed_hop_carries_both_the_last_blocker_and_the_full_breakdown(
        self,
    ) -> None:
        bus = wall_bus("WALL_A", "WALL_B")
        plan = [
            {"name": "P0", "pad": (0.0, 0.0), "via": False},
            {"name": "P1", "pad": (10.0, 10.0), "via": False},
        ]
        with zero_detour(), met1_only():
            hops, routed = bus_routing._draw_chain(bus, "N1", plan)
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
        hops, routed = bus_routing._draw_chain(bus, "N1", plan)
        self.assertTrue(routed)
        self.assertEqual(len(hops), 1)
        self.assertNotIn("blocked_by", hops[0])
        self.assertNotIn("blocked_by_counts", hops[0])


class TestDrawChainTree(unittest.TestCase):
    """`_draw_chain(tree=True)` (issue #669): a terminal that cannot reach its
    chain predecessor attaches to another already-connected terminal, instead
    of stranding itself and everything behind it."""

    def test_tree_attaches_to_a_reachable_member(self) -> None:
        # wall_bus walls both elbows of the P0-P1 hop; P2 sits clear of both,
        # so P1 can only join the node through P2.
        def point(name: str, x: float, y: float) -> dict:
            return {"name": name, "pad": (x, y), "via": False}

        p0, p1, p2 = point("P0", 0.0, 0.0), point("P1", 10.0, 10.0), point("P2", 10.0, 5.0)
        plan = [p2, p0, p1]
        with zero_detour(), met1_only():
            _, chain_routed = bus_routing._draw_chain(
                wall_bus("WALL"), "N1", plan
            )
            self.assertFalse(chain_routed, "the chain order strands P1")
            hops, routed = bus_routing._draw_chain(
                wall_bus("WALL"), "N1", plan, tree=True
            )
        self.assertTrue(routed)
        self.assertEqual([(h["from"], h["to"]) for h in hops], [("P2", "P0"), ("P2", "P1")])

    def test_tree_reports_the_failed_attachment(self) -> None:
        with zero_detour(), met1_only():
            bus = wall_bus("WALL")
            hops, routed = bus_routing._draw_chain(
                bus, "N1",
                [
                    {"name": "P0", "pad": (0.0, 0.0), "via": False},
                    {"name": "P1", "pad": (10.0, 10.0), "via": False},
                ],
                tree=True,
            )
        self.assertFalse(routed)
        self.assertEqual(hops[0]["from"], "P0")
        self.assertEqual(hops[0]["to"], "P1")
        self.assertFalse(hops[0]["routed"])
        self.assertEqual(hops[0]["blocked_by"], "WALL")

    def test_tree_failure_attributes_blockers_per_parent(self) -> None:
        """Issue #683: a fully failed tree attachment used to pair the
        *nearest* parent's name with the *last* parent's blocker tally,
        because _connect clears _BLOCKER_COUNTS on entry and the failure
        record was assembled after the loop. The failed hop must describe
        one attempt -- the last parent tried -- and carry a per-parent
        `attempts` trail in trial order. Blocker fields are compared
        against isolated single-parent runs rather than a frozen count, so
        a change to the elbow/detour retry ladder (#645) does not have to
        update this test to keep the attribution honest."""
        def point(name: str, x: float, y: float) -> dict:
            return {"name": name, "pad": (x, y), "via": False}

        def boxed_bus(*nets: str) -> met1_bus.Met1Bus:
            # Horizontal 0.3 um walls that veto C=(10, 7) differently per
            # parent: WEST walls the approaches from A=(0, 0), EAST the
            # approaches from B=(20, 20). A joins B cleanly either way.
            bus = met1_bus.Met1Bus()
            if "WEST" in nets:
                bus.net("WEST")
                bus.hseg(9.85, 10.15, 3.0)
                bus.hseg(4.85, 5.15, 7.0)
            if "EAST" in nets:
                bus.net("EAST")
                bus.hseg(9.85, 10.15, 15.0)
                bus.hseg(14.85, 15.15, 7.0)
            return bus

        a, b, c = point("A", 0.0, 0.0), point("B", 20.0, 20.0), point("C", 10.0, 7.0)
        with zero_detour(), met1_only():
            west_alone, _ = bus_routing._draw_chain(
                boxed_bus("WEST", "EAST"), "N1", [a, c], tree=True
            )
            east_alone, _ = bus_routing._draw_chain(
                boxed_bus("WEST", "EAST"), "N1", [b, c], tree=True
            )
            self.assertFalse(west_alone[0]["routed"])
            self.assertFalse(east_alone[0]["routed"])
            self.assertEqual(west_alone[0]["blocked_by"], "WEST")
            self.assertEqual(east_alone[0]["blocked_by"], "EAST")
            west_ref = {
                "blocked_by": west_alone[0]["blocked_by"],
                "blocked_by_counts": west_alone[0]["blocked_by_counts"],
            }
            east_ref = {
                "blocked_by": east_alone[0]["blocked_by"],
                "blocked_by_counts": east_alone[0]["blocked_by_counts"],
            }
            hops, routed = bus_routing._draw_chain(
                boxed_bus("WEST", "EAST"), "N1", [a, b, c], tree=True
            )
        self.assertFalse(routed)
        self.assertEqual(
            [(h["from"], h["to"], h["routed"]) for h in hops],
            [("A", "B", True), ("B", "C", False)],
        )
        failed = hops[1]
        # Top level describes the final parent attempted, preserving the
        # blocker _repair_unrouted_hops reads.
        self.assertEqual(failed["from"], "B")
        self.assertEqual(failed["blocked_by"], east_ref["blocked_by"])
        self.assertEqual(failed["blocked_by_counts"], east_ref["blocked_by_counts"])
        # Per-parent trail in trial order: A's entry matches the isolated
        # A->C attempt, B's the isolated B->C attempt.
        self.assertEqual(
            failed["attempts"],
            [
                {"from": "A", **west_ref},
                {"from": "B", **east_ref},
            ],
        )

    def test_tree_success_after_earlier_parent_fails_emits_one_hop(self) -> None:
        """A terminal reached through a later parent emits only its successful hop."""
        def point(name: str, x: float, y: float) -> dict:
            return {"name": name, "pad": (x, y), "via": False}

        bus = met1_bus.Met1Bus()
        bus.net("WEST")
        bus.hseg(9.85, 10.15, 3.0)
        bus.hseg(4.85, 5.15, 7.0)
        plan = [
            point("A", 0.0, 0.0),
            point("B", 20.0, 20.0),
            point("C", 10.0, 7.0),
        ]
        with zero_detour(), met1_only():
            hops, routed = bus_routing._draw_chain(bus, "N1", plan, tree=True)
        self.assertTrue(routed)
        self.assertEqual(
            [(h["from"], h["to"], h["routed"]) for h in hops],
            [("A", "B", True), ("B", "C", True)],
        )
        self.assertNotIn("attempts", hops[1])
        self.assertNotIn("blocked_by", hops[1])
        self.assertNotIn("blocked_by_counts", hops[1])


class TestChannelPaths(unittest.TestCase):
    """`_channel_paths()` is the shape a cross-floorplan hop needs that no
    elbow or single-jog Z can express -- see its own docstring. These check
    the geometric contract every caller relies on: every returned path is a
    legal orthogonal polyline, shortest first, and the double-dogleg variants
    genuinely use two different tracks (a same-track "dogleg" would just be
    a single-jog Z, already covered by the plain paths above it)."""

    CHANNELS = {"x": [2.0, 8.0, -5.0], "y": [3.0, 7.0, -4.0]}

    def test_every_path_is_orthogonal(self) -> None:
        paths = bus_routing._channel_paths(
            (0.0, 0.0), (10.0, 10.0), self.CHANNELS
        )
        self.assertTrue(paths)
        for path in paths:
            for (x0, y0), (x1, y1) in zip(path, path[1:]):
                self.assertTrue(x0 == x1 or y0 == y1, path)

    def test_paths_are_sorted_shortest_first(self) -> None:
        paths = bus_routing._channel_paths(
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
        paths = bus_routing._channel_paths(
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
            bus_routing._channel_paths((0.0, 0.0), (10.0, 10.0), {}), []
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
        orders = bus_routing._chain_orders(points)
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
        orders = bus_routing._chain_orders(points)
        self.assertEqual(len(orders), 3)

    def test_column_and_row_major_orders_are_both_present(self) -> None:
        points = [self._pt(5.0, 0.0), self._pt(0.0, 5.0), self._pt(5.0, 5.0)]
        orders = bus_routing._chain_orders(points)
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
        orders = bus_routing._chain_orders(points)
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
        orders = bus_routing._chain_orders([start, far, near])
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
        assignments = bus_routing._candidate_assignments([fixed], 0.0, 0.0)
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
        assignments = bus_routing._candidate_assignments([point], 0.0, 0.0)
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
        assignments = bus_routing._candidate_assignments(
            [point_a, point_b], 2.0, 5.0
        )
        self.assertLessEqual(
            len(assignments), bus_routing.CANDIDATE_ASSIGNMENTS
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
        pad of its own (layout/generator-notes.md#mos-comb-note) -- claiming
        it would falsely reserve a pad no other net could then legally
        use."""
        point = {
            "block": "b",
            "via": False,
            "claims_pad": False,
            "candidates": [("escape", 3.0, 4.0)],
        }
        assignments = bus_routing._candidate_assignments([point], 0.0, 0.0)
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
        result = bus_routing._route_one_net(
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
        result = bus_routing._route_one_net(
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
        specs = self._specs()
        specs["A"]["terminals"].reverse()  # label the chosen comb escape
        result = bus_routing._route_one_net(
            bus, "A", specs, {}, {}, trunks, combs, set(), {}, skip_first=99,
        )
        self.assertTrue(result["routed"])
        self.assertIn("near", result["terminals"])
        self.assertEqual(bus.labels[0]["at_um"], [10.0, 0.0])

    def test_tree_retry_and_redraw_after_exhaustion(self) -> None:
        # A, B and C each reach H, but walls block both elbows between
        # any two leaves. Only a branching tree can join all four trunks.
        trunks = {
            ("H", "N"): (6, 13), ("A", "N"): (0, 0),
            ("B", "N"): (10, 10), ("C", "N"): (20, 20),
        }
        specs = {"N": {"net": "N", "schematic": "star", "terminals": [
            {"trunk": trunk} for trunk in trunks
        ]}}

        def route(skip_first):
            bus = met1_bus.Met1Bus()
            bus.net("WALL")
            for x in (0, 10, 20):
                for y in (0, 10, 20):
                    if x != y:
                        bus.hseg(x - 0.15, x + 0.15, y)
            with zero_detour(), met1_only():
                result = bus_routing._route_one_net(
                    bus, "N", specs, {}, {}, trunks, {}, set(), {},
                    skip_first=skip_first,
                )
            self.assertTrue(result["routed"])
            self.assertEqual(bus.components()["N"], 1)
            self.assertEqual(bus.conflicts(), [])
            return result, bus.shapes

        first, first_shapes = route(0)
        retry, _ = route(1)
        self.assertNotEqual(retry["terminals"], first["terminals"])
        redrawn, shapes = route(99)
        self.assertEqual(redrawn, first)
        self.assertEqual(shapes, first_shapes)


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
                    bus_routing._route_one_net(
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
            bus_routing._repair_unrouted_hops(
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
                bus_routing._route_one_net(
                    bus, "B", specs, {}, {}, trunks, {}, used_ports, channels,
                )
            ]
        self.assertFalse(results[0]["routed"])
        self.assertEqual(results[0]["hops"][0]["blocked_by"], "WALL")

        mark_before_repair = bus.mark()
        with met1_only():
            bus_routing._repair_unrouted_hops(
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
            bus_routing._repair_unrouted_hops(
                bus, sequence, specs, {}, {}, trunks, {}, used_ports, channels,
                marks, port_snapshots, results,
            )

        self.assertFalse(results[1]["routed"])
        self.assertEqual(results[0]["terminals"], original_terminals)
        self.assertEqual(bus.mark(), mark_before_repair)
        self.assertEqual(bus.conflicts(), [])


class TestCombLanePitch(unittest.TestCase):
    """`bus_mos_comb` packs one horizontal trunk lane per node inside each
    device row. Until issue #285 the lane spacing was derived purely from the
    row's own height (`height / (lanes + 1)`), which silently produces an
    ILLEGAL pitch once the row is short enough -- 0.25 um on the startup
    injector's W=1 MPC1/MPC2 reference, against met1's 0.24 um width plus the
    deck's 0.14 um `met1.space.1`. The drawn result was six drawn-short
    conflicts and seven `met1.space.1` violations: two nodes' trunks merged
    into one conductor, which reads downstream as *better* connectivity.

    Two properties close it, and both are asserted here rather than left to
    an end-to-end run: the pitch never goes below `MOS_LANE_PITCH_UM`, and a
    row that cannot hold its own lanes at that pitch raises instead of
    drawing. The third -- that the lane index is a dense rank of the
    block-wide order *within each row* -- is what lets a three-node block
    with one device per row fit at all.
    """

    GAP_UM = 0.4

    def _report(self, w_um: float) -> dict[str, object]:
        """A two-row `diff_pair`-shaped report with `splits=1`: M1 alone in
        the bottom row, M2 alone in the top one."""
        rows = [0.0, w_um + self.GAP_UM]
        ports: list[dict[str, object]] = []
        for half, y0 in (("M1", rows[0]), ("M2", rows[1])):
            for name, x in ((f"{half}_1_S", 0.2), (f"{half}_1_D", 2.0)):
                ports.append({
                    "name": name, "x_um": x, "y_um": y0 + w_um / 2.0,
                    "width_um": w_um,
                    "layer": {"layer": met1_bus.LI1_LAYER[0],
                              "datatype": met1_bus.LI1_LAYER[1]},
                    "direction_deg": 180 if name.endswith("_S") else 0,
                })
            ports.append({
                "name": f"{half}_1_G", "x_um": 1.1, "y_um": y0 + w_um + 0.1,
                "width_um": 0.42,
                "layer": {"layer": 66, "datatype": 20},
                "direction_deg": 90,
            })
        return {
            "ports": ports,
            "bbox_um": {"x0": 0.0, "y0": 0.0, "x1": 2.4,
                        "y1": 2 * w_um + self.GAP_UM + 0.2},
        }

    def _draw(self, w_um: float, groups: list[dict[str, object]]):
        bus = met1_bus.Met1Bus()
        halves = {
            "drain_suffix": "_D", "drain_facing": 0,
            "source_suffix": "_S", "source_facing": 180,
            "devices": {"MPC1": "M1", "MPC2": "M2"},
        }
        saved = bus_routing.MOS_HALVES.get("_probe")
        bus_routing.MOS_HALVES["_probe"] = halves
        try:
            records = bus_routing.bus_mos_comb(
                bus, "_probe", self._report(w_um), {"x": 0.0, "y": 0.0},
                "W", groups,
            )
        finally:
            if saved is None:
                del bus_routing.MOS_HALVES["_probe"]
            else:  # pragma: no cover -- only if a real block is ever named _probe
                bus_routing.MOS_HALVES["_probe"] = saved
        return bus, records

    #: The real MPC1/MPC2 comb: NC1 spans both rows, NG is MPC2's alone,
    #: GDRV is MPC1's alone -- so no row ever carries more than two lanes.
    INJECTOR_GROUPS = [
        {"net": "NC1", "terminals": [("MPC1", "drain"), ("MPC1", "gate"),
                                     ("MPC2", "source")]},
        {"net": "NG", "terminals": [("MPC2", "drain"), ("MPC2", "gate")]},
        {"net": "GDRV", "terminals": [("MPC1", "source")]},
    ]

    def test_three_nodes_on_a_1um_device_draw_no_short(self) -> None:
        bus, _ = self._draw(1.0, self.INJECTOR_GROUPS)
        self.assertEqual(bus.conflicts(), [])

    @staticmethod
    def _lanes_by_row(records) -> dict[int, list[float]]:
        """`{device row index: sorted lane y's}` read back out of the comb's
        own escape records (each is named `<block>:<net>:<tag><band>`)."""
        rows: dict[int, dict[str, float]] = {}
        for record in records:
            for name, _x, y in record["escapes"]:
                band = int(name[-1])
                rows.setdefault(band, {})[record["net"]] = y
        return {band: sorted(nets.values()) for band, nets in rows.items()}

    def test_lane_pitch_never_goes_below_the_met1_minimum(self) -> None:
        """The property the drawn-short check above is a consequence of."""
        _, records = self._draw(1.0, self.INJECTOR_GROUPS)
        rows = self._lanes_by_row(records)
        self.assertEqual(sorted(rows), [0, 1])
        for lanes in rows.values():
            self.assertEqual(len(lanes), 2)
            for lower, upper in zip(lanes, lanes[1:]):
                self.assertGreaterEqual(
                    round(upper - lower, 6), bus_routing.MOS_LANE_PITCH_UM
                )

    def test_a_row_too_short_for_its_own_lanes_raises(self) -> None:
        """Three nodes that all reach into the SAME row cannot fit a 1 um
        row at a legal pitch, and the flow must say so rather than draw it."""
        groups = [
            {"net": "A", "terminals": [("MPC1", "drain")]},
            {"net": "B", "terminals": [("MPC1", "gate")]},
            {"net": "C", "terminals": [("MPC1", "source")]},
        ]
        with self.assertRaises(ValueError) as caught:
            self._draw(1.0, groups)
        self.assertIn("too short", str(caught.exception))

    def test_a_tall_row_still_spreads_lanes_across_its_own_height(self) -> None:
        """The floor must be a floor, not a fixed pitch: every block drawn
        before issue #285 has rows 6 um or taller, and this asserts their
        lane spacing is still the height-derived one (so those layouts
        reproduce unchanged)."""
        w_um = 8.0
        groups = [
            {"net": "A", "terminals": [("MPC1", "drain"), ("MPC2", "drain")]},
            {"net": "B", "terminals": [("MPC1", "source"), ("MPC2", "source")]},
        ]
        _, records = self._draw(w_um, groups)
        bottom = self._lanes_by_row(records)[0]
        self.assertEqual(len(bottom), 2)
        # `escapes` rounds to 3 dp, so assert against the same rounding
        # rather than against the exact third -- the point is that the pitch
        # is height-derived (2.667 um, far above the floor), not exact
        # arithmetic.
        self.assertAlmostEqual(
            bottom[1] - bottom[0], w_um / 3.0, delta=0.002
        )
        self.assertGreater(bottom[1] - bottom[0], bus_routing.MOS_LANE_PITCH_UM)


if __name__ == "__main__":
    unittest.main()
