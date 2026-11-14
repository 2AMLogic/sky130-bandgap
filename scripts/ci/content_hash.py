#!/usr/bin/env python3
"""One SHA-256 implementation, and a separate honest name per return convention
(issue #538).

Ten copies of `sha256_file(path) -> str` used to live across `sim/`, `layout/`
and `scripts/ci/`: six returned bare hex, four returned the `sha256:`-prefixed
form -- same name, same signature, opposite output. Nothing in the repo
normalized or stripped the prefix, so which convention a given call site needed
was invisible at the call and enforced by nothing. The two ends of one
signoff-envelope contract disagreed behind that single identifier:
`check_signoff_pins.py` compares its digest straight against a
`signoff/block-manifest.json` pin (every `content_hash` there is prefixed),
while `emit_klt_sim_envelopes.py` wrote that same field from a *bare* copy plus
a hand-written `f"sha256:{...}"`.

Pointing a prefixed call site at a bare helper (or the reverse) is not a type
error and fails no test where the value is written; it surfaces later as a
signoff gate rejecting evidence that is append-only, which is the one defect
class this repo cannot correct after the fact. So the convention lives in the
*name* here, never in which copy you happened to import:

* `sha256_bytes()` / `sha256_text()` / `sha256_file()` -> bare lowercase hex,
  the form `manifests/artifacts/*.manifest.json` `sha256` fields and the
  `*_sha256` keys in `sim/` records carry.
* `sha256_file_tagged()`, or `tagged()` over a digest you already hold -> the
  `PREFIX`-qualified form `signoff/` manifests and pins, and every
  `provenance.input.content_hash`, record.

Why this directory. It is the direction the repo's one pre-existing cross-tree
hashing import already runs: `sim/bin/sim_common.py::_tracked_hashes()` loads
`check_artifact_manifests.tracked_hashes()` out of `scripts/ci` explicitly "so
there is one copy of the rule-4 hashing", while nothing under `scripts/ci/`
imports from `sim/bin`. Consumers in other trees add this directory to
`sys.path` and `from content_hash import ...`; the four `scripts/ci/` checks do
the same, because their own tests load them by file path rather than by package
import.

`scripts/ci/tests/test_content_hash.py` pins the `tagged == PREFIX + bare`
relationship so the two conventions cannot drift apart again, and fails if any
module grows a fresh copy of one of these helpers.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

#: Algorithm tag `signoff/` records in front of a digest. The 7-character
#: difference between a tagged and a bare digest is the whole bug this module
#: exists to make visible.
PREFIX = "sha256:"

#: Read granularity of `sha256_file`. Bounds memory on a multi-hundred-MB GDS
#: while staying far above per-read overhead; the digest is identical at any
#: chunk size, so this is a performance knob and never a correctness one.
_CHUNK_BYTES = 1 << 20


def tagged(bare_hex: str) -> str:
    """`PREFIX` + an already-computed bare digest.

    For the call sites that hold a digest from somewhere else (a manifest
    field, a hash of in-memory text) and need the recorded form.
    """
    return f"{PREFIX}{bare_hex}"


def sha256_bytes(data: bytes) -> str:
    """SHA-256 of `data` as bare lowercase hex."""
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """SHA-256 of `text`'s UTF-8 encoding as bare lowercase hex."""
    return sha256_bytes(text.encode())


def sha256_file(path: Path | str) -> str:
    """SHA-256 of `path`'s bytes as bare lowercase hex, read in chunks."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_file_tagged(path: Path | str) -> str:
    """`sha256_file()` in the `PREFIX`-qualified form `signoff/` records."""
    return tagged(sha256_file(path))
