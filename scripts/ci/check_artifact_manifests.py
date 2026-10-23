#!/usr/bin/env python3
"""Validate manifests/artifacts/*.manifest.json (issue #424).

Evidence bytes live in the fleet artifact store; git keeps only manifests.
Rules, each failing the check:
  1. schema: {"schema_version": 1, "entries": [...]}; every entry has
     sha256 (64 hex), size (int >= 0), kind, producer (object), uri (str),
     and only those plus optional name/media_type.
  2. every uri starts with "artifact:".
  3. no field names a storage location (s3:// or arn:aws:).
  4. no entry's sha256 equals the sha256 of a tracked file (its bytes were
     also committed).

Stdlib-only; rule 4 uses `git ls-files`. Usage:
  check_artifact_manifests.py [--root DIR]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

MANIFEST_GLOB = "manifests/artifacts/*.manifest.json"
REQUIRED = {"sha256", "size", "kind", "producer", "uri"}
OPTIONAL = {"name", "media_type"}
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
STORAGE_RE = re.compile(r"s3://|arn:aws:")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tracked_hashes(root: Path) -> dict[str, str]:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True
    ).stdout.decode()
    hashes: dict[str, str] = {}
    for rel in filter(None, out.split("\0")):
        p = root / rel
        if p.is_file() and not p.is_symlink():
            hashes.setdefault(sha256_file(p), rel)
    return hashes


def check_manifest(path: Path, tracked: dict[str, str]) -> list[str]:
    errs: list[str] = []
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError) as err:
        return [f"{path}: unreadable manifest: {err}"]
    if STORAGE_RE.search(path.read_text()):
        errs.append(f"{path}: names a storage location (s3:// or arn:aws:)")
    if not isinstance(doc, dict) or doc.get("schema_version") != 1 or not isinstance(
        doc.get("entries"), list
    ):
        return errs + [f"{path}: schema: want {{schema_version: 1, entries: [...]}}"]
    for i, e in enumerate(doc["entries"]):
        where = f"{path}: entries[{i}]"
        if not isinstance(e, dict):
            errs.append(f"{where}: not an object")
            continue
        keys = set(e)
        if REQUIRED - keys or keys - REQUIRED - OPTIONAL:
            errs.append(
                f"{where}: schema: missing {sorted(REQUIRED - keys)} "
                f"unknown {sorted(keys - REQUIRED - OPTIONAL)}"
            )
        sha = e.get("sha256")
        if not (isinstance(sha, str) and SHA_RE.match(sha)):
            errs.append(f"{where}: sha256 is not 64 lowercase hex chars")
        size = e.get("size")
        if not (isinstance(size, int) and not isinstance(size, bool) and size >= 0):
            errs.append(f"{where}: size is not a non-negative integer")
        if not isinstance(e.get("producer"), dict):
            errs.append(f"{where}: producer is not an object")
        uri = e.get("uri")
        if not (isinstance(uri, str) and uri.startswith("artifact:")):
            errs.append(f"{where}: uri {uri!r} does not start with 'artifact:'")
        if isinstance(sha, str) and sha in tracked:
            errs.append(f"{where}: bytes also committed as {tracked[sha]} (sha256 {sha})")
    return errs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    root = ap.parse_args(argv).root
    manifests = sorted(root.glob(MANIFEST_GLOB))
    errs: list[str] = []
    if manifests:
        tracked = tracked_hashes(root)
        for m in manifests:
            errs += check_manifest(m, tracked)
    for e in errs:
        print(f"FAIL {e}", file=sys.stderr)
    print(f"artifact manifests: {len(manifests)} checked, {len(errs)} problem(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
