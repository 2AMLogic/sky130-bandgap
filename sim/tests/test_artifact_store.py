#!/usr/bin/env python3
"""Unit coverage for sim_common.publish_corner_evidence() (issue #424) with a
stubbed `klt`: manifest emission and the fail-closed paths."""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import sim_common  # noqa: E402

STUB = """#!/usr/bin/env python3
import json, hashlib, sys
a = sys.argv[1:]
if a[:3] != ["artifact", "put", "--help"] and a[:2] != ["artifact", "put"]:
    sys.exit(2)
if "--help" in a:
    sys.exit(%(help_rc)d)
if %(put_rc)d:
    sys.stderr.write("broker_unreachable")
    sys.exit(%(put_rc)d)
manifest = a[a.index("--manifest") + 1]
files = a[a.index("--format") + 2:]
entries = [{"sha256": hashlib.sha256(open(f, "rb").read()).hexdigest(),
            "size": len(open(f, "rb").read()), "kind": "evidence",
            "producer": {"tool": "klt", "version": "1", "loom.repo": "o/n", "commit": None},
            "uri": "artifact:evidence/o__n/xx/" + hashlib.sha256(open(f, "rb").read()).hexdigest(),
            "name": f.split("/")[-1]} for f in files]
json.dump({"schema_version": 1, "entries": entries}, open(manifest, "w"))
"""


class PublishCornerEvidence(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "repo"
        self.corners = self.repo / "sim" / "benchx" / "corners" / "run1"
        self.corners.mkdir(parents=True)
        (self.corners / "tt.log").write_text("raw bytes\n")
        self.bin = self.tmp / "bin"
        self.bin.mkdir()

    def stub(self, help_rc=0, put_rc=0):
        p = self.bin / "klt"
        p.write_text(STUB % {"help_rc": help_rc, "put_rc": put_rc})
        p.chmod(p.stat().st_mode | stat.S_IXUSR)

    def env(self, broker="http://broker.invalid"):
        e = {"PATH": f"{self.bin}:/usr/bin:/bin"}
        if broker:
            e["KLT_ARTIFACT_BROKER"] = broker
        return mock.patch.dict(os.environ, e, clear=True)

    def publish(self):
        return sim_common.publish_corner_evidence(self.corners, self.repo)

    def assert_nothing_written(self):
        self.assertFalse((self.repo / "manifests").exists())

    def test_writes_manifest_and_summary(self):
        self.stub()
        with self.env():
            manifest = self.publish()
        self.assertEqual(manifest, self.repo / "manifests/artifacts/benchx-run1.manifest.json")
        entries = json.loads(manifest.read_text())["entries"]
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0]["uri"].startswith("artifact:"))
        summary = manifest.with_suffix("").with_suffix(".md").read_text()
        self.assertIn(entries[0]["sha256"], summary)

    def test_explicit_bench_and_run_id_name_the_manifest(self):
        self.stub()
        with self.env():
            manifest = sim_common.publish_corner_evidence(
                self.corners, self.repo, bench="layout-x", run_id="rec9"
            )
        self.assertEqual(manifest, self.repo / "manifests/artifacts/layout-x-rec9.manifest.json")

    def test_broker_unset_fails_closed(self):
        self.stub()
        with self.env(broker=None), self.assertRaisesRegex(
            sim_common.EvidenceStoreError, "KLT_ARTIFACT_BROKER"
        ):
            self.publish()
        self.assert_nothing_written()

    def test_klt_without_artifact_put_fails_closed(self):
        self.stub(help_rc=2)
        with self.env(), self.assertRaisesRegex(sim_common.EvidenceStoreError, "artifact put"):
            self.publish()
        self.assert_nothing_written()

    def test_klt_missing_fails_closed(self):
        with self.env(), self.assertRaisesRegex(sim_common.EvidenceStoreError, "klt"):
            self.publish()
        self.assert_nothing_written()

    def test_broker_unreachable_fails_closed(self):
        self.stub(put_rc=1)
        with self.env(), self.assertRaisesRegex(sim_common.EvidenceStoreError, "put failed"):
            self.publish()
        self.assert_nothing_written()
        self.assertTrue((self.corners / "tt.log").exists())

    def test_empty_run_writes_nothing(self):
        self.stub()
        (self.corners / "tt.log").unlink()
        with self.env():
            self.assertIsNone(self.publish())
        self.assert_nothing_written()

    def test_existing_manifest_is_not_overwritten(self):
        self.stub()
        with self.env():
            self.publish()
            with self.assertRaisesRegex(sim_common.EvidenceStoreError, "append-only"):
                self.publish()


if __name__ == "__main__":
    unittest.main()
