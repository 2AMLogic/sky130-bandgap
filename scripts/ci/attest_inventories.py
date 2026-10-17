#!/usr/bin/env python3
"""Build and verify the artifact-anchored T1 attestations for items 1, 2, 9, 10.

`klt signoff` 0.7.0 has no verb for T1 items 1 (Design sources), 2 (Layout),
9 (Testbenches shipped) and 10 (Repo hygiene). It grades them `met` only for a
generic envelope that declares `t1_item`, pins the audited artifact by path and
content hash (`provenance.input`), and is cited by a manifest entry pinning the
same hash (klayout-tools#2718). `klt signoff --attest` (klayout-tools#2844) is
not in 0.7.0, so this script produces that generic form itself; switch to the
verb when a release carries it.

What it writes (all under signoff/attest/, plus the manifest pins):

  item 1   design-sources.inventory.json   .sch/.sym sources + derived netlists
  item 9   testbench-inventory.json        every runnable testbench + cold start
  item 10  repo-hygiene.inventory.json     README, LICENSE, CI workflow, commands
  item 2   (no inventory)                  the envelope pins the routed GDS
  item-{1,2,9,10}.evidence.json            the envelopes `klt signoff` grades

Every inventory lists its files with `content_hash`; the envelope pins the
inventory's own hash, and signoff/block-manifest.json pins the same value, so
the chain is: manifest pin == envelope pin == sha256(inventory) and each
inventory entry == sha256(file). Editing any inventoried file breaks the second
link, and this script's default (check) mode fails naming the file.

Modes:
  --write   rebuild everything from the tree (signoff/regenerate.sh step 1)
  (default) rebuild in memory and require the committed bytes to match
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ATTEST = REPO_ROOT / "signoff" / "attest"
MANIFEST = REPO_ROOT / "signoff" / "block-manifest.json"
PINNED_INPUTS = REPO_ROOT / "signoff" / "pinned-inputs.json"

ROUTED_GDS = (
    "layout/bandgap-core/reports/20260923-070209-dbd57a9/bandgap_core_routed.gds"
)
SCHEMATICS = ("bandgap_core", "error_amp", "startup_injector")

RED = "\033[31m"
RESET = "\033[0m"

SWITCH_NOTE = (
    "Produced by scripts/ci/attest_inventories.py in the artifact-anchored "
    "generic form klt 0.7.0 grades; replace with `klt signoff --attest` once a "
    "klayout-tools release carries it (klayout-tools#2844)."
)


def sha256_file(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def dump(document: dict) -> str:
    return json.dumps(document, indent=2) + "\n"


def tracked(pattern: str) -> list[str]:
    """Repo-relative files matching a glob, sorted (the tree, not git: offline)."""
    return sorted(
        p.relative_to(REPO_ROOT).as_posix()
        for p in REPO_ROOT.glob(pattern)
        if p.is_file()
    )


def entries(roles: list[tuple[str, str]]) -> list[dict]:
    seen: set[str] = set()
    out = []
    for path, role in roles:
        if path in seen:
            continue
        seen.add(path)
        out.append(
            {"path": path, "role": role, "content_hash": sha256_file(REPO_ROOT / path)}
        )
    return out


def klt_version() -> str:
    text = (REPO_ROOT / "scripts/ci/check_signoff_freshness.py").read_text()
    return re.search(r'^KLT_VERSION = "([^"]+)"', text, re.M).group(1)


def design_sources() -> dict:
    roles = []
    for name in SCHEMATICS:
        roles += [(f"design/{name}.sch", "schematic"), (f"design/{name}.sym", "symbol")]
    for name in SCHEMATICS:
        roles.append((f"design/netlist/{name}.spice", "derived-netlist"))
    roles.append(("design/netlist/netlist.lock.json", "netlist-freshness-lock"))
    roles.append(("scripts/ci/design_netlists.py", "netlist-generator-and-checker"))
    return {
        "schema_version": 1,
        "t1_item": 1,
        "description": (
            "Design sources: the xschem schematics/symbols of the three cells and "
            "the netlists derived from them. netlist.lock.json records, per "
            "netlist, the schematic hash it was derived from, so a schematic edit "
            "without regenerating its netlist fails the freshness check."
        ),
        "files": entries(roles),
        "checks": [
            {
                "id": "netlist-freshness-lock",
                "command": "python3 scripts/ci/design_netlists.py --check-lock",
                "needs": "python3 only",
                "ci_job": "checks",
            },
            {
                "id": "netlist-regeneration",
                "command": "python3 scripts/ci/design_netlists.py --check-regen",
                "needs": "xschem 3.4.7, the pinned sky130 PDK, klt netlist",
                "ci_job": "pdk-smoke",
            },
        ],
    }


def testbench_dirs() -> tuple[list[dict], list[str]]:
    """Per-harness-directory rows, plus record-only directories (no bench)."""
    rows, record_only = [], []
    for directory in sorted(p for p in (REPO_ROOT / "sim").iterdir() if p.is_dir()):
        name = directory.name
        if name in ("bin", "tests"):
            continue
        experiment = directory / "experiment.json"
        runners = sorted(directory.glob("run_*.py"))
        benches = sorted(directory.glob("testbench/*.sch"))
        if not (experiment.is_file() or runners):
            record_only.append(f"sim/{name}")
            continue
        files = [(p.relative_to(REPO_ROOT).as_posix(), "testbench") for p in benches]
        files += [(p.relative_to(REPO_ROOT).as_posix(), "runner") for p in runners]
        if experiment.is_file():
            files.insert(0, (f"sim/{name}/experiment.json", "experiment"))
            command = f"python3 sim/bin/corner-run.py sim/{name}"
        else:
            command = f"python3 sim/{name}/{runners[0].name}"
        rows.append({"directory": f"sim/{name}", "cold_start": command, "files": files})
    return rows, record_only


def testbench_inventory() -> dict:
    rows, record_only = testbench_dirs()
    pdk = json.loads((REPO_ROOT / "sim/pdk.json").read_text())
    harness = entries(
        [
            ("sim/pdk.json", "pdk-pin"),
            ("sim/bin/corner-run.py", "harness"),
            ("sim/bin/sim_common.py", "harness"),
            ("sim/spiceinit", "harness"),
        ]
    )
    benches = []
    for row in rows:
        benches.append(
            {
                "directory": row["directory"],
                "cold_start": row["cold_start"],
                "files": entries(row["files"]),
            }
        )
    return {
        "schema_version": 1,
        "t1_item": 9,
        "description": (
            "Testbenches shipped: every sim/ directory that carries a runnable "
            "testbench (an experiment.json for sim/bin/corner-run.py, or a "
            "run_*.py entry point), with its cold-start command, and the PDK "
            "revision and tool versions the results were produced under. "
            "Directories that only hold derived records (no bench of their own) "
            "are listed in `record_only_directories` rather than silently omitted."
        ),
        "pdk": {
            "pin_file": "sim/pdk.json",
            "family": pdk["family"],
            "variant": pdk["variant"],
            "open_pdks_commit": pdk["open_pdks_commit"],
            "install_command": pdk["install_command"],
            "note": (
                "Records the revision in force when this inventory was written. "
                "A PDK re-pin (#369) or requalification (#370) changes "
                "sim/pdk.json; this inventory then goes stale and must be "
                "regenerated."
            ),
        },
        "tools": {
            "xschem": "3.4.7 (built from source by .github/workflows/ci.yml)",
            "ngspice": "see the `tools` block of each sim/*/records/*.json",
            "klayout-tools": klt_version(),
            "python": "3.9+, standard library only (sim/README.md)",
        },
        "harness": harness,
        "testbenches": benches,
        "record_only_directories": record_only,
    }


def repo_hygiene() -> dict:
    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text()
    triggers = [t for t in ("push", "pull_request") if re.search(rf"^\s+{t}:", workflow, re.M)]
    commands = re.findall(r"^\s+run:\s+(\S.*)$", workflow, re.M)
    return {
        "schema_version": 1,
        "t1_item": 10,
        "description": (
            "Repo hygiene: README, LICENSE, and the CI workflow that runs on "
            "every push/PR, with the commands it runs."
        ),
        "files": entries(
            [
                ("README.md", "readme"),
                ("LICENSE", "license"),
                (".github/workflows/ci.yml", "ci-workflow"),
                ("package.json", "ci-entry-points"),
            ]
        ),
        "ci": {
            "workflow": ".github/workflows/ci.yml",
            "runs_on": triggers,
            "single_line_commands": commands,
            "entry_point": "npm run check:ci (package.json)",
        },
    }


def inventory_passes(inventory: dict | None) -> bool:
    """Mechanical verdict: the inventory is non-empty and every row has its anchors.

    Item 2 has no inventory (the envelope pins the GDS, whose existence
    sha256_file already asserted by reading it), so it passes by construction.
    """
    if inventory is None:
        return True
    if "testbenches" in inventory:
        return bool(inventory["testbenches"]) and all(
            row["files"] and all(f["content_hash"] for f in row["files"])
            for row in inventory["testbenches"]
        )
    return bool(inventory.get("files"))


def envelope(item: int, summary: str, source: str, anchor: str, anchor_hash: str,
             inventory: dict | None) -> dict:
    return {
        "schema_version": 1,
        "kind": "generic",
        "t1_item": item,
        "status": "pass" if inventory_passes(inventory) else "fail",
        "summary": summary,
        "source": source,
        "provenance": {
            "input": {"path": {"path": anchor, "scope": "repo"}, "content_hash": anchor_hash}
        },
        "note": SWITCH_NOTE,
    }


def build() -> dict[Path, str]:
    """Every generated file, as {path: text}."""
    out: dict[Path, str] = {}
    inventories = {
        1: ("design-sources.inventory.json", design_sources()),
        9: ("testbench-inventory.json", testbench_inventory()),
        10: ("repo-hygiene.inventory.json", repo_hygiene()),
    }
    summaries = {
        1: "Design sources: schematics, symbols and derived netlists, each hash-pinned.",
        9: "Testbenches shipped: every runnable testbench with its cold-start command and the PDK/tool pins.",
        10: "Repo hygiene: README, LICENSE, CI workflow and the commands it runs.",
    }
    pins: dict[int, tuple[str, str]] = {}
    for item, (filename, inventory) in inventories.items():
        path = ATTEST / filename
        text = dump(inventory)
        out[path] = text
        rel = path.relative_to(REPO_ROOT).as_posix()
        digest = f"sha256:{hashlib.sha256(text.encode()).hexdigest()}"
        pins[item] = (rel, digest)
        out[ATTEST / f"item-{item}.evidence.json"] = dump(
            envelope(item, summaries[item], rel, rel, digest, inventory)
        )
    gds_hash = sha256_file(REPO_ROOT / ROUTED_GDS)
    pins[2] = (ROUTED_GDS, gds_hash)
    out[ATTEST / "item-2.evidence.json"] = dump(
        envelope(
            2,
            "Layout: the committed routed GDS, regenerated by "
            "layout/bin/run-bandgap-routed-flow.sh (DRC/ERC cited by items 3 and 11 "
            "pin this same stream).",
            "layout/bin/run-bandgap-routed-flow.sh",
            ROUTED_GDS,
            gds_hash,
            None,
        )
    )

    manifest = json.loads(MANIFEST.read_text())
    for item, (_, digest) in pins.items():
        manifest["evidence"][str(item)] = {
            "file": f"signoff/attest/item-{item}.evidence.json",
            "content_hash": digest,
        }
    manifest["evidence"] = dict(sorted(manifest["evidence"].items(), key=lambda kv: int(kv[0])))
    out[MANIFEST] = dump(manifest)

    declared = json.loads(PINNED_INPUTS.read_text())
    declared["pins"] = [p for p in declared["pins"] if str(p["item"]) not in {"1", "2", "9", "10"}]
    notes = {
        1: "design-sources.inventory.json; every listed file is re-hashed by scripts/ci/attest_inventories.py.",
        2: "the routed GDS item 3 and item 11 also pin; generator layout/bin/run-bandgap-routed-flow.sh.",
        9: "testbench-inventory.json; every listed file is re-hashed by scripts/ci/attest_inventories.py. Pins the PDK revision from sim/pdk.json (#369/#370 will move it).",
        10: "repo-hygiene.inventory.json; every listed file is re-hashed by scripts/ci/attest_inventories.py.",
    }
    for item, (rel, _) in pins.items():
        declared["pins"].append({"item": str(item), "describes": rel, "note": notes[item]})
    declared["pins"].sort(key=lambda p: (int(p["item"]), p.get("index", -1)))
    out[PINNED_INPUTS] = dump(declared)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    ATTEST.mkdir(parents=True, exist_ok=True)
    expected = build()
    if args.write:
        for path, text in expected.items():
            path.write_text(text)
        print(f"wrote {len(expected)} attestation files")
        return 0

    errors = []
    for path, text in expected.items():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if not path.is_file():
            errors.append(f"{rel}: missing")
        elif path.read_text() != text:
            errors.append(f"{rel}: stale against the tree")
    stale_inventories = sorted(
        p.relative_to(REPO_ROOT).as_posix()
        for p in ATTEST.glob("*.inventory.json")
        if p not in expected
    )
    errors += [f"{p}: not produced by this script" for p in stale_inventories]
    if errors:
        print(f"{RED}T1 attestation check FAILED:{RESET}", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        print(
            "\nAn inventoried file (or a testbench/GDS/CI workflow) changed, or one "
            "was added, without the attestation being rebuilt. If the change is "
            "intended: ./signoff/regenerate.sh (or `python3 "
            "scripts/ci/attest_inventories.py --write`), then commit.",
            file=sys.stderr,
        )
        return 1
    print(f"T1 attestations current: {len(expected)} generated files match the tree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
