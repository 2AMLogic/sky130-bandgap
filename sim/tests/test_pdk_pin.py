#!/usr/bin/env python3
"""The PDK pin guard (issue #369): the installed open_pdks revision is read
from the resolved tree's `SOURCES` file, never from its path, and compared
with `sim/pdk.json`. No real PDK, ngspice or network needed -- fake trees.

  * a tree whose SOURCES says the old revision is refused, even when it is
    reached through a ciel-looking path;
  * a tree at the pin passes;
  * missing / unparseable SOURCES is "unknown" and never matches the pin;
  * resolution is $PDK_ROOT -> default_pdk_root (~/.ciel); `volare path` is
    never consulted.
"""

from __future__ import annotations

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
OLD = "c6d73a35f524070e85faff4a6a9eef49553ebc2b"
NEW = "f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7"


def fake_pdk(root: Path, sources: str | None) -> Path:
    d = root / PIN["variant"]
    lib = d / PIN["ngspice_lib"]
    lib.parent.mkdir(parents=True)
    lib.write_text("* fake\n")
    if sources is not None:
        (d / "SOURCES").write_text(sources)
    return d


class PdkPinTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def resolve(self, **env):
        with mock.patch.dict(os.environ, {"PDK_ROOT": str(self.root), **env}):
            return cr.resolve_pdk(PIN)

    def test_pin_is_new_revision(self):
        self.assertEqual(PIN["open_pdks_commit"], NEW)
        self.assertEqual(PIN["default_pdk_root"], "~/.ciel")
        self.assertIn("ciel", PIN["install_command"])

    def test_old_revision_refused(self):
        fake_pdk(self.root, f"open_pdks {OLD}\nmagic abc\n")
        pdk = self.resolve()
        self.assertEqual(pdk.installed_commit, OLD)
        self.assertFalse(pdk.matches_pin)
        with mock.patch.dict(os.environ, {"PDK_ROOT": str(self.root)}):
            with self.assertRaises(cr.HarnessError):
                sim_common.check_pdk_and_ngspice(PIN, False, require_ngspice=False)
            # --allow-pdk-mismatch still resolves (the record carries the mismatch)
            self.assertFalse(
                sim_common.check_pdk_and_ngspice(PIN, True, require_ngspice=False).matches_pin
            )

    def test_pinned_revision_passes(self):
        fake_pdk(self.root, f"magic abc\nopen_pdks {NEW}\n")
        pdk = self.resolve()
        self.assertEqual(pdk.installed_commit, NEW)
        self.assertTrue(pdk.matches_pin)

    def test_missing_sources_is_unknown(self):
        fake_pdk(self.root, None)
        pdk = self.resolve()
        self.assertEqual(pdk.installed_commit, "unknown")
        self.assertFalse(pdk.matches_pin)

    def test_garbage_sources_is_unknown(self):
        fake_pdk(self.root, "nothing useful\nopen_pdks\n")
        self.assertEqual(self.resolve().installed_commit, "unknown")

    def test_path_is_not_trusted(self):
        # A path containing the pin must not make an old tree look pinned.
        nested = self.root / "versions" / NEW
        nested.mkdir(parents=True)
        fake_pdk(nested, f"open_pdks {OLD}\n")
        with mock.patch.dict(os.environ, {"PDK_ROOT": str(nested)}):
            self.assertEqual(cr.resolve_pdk(PIN).installed_commit, OLD)

    def test_default_root_is_ciel_and_no_volare_call(self):
        env = {k: v for k, v in os.environ.items() if k != "PDK_ROOT"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("subprocess.run") as run:
            with self.assertRaises(cr.HarnessError) as ctx:
                cr.resolve_pdk({**PIN, "default_pdk_root": str(self.root / "ciel-home")})
        run.assert_not_called()
        self.assertIn("ciel-home", str(ctx.exception))
        self.assertFalse(hasattr(cr, "volare_path"))


if __name__ == "__main__":
    unittest.main()
