#!/usr/bin/env python3
"""Regression guard for `layout/generator-notes.md` pointer integrity (#565).

Issue #552 moved 13 never-loaded ``*_NOTE`` constants out of ``layout/bin/``
into anchored sections of `layout/generator-notes.md`; #565 retargeted the
25 citations that still named a moved constant bare. This test keeps that
invariant fresh -- #565 is the *second* cleanup pass over the same move, so
the rot is known to recur on the next one.

Both sets are derived from the document itself, never hardcoded, so a
future note (a 14th section, a renamed anchor) updates the guard with the
doc, not against it:

* the moved-name set, from the ``## <NAME>_NOTE`` headings;
* the anchor set, from the ``<a id="...">`` tags beside them.

Two halves of the invariant, each a test method:

(a) no bare moved-note name appears in the guarded set -- ``layout/bin``,
    ``layout/tests``, `layout/README.md`, `layout/matching-plan.md`, the
    paths #565 retargeted -- without a ``generator-notes.md#`` pointer on
    the same line. The ``*_NOTE`` constants that still live in source next
    to the code they explain are not headings in the document, so the
    derived moved-name set cannot flag them.
(b) every ``generator-notes.md#<anchor>`` pointer anywhere in the repo
    names an ``<a id="...">`` anchor that exists in the document.

Two deliberate non-requirements, each of which would be red for reasons
outside this invariant: the guard does **not** assert that every anchor is
referenced somewhere (an anchor may legitimately have no pointer yet), and
the half-(a) scan does **not** reach the dated/append-only paths --
`layout/matching-plan-history.md`, ``spec/decision-records/**``,
``layout/bandgap-core/**`` -- which record what the source said at the
time and stay as written.

Wrapped pointers: a ``generator-notes.md#<anchor>`` pointer that wraps
across two comment lines never trips half (a), because the anchor form is
lowercase and hyphenated while half (a) matches only the UPPERCASE
constant form. A bare name whose pointer sits on a *different* line is
exactly the staleness half (a) exists to catch.

Standard library only (``unittest``), matching every other test under
`layout/tests`. Run directly, or via:

    npm run test:unit
    python3 -m unittest discover --start-directory layout/tests
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
NOTES_PATH = REPO_ROOT / "layout" / "generator-notes.md"

# Exactly the paths #565 retargeted: the two source trees plus the two
# standalone documents. Deliberately excludes the dated and append-only
# evidence paths (see module docstring).
GUARDED_DIRS = (REPO_ROOT / "layout" / "bin", REPO_ROOT / "layout" / "tests")
GUARDED_FILES = (
    REPO_ROOT / "layout" / "README.md",
    REPO_ROOT / "layout" / "matching-plan.md",
)
GUARDED_SUFFIXES = {".py", ".sh", ".md"}

HEADING_RE = re.compile(r"^## ([A-Z][A-Z0-9_]*_NOTE)\s*$", re.MULTILINE)
ANCHOR_RE = re.compile(r'^<a id="([a-z0-9-]+)"></a>$', re.MULTILINE)
POINTER_RE = re.compile(r"generator-notes\.md#([a-z0-9][a-z0-9-]*)")

# Pruned from the repo-wide half-(b) walk: VCS/orchestration state, vendor
# and virtualenv trees a pointer would never legitimately live in.
PRUNED_DIRS = {".git", ".loom", "node_modules", ".venv", "__pycache__"}


def guarded_files() -> list[Path]:
    paths: list[Path] = []
    for directory in GUARDED_DIRS:
        paths.extend(
            p for p in directory.rglob("*") if p.suffix in GUARDED_SUFFIXES
        )
    paths.extend(p for p in GUARDED_FILES if p.is_file())
    return paths


def repo_text_files() -> list[Path]:
    paths: list[Path] = []
    for dirpath, dirnames, filenames in Path(REPO_ROOT).walk():
        dirnames[:] = [d for d in dirnames if d not in PRUNED_DIRS]
        for filename in filenames:
            path = Path(dirpath) / filename
            try:
                if b"\x00" in path.read_bytes():
                    continue
            except OSError:
                continue
            paths.append(path)
    return paths


class TestGeneratorNotesPointers(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        notes = NOTES_PATH.read_text(encoding="utf-8")
        cls.moved_names = set(HEADING_RE.findall(notes))
        cls.anchors = set(ANCHOR_RE.findall(notes))

    def test_heading_and_anchor_derivations_agree(self) -> None:
        """The two derived sets describe the same sections.

        The document's own preamble convention: each ``## <NAME>_NOTE``
        heading carries an ``<a id>`` that is the lowercased name with
        underscores as hyphens. If the two derivations disagree, one of
        them is wrong and both halves below score against a broken map.
        """
        self.assertTrue(
            self.moved_names, "no *_NOTE headings found in generator-notes.md"
        )
        self.assertEqual(
            {name.lower().replace("_", "-") for name in self.moved_names},
            self.anchors,
        )

    def test_no_bare_moved_note_name_in_guarded_set(self) -> None:
        """Half (a): a moved name in the guarded set needs a same-line
        pointer."""
        stale: list[str] = []
        for path in guarded_files():
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(),
                start=1,
            ):
                if "generator-notes.md#" in line:
                    continue
                hits = [
                    name
                    for name in sorted(self.moved_names)
                    if re.search(rf"\b{re.escape(name)}\b", line)
                ]
                if hits:
                    stale.append(
                        f"{path.relative_to(REPO_ROOT)}:{lineno}: "
                        f"{', '.join(hits)}: {line.strip()}"
                    )
        self.assertEqual(
            stale,
            [],
            "bare moved-note name(s) without a generator-notes.md# pointer "
            "on the same line -- cite layout/generator-notes.md#<anchor> "
            "instead (surviving *_NOTE constants that still live in source "
            "are unaffected: they are not headings in the document)",
        )

    def test_every_pointer_names_an_existing_anchor(self) -> None:
        """Half (b): every pointer in the repo resolves."""
        missing: list[str] = []
        for path in repo_text_files():
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in POINTER_RE.finditer(text):
                if match.group(1) not in self.anchors:
                    missing.append(
                        f"{path.relative_to(REPO_ROOT)}: "
                        f"generator-notes.md#{match.group(1)}"
                    )
        self.assertEqual(
            missing,
            [],
            "generator-notes.md# pointer(s) name no <a id> anchor in "
            "layout/generator-notes.md",
        )


if __name__ == "__main__":
    unittest.main()
