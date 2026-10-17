#!/usr/bin/env python3
"""Shared helpers for the `layout/bin/gen_bandgap_*.py` CLI scripts.

`gen_bandgap_routed.py` (issue #62) drives `klt` as a subprocess and composes
block placements. Mirrors `sim/bin/sim_common.py`'s role for the `sim/`
scripts (issue #169, after five prior `loom:hermit` dedupe rounds on that
module: #153, #154, #160, #162, #163):

    run_klt_json()   runs `klt <args> --format json` and parses the stdout
                     envelope, tolerating a caller-supplied set of "still
                     carries a payload" exit codes (e.g. `klt drc`'s 3)
    klt_gen()        runs `klt gen <generator>` for one BLOCKS entry and
                     writes its report alongside the generated GDS
    union_bbox()     computes the union bounding box of a set of placed
                     block ids, given each one's own reported bbox_um and
                     its placement origin
    git()            runs one `git -C <repo_root> <args>` and returns its
                     stripped stdout (issue #253, deduped out of
                     `gen_bandgap_routed.py` and `render-record.py`)
    klt_version()    runs `klt --version` and returns its stripped stdout
                     (issue #257, deduped out of `render-record.py` and
                     `routed_record.py`)
    git_repo_state() returns the (sha, branch, dirty) tuple used to stamp
                     record.md provenance (issue #263, deduped out of
                     `render-record.py` and `routed_record.py`)

`place_blocks()` is intentionally NOT here -- it lives in
`gen_bandgap_routed.py` itself, which needs an `align` parameter
(`top`/`bottom`/`center`) for `bjt_array`'s north-facing ports (issue #169's
scope note; `gen_bandgap_floorplan.py`, the #15 flow this module used to also
serve, was removed in issue #215 as superseded by the routed flow).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def run_klt_json(klt: str, *args: str, allow_exit: tuple[int, ...] = (0,)) -> dict[str, Any]:
    """Run one `klt <args> --format json` and parse its stdout envelope.

    `allow_exit` lists the exit codes that still carry a full payload on
    stdout -- `klt drc`'s 3 ("ran clean but found violations") and
    `klt gen-compose`'s 3 ("partial success: unrouted_nets[] non-empty") both
    do, and both are results this flow records rather than crashes. The
    default `(0,)` raises on any nonzero exit, matching
    `subprocess.run(..., check=True)`'s behavior (only the exception type
    differs: `RuntimeError` with `stderr` attached, instead of
    `subprocess.CalledProcessError`).
    """
    result = subprocess.run(
        [klt, *args, "--format", "json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode not in allow_exit:
        raise RuntimeError(
            f"klt {' '.join(args)} exited {result.returncode}:\n{result.stderr}"
        )
    return json.loads(result.stdout)


def klt_gen(klt: str, pdk: str, out_dir: Path, block: dict[str, Any]) -> dict[str, Any]:
    cell_name = block["id"]
    gds_path = out_dir / f"{cell_name}.gds"
    report = run_klt_json(
        klt,
        "gen",
        block["generator"],
        "--pdk",
        pdk,
        "--cell-name",
        cell_name,
        "--params",
        json.dumps(block["params"]),
        "-o",
        str(gds_path),
    )
    (out_dir / f"{cell_name}.gen.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def union_bbox(
    block_ids: list[str],
    reports: dict[str, dict[str, Any]],
    origins: dict[str, dict[str, float]],
) -> dict[str, float]:
    x0s, y0s, x1s, y1s = [], [], [], []
    for bid in block_ids:
        bbox = reports[bid]["bbox_um"]
        origin = origins[bid]
        x0s.append(bbox["x0"] + origin["x"])
        y0s.append(bbox["y0"] + origin["y"])
        x1s.append(bbox["x1"] + origin["x"])
        y1s.append(bbox["y1"] + origin["y"])
    return {"x0": min(x0s), "y0": min(y0s), "x1": max(x1s), "y1": max(y1s)}


def git(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def git_repo_state(repo_root: Path) -> tuple[str, str, bool]:
    sha = git(repo_root, "rev-parse", "HEAD")
    branch = git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    dirty = git(repo_root, "status", "--porcelain") != ""
    return sha, branch, dirty


def klt_version(klt: str) -> str:
    return subprocess.run(
        [klt, "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()


# ---------------------------------------------------------------------------
# Constants and scoring shared by gen_bandgap_routed.py, bus_routing.py and
# routed_record.py (issue #384). They live here so the three modules form an
# acyclic import graph: each imports from this one, never from each other
# in a loop.
# ---------------------------------------------------------------------------
MET1_BUS_NOTE = (
    "Every intra-block bus and every inter-block net in this cell is drawn "
    "by this repo with `klt draw`, on met1 over mcon -- see "
    "layout/bin/met1_bus.py. That started as the only option: sky130's "
    "generator/router layer-role table exposed exactly one routing metal "
    "role (`metal` -> li1 67/20), the same layer every generator draws its "
    "device pads on, so `klt gen-compose` could not express a bus at all "
    "(klayout-tools#433; its fix #439 made the failure visible rather than "
    "expressible). klayout-tools#454 (merged via #468) has since added "
    "`metal2`/`via1` roles with via-drop bussing, and #508 (merged via "
    "#511) a third `metal3`/`via2` level, so the router *can* now plan "
    "wires above the pad layer. This flow has not moved its bussing onto "
    "them (its own met2 escape plane is hand-drawn too, MET2_ESCAPE_NOTE): "
    "the "
    "bussing here is a planar lane assignment derived from each block's own "
    "reported geometry (MOS_COMB_NOTE), and swapping it for router-planned "
    "routing is a rework to be measured on its own, not a parameter change "
    "to be slipped into an increment that is already changing the device "
    "topology. Hand-placing what a router could plan remains the residual "
    "gap."
)

#: Outward `direction_deg` each `klt gen` port family faces.
DIRECTION_EAST = 0
DIRECTION_NORTH = 90
DIRECTION_WEST = 180

RING_MARGIN_UM = 8.0  # clearance between the composed content and the outer ring

#: Held at 7, unchanged by issue #99/#108's n_r2 resize: DR-003's closure
#: deliberately left n_r1 fixed so the resize corrects K = R2/R1 without
#: raising the branch current (and therefore the hot-corner headroom the
#: ff/2.97V, fs/2.97V regulation-collapse margin depends on). See
#: RES_RESIZE_NOTE.
N_R1 = 7
#: The R2 divider leg's **drawn** decomposition (issue #91, re-transcribed
#: to the resized sizing by issue #108, then re-partitioned by issue #112
#: when the fine unit's drawn length halved). The schematic states one
#: length per leg -- `L = r_lseg*n_r2 + r_lseg_trim*n_r2_trim` = 5*50 +
#: 0.5*0 = 250 um at DR-002's untrimmed code 0 (n_r2=50 since issue #99/
#: PR #105; r_lseg_trim halved 1 -> 0.5 by issue #106/PR #111, see
#: RES_TRIM_LSB_NOTE) -- and the layout has to reproduce *that* number
#: while still offering DR-002's downward-only trim codes. It does so by
#: splitting the 250 um, not by adding to it: 48 coarse 5 um units
#: (240 um) in `res_r2` plus 20 fine 0.5 um units (10 um) in `res_trim`.
#: Joining the leg's low node at the far end of the fine chain is then
#: exactly 250 um = code 0, and every tap short of that end *subtracts*
#: 0.5 um per skipped unit -- the only direction DR-002 permits.
#:
#: Before issue #91 the coarse leg was drawn at the full pre-resize count
#: (54 units, 270 um) and the fine ladder was wired in series *after* it,
#: so the drawn leg was 286 um and every tap moved it further up: trim
#: code +16, which DR-002 rejects outright. See RES_TRIM_LENGTH_NOTE.
#:
#: 48/20 is the coarse count DR-002's revision forces to hold the leg
#: fixed at 250 um: `N_R2_TRIM_UNITS` stays 20 (the revision re-partitions
#: the fixed leg length between coarse and fine segments; it does not
#: touch the fine ladder's unit *count*, so all 20 units -- and DR-002's
#: certified 0..-16 downward range -- are still reachable), so
#: `N_R2_COARSE` has to absorb the 0.5 um/unit reduction across all 20
#: units (10 um) to keep `5*N_R2_COARSE + 0.5*20 == 250`: 46 -> 48. See
#: RES_RESIZE_NOTE for why the leg length itself moved (issue #99) and
#: RES_TRIM_LSB_NOTE for why the fine unit length itself halved
#: (issue #106).
#: 48 -> 49 by issue #178 (n_r2 50 -> 51 re-centres the untrimmed VREF
#: inside DR-005's ratified +/-2 % window once the schematic itself models
#: the chained array's per-instance head resistance -- see
#: design/bandgap_core.sch's CHAINED-ARRAY MODEL / SIZING blocks and
#: RES_HEAD_SIZING_NOTE). The fine ladder's unit count is untouched, so
#: `5*49 + 0.5*20 == 255 == 5*51` still holds the leg at the specified
#: length and DR-002's certified 0..-16 downward range is still reachable.
N_R2_COARSE = 49
N_R2_TRIM_UNITS = 20


#: The bar criterion 1 is measured against: every node of
#: design/bandgap_core.sch (+ design/error_amp.sch) that joins devices living
#: in *different* layout blocks, with the set of blocks the schematic says it
#: must reach. This is deliberately independent of CORE_NETS -- scoring
#: "9/9 declared nets routed" measures the flow against its own declaration,
#: which is not what issue #62 asks for. `hops` names the CORE_NETS entries
#: that carry this node's label; a node counts as fully drawn only when the
#: blocks those routed hops actually touch cover `blocks`.
SCHEMATIC_INTER_BLOCK_NETS: list[dict[str, Any]] = [
    {
        "net": "VA",
        "blocks": ["pnp_ctat", "res_trim", "amp_input_pair"],
        "hops": ["VA"],
        "schematic": "Q1 emitter + R2A low end (which the layout splits into "
        "ladder + DR-002 trim taps, so the low end sits on res_trim) + MP2 "
        "gate (amp VINN)",
    },
    {
        "net": "VB",
        "blocks": ["res_trim", "res_r1", "amp_input_pair"],
        "hops": ["VB"],
        "schematic": "R2B low end (through the trim taps) + R1 head + MP1 "
        "gate (amp VINP)",
    },
    {
        "net": "TRIM",
        "blocks": ["res_r2", "res_trim"],
        "hops": ["TRIM_A", "TRIM_B"],
        "schematic": "layout-internal split of both R2 legs into ladder + "
        "DR-002 trim taps (one device per leg in the schematic)",
    },
    {
        "net": "VBQ",
        "blocks": ["res_r1", "pnp_ptat"],
        "hops": ["VBQ"],
        "schematic": "R1 tail + Q2 emitter",
    },
    {
        "net": "VOUT",
        "blocks": ["core_mirror", "res_r2", "su_sense", "su_clamp"],
        "hops": ["VOUT"],
        "schematic": "MPOUT drain + both R2A/R2B tops (the reference "
        "output) + the startup injector's VSENSE input (MNS/MNC gates)",
    },
    {
        "net": "GDRV",
        "blocks": ["core_mirror", "amp_pmirr", "amp_nmirr", "amp_cc",
                   "su_ref", "su_inj", "su_clamp"],
        "hops": ["GDRV"],
        "schematic": "amp output (MP4/MN3 drains) + MPOUT/MPAMP gates + "
        "MCC's gate + the startup injector's MPC1 source, MNI drain and "
        "MNC source -- one node in the schematic and, since the "
        "gate-contact gap closed, one drawn node in the layout too",
    },
    {
        "net": "NG",
        "blocks": ["su_ref", "su_sense", "su_inj"],
        "hops": ["NG"],
        "schematic": "MPC2 diode drain/gate + MNS drain + MNI gate "
        "(design/startup_injector.sch)",
    },
    {
        "net": "NE",
        "blocks": ["su_sense", "pnp_su"],
        "hops": ["NE"],
        "schematic": "MNS source + QS emitter (design/startup_injector.sch)",
    },
    {
        "net": "TAIL",
        "blocks": ["core_mirror", "amp_input_pair"],
        "hops": ["TAIL"],
        "schematic": "MPAMP drain + MP1/MP2 common source",
    },
    {
        "net": "D1",
        "blocks": ["amp_input_pair", "amp_nload", "amp_nmirr"],
        "hops": ["D1"],
        "schematic": "MP1 drain + MN1 diode + MN3 gate",
    },
    {
        "net": "D2",
        "blocks": ["amp_input_pair", "amp_nload", "amp_nmirr"],
        "hops": ["D2"],
        "schematic": "MP2 drain + MN2 diode + MN4 gate",
    },
    {
        "net": "PN",
        "blocks": ["amp_nmirr", "amp_pmirr"],
        "hops": ["PN"],
        "schematic": "MN4 drain + MP3 diode + MP4 gate",
    },
    {
        "net": "VDD",
        "blocks": ["core_mirror", "amp_input_pair", "amp_pmirr", "amp_cc",
                   "su_ref", "su_clamp"],
        "hops": ["VDD"],
        "schematic": "supply trunk: MPOUT/MPAMP sources + MP1/MP2 well side "
        "+ MP3/MP4 sources + MCC drain/source + the startup injector's "
        "MPC1/MPC2 n-well tap and MNC drain",
    },
    {
        "net": "VSS",
        "blocks": ["amp_nload", "amp_nmirr", "pnp_ctat", "pnp_ptat",
                   "su_inj", "pnp_su"],
        "hops": ["VSS"],
        "schematic": "ground trunk: MN1-MN4 sources + both PNPs' base ties. "
        "The three resistor blocks' res_high_po bulk terminals "
        "(design/bandgap_core.sch r2ab/r2bb/r1b) are on this node in the "
        "schematic too, and now resolve to the same real drawn `VSS` net "
        "the rest of this row does (SUBSTRATE_NET_NOTE) -- but not through "
        "a pad this router can target: `res_array` draws no bulk-terminal "
        "pad inside those three blocks for metal to land on, so they stay "
        "uncounted as routing targets here even though the correspondence "
        "itself is no longer in question",
    },
]


def schematic_net_coverage(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Score each schematic inter-block node against the met1 metal actually
    drawn for it.

    `status` is "drawn" only when the drawn nets carrying that node touch
    every block the schematic says the node reaches; "partial" when some but
    not all are joined; "labelled only" when no metal is drawn for it at all
    (the node exists in the layout solely as a promoted pin label).

    Scored against design/bandgap_core.sch's own node list, never against
    this flow's own routing declaration -- a net this flow simply forgot to
    declare has to show up here as a miss.
    """
    # Credit is per *hop*, not per net, and only for blocks that end up in one
    # connected piece of metal. A net whose chain breaks in the middle leaves
    # two disjoint pieces; counting its whole block list would claim
    # connectivity that is not drawn, and counting nothing (what this function
    # did before) throws away the piece that *is*. Union-find over the routed
    # hops, then keep the largest component, states exactly what is joined.
    parent: dict[tuple[str, str], tuple[str, str]] = {}

    def find(key: tuple[str, str]) -> tuple[str, str]:
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(a: tuple[str, str], b: tuple[str, str]) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    endpoint_block: dict[tuple[str, str], str] = {}
    for route in routes:
        net = route["net"]
        for hop in route.get("hops", []):
            ends = []
            for side in ("from", "to"):
                name = hop.get(side)
                if not name:
                    continue
                block = name.split(".")[0].split(":")[0]
                key = (net, name)
                endpoint_block[key] = block
                find(key)
                ends.append(key)
            if hop.get("routed") and len(ends) == 2:
                union(ends[0], ends[1])

    components: dict[tuple[str, str], set[str]] = {}
    for key, block in endpoint_block.items():
        components.setdefault(find(key), set()).add(block)
    touched: dict[str, set[str]] = {}
    for root, blocks in components.items():
        net = root[0]
        if len(blocks) > len(touched.get(net, set())):
            touched[net] = blocks
    rows = []
    for spec in SCHEMATIC_INTER_BLOCK_NETS:
        want = set(spec["blocks"])
        have: set[str] = set()
        for hop in spec["hops"]:
            have |= touched.get(hop, set())
        joined = want & have
        if joined >= want:
            status = "drawn"
        elif len(joined) >= 2:
            status = "partial"
        else:
            status = "labelled only"
        rows.append(
            {
                "net": spec["net"],
                "schematic": spec["schematic"],
                "blocks": spec["blocks"],
                "joined": sorted(joined),
                "missing": sorted(want - joined),
                "status": status,
            }
        )
    return rows
