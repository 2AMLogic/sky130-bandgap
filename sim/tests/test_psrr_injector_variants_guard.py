#!/usr/bin/env python3
"""The `--variants` empty-selection guard in both psrr-injector benches (issue #583).

`--variants`' `type=` lambda filters empty fields, so `--variants ""` or
`--variants ","` parsed to an empty list that slipped past the unknown-name
check and blew up later as an unhandled `groups[0]` IndexError on the
dry-run/explore paths. `parse_args` now refuses the empty selection beside
that check; these tests pin the refusal (argparse error, exit code 2) and the
unchanged behaviour of valid and default selections.
"""

from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM_DIR / "tests"))

import test_psrr_injector_shared  # noqa: E402

load_runner = test_psrr_injector_shared.load_runner


class VariantsGuardTests(unittest.TestCase):
    """Both benches refuse an empty --variants selection at parse time."""

    def test_empty_selection_refused_with_argparse_error(self):
        for name in ("attribution", "candidates"):
            mod = load_runner(name)
            for selection in ("", ","):
                with self.subTest(bench=name, selection=repr(selection)):
                    with contextlib.redirect_stderr(io.StringIO()), \
                         self.assertRaises(SystemExit) as ctx:
                        mod.parse_args(["--variants", selection])
                    self.assertEqual(ctx.exception.code, 2)

    def test_whitespace_only_selection_refused(self):
        for name in ("attribution", "candidates"):
            mod = load_runner(name)
            with self.subTest(bench=name), \
                 contextlib.redirect_stderr(io.StringIO()), \
                 self.assertRaises(SystemExit) as ctx:
                mod.parse_args(["--variants", " , "])
            self.assertEqual(ctx.exception.code, 2)

    def test_valid_single_variant_unchanged(self):
        for name in ("attribution", "candidates"):
            mod = load_runner(name)
            with self.subTest(bench=name):
                args = mod.parse_args(["--variants", "base"])
                self.assertEqual(args.variants, ["base"])

    def test_default_selection_is_all_variants(self):
        for name in ("attribution", "candidates"):
            mod = load_runner(name)
            with self.subTest(bench=name):
                args = mod.parse_args([])
                self.assertEqual(sorted(args.variants),
                                 sorted(v.name for v in mod.VARIANTS))


if __name__ == "__main__":
    unittest.main()
