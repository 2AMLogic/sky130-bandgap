#!/usr/bin/env python3
"""Re-hash the committed artifact behind every manifest pin; fail when it changed.

This is the half of issue #282's acceptance criterion ("CI fails when a
manifest cites an artifact that has since changed") that re-grading the
manifest structurally cannot cover, and issue #292 exists to close.

Why re-grading is not enough
----------------------------
`signoff/block-manifest.json` pins each citation to a `content_hash`. For
items 3 and 8 that hash is **not** the hash of the cited envelope file -- it
is the hash of the artifact that envelope *describes*, copied from the
envelope's own `provenance.input.content_hash` (see
`layout/bin/erc_signoff_citation.py`'s module docstring, and
`signoff/regenerate.sh` step 1 for item 8). When `klt signoff --manifest`
grades that kind of citation it compares the manifest pin against the recorded
hash and stops there: it never opens the artifact. The committed
`signoff/signoff-report.json` shows the consequence directly --
`citation.input_verified` is `null` on both of those rows.

So the two sides can keep agreeing with each other while the artifact they
both claim to describe has moved on:

  - item 3's DRC envelope records its input as an absolute path into the
    worktree that produced it, which exists on no other machine
    (klayout-tools#2340). Rewrite `bandgap_core_routed.gds` and nothing in the
    rendered report changes.
  - item 8's generic envelope is hand-rolled and never re-derived at grading
    time. Edit `design/block-characterization-report.md` and, again, nothing
    in the rendered report changes.

`scripts/ci/check_signoff_freshness.py` (byte-compare of a fresh re-grade
against the committed report) therefore cannot catch either case -- the fresh
render is identical. This check closes that gap.

Item 6 is the exception, and it inverts
---------------------------------------
A `klt yield` report carries no `provenance` block at all, so there is no
recorded hash to compare against and `klt signoff` opens and hashes the
sample-set document the report names in its own `samples` field. Item 6 is
therefore the one row whose `citation.input_verified` is `true`, and a
re-grade *does* catch an edit to the artifact behind it: the pinned document
is hashed at grading time, so `check-signoff-freshness.sh`'s byte-compare
fails -- the opposite of items 3 and 8 above. What this check adds for item 6
is coverage the re-grade cannot give (it runs klt-free and PDK-free in the
`checks` job) rather than a hash the re-grade misses, and with no
envelope-recorded hash to compare, item 6 is verified on two of the three legs
below rather than three. It is also why that `samples` value must stay
repo-relative (issue #288): `klt signoff` resolves it from the directory
grading runs in, so an absolute, machine-local path resolves nowhere else.

What it asserts
---------------
For every manifest evidence entry carrying a `content_hash`, a three-way
agreement:

    manifest pin  ==  sha256(the committed artifact)  ==  the hash the cited
                                                          envelope recorded

`signoff/pinned-inputs.json` supplies the one piece neither JSON file holds:
where in this repo the described artifact lives. Every pin must have an entry
there and every entry must match a live pin, so a new citation cannot be added
without declaring what its hash describes, and a removed one cannot leave a
stale mapping behind.

Deliberately stdlib-only and offline: no `klt`, no PDK, no network. It runs in
CI's `checks` job via `npm run check:ci`, beside the PDK-free repo checks,
rather than in the `signoff` job that has to install the pinned grader.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "signoff" / "block-manifest.json"
PINNED_INPUTS = REPO_ROOT / "signoff" / "pinned-inputs.json"

RED = "\033[31m"
RESET = "\033[0m"

REMEDY = """
How to fix, depending on which one is true:
  - the artifact was regenerated on purpose  -> re-run the flow that produces
    its evidence envelope, then ./signoff/regenerate.sh, and commit both;
  - the citation now describes a different artifact -> update that pin's
    `describes` path in signoff/pinned-inputs.json;
  - neither -> the committed artifact changed without its evidence being
    re-derived. That is the rot this check exists to catch; do not re-pin
    around it.
""".strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def pin_key(item: str, index: int | None) -> str:
    """Stable human-readable key for one manifest citation."""
    return f"item {item}" if index is None else f"item {item}[{index}]"


def manifest_pins(manifest: dict) -> tuple[dict[str, dict], list[str]]:
    """Return {pin key: {file, content_hash}} plus the unpinned citations."""
    pinned: dict[str, dict] = {}
    unpinned: list[str] = []
    for item, value in (manifest.get("evidence") or {}).items():
        entries = value if isinstance(value, list) else [value]
        for offset, entry in enumerate(entries):
            index = offset if isinstance(value, list) else None
            key = pin_key(item, index)
            if not isinstance(entry, dict):
                unpinned.append(key)
                continue
            if entry.get("content_hash"):
                pinned[key] = entry
            else:
                unpinned.append(key)
    return pinned, unpinned


def declared_pins(document: dict, errors: list[str]) -> dict[str, dict]:
    """Return {pin key: entry} from signoff/pinned-inputs.json."""
    declared: dict[str, dict] = {}
    for entry in document.get("pins") or []:
        item = entry.get("item")
        if item is None or not entry.get("describes"):
            errors.append(
                "signoff/pinned-inputs.json: every pin needs both `item` and "
                f"`describes`; got {json.dumps(entry, sort_keys=True)}"
            )
            continue
        key = pin_key(str(item), entry.get("index"))
        if key in declared:
            errors.append(f"signoff/pinned-inputs.json: duplicate entry for {key}")
            continue
        declared[key] = entry
    return declared


def envelope_input_hash(path: Path) -> str | None:
    """The hash the cited envelope itself recorded for its input, if any."""
    try:
        envelope = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(envelope, dict):
        return None
    provenance = envelope.get("provenance")
    if not isinstance(provenance, dict):
        return None
    recorded = provenance.get("input")
    if not isinstance(recorded, dict):
        return None
    value = recorded.get("content_hash")
    return value if isinstance(value, str) else None


def check_pin(key: str, citation: dict, declaration: dict, errors: list[str]) -> bool:
    """Verify one pin's three-way agreement. Returns True when it holds."""
    pin = citation["content_hash"]
    envelope_path = REPO_ROOT / citation["file"]
    artifact_path = REPO_ROOT / declaration["describes"]

    if not envelope_path.is_file():
        errors.append(f"{key}: cited evidence file is missing: {citation['file']}")
        return False
    if not artifact_path.is_file():
        errors.append(
            f"{key}: the artifact its pin describes is missing: "
            f"{declaration['describes']} (signoff/pinned-inputs.json)"
        )
        return False

    ok = True
    actual = sha256_file(artifact_path)
    if actual != pin:
        errors.append(
            f"{key}: {declaration['describes']} no longer matches the pin in "
            f"signoff/block-manifest.json.\n"
            f"      manifest pin: {pin}\n"
            f"      on disk now:  {actual}\n"
            f"      cited by:     {citation['file']}"
        )
        ok = False

    recorded = envelope_input_hash(envelope_path)
    if recorded is not None and recorded != pin:
        errors.append(
            f"{key}: the cited envelope records a different input hash than the "
            f"manifest pins.\n"
            f"      manifest pin:            {pin}\n"
            f"      {citation['file']}: {recorded}"
        )
        ok = False
    return ok


def main() -> int:
    for path in (MANIFEST, PINNED_INPUTS):
        if not path.is_file():
            print(
                f"{RED}FATAL:{RESET} missing {path.relative_to(REPO_ROOT)}",
                file=sys.stderr,
            )
            return 1

    manifest = json.loads(MANIFEST.read_text())
    pinned_inputs = json.loads(PINNED_INPUTS.read_text())

    errors: list[str] = []
    citations, unpinned = manifest_pins(manifest)
    declarations = declared_pins(pinned_inputs, errors)

    for key in sorted(set(citations) - set(declarations)):
        errors.append(
            f"{key}: pinned in signoff/block-manifest.json but undeclared in "
            "signoff/pinned-inputs.json. Add an entry naming the committed "
            "artifact that content_hash describes, so CI can re-hash it."
        )
    for key in sorted(set(declarations) - set(citations)):
        errors.append(
            f"{key}: declared in signoff/pinned-inputs.json but the manifest has "
            "no such pinned citation. Remove the stale entry."
        )

    verified = 0
    for key in sorted(set(citations) & set(declarations)):
        if check_pin(key, citations[key], declarations[key], errors):
            verified += 1

    if errors:
        print(
            f"{RED}signoff pin check FAILED:{RESET} a manifest pin no longer "
            "describes what is committed.",
            file=sys.stderr,
        )
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        print(f"\n{REMEDY}", file=sys.stderr)
        return 1

    print(
        f"signoff pins verified: {verified}/{len(citations)} pinned citations "
        "re-hashed against the committed artifact they describe "
        f"({len(unpinned)} unpinned citation(s) skipped"
        + (f": {', '.join(sorted(unpinned))}" if unpinned else "")
        + ")"
    )
    for key in sorted(set(citations) & set(declarations)):
        print(f"  [OK] {key} -> {declarations[key]['describes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
