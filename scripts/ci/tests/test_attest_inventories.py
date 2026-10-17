#!/usr/bin/env python3
"""Negative controls for the T1 item 1/2/9/10 attestations (issue #387).

The committed tree always passes these checks, so the proof that editing an
inventoried file makes CI fail has to live here: each test copies the files the
attestations read into a temp tree, mutates one, and requires the check to
fail naming the right thing. Also covers the design-netlist freshness lock.

Run directly (`python3 scripts/ci/tests/test_attest_inventories.py`) or via
`npm run test:unit`.
"""

from __future__ import annotations

import importlib.util
import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

CI_DIR = Path(__file__).resolve().parents[1]
REAL_ROOT = CI_DIR.parents[1]


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, CI_DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


attest = load("attest_inventories")
netlists = load("design_netlists")
pins = load("check_signoff_pins")


PDK_COMMIT = "c6d73a35f524070e85faff4a6a9eef49553ebc2b"


def copy_inputs(dest: Path) -> None:
    """Copy exactly what the attestation scripts read (no sim records, no layout)."""
    shutil.copytree(REAL_ROOT / "design", dest / "design")
    shutil.copytree(REAL_ROOT / "signoff", dest / "signoff")
    shutil.copytree(
        REAL_ROOT / "sim", dest / "sim",
        ignore=shutil.ignore_patterns("records", "netlist-snapshots", "corners", "parasitics-snapshot"),
    )
    (dest / "scripts" / "ci").mkdir(parents=True)
    for name in ("check_signoff_freshness.py", "design_netlists.py"):
        shutil.copy(CI_DIR / name, dest / "scripts" / "ci" / name)
    (dest / ".github" / "workflows").mkdir(parents=True)
    shutil.copy(REAL_ROOT / ".github/workflows/ci.yml", dest / ".github/workflows/ci.yml")
    for name in ("README.md", "LICENSE", "package.json"):
        shutil.copy(REAL_ROOT / name, dest / name)
    gds = dest / attest.ROUTED_GDS
    gds.parent.mkdir(parents=True)
    shutil.copy(REAL_ROOT / attest.ROUTED_GDS, gds)


class AttestTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        copy_inputs(self.root)
        saved = (attest.REPO_ROOT, attest.ATTEST, attest.MANIFEST, attest.PINNED_INPUTS)
        attest.REPO_ROOT = self.root
        attest.ATTEST = self.root / "signoff" / "attest"
        attest.MANIFEST = self.root / "signoff" / "block-manifest.json"
        attest.PINNED_INPUTS = self.root / "signoff" / "pinned-inputs.json"
        saved_nl = (netlists.REPO_ROOT, netlists.DESIGN, netlists.NETLIST_DIR, netlists.LOCK)
        netlists.REPO_ROOT = self.root
        netlists.DESIGN = self.root / "design"
        netlists.NETLIST_DIR = self.root / "design" / "netlist"
        netlists.LOCK = netlists.NETLIST_DIR / "netlist.lock.json"
        saved_pins = (pins.REPO_ROOT, pins.MANIFEST, pins.PINNED_INPUTS)
        pins.REPO_ROOT = self.root
        pins.MANIFEST = attest.MANIFEST
        pins.PINNED_INPUTS = attest.PINNED_INPUTS

        def restore() -> None:
            attest.REPO_ROOT, attest.ATTEST, attest.MANIFEST, attest.PINNED_INPUTS = saved
            netlists.REPO_ROOT, netlists.DESIGN, netlists.NETLIST_DIR, netlists.LOCK = saved_nl
            pins.REPO_ROOT, pins.MANIFEST, pins.PINNED_INPUTS = saved_pins

        self.addCleanup(restore)

    def run_attest(self) -> tuple[int, str]:
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            import sys

            argv, sys.argv = sys.argv, ["attest_inventories.py"]
            try:
                code = attest.main()
            finally:
                sys.argv = argv
        return code, err.getvalue()

    def run_pins(self) -> tuple[int, str]:
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = pins.main()
        return code, err.getvalue()

    def run_lock(self) -> tuple[int, str]:
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = netlists.check_lock()
        return code, err.getvalue()


class CommittedStateTest(AttestTestCase):
    def test_committed_tree_passes_every_check(self) -> None:
        self.assertEqual(self.run_attest()[0], 0)
        self.assertEqual(self.run_lock()[0], 0)
        # The temp tree omits the DRC/ERC/sim artifacts of the other items, so
        # the pin check as a whole fails here; only items 1/2/9/10 must be clean.
        _, err = self.run_pins()
        for item in ("1", "2", "9", "10"):
            self.assertNotIn(f"item {item}:", err)


class NegativeControlTest(AttestTestCase):
    def test_editing_a_schematic_fails_attest_and_netlist_lock(self) -> None:
        sch = self.root / "design" / "error_amp.sch"
        sch.write_text(sch.read_text() + "\n* edited\n")
        code, err = self.run_attest()
        self.assertEqual(code, 1)
        self.assertIn("design-sources.inventory.json: stale", err)
        code, err = self.run_lock()
        self.assertEqual(code, 1)
        self.assertIn("design/error_amp.sch changed", err)

    def test_regenerating_attestation_alone_does_not_hide_a_stale_netlist(self) -> None:
        sch = self.root / "design" / "error_amp.sch"
        sch.write_text(sch.read_text() + "\n* edited\n")
        attest.sys.argv = ["attest_inventories.py", "--write"]
        try:
            with redirect_stdout(io.StringIO()):
                attest.main()
        finally:
            attest.sys.argv = ["attest_inventories.py"]
        self.assertEqual(self.run_attest()[0], 0)
        self.assertEqual(self.run_lock()[0], 1)

    def test_editing_a_netlist_by_hand_fails_the_lock(self) -> None:
        net = self.root / "design" / "netlist" / "bandgap_core.spice"
        net.write_text(net.read_text() + "* hand edit\n")
        self.assertEqual(self.run_lock()[0], 1)

    def test_editing_a_testbench_fails(self) -> None:
        bench = next((self.root / "sim").glob("*/testbench/*.sch"))
        bench.write_text(bench.read_text() + "\n* edited\n")
        code, err = self.run_attest()
        self.assertEqual(code, 1)
        self.assertIn("testbench-inventory.json: stale", err)

    def test_adding_a_testbench_directory_fails(self) -> None:
        new = self.root / "sim" / "brand-new-bench"
        new.mkdir()
        (new / "experiment.json").write_text("{}\n")
        code, err = self.run_attest()
        self.assertEqual(code, 1)
        self.assertIn("testbench-inventory.json: stale", err)

    def test_editing_pdk_pin_fails(self) -> None:
        pdk = self.root / "sim" / "pdk.json"
        pdk.write_text(pdk.read_text().replace(PDK_COMMIT, "0" * 40))
        self.assertEqual(self.run_attest()[0], 1)

    def test_editing_ci_workflow_or_readme_fails(self) -> None:
        for name in (".github/workflows/ci.yml", "README.md"):
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_text()
                path.write_text(original + "\n# edited\n")
                code, err = self.run_attest()
                self.assertEqual(code, 1)
                self.assertIn("repo-hygiene.inventory.json: stale", err)
                path.write_text(original)

    def test_editing_the_routed_gds_fails_the_pin_check(self) -> None:
        gds = self.root / attest.ROUTED_GDS
        gds.write_bytes(gds.read_bytes() + b"\0")
        code, err = self.run_pins()
        self.assertEqual(code, 1)
        self.assertIn("item 2", err)

    def test_editing_an_inventory_by_hand_fails_the_pin_check(self) -> None:
        inv = self.root / "signoff" / "attest" / "repo-hygiene.inventory.json"
        inv.write_text(inv.read_text() + " ")
        code, err = self.run_pins()
        self.assertEqual(code, 1)
        self.assertIn("item 10", err)


if __name__ == "__main__":
    unittest.main()
