#!/usr/bin/env python3
"""Unit coverage for scripts/ci/content_hash.py (issue #538).

Two jobs, matching the two halves of the defect that consolidated ten copies of
`sha256_file()` into one:

1. **The conventions cannot drift apart.** `sha256_file_tagged()` must stay
   exactly `PREFIX + sha256_file()`. The old bug was six copies returning bare
   hex and four returning the `sha256:`-prefixed form under one name; the fix is
   worthless if the two names it replaced them with stop agreeing.
2. **A copy cannot quietly regrow.** `test_no_module_redefines_the_helpers` and
   `test_hashlib_sha256_is_confined` fail on a fresh in-tree `hashlib.sha256`
   call site, which is how this duplication accumulated in the first place
   (issue #404 deduped one copy; nine were still standing).

Digests are checked against an independent `hashlib` oracle, never against
another `content_hash` call, so a wrong implementation cannot agree with itself.

Run directly (`python3 scripts/ci/tests/test_content_hash.py`) or via
`npm run test:unit`.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
import tempfile
import unittest
from pathlib import Path

CI_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = CI_DIR.parents[1]

_spec = importlib.util.spec_from_file_location("content_hash", CI_DIR / "content_hash.py")
assert _spec and _spec.loader
ch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ch)

#: Trees whose non-test Python is expected to hash through `content_hash`.
SCANNED_TREES = ("sim", "layout", "scripts")

#: Non-test files that may still call `hashlib.sha256` directly, each with the
#: reason it is not a `sha256_file()` copy. Shrinking this list is welcome;
#: growing it needs the same justification the entries below carry.
#:
#: Not scanned, for the record: `sim/pex-native/run.sh` embeds a `python3 -I`
#: heredoc, which by design cannot import a repo module.
HASHLIB_ALLOWED = {
    # The canonical implementation itself.
    "scripts/ci/content_hash.py",
    # `_sha()` -- a bare file digest under its own name, never presented as
    # `sha256_file`, so it is outside issue #538's convention split.
    "sim/monte-carlo-untrimmed/qualify_dr005.py",
    # Hashes an in-memory netlist body (joined text), not a file.
    "sim/trim-lsb-chained/run_trim_lsb_chained.py",
}

#: The helper names that used to be duplicated. Only `content_hash` may bind
#: them with a `def`.
GUARDED_DEFS = ("sha256_file", "sha256_file_tagged", "sha256_bytes", "sha256_text")

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def tracked_python() -> list[Path]:
    """Non-test `.py` files under the scanned trees (the tree, not git: offline)."""
    out: list[Path] = []
    for tree in SCANNED_TREES:
        for p in sorted((REPO_ROOT / tree).rglob("*.py")):
            rel = p.relative_to(REPO_ROOT).as_posix()
            if "/tests/" in f"/{rel}" or p.name.startswith("test_"):
                continue
            if "/.venv/" in f"/{rel}":
                continue
            out.append(p)
    return out


class ContentHashTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def write(self, name: str, data: bytes) -> Path:
        p = self.tmp / name
        p.write_bytes(data)
        return p

    # -- the relationship issue #538 exists to pin -------------------------

    def test_tagged_is_exactly_prefix_plus_bare(self) -> None:
        """AC5: the tagged helper's output is `"sha256:" + ` the bare one's."""
        self.assertEqual(ch.PREFIX, "sha256:")
        for name, data in (
            ("empty.bin", b""),
            ("small.txt", b"sky130 bandgap\n"),
            ("chunk_crossing.bin", bytes(range(256)) * 8192),  # 2 MiB
        ):
            path = self.write(name, data)
            with self.subTest(name=name):
                bare = ch.sha256_file(path)
                self.assertEqual(ch.sha256_file_tagged(path), f"sha256:{bare}")
                self.assertEqual(ch.sha256_file_tagged(path), ch.tagged(bare))

    def test_bare_helpers_return_plain_lowercase_hex(self) -> None:
        """No helper documented as bare may leak the tag (the inverse of AC5)."""
        path = self.write("x.bin", b"abc")
        for label, got in (
            ("sha256_file", ch.sha256_file(path)),
            ("sha256_bytes", ch.sha256_bytes(b"abc")),
            ("sha256_text", ch.sha256_text("abc")),
        ):
            with self.subTest(helper=label):
                self.assertRegex(got, HEX64)
                self.assertNotIn(ch.PREFIX, got)

    # -- correctness against an independent oracle ------------------------

    def test_matches_hashlib_oracle_across_the_chunk_boundary(self) -> None:
        """Chunked reads must not change the digest at any size."""
        for size in (0, 1, 1 << 20, (1 << 20) + 1, 3 * (1 << 20) - 7):
            data = bytes((i * 7 + 13) % 256 for i in range(size))
            path = self.write(f"n{size}.bin", data)
            with self.subTest(size=size):
                expected = hashlib.sha256(data).hexdigest()
                self.assertEqual(ch.sha256_file(path), expected)
                self.assertEqual(ch.sha256_file_tagged(path), f"sha256:{expected}")

    def test_bytes_text_and_file_agree_on_the_same_payload(self) -> None:
        text = "VDD/VSS\nsky130\n"
        path = self.write("t.txt", text.encode())
        expected = hashlib.sha256(text.encode()).hexdigest()
        self.assertEqual(ch.sha256_text(text), expected)
        self.assertEqual(ch.sha256_bytes(text.encode()), expected)
        self.assertEqual(ch.sha256_file(path), expected)

    def test_accepts_a_str_path(self) -> None:
        """`pexlib.sha256_file` accepted `str` before consolidation; it still must."""
        path = self.write("s.bin", b"hello")
        self.assertEqual(ch.sha256_file(str(path)), ch.sha256_file(path))

    # -- the copies cannot regrow ------------------------------------------

    def test_no_module_redefines_the_helpers(self) -> None:
        """Only `content_hash` may `def` one of the consolidated names."""
        offenders: list[str] = []
        pattern = re.compile(rf"^\s*def _?({'|'.join(GUARDED_DEFS)})\s*\(", re.MULTILINE)
        for path in tracked_python():
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel == "scripts/ci/content_hash.py":
                continue
            for m in pattern.finditer(path.read_text()):
                offenders.append(f"{rel}: def {m.group(1)}")
        self.assertEqual(
            offenders,
            [],
            "these redefine a helper that scripts/ci/content_hash.py owns "
            "(issue #538 consolidated 10 such copies); import it instead:\n  "
            + "\n  ".join(offenders),
        )

    def test_hashlib_sha256_is_confined(self) -> None:
        """A new in-tree SHA-256 call site is how copy #11 would start."""
        offenders: list[str] = []
        for path in tracked_python():
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel in HASHLIB_ALLOWED:
                continue
            if "hashlib.sha256" in path.read_text():
                offenders.append(rel)
        self.assertEqual(
            offenders,
            [],
            "these call hashlib.sha256 directly outside scripts/ci/content_hash.py; "
            "import the helper, or add the file to HASHLIB_ALLOWED with the reason "
            "it is not a sha256_file() copy:\n  " + "\n  ".join(offenders),
        )

    def test_allowlist_has_no_stale_entries(self) -> None:
        """An allowlisted file that stopped calling hashlib must leave the list."""
        stale = [
            rel
            for rel in sorted(HASHLIB_ALLOWED)
            if "hashlib.sha256" not in (REPO_ROOT / rel).read_text()
        ]
        self.assertEqual(stale, [], f"drop these from HASHLIB_ALLOWED: {stale}")


if __name__ == "__main__":
    unittest.main()
