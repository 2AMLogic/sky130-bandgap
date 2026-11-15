#!/usr/bin/env python3
"""Unit coverage for the resistor-ladder scoreboard helpers (issue #62).

The flow's record states ladder facts from the design's own constants rather
than from prose that can drift: `r2_leg_length()` reports the drawn-vs-
specified R2 divider leg length, `trim_tap_port()` resolves a trim code to
the ladder tap DR-002 certifies, and the `internal` net declarations keep
`combine_devices` able to fold the R2A/R2B series chain (a labelled interior
node would pin it and split the device). These tests exercise the helpers
directly, so a constants regression shows up here whether or not `klt lvs`
ever reaches the devices.

SEE ALSO `layout/tests/test_routed_flow_gates.py` -- the flow's pass/fail
gates -- and `layout/tests/test_bus_routing.py`, the router that draws the
ladder's met1.

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


class TestR2LegLength(unittest.TestCase):
    """`r2_leg_length()` states the drawn-vs-specified R2 divider leg length
    from the flow's own constants, so any regression in either constant is in
    every record whether or not `klt lvs` reaches those devices -- see
    RES_TRIM_LENGTH_NOTE."""

    def test_reports_the_schematic_value_from_core_params(self) -> None:
        report = gen_bandgap_routed.r2_leg_length()
        self.assertEqual(report["spec_um"], 255.0)  # r_lseg=5 * n_r2=51

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
        the specified leg (issue #178's 49/20 decomposition at n_r2=51; before
        that issue #112's 48/20 re-partition, forced by DR-002's revised
        `r_lseg_trim=0.5`, of issue #108's 46/20 decomposition -- which was
        itself issue #108's resize of issue #91's decomposition), which is
        what rules out e.g. 50 coarse + 10 fine (also totals 255 um but only
        reaches code -10 at the halved fine-unit length)."""
        report = gen_bandgap_routed.r2_leg_length()
        self.assertEqual(report["coarse_um"], 245.0)
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
            for spec in bus_routing.INTER_BLOCK_MET1
            if spec["net"] in ("VA", "VB")
        }
        self.assertEqual(wired["VA"], [bus_routing.trim_tap_port(0, 0)])
        self.assertEqual(wired["VB"], [bus_routing.trim_tap_port(1, 0)])

    def test_the_coarse_leg_hands_off_to_the_head_of_the_fine_chain(
        self,
    ) -> None:
        """`TRIM_A`/`TRIM_B` join `res_r2`'s tail to `res_trim`'s head, so the
        coarse and fine parts are in series and the whole 250 um (issue
        #108's resize of issue #91's 270 um) is one device per leg."""
        trims = {
            spec["net"]: {t["block"]: t["port"] for t in spec["terminals"]}
            for spec in bus_routing.INTER_BLOCK_MET1
            if spec["net"] in ("TRIM_A", "TRIM_B")
        }
        coarse = 2 * gen_bandgap_routed.N_R2_COARSE
        self.assertEqual(trims["TRIM_A"]["res_r2"], f"R{coarse - 2}_B")
        self.assertEqual(trims["TRIM_A"]["res_trim"], "R0_A")
        self.assertEqual(trims["TRIM_B"]["res_r2"], f"R{coarse - 1}_B")
        self.assertEqual(trims["TRIM_B"]["res_trim"], "R1_A")

    def test_a_positive_code_is_not_addressable_at_all(self) -> None:
        with self.assertRaises(ValueError):
            bus_routing.trim_tap_port(0, 1)
        with self.assertRaises(ValueError):
            bus_routing.trim_tap_port(
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
        bus_routing._route_one_net(
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
            for spec in bus_routing.INTER_BLOCK_MET1
            if spec.get("internal")
        }
        self.assertEqual(internal, {"TRIM_A": "R2A", "TRIM_B": "R2B"})


if __name__ == "__main__":
    unittest.main()
