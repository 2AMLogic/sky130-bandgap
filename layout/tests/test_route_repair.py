#!/usr/bin/env python3
"""Unit coverage for the inter-block router's rip-up-and-reroute repair pass
(issue #62).

`layout/bin/gen_bandgap_routed.py`'s `build_bus_overlay` already retries a
*whole* redraw with a different net order when something fails
(`ROUTE_ORDER_PASSES`) -- a coarse, whole-cell form of rip-up. Issue #62's
last increment (PR #71) measured that this is not enough: the same three
nets, on every one of those orderings, come up exactly one hop short, because
reordering *which net goes first* cannot express "net J's own greedy first
solution happens to sit exactly where net K's one remaining hop needs to go,
and no order changes that because J must still be drawn before K".

`_route_one_net` (the per-net solver, extracted so this pass can call it in
isolation), `_replay_tail` and `_repair_unrouted_hops` are what closes that
gap: find a still-unrouted hop, read which already-drawn net blocked it
(`_LAST_BLOCKER`, recorded per hop), and -- when that net is itself earlier
in the same draw order -- roll back to just before it, redraw it forced past
its own first `skip_first` fully-routed solutions, and replay everything
after it so the forward pass's "a net only ever sees final geometry"
invariant still holds.

These are pure-Python unit tests exercising the control flow directly (no
`klt`, no PDK, no real block geometry beyond a couple of hand-built li1
ports) -- following the pattern `test_routed_flow_gates.py` established for
this repo's other router-internal gates.

Standard library only (`unittest`), matching every other script under
`layout/`. Run directly, or via:

    npm run test:unit
    python3 -m unittest discover --start-directory layout/tests
"""

from __future__ import annotations

import sys
import unittest
import unittest.mock
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "layout" / "bin"))

import gen_bandgap_routed  # noqa: E402  -- resolved from layout/bin, above
import met1_bus  # noqa: E402


# ---------------------------------------------------------------------------
# `_route_one_net`'s `skip_first` parameter
# ---------------------------------------------------------------------------
class TestRouteOneNetSkipFirst(unittest.TestCase):
    """A single-terminal net whose one terminal offers three li1 candidate
    ports, ranked by distance to the candidates' own centroid. This isolates
    *which candidate is chosen* from whether a hop routes: a one-terminal net
    draws its via and has zero hops to fail, so it always reports `routed`
    and the only thing `skip_first` can change is the picked port.
    """

    REPORTS = {
        "B": {
            "bbox_um": {"x0": 8.0, "y0": -2.0, "x1": 12.0, "y1": 12.0},
            "ports": [
                {
                    "name": "Q1_X", "x_um": 10.0, "y_um": 0.0,
                    "layer": {"layer": 67, "datatype": 20}, "direction_deg": 180,
                },
                {
                    "name": "Q2_X", "x_um": 10.0, "y_um": 4.0,
                    "layer": {"layer": 67, "datatype": 20}, "direction_deg": 180,
                },
                {
                    "name": "Q3_X", "x_um": 10.0, "y_um": 10.0,
                    "layer": {"layer": 67, "datatype": 20}, "direction_deg": 180,
                },
            ],
        },
    }
    ORIGINS = {"B": {"x": 0.0, "y": 0.0}}
    SPECS = {
        "NET1": {
            "net": "NET1",
            "terminals": [{"block": "B", "suffix": "_X", "facing": 180}],
            "schematic": "test net",
        }
    }

    def _route(self, skip_first: int) -> dict[str, Any]:
        channels = gen_bandgap_routed.free_channels(self.REPORTS, self.ORIGINS)
        bus = met1_bus.Met1Bus()
        return gen_bandgap_routed._route_one_net(
            bus, "NET1", self.SPECS, self.REPORTS, self.ORIGINS, {}, {},
            set(), channels, skip_first=skip_first,
        )

    def test_skip_first_zero_is_the_greedy_nearest_candidate(self) -> None:
        # Centroid of the three ports is (10, 4.667); Q2_X (y=4.0) is nearest.
        result = self._route(skip_first=0)
        self.assertTrue(result["routed"])
        self.assertEqual(result["terminals"], ["B.Q2_X"])

    def test_skip_first_walks_to_the_next_nearest_candidate(self) -> None:
        # Second-nearest to the centroid is Q1_X (y=0.0, distance 4.667),
        # ahead of Q3_X (y=10.0, distance 5.333).
        result = self._route(skip_first=1)
        self.assertTrue(result["routed"])
        self.assertEqual(result["terminals"], ["B.Q1_X"])

    def test_skip_first_exhausts_to_the_last_candidate(self) -> None:
        result = self._route(skip_first=2)
        self.assertTrue(result["routed"])
        self.assertEqual(result["terminals"], ["B.Q3_X"])

    def test_skip_first_past_every_solution_falls_back_to_the_first(self) -> None:
        """Asking to skip more solutions than exist must not raise or leave
        the net unrouted -- it must fall back to the original (skip_first=0)
        choice, the same way _repair_unrouted_hops relies on to revert a
        repair attempt that did not pan out."""
        result = self._route(skip_first=5)
        self.assertTrue(result["routed"])
        self.assertEqual(result["terminals"], ["B.Q2_X"])

    def test_every_skip_level_is_a_real_via_no_leftover_geometry(self) -> None:
        """Each call gets its own fresh bus, so this is really just guarding
        against a future refactor accidentally sharing bus state across the
        skip levels the way a single "try harder" search might."""
        for skip_first, want in ((0, "B.Q2_X"), (1, "B.Q1_X"), (2, "B.Q3_X")):
            bus = met1_bus.Met1Bus()
            channels = gen_bandgap_routed.free_channels(self.REPORTS, self.ORIGINS)
            result = gen_bandgap_routed._route_one_net(
                bus, "NET1", self.SPECS, self.REPORTS, self.ORIGINS, {}, {},
                set(), channels, skip_first=skip_first,
            )
            self.assertEqual(result["terminals"], [want])
            self.assertEqual(bus.via_count, 1)


# ---------------------------------------------------------------------------
# `_repair_unrouted_hops` / `_replay_tail`
# ---------------------------------------------------------------------------
class TestRepairUnroutedHops(unittest.TestCase):
    """Control-flow coverage for the repair pass itself, with `_route_one_net`
    replaced by a scripted stand-in:
    `{net: (skip_first, last_skip) -> (routed, blocked_by)}`. This isolates
    "does the repair pass ask the right net for its next solution, the right
    number of times, and keep only real improvements" from the real router's
    geometry, which :class:`TestRouteOneNetSkipFirst` above already covers
    directly.
    """

    #: A `script[net_name]` entry is `(skip_first, last_skip) -> (routed,
    #: blocked_by)`, where `last_skip` is a shared `{net: skip_first}` map of
    #: what every net (including this one) was *most recently* redrawn with.
    #: Modelling a net's outcome as a function of the current world state --
    #: not just its own `skip_first` -- is what lets a script express "K only
    #: routes once J is past its greedy first pick", the real dependency
    #: `_repair_unrouted_hops` exists to resolve.
    def _fake(self, script, calls: list[tuple[str, int]], last_skip: dict[str, int]):
        def fake_route_one_net(
            bus, net_name, specs, reports, origins, trunks, combs,
            used_ports, channels, skip_first: int = 0,
        ) -> dict[str, Any]:
            calls.append((net_name, skip_first))
            # A real per-call shape, purely so bus.mark()/.restore() round-trip
            # over something -- the repair pass must not corrupt the bus's own
            # bookkeeping even though this fake never draws real routing.
            bus.net(net_name)
            bus.hseg(0.0, 1.0, float(len(calls)))
            last_skip[net_name] = skip_first
            routed, blocked_by = script[net_name](skip_first, last_skip)
            hops = [
                {
                    "from": f"{net_name}.a",
                    "to": f"{net_name}.b",
                    "routed": routed,
                    "blocked_by": None if routed else blocked_by,
                }
            ]
            return {
                "net": net_name,
                "routed": routed,
                "schematic": "",
                "terminals": [],
                "blocks": [],
                "hops": hops,
            }

        return fake_route_one_net

    def _run(
        self, sequence: list[str], script
    ) -> tuple[list[dict[str, Any]], list[tuple[str, int]]]:
        bus = met1_bus.Met1Bus()
        used_ports: set[tuple[str, str]] = set()
        channels: dict[str, list[float]] = {}
        marks: list[tuple[int, ...]] = []
        port_snapshots: list[set[tuple[str, str]]] = []
        results: list[dict[str, Any]] = []
        calls: list[tuple[str, int]] = []
        last_skip: dict[str, int] = {}
        fake = self._fake(script, calls, last_skip)
        with unittest.mock.patch.object(gen_bandgap_routed, "_route_one_net", side_effect=fake):
            for net_name in sequence:
                marks.append(bus.mark())
                port_snapshots.append(set(used_ports))
                results.append(
                    gen_bandgap_routed._route_one_net(
                        bus, net_name, {}, {}, {}, {}, {}, used_ports, channels,
                    )
                )
            gen_bandgap_routed._repair_unrouted_hops(
                bus, sequence, {}, {}, {}, {}, {}, used_ports, channels,
                marks, port_snapshots, results,
            )
        return results, calls

    def test_a_blocker_with_a_next_solution_is_ripped_up_and_retried(self) -> None:
        """J always routes; K only routes once J has been forced past its
        greedy first pick (skip_first >= 1). The repair pass should force
        that and K should end up routed."""
        script = {
            "J": lambda skip_first, last_skip: (True, None),
            "K": lambda skip_first, last_skip: (
                (True, None) if last_skip.get("J", 0) >= 1 else (False, "J")
            ),
        }
        results, calls = self._run(["J", "K"], script)
        self.assertTrue(results[0]["routed"])
        self.assertTrue(results[1]["routed"])
        # J was redrawn at least once past its greedy first pick.
        self.assertIn(("J", 1), calls)

    def test_a_genuine_deadlock_is_bounded_and_reverted(self) -> None:
        """No skip level of J ever frees K. The repair pass must still
        terminate rather than loop forever, must give up within
        REPAIR_MAX_SKIPS_PER_NET, and must leave J on its original
        (skip_first=0) solution rather than an arbitrary later one."""
        script = {
            "J": lambda skip_first, last_skip: (True, None),
            "K": lambda skip_first, last_skip: (False, "J"),  # never frees
        }
        results, calls = self._run(["J", "K"], script)
        self.assertTrue(results[0]["routed"])
        self.assertFalse(results[1]["routed"])
        j_skips = [skip for net, skip in calls if net == "J"]
        # Bounded: J is never asked to skip more than the declared budget.
        self.assertLessEqual(max(j_skips), gen_bandgap_routed.REPAIR_MAX_SKIPS_PER_NET)
        # Reverted: J's *last* redraw (the one whose geometry is what remains
        # on the bus) is back to its original, unskipped choice.
        self.assertEqual(j_skips[-1], 0)

    def test_no_repairable_blocker_is_a_no_op(self) -> None:
        """`blocked_by` naming a net that is not one of this call's own nets
        at all must not trigger any repair attempt."""
        script = {
            "J": lambda skip_first, last_skip: (True, None),
            "K": lambda skip_first, last_skip: (False, "not-a-real-net"),
        }
        results, calls = self._run(["J", "K"], script)
        self.assertFalse(results[1]["routed"])
        # Only the two forward-pass calls -- no repair attempt fired.
        self.assertEqual(calls, [("J", 0), ("K", 0)])

    def test_later_net_named_as_blocker_is_never_rolled_back(self) -> None:
        """A hop can only be genuinely blocked by a net drawn *before* it;
        the repair pass must not roll back a later net (nonsensical: it has
        not been drawn yet from the failing net's point of view) even if the
        data mistakenly names one."""
        script = {
            "J": lambda skip_first, last_skip: (False, "K"),
            "K": lambda skip_first, last_skip: (True, None),
        }
        results, calls = self._run(["J", "K"], script)
        self.assertFalse(results[0]["routed"])
        self.assertTrue(results[1]["routed"])
        self.assertEqual(calls, [("J", 0), ("K", 0)])

    def test_multiple_unrouted_hops_can_each_be_repaired(self) -> None:
        """Three nets: L is blocked by J and never frees regardless of J's
        skip level (a genuine deadlock, bounded and reverted, exactly as
        the two-net case above); K is a red herring that always routes and
        never blocks or is blocked by anything, proving the target search
        does not get confused by an unrelated third net."""
        script = {
            "J": lambda skip_first, last_skip: (True, None),
            "K": lambda skip_first, last_skip: (True, None),
            "L": lambda skip_first, last_skip: (False, "J"),
        }
        results, calls = self._run(["J", "K", "L"], script)
        self.assertTrue(results[0]["routed"])
        self.assertTrue(results[1]["routed"])
        self.assertFalse(results[2]["routed"])
        j_skips = [skip for net, skip in calls if net == "J"]
        self.assertEqual(j_skips[-1], 0)
        # K, the unrelated net, is replayed (it sits between blocker J and
        # failing net L in `sequence`, so every repair attempt on J replays
        # it too) but is never itself forced past its own greedy first pick.
        self.assertTrue(all(skip == 0 for net, skip in calls if net == "K"))


if __name__ == "__main__":
    unittest.main()
