#!/usr/bin/env python3
"""Independent geometry estimate of VB / VBQ resistance from the routed GDS (issue #573).

Question: is the 5114.5 ohm (VB) / 199.5 ohm (VBQ) total that `klt pex`
0.8.0 extracts physical?  This script never uses klt's number: it flood-fills
the net from its label through poly / licon / li1 / mcon / met1 (own
connectivity, resistor bodies `poly & rpm` and gates `poly & diff` cut out),
then solves each conductor fragment as a 2-D resistor grid between its real
ports and adds the cut resistances.

Sheet / cut values, sky130A.tech nominal block (`resist` in milliohm/sq for
metals, ohm/sq for poly/li; `contact` in milliohm per cut):
  poly (allpolynonres) 48.2 ohm/sq | li1 (allli) 12.8 ohm/sq | met1 (allm1)
  0.125 ohm/sq | licon on poly `contact pc,xpc` 152 ohm/cut | mcon 9.3 ohm/cut.

Run (pinned klayout via the klt pin, never the host tool):
  uvx --with numpy --with scipy --from klayout-tools==0.8.0 \
      python -I sim/pex-native/geometry_resistance.py <gds> -o <record-dir>

The grid solver (`grid_squares`) is pure numpy/scipy; `series_squares` and
the unit test (`test_geometry_resistance.py`) need no klayout and no ngspice.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "ci"))

# The repo's one SHA-256 helper (issue #538): bare hex, exactly the form the
# `*_sha256` keys in `inputs.json` below carry.
from content_hash import sha256_file  # noqa: E402

SHEET = {"poly": 48.2, "li1": 12.8, "met1": 0.125}  # ohm/sq, sky130A.tech
CUT = {"licon": 152.0, "mcon": 9.3}  # ohm per cut, sky130A.tech `contact pc,xpc` / `contact mcon`
PITCHES_NM = (40, 20)  # two grid pitches -> discretisation spread is the method uncertainty

Rect = tuple[int, int, int, int]  # l, b, r, t in nm


def _cells(rects: list[Rect], x0: int, y0: int, h: int, shape: tuple[int, int]) -> np.ndarray:
    """Boolean grid: cell (i, j) is set when its centre lies in any rect."""
    g = np.zeros(shape, dtype=bool)
    for l, b, r, t in rects:
        i0 = max(0, -((-(2 * (l - x0) - h)) // (2 * h)))  # ceil((l-x0)/h - .5)
        i1 = max(0, -((-(2 * (r - x0) - h)) // (2 * h)))
        j0 = max(0, -((-(2 * (b - y0) - h)) // (2 * h)))
        j1 = max(0, -((-(2 * (t - y0) - h)) // (2 * h)))
        g[i0:min(i1, shape[0]), j0:min(j1, shape[1])] = True
    return g


def grid_squares(rects: list[Rect], port_a: list[Rect], port_b: list[Rect], h: int) -> float:
    """Resistance in squares between two port electrodes of a rectilinear conductor."""
    xs = [v for r in rects for v in (r[0], r[2])]
    ys = [v for r in rects for v in (r[1], r[3])]
    x0, y0 = min(xs) - h, min(ys) - h
    shape = ((max(xs) - x0) // h + 2, (max(ys) - y0) // h + 2)
    body = _cells(rects, x0, y0, h, shape)
    a = _cells(port_a, x0, y0, h, shape) & body
    b = _cells(port_b, x0, y0, h, shape) & body
    if not a.any() or not b.any() or (a & b).any():
        raise ValueError("port does not land on (or overlaps another port in) the conductor")
    idx = -np.ones(shape, dtype=np.int64)
    idx[body] = np.arange(int(body.sum()))
    rows, cols = [], []
    for sl_a, sl_b in (((slice(None, -1), slice(None)), (slice(1, None), slice(None))),
                       ((slice(None), slice(None, -1)), (slice(None), slice(1, None)))):
        m = body[sl_a] & body[sl_b]
        rows.append(idx[sl_a][m])
        cols.append(idx[sl_b][m])
    r_, c_ = np.concatenate(rows), np.concatenate(cols)
    n = int(body.sum())
    deg = np.bincount(r_, minlength=n) + np.bincount(c_, minlength=n)
    lap = coo_matrix((np.concatenate([-np.ones(len(r_)), -np.ones(len(r_)), deg.astype(float)]),
                      (np.concatenate([r_, c_, np.arange(n)]), np.concatenate([c_, r_, np.arange(n)]))),
                     shape=(n, n)).tocsr()
    fixed = np.zeros(n, dtype=bool)
    v = np.zeros(n)
    ia, ib = idx[a], idx[b]
    fixed[ia] = fixed[ib] = True
    v[ia] = 1.0
    free = ~fixed
    rhs = -lap[free][:, fixed] @ v[fixed]
    v[free] = spsolve(lap[free][:, free].tocsc(), rhs)
    current = float((lap[ia] @ v).sum())  # unit conductance per link
    return 1.0 / current


def series_squares(parts: list[float]) -> float:
    """Series combination of fragment resistances (same rho) -- plain sum."""
    return float(sum(parts))


# ---------------------------------------------------------------- layout side


def _rects(region) -> list[Rect]:
    import klayout.db as kdb

    out = []
    for p in region.merged().each():
        for t in p.decompose_trapezoids(kdb.Polygon.TD_simple):
            b = t.bbox()
            out.append((b.left, b.bottom, b.right, b.top))
    return out


def _flood(layers, adj, seed_layer, pt):
    import klayout.db as kdb

    p = kdb.Region(kdb.Box(pt[0] - 1, pt[1] - 1, pt[0] + 1, pt[1] + 1))
    net = {k: kdb.Region() for k in layers}
    net[seed_layer] = layers[seed_layer].interacting(p)
    changed = True
    while changed:
        changed = False
        for k in layers:
            for a in adj[k]:
                if net[a].is_empty():
                    continue
                new = (layers[k].interacting(net[a]) | net[k]).merged()
                if new.area() != net[k].area():
                    net[k] = new
                    changed = True
    return net


def _frag_squares(frag_region, port_a, port_b):
    """(squares by pitch, spread) for one fragment between two port regions."""
    if not port_a.interacting(port_b).is_empty():  # stacked cuts: no lateral path
        return {h: 0.0 for h in PITCHES_NM}
    vals = {h: grid_squares(_rects(frag_region), _rects(port_a), _rects(port_b), h) for h in PITCHES_NM}
    return vals


def analyse(gds: Path) -> dict:
    import klayout.db as kdb

    ly = kdb.Layout()
    ly.read(str(gds))
    top = ly.top_cell()

    def reg(a, b):
        return kdb.Region(top.begin_shapes_rec(ly.find_layer(a, b))).merged()

    poly, diff, rpm = reg(66, 20), reg(65, 20), reg(86, 20)
    layers = {"poly": poly - rpm - (poly & diff), "licon": reg(66, 44), "li1": reg(67, 20),
              "mcon": reg(67, 44), "met1": reg(68, 20)}
    adj = {"poly": ["licon"], "licon": ["poly", "li1"], "li1": ["licon", "mcon"],
           "mcon": ["li1", "met1"], "met1": ["mcon"]}
    labels = {t.string: t.trans.disp for li in ly.layer_indexes()
              for t in kdb.Texts(top.begin_shapes_rec(li)).each() if ly.get_info(li).layer == 68}
    out = {}
    for name in ("VB", "VBQ"):
        d = labels[name]
        net = _flood(layers, adj, "met1", (d.x, d.y))
        trunk = next(net["met1"].each())
        trunk_r = kdb.Region(trunk)
        heads, others = [], []
        for pf in net["poly"].each():
            fr = kdb.Region(pf)
            (heads if not (fr.sized(20) & rpm).is_empty() else others).append(fr)
        arms = []
        for fr in heads:  # resistor head: body edge -> licon -> li1 -> mcon -> met1
            lic = net["licon"].interacting(fr)
            li = next(net["li1"].interacting(lic).each())
            mc = net["mcon"].interacting(kdb.Region(li))
            poly_sq = _frag_squares(fr, fr & rpm.sized(60), lic)
            li_sq = _frag_squares(kdb.Region(li), lic, mc)
            arms.append({"li": kdb.Region(li), "licon_xy_nm": [lic.bbox().center().x, lic.bbox().center().y],
                         "mcon": mc, "poly_sq": poly_sq, "li1_sq": li_sq})
        sinks = []
        for li in net["li1"].each():  # every other li1 fragment: emitter plate / gate strap
            lr = kdb.Region(li)
            if any(not lr.interacting(a["li"]).is_empty() for a in arms):
                continue
            sinks.append(lr)
        rec = {"label_xy_nm": [d.x, d.y], "n_heads": len(arms), "n_other_li1_fragments": len(sinks),
               "met1_area_um2": trunk_r.area() / 1e6, "sheet_ohm_sq": SHEET, "cut_ohm": CUT}

        def ohm(sq_by_h, layer):
            return {str(h): sq * SHEET[layer] for h, sq in sq_by_h.items()}

        rec["heads"] = []
        for a in arms:
            rec["heads"].append({"licon_xy_nm": a["licon_xy_nm"],
                                 "poly_ohm": ohm(a["poly_sq"], "poly"),
                                 "li1_ohm": ohm(a["li1_sq"], "li1")})
        # met1 path between the head mcons (VB: the two resistor terminals)
        if len(arms) == 2:
            m = {h: grid_squares(_rects(trunk_r), _rects(arms[0]["mcon"]), _rects(arms[1]["mcon"]), h)
                 for h in PITCHES_NM}
            rec["met1_head_to_head_ohm"] = ohm(m, "met1")
        else:  # VBQ: head -> each other terminal's mcon on the trunk
            per = []
            for s in sinks:
                mc = net["mcon"].interacting(s)
                per.append({str(h): grid_squares(_rects(trunk_r), _rects(arms[0]["mcon"]), _rects(mc), h)
                            * SHEET["met1"] for h in PITCHES_NM})
            rec["met1_head_to_sink_ohm"] = per
        # whole-net series-sum a la klt, for the like-for-like comparison
        rec["all_fragments_series_ohm_note"] = ("klt charges every fragment in series; "
                                                "this script reports DC paths instead")
        out[name] = rec
    return out


def end_to_end(rec: dict) -> dict:
    """Head-to-head (VB) or head-to-mean-sink (VBQ) path ohms per pitch, with and without licon."""
    res = {}
    for h in map(str, PITCHES_NM):
        arms = [x["poly_ohm"][h] + x["li1_ohm"][h] + CUT["mcon"] for x in rec["heads"]]
        if "met1_head_to_head_ohm" in rec:
            core = sum(arms) + rec["met1_head_to_head_ohm"][h]
            n_lic = 2
        else:
            sinks = [s[h] for s in rec["met1_head_to_sink_ohm"]]
            core = arms[0] + float(np.mean(sinks))
            n_lic = 1
        res[h] = {"without_licon_ohm": core, "with_licon_ohm": core + n_lic * CUT["licon"]}
    return res


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gds", type=Path)
    ap.add_argument("-o", "--outdir", type=Path, required=True)
    args = ap.parse_args(argv)
    res = analyse(args.gds)
    for rec in res.values():
        rec["end_to_end"] = end_to_end(rec)
    args.outdir.mkdir(parents=True, exist_ok=True)
    (args.outdir / "geometry-r.json").write_text(json.dumps(res, indent=2, sort_keys=True, default=str) + "\n")
    (args.outdir / "inputs.json").write_text(json.dumps(
        {"gds": str(args.gds), "gds_sha256": sha256_file(args.gds),
         "script_sha256": sha256_file(Path(__file__)),
         "pitches_nm": list(PITCHES_NM)}, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v["end_to_end"] for k, v in res.items()}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
