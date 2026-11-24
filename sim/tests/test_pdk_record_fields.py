#!/usr/bin/env python3
"""The shared PDK record blocks (issue #676): `pdk_record_fields()` is the
one six-field `"pdk"` dict behind `run_matrix_and_write_record()` and the
three MC mismatch benches; `pdk_record_fields_compact()` is the one
four-field dict behind the four trim / res-array benches. `sim/` records
are append-only evidence, so each helper's output must stay identical to
the inline expression it replaced -- same keys, same order, same path
strings, same pin-match boolean -- on a matching, a mismatching and an
unresolvable installed revision. No real PDK needed -- fake trees.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SIM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIM_DIR / "bin"))

import sim_common  # noqa: E402

cr = sim_common.load_corner_run()
PIN = cr.load_pin()
PINNED = PIN["open_pdks_commit"]
# Any revision that is not the pin; readable out of a fake SOURCES file.
OTHER = "0123456789abcdef0123456789abcdef01234567"

# The eight writers these helpers replaced, as of d1a95f74 (issue #676):
# each named file must route its record's `"pdk"` block through the helper,
# not back through a re-inlined copy of the expression.
FULL_FIELD_WRITERS = (
    "monte-carlo-untrimmed/run_mc_untrimmed.py",
    "error-amp-offset-mc/run_amp_offset_mc.py",
    "pnp-mismatch/run_pnp_mismatch.py",
)
COMPACT_FIELD_WRITERS = (
    "res-array-resize/run_res_array_resize.py",
    "res-array-head-resistance/run_res_array_head_resistance.py",
    "trim-range-monotonicity/run_trim_sweep.py",
    "trim-lsb-chained/run_trim_lsb_chained.py",
)


def six_field_inline(pdk, pin):
    # The six-field expression as it was inlined at the four full-provenance
    # writers (sim_common's matrix runner had it byte-for-byte too) -- the
    # differential oracle the helper must reproduce exactly.
    return {
        "root": str(pdk.root),
        "variant": pdk.variant,
        "installed_commit": pdk.installed_commit,
        "pinned_commit": pin["open_pdks_commit"],
        "matches_pin": pdk.matches_pin,
        "lib_file": str(pdk.lib_file),
    }


def four_field_inline(pdk):
    # The compact expression as it was inlined at the four trim / res-array
    # writers, same contract.
    return {
        "variant": pdk.variant,
        "installed_commit": pdk.installed_commit,
        "matches_pin": pdk.matches_pin,
        "lib_file": str(pdk.lib_file),
    }


def fake_pdk(root: Path, sources: str | None) -> Path:
    d = root / PIN["variant"]
    lib = d / PIN["ngspice_lib"]
    lib.parent.mkdir(parents=True)
    lib.write_text("* fake\n")
    if sources is not None:
        (d / "SOURCES").write_text(sources)
    return d


class PdkRecordFieldsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def resolve(self, sources: str | None):
        fake_pdk(self.root, sources)
        with mock.patch.dict(os.environ, {"PDK_ROOT": str(self.root)}):
            return cr.resolve_pdk(PIN)

    def check_both_helpers(self, pdk):
        full = sim_common.pdk_record_fields(pdk, PIN)
        compact = sim_common.pdk_record_fields_compact(pdk)
        # Serialized equality covers values, key set AND key order (json
        # keeps insertion order); dict equality alone would not.
        self.assertEqual(json.dumps(full), json.dumps(six_field_inline(pdk, PIN)))
        self.assertEqual(json.dumps(compact), json.dumps(four_field_inline(pdk)))
        self.assertEqual(full, six_field_inline(pdk, PIN))
        self.assertEqual(compact, four_field_inline(pdk))
        return full, compact

    def test_matching_revision(self):
        pdk = self.resolve(f"open_pdks {PINNED}\n")
        self.assertTrue(pdk.matches_pin)
        full, compact = self.check_both_helpers(pdk)
        self.assertIs(full["matches_pin"], True)
        self.assertIs(compact["matches_pin"], True)
        self.assertEqual(full["pinned_commit"], PINNED)
        self.assertEqual(full["installed_commit"], PINNED)

    def test_mismatching_revision(self):
        pdk = self.resolve(f"open_pdks {OTHER}\n")
        self.assertFalse(pdk.matches_pin)
        full, compact = self.check_both_helpers(pdk)
        self.assertIs(full["matches_pin"], False)
        self.assertIs(compact["matches_pin"], False)
        # The record still publishes both revisions: what is installed, and
        # what sim/pdk.json pins -- it never rewrites the pin to match.
        self.assertEqual(full["installed_commit"], OTHER)
        self.assertEqual(full["pinned_commit"], PINNED)

    def test_unknown_revision(self):
        pdk = self.resolve(None)
        self.assertEqual(pdk.installed_commit, "unknown")
        full, compact = self.check_both_helpers(pdk)
        self.assertIs(full["matches_pin"], False)
        self.assertIs(compact["matches_pin"], False)

    def test_path_strings_not_path_objects(self):
        pdk = self.resolve(f"open_pdks {PINNED}\n")
        full, compact = self.check_both_helpers(pdk)
        # Path values cross into JSON/Markdown as plain strings of the
        # resolved tree, exactly as the inline str() calls produced.
        self.assertIsInstance(full["root"], str)
        self.assertIsInstance(full["lib_file"], str)
        self.assertIsInstance(compact["lib_file"], str)
        self.assertEqual(full["root"], str(pdk.root))
        self.assertEqual(full["lib_file"], str(pdk.lib_file))
        self.assertEqual(compact["lib_file"], str(pdk.lib_file))

    def test_key_order(self):
        pdk = self.resolve(f"open_pdks {PINNED}\n")
        full, compact = self.check_both_helpers(pdk)
        self.assertEqual(
            list(full),
            ["root", "variant", "installed_commit", "pinned_commit",
             "matches_pin", "lib_file"],
        )
        self.assertEqual(
            list(compact),
            ["variant", "installed_commit", "matches_pin", "lib_file"],
        )
        # The rendered record header reads these four keys off the block;
        # the compact order keeps them in the sequence the benches published.
        for key in ("variant", "installed_commit", "matches_pin", "lib_file"):
            self.assertIn(key, compact)
            self.assertIn(key, full)

    def test_published_evidence_key_sets_unchanged(self):
        # The two record formats as they exist in committed, append-only
        # evidence (the two records the issue cites). The written JSON is
        # sort_keys=True, so published files pin the key set, not the dict
        # order -- the order oracle is the inline expression above.
        mc = json.loads(
            (SIM_DIR / "monte-carlo-untrimmed/records/20261105-061037-ef9df345.json").read_text()
        )
        self.assertEqual(
            set(mc["pdk"]),
            {"root", "variant", "installed_commit", "pinned_commit",
             "matches_pin", "lib_file"},
        )
        trim = json.loads(
            (SIM_DIR / "trim-lsb-chained/records/20261112-224417-24a14a1.json").read_text()
        )
        self.assertEqual(
            set(trim["pdk"]),
            {"variant", "installed_commit", "matches_pin", "lib_file"},
        )


class WritersUseTheHelpersTest(unittest.TestCase):
    """The dedup itself: every named writer routes its `"pdk"` block through
    the shared helper instead of a re-inlined copy of the expression."""

    def test_full_field_writers_call_pdk_record_fields(self):
        for rel in FULL_FIELD_WRITERS:
            with self.subTest(rel=rel):
                text = (SIM_DIR / rel).read_text()
                self.assertIn('"pdk": pdk_record_fields(pdk, pin),', text)
                self.assertNotIn('"pinned_commit": pin["open_pdks_commit"]', text)

    def test_compact_field_writers_call_pdk_record_fields_compact(self):
        for rel in COMPACT_FIELD_WRITERS:
            with self.subTest(rel=rel):
                text = (SIM_DIR / rel).read_text()
                self.assertIn('"pdk": pdk_record_fields_compact(pdk),', text)
                self.assertNotIn('"matches_pin": pdk.matches_pin', text)


if __name__ == "__main__":
    unittest.main()
