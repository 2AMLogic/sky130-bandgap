#!/usr/bin/env python3
"""Committed xschem netlists of design/*.sch, and the gates that keep them fresh.

T1 item 1 ("Design sources") is attested by an inventory that lists the
schematics *and the netlists derived from them* (signoff/attest/, issue #387).
A netlist that has silently drifted from its schematic attributes simulation
to a schematic that no longer exists, so this module owns three things:

  --write        regenerate design/netlist/<name>.spice with `klt netlist` and
                 rewrite design/netlist/netlist.lock.json (schematic hash,
                 netlist hash, xschem version). Needs xschem + the pinned
                 sky130 PDK's xschemrc. This is the only way the lock moves.
  --check-lock   (default) stdlib-only, offline, no xschem: the lock's recorded
                 schematic hash must equal sha256 of the committed .sch, and
                 its netlist hash must equal sha256 of the committed .spice.
                 Editing a schematic without re-running --write fails here, in
                 the PDK-free `checks` job.
  --check-regen  regenerate each netlist in a temp dir and diff it against the
                 committed one. Needs xschem; runs in the `pdk-smoke` job.

The first line of an xschem netlist is `** sch_path: <absolute path>`, which
differs per checkout, so `klt netlist --check` reports `drifted` on any
machine other than the generating one. Committed netlists therefore carry the
repo-relative path instead (the form sim/*/netlist-snapshots already use), and
--check-regen normalizes the same line before comparing.

xschem must be 3.4.7 (the version CI builds; 3.4.4 leaves the sky130 symbols'
`expr(...)` attributes unevaluated, see .github/workflows/ci.yml).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DESIGN = REPO_ROOT / "design"
NETLIST_DIR = DESIGN / "netlist"
LOCK = NETLIST_DIR / "netlist.lock.json"
SCHEMATICS = ("bandgap_core", "error_amp", "startup_injector")
XSCHEM_VERSION = "3.4.7"

RED = "\033[31m"
RESET = "\033[0m"


def sha256_file(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def normalize(text: str, name: str) -> str:
    """Replace the machine-local `** sch_path:` first line with the repo-relative one."""
    lines = text.splitlines(keepends=True)
    if not lines or not lines[0].startswith("** sch_path:"):
        raise ValueError(f"{name}: netlist does not start with a `** sch_path:` line")
    lines[0] = f"** sch_path: design/{name}.sch\n"
    return "".join(lines)


def generate(name: str, workdir: Path) -> str:
    """Run `klt netlist` on design/<name>.sch; return the normalized netlist."""
    pdk_root = os.environ.get("PDK_ROOT")
    pdk = os.environ.get("PDK", "sky130A")
    rcfile = os.environ.get("XSCHEM_RCFILE") or (
        f"{pdk_root}/{pdk}/libs.tech/xschem/xschemrc" if pdk_root else None
    )
    if not rcfile or not Path(rcfile).is_file():
        sys.exit(
            "FATAL: set PDK_ROOT (and PDK) or XSCHEM_RCFILE to the pinned sky130 "
            "PDK's xschemrc (see sim/bin/pdk-env.sh)."
        )
    out = workdir / f"{name}.spice"
    cmd = ["klt", "netlist", "--rcfile", rcfile, "-o", str(out), f"design/{name}.sch"]
    if os.environ.get("XSCHEM_BINARY"):
        cmd[2:2] = ["--xschem-binary", os.environ["XSCHEM_BINARY"]]
    run = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    if run.returncode != 0:
        sys.exit(f"FATAL: {' '.join(cmd)} exited {run.returncode}:\n{run.stdout}{run.stderr}")
    return normalize(out.read_text(), name)


def xschem_version() -> str:
    binary = os.environ.get("XSCHEM_BINARY", "xschem")
    out = subprocess.run([binary, "--version"], capture_output=True, text=True, check=False)
    first = (out.stdout or out.stderr).split()
    return first[1] if len(first) > 1 and first[0] == "XSCHEM" else "unknown"


def write() -> int:
    version = xschem_version()
    if version != f"V{XSCHEM_VERSION}":
        sys.exit(f"FATAL: xschem {version} found, {XSCHEM_VERSION} required (see module docstring).")
    NETLIST_DIR.mkdir(exist_ok=True)
    entries = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name in SCHEMATICS:
            text = generate(name, Path(tmp))
            path = NETLIST_DIR / f"{name}.spice"
            path.write_text(text)
            entries[name] = {
                "schematic": f"design/{name}.sch",
                "schematic_hash": sha256_file(DESIGN / f"{name}.sch"),
                "netlist": f"design/netlist/{name}.spice",
                "netlist_hash": sha256_file(path),
            }
    LOCK.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "comment": "Written by scripts/ci/design_netlists.py --write; do not edit by hand.",
                "xschem_version": XSCHEM_VERSION,
                "netlists": entries,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"wrote {len(entries)} netlists + {LOCK.relative_to(REPO_ROOT)}")
    return 0


def check_lock() -> int:
    errors: list[str] = []
    if not LOCK.is_file():
        errors.append(f"missing {LOCK.relative_to(REPO_ROOT)}")
        lock: dict = {}
    else:
        lock = json.loads(LOCK.read_text())
    entries = lock.get("netlists", {})
    for name in SCHEMATICS:
        entry = entries.get(name)
        if entry is None:
            errors.append(f"{name}: no entry in the netlist lock")
            continue
        sch, net = REPO_ROOT / entry["schematic"], REPO_ROOT / entry["netlist"]
        if sha256_file(sch) != entry["schematic_hash"]:
            errors.append(
                f"{entry['schematic']} changed since design/netlist/{name}.spice was derived "
                "from it; re-run scripts/ci/design_netlists.py --write"
            )
        if sha256_file(net) != entry["netlist_hash"]:
            errors.append(f"{entry['netlist']} was edited by hand; re-run --write")
    for extra in sorted(set(entries) - set(SCHEMATICS)):
        errors.append(f"{extra}: lock entry for a schematic this script does not manage")
    if errors:
        print(f"{RED}design netlist lock check FAILED:{RESET}", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(f"design netlists: {len(SCHEMATICS)}/{len(SCHEMATICS)} match their schematics (lock)")
    return 0


def check_regen() -> int:
    drifted = []
    with tempfile.TemporaryDirectory() as tmp:
        for name in SCHEMATICS:
            fresh = generate(name, Path(tmp))
            committed = (NETLIST_DIR / f"{name}.spice").read_text()
            if fresh != committed:
                drifted.append(name)
    if drifted:
        print(
            f"{RED}design netlists drifted from their schematics:{RESET} {', '.join(drifted)}; "
            "re-run scripts/ci/design_netlists.py --write",
            file=sys.stderr,
        )
        return 3
    print(f"design netlists: {len(SCHEMATICS)} regenerated byte-identical (klt netlist)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check-lock", action="store_true")
    mode.add_argument("--check-regen", action="store_true")
    args = parser.parse_args()
    if args.write:
        return write()
    if args.check_regen:
        return check_regen()
    return check_lock()


if __name__ == "__main__":
    raise SystemExit(main())
