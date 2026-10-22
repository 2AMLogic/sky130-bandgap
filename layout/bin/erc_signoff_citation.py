#!/usr/bin/env python3
"""Point `signoff/block-manifest.json`'s T1 item-11 citation at a given ERC record.

Invoked by ``layout/bin/run-erc-supply-flow.sh`` after it writes a record, so
the block's machine-graded T1 tracker (issue #282) cannot silently keep citing
a superseded ERC run. Regrading is deliberately **not** done here — that is
``signoff/regenerate.sh``'s job, and CI's ``signoff`` job re-grades and fails on
any drift.

Item 11 is the first T1 item no single artifact proves
(`klayout-tools/docs/cli/signoff.md`, "Power delivery (structural)"), so its
manifest ``evidence`` entry is a JSON **array**: the `klt erc` supply run plus
the `klt lvs` report item 4 grades (this block is analog with a SPICE
reference, so there is no `klt place-and-route` citation and the analog branch
applies — the reference must have carried the supplies in
``net_correspondence``).

The ``content_hash`` pinned for each part is that envelope's own
``provenance.input.content_hash`` — the hash of the artifact the report
*describes*, not of the report file — matching how the existing items 3 and 8
entries are pinned.
"""

from __future__ import annotations

import argparse
import json
import pathlib

MANIFEST = pathlib.Path("signoff/block-manifest.json")
CELL = pathlib.Path("layout/bandgap-core")


def input_hash(envelope: pathlib.Path) -> str | None:
    data = json.loads(envelope.read_text())
    prov = data.get("provenance") or {}
    src = prov.get("input") or {}
    return src.get("content_hash")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--record-id", required=True)
    ap.add_argument("--newest", required=True, help="routed-GDS record id to cite")
    args = ap.parse_args()

    erc = CELL / "erc" / args.record_id / f"erc.{args.newest}.json"
    if not MANIFEST.is_file():
        raise SystemExit(f"erc_signoff_citation.py: missing {MANIFEST}")
    manifest = json.loads(MANIFEST.read_text())
    # Item 11's LVS half is item 4's report, whichever record that is: the
    # newest routed-GDS record's own lvs.combined.json can predate the
    # provenance block (see below), and item 4 is where the pinnable one lives.
    item4 = manifest.get("evidence", {}).get("4")
    if not isinstance(item4, dict) or "file" not in item4:
        raise SystemExit("erc_signoff_citation.py: manifest has no item 4 LVS citation")
    lvs = pathlib.Path(item4["file"])
    for path in (erc, lvs):
        if not path.is_file():
            raise SystemExit(f"erc_signoff_citation.py: missing {path}")

    erc_hash = input_hash(erc)
    if erc_hash is None:
        raise SystemExit(f"erc_signoff_citation.py: {erc} has no provenance.input hash")

    # The ERC part carries the load-bearing pin: `provenance.input.content_hash`
    # is what binds the committed report to the committed routed GDS.
    erc_entry: dict[str, str] = {"file": str(erc), "content_hash": erc_hash}

    # The LVS part is pinned the same way, to the `provenance.input.content_hash`
    # a `klt lvs` >= 0.7.0 report records (the hash of the pre-extracted layout
    # netlist it compared). Item 4 cites the same report, so the two stay in
    # step. A report that records no input hash at all (a 0.2.0-era `klt lvs`
    # writes `provenance.input: null`) cannot be pinned: pinning against it
    # renders `unverifiable_provenance`, so refuse rather than cite it unpinned.
    lvs_hash = input_hash(lvs)
    if lvs_hash is None:
        raise SystemExit(
            f"erc_signoff_citation.py: {lvs} has no provenance.input hash "
            "(re-produce it with a klt lvs that records provenance)"
        )
    lvs_entry: dict[str, str] = {"file": str(lvs), "content_hash": lvs_hash}

    manifest.setdefault("evidence", {})["11"] = [erc_entry, lvs_entry]
    manifest["evidence"] = {
        k: manifest["evidence"][k] for k in sorted(manifest["evidence"], key=int)
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        f"erc_signoff_citation.py: item 11 cites {erc} + {lvs} "
        "-- run ./signoff/regenerate.sh to re-grade"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
