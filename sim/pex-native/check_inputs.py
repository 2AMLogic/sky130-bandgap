#!/usr/bin/env python3
"""Refuse a native-pex pilot whose inputs or result cannot be compared (issue #335).

    check_inputs.py inputs  --reference REF.spice --extracted X.spice
    check_inputs.py matrix  --measurements measurement-doc.json

Exit 0 ok; 1 refused (reason on stderr).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pexlib  # noqa: E402


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("inputs")
    a.add_argument("--reference", type=Path, required=True)
    a.add_argument("--extracted", type=Path, required=True)
    b = sub.add_parser("matrix")
    b.add_argument("--measurements", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "inputs":
            pexlib.check_reference(args.reference.read_text(), args.extracted.read_text())
        else:
            pexlib.check_matrix(json.loads(args.measurements.read_text()))
    except pexlib.PexNativeError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
