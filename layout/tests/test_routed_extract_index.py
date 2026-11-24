#!/usr/bin/env python3
"""Headless evidence-index assertion for the routed record (issue #675).

Before PR #674, the label-collision gate's current-record tripwire reached
``_fetch_from_artifact_store()`` even in the no-broker CI job, and thereby
asserted -- before anything broker-specific happened -- that the record
``layout/bandgap-core/reports/LATEST`` names has a resolvable extract
netlist: a committed artifact manifest carrying an entry for it. PR #674
(correctly, per issue #671) moved that whole branch behind
``shutil.which("klt") and os.environ.get("KLT_ARTIFACT_BROKER")``, so
headless CI no longer touches the manifest at all -- and with it lost the
only assertion that a store-backed ``LATEST`` record's evidence index can
actually resolve its extract netlist. A record could be published with the
manifest omitted or its entry mis-named and every headless check would
stay green; nothing would say so until someone tried to fetch the bytes.

This module restores that invariant in its own right: the record
``LATEST`` names must either have the extract netlist committed in-tree or
an artifact manifest naming it exactly once. The lookup mirrors
``TestLabelCollisionGate._fetch_from_artifact_store`` in
``test_routed_flow_gates.py`` -- same manifest path, same complete
staging-path entry name, same exactly-one-match requirement -- and stops
before fetching any bytes, so it needs no broker, network, PDK, or `klt`
install.

Standard library only, matching every other test under ``layout/tests/``.
Run directly, or via::

    npm run test:unit
    python3 -m unittest discover --start-directory layout/tests
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestRoutedExtractIndex(unittest.TestCase):
    """The record ``reports/LATEST`` names must have a resolvable extract
    netlist: committed in-tree, or named by exactly one manifest entry."""

    def test_latest_record_resolves_its_extract_netlist(self) -> None:
        """Reads ``LATEST`` fresh on every run, so each new store-backed
        record re-asserts its own evidence index. An in-tree netlist
        satisfies the invariant outright; otherwise the manifest must
        exist and match the wanted entry exactly once -- a missing
        manifest, a renamed entry, or a duplicated one all fail here,
        naming the manifest and entry that was expected."""
        reports = REPO_ROOT / "layout/bandgap-core/reports"
        latest_id = (reports / "LATEST").read_text().strip()
        netlist = reports / latest_id / "bandgap_core_routed.extract.spice"
        if netlist.is_file():
            # In-tree record: the bytes are committed, so there is nothing
            # an artifact index needs to resolve.
            return
        manifest = (
            REPO_ROOT
            / "manifests/artifacts"
            / f"layout-bandgap-core-{latest_id}.manifest.json"
        )
        self.assertTrue(
            manifest.is_file(),
            f"record {latest_id} is store-backed (no extract netlist at "
            f"{netlist}) and no artifact manifest exists at {manifest}",
        )
        wanted = (
            f"layout/bandgap-core/staging/{latest_id}/"
            "bandgap_core_routed.extract.spice"
        )
        entries = json.loads(manifest.read_text()).get("entries", [])
        names = [e.get("name") for e in entries if e.get("name") == wanted]
        self.assertEqual(
            names,
            [wanted],
            f"expected exactly one entry named '{wanted}' in "
            f"{manifest.relative_to(REPO_ROOT)} to resolve the extract "
            f"netlist from, found {len(names)}",
        )


if __name__ == "__main__":
    unittest.main()
