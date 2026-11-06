#!/usr/bin/env python3
"""Regenerate `reference/bandgap_core_composed.spice` from design/netlist/*.spice.

    python3 sim/pex-native/compose_reference.py [--check]

`--check` exits 1 if the committed file is stale against the design netlists.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pexlib  # noqa: E402

OUT = pexlib.HERE / "reference" / "bandgap_core_composed.spice"

if __name__ == "__main__":
    text = pexlib.compose_reference()
    if "--check" in sys.argv:
        sys.exit(0 if OUT.is_file() and OUT.read_text() == text else 1)
    OUT.write_text(text)
    print(f"{OUT.relative_to(pexlib.REPO_ROOT)} sha256={pexlib.sha256_text(text)}")
