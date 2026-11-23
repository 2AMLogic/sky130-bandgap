#!/usr/bin/env python3
"""Unit + recurrence-guard coverage for the canonical VREF accuracy windows (issue #545).

`sim_common.RATIFIED_VREF_WINDOW_V` is the single hand-rolled declaration of
DR-005's ratified 1.20 V +/-2% untrimmed window; every grading site imports
it. The two DR-003-era chained-array runners deliberately keep grading against
the historical pre-DR-005 draft +/-1% band (operator ruling 2026-11-23, option
`a`), renamed `DRAFT_VREF_WINDOW_V` so the next script copying the pattern
cannot read "draft, superseded" as "the spec".

`NoHandRolledCopiesTests` is the recurrence guard (mirrors
`test_batch_cli_flags.py::NoHandRolledCopiesTests` from issue #544): it fails
if any harness under `sim/` re-types the ratified floats or the retired
identifiers itself. Without it, the next bespoke script copies whichever
block it started from and the drift returns -- which is how four copies of
the ratified band and a false provenance citation happened in the first
place.
"""

from __future__ import annotations

import ast
import inspect
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SIM_DIR = REPO_ROOT / "sim"
sys.path.insert(0, str(SIM_DIR / "bin"))
sys.path.insert(0, str(SIM_DIR / "monte-carlo-untrimmed"))
sys.path.insert(0, str(SIM_DIR / "signoff-envelopes"))
sys.path.insert(0, str(SIM_DIR / "res-array-resize"))
sys.path.insert(0, str(SIM_DIR / "res-array-head-resistance"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "ci"))

import sim_common  # noqa: E402
import emit_klt_yield as eky  # noqa: E402
import emit_klt_sim_envelopes as emit  # noqa: E402
import qualify_dr005 as q  # noqa: E402
import run_mc_untrimmed  # noqa: E402
import run_res_array_head_resistance as rah  # noqa: E402
import run_res_array_resize as rar  # noqa: E402

#: The two DR-003-era runners that keep the historical draft band (operator
#: ruling option `a`): the only scripts allowed to name `DRAFT_VREF_WINDOW_V`.
DRAFT_BAND_SCRIPTS = (
    SIM_DIR / "res-array-resize" / "run_res_array_resize.py",
    SIM_DIR / "res-array-head-resistance" / "run_res_array_head_resistance.py",
)

RETIRED_IDENTIFIERS = ("VREF_SPEC_V", "SPEC_WINDOW_V", "WINDOW_V")
RATIFIED_FLOATS = (1.176, 1.224)
LITERAL_HIT = "ratified-band literal"


def _identifiers(node: ast.AST) -> list[str]:
    """Every name `node` binds or references (not strings/comments)."""
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, ast.arg):
        return [node.arg]
    if isinstance(node, ast.keyword):
        return [node.arg] if node.arg else []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.alias):
        return [node.asname or node.name]
    return []


def _numbers(nodes: list[ast.AST]) -> set[float]:
    return {
        n.value
        for n in nodes
        if isinstance(n, ast.Constant) and isinstance(n.value, float)
    }


def scan_for_hand_rolled_copies(text: str) -> list[str]:
    """Every retired identifier / re-typed ratified-band literal in `text`.

    Walks the parsed AST rather than matching source text, so formatting
    (multiline dicts, trailing commas, quote style) cannot hide a copy and a
    comment merely mentioning a retired name is not a hit. A tuple, list, set or
    dict display holding both ratified floats directly is a copy.
    """
    tree = ast.parse(text)
    idents: set[str] = set()
    literal = False
    for node in ast.walk(tree):
        idents.update(_identifiers(node))
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            elts = list(node.elts)
        elif isinstance(node, ast.Dict):
            elts = list(node.values)
        else:
            continue
        if set(RATIFIED_FLOATS) <= _numbers(elts):
            literal = True
    hits = [n for n in RETIRED_IDENTIFIERS if n in idents]
    return hits + ([LITERAL_HIT] if literal else [])


class CanonicalConstantTests(unittest.TestCase):
    def test_ratified_window_value(self) -> None:
        self.assertEqual(sim_common.RATIFIED_VREF_WINDOW_V, (1.176, 1.224))

    def test_matches_output_voltage_tc_manifest_limits(self) -> None:
        exp = json.loads((SIM_DIR / "output-voltage-tc" / "experiment.json").read_text())
        for name in ("vref_27", "vref_min", "vref_max"):
            m = next(m for m in exp["measurements"] if m["name"] == name)
            self.assertEqual(
                (m["min"], m["max"]),
                sim_common.RATIFIED_VREF_WINDOW_V,
                f"{name} limits drifted from DR-005's ratified window",
            )


class RatifiedConsumerTests(unittest.TestCase):
    def test_run_mc_untrimmed_imports_the_canonical_window(self) -> None:
        self.assertIs(run_mc_untrimmed.RATIFIED_VREF_WINDOW_V, sim_common.RATIFIED_VREF_WINDOW_V)
        self.assertFalse(hasattr(run_mc_untrimmed, "SPEC_WINDOW_V"))

    def test_spec_yield_grades_against_the_ratified_bounds(self) -> None:
        # 1.17 < 1.176 and 1.23 > 1.224 fall outside; only the midpoint counts.
        self.assertAlmostEqual(run_mc_untrimmed.spec_yield([1.17, 1.20, 1.23]), 1 / 3)

    def test_emit_klt_yield_imports_the_canonical_window(self) -> None:
        self.assertIs(eky.RATIFIED_VREF_WINDOW_V, sim_common.RATIFIED_VREF_WINDOW_V)
        self.assertFalse(hasattr(eky, "SPEC_WINDOW_V"))

    def test_qualify_dr005_defaults_bind_the_canonical_window(self) -> None:
        for fn in (q.grade_temperature, q.qualify):
            default = inspect.signature(fn).parameters["window"].default
            self.assertIs(default, sim_common.RATIFIED_VREF_WINDOW_V, fn.__name__)
        self.assertFalse(hasattr(q, "WINDOW_V"))

    def test_emit_klt_sim_envelopes_derives_window_from_canonical(self) -> None:
        self.assertEqual(emit.WINDOW, {"min": 1.176, "max": 1.224})
        self.assertIs(emit.WINDOW["min"], sim_common.RATIFIED_VREF_WINDOW_V[0])
        self.assertIs(emit.WINDOW["max"], sim_common.RATIFIED_VREF_WINDOW_V[1])


class DraftWindowTests(unittest.TestCase):
    def test_draft_band_scripts_expose_the_draft_window(self) -> None:
        for mod in (rar, rah):
            self.assertEqual(mod.DRAFT_VREF_WINDOW_V, (1.188, 1.212), mod.__name__)
            self.assertFalse(hasattr(mod, "VREF_SPEC_V"), mod.__name__)

    def test_draft_window_lines_do_not_cite_output_voltage_tc(self) -> None:
        # The pre-#545 comment at run_res_array_head_resistance.py:182 cited
        # sim/output-voltage-tc/experiment.json, a file stating 1.176/1.224 --
        # the opposite band. The declaration must name the historical draft
        # band instead.
        for path in DRAFT_BAND_SCRIPTS:
            decl = next(
                ln for ln in path.read_text().splitlines() if ln.startswith("DRAFT_VREF_WINDOW_V")
            )
            self.assertNotIn("output-voltage-tc", decl, str(path))
            self.assertIn("draft", decl.lower(), str(path))


class NoHandRolledCopiesTests(unittest.TestCase):
    """The recurrence guard: the ratified band lives in exactly one place."""

    HOME = SIM_DIR / "bin" / "sim_common.py"

    def test_no_local_copies_of_the_ratified_band(self) -> None:
        offenders: dict[str, list[str]] = {}
        for path in sorted(SIM_DIR.rglob("*.py")):
            if path == self.HOME or path.parent == SIM_DIR / "tests":
                continue
            hits = scan_for_hand_rolled_copies(path.read_text())
            if hits:
                offenders[str(path.relative_to(SIM_DIR))] = hits
        self.assertEqual(
            offenders,
            {},
            "these harnesses hand-roll the ratified VREF window (or use a retired "
            "identifier) instead of importing sim_common.RATIFIED_VREF_WINDOW_V -- "
            "that is the copy-paste that drifted into four duplicates and a false "
            "provenance citation before issue #545",
        )

    def test_guard_catches_a_reintroduced_copy(self) -> None:
        self.assertEqual(scan_for_hand_rolled_copies("SPEC_WINDOW_V = (1.176, 1.224)\n"),
                         ["SPEC_WINDOW_V", LITERAL_HIT])
        self.assertEqual(scan_for_hand_rolled_copies('WINDOW = {"min": 1.176, "max": 1.224}\n'),
                         [LITERAL_HIT])
        self.assertEqual(scan_for_hand_rolled_copies("VREF_SPEC_V = (1.188, 1.212)\n"),
                         ["VREF_SPEC_V"])

    def test_guard_catches_reformatted_copies(self) -> None:
        # Review of #635: the old regexes missed every one of these.
        for src in (
            'LIMITS = {\n    "min": 1.176,\n    "max": 1.224,\n}\n',
            "LIMITS = (1.176, 1.224,)\n",
            "LIMITS = {'min': 1.176, 'max': 1.224}\n",
            "LIMITS = [1.224,\n          1.176]\n",
        ):
            self.assertEqual(scan_for_hand_rolled_copies(src), [LITERAL_HIT], src)

    def test_guard_ignores_comments_and_unrelated_tuples(self) -> None:
        self.assertEqual(scan_for_hand_rolled_copies("# was SPEC_WINDOW_V (1.176, 1.224)\nx = 1\n"), [])
        self.assertEqual(scan_for_hand_rolled_copies("x = (1.176, 1.2)\n"), [])

    def test_guard_allows_the_draft_band_in_its_two_owning_scripts(self) -> None:
        for path in DRAFT_BAND_SCRIPTS:
            self.assertEqual(scan_for_hand_rolled_copies(path.read_text()), [], str(path))


if __name__ == "__main__":
    unittest.main()
