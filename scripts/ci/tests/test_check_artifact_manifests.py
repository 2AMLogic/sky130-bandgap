#!/usr/bin/env python3
"""Unit coverage for scripts/ci/check_artifact_manifests.py (issue #424):
the passing case plus one failing fixture per rule."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

CHECK = Path(__file__).resolve().parents[1] / "check_artifact_manifests.py"
_spec = importlib.util.spec_from_file_location("check_artifact_manifests", CHECK)
assert _spec and _spec.loader
cam = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cam)

GOOD_SHA = hashlib.sha256(b"stored elsewhere").hexdigest()


def entry(**over):
    e = {
        "sha256": GOOD_SHA, "size": 16, "kind": "evidence",
        "producer": {"tool": "klt", "version": "1", "loom.repo": "o/n", "commit": None},
        "uri": "artifact:evidence/o__n/ab/" + GOOD_SHA, "name": "sim/x/corners/r/a.log",
    }
    e.update(over)
    return e


class CheckArtifactManifests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "manifests/artifacts").mkdir(parents=True)

    def run_check(self, doc, tracked: dict[str, bytes] | None = None):
        (self.root / "manifests/artifacts/b-r.manifest.json").write_text(
            doc if isinstance(doc, str) else json.dumps(doc)
        )
        for name, data in (tracked or {}).items():
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_bytes(data)
        subprocess.run(["git", "-C", str(self.root), "add", "-f", "."], check=True)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cam.main(["--root", str(self.root)])
        return rc, err.getvalue()

    def test_valid_manifest_passes(self):
        rc, err = self.run_check({"schema_version": 1, "entries": [entry()]})
        self.assertEqual((rc, err), (0, ""))

    def test_no_manifests_passes(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cam.main(["--root", str(self.root)]), 0)

    def test_bad_schema_version(self):
        rc, err = self.run_check({"schema_version": 2, "entries": []})
        self.assertEqual(rc, 1)
        self.assertIn("schema", err)

    def test_unknown_field_and_missing_field(self):
        e = entry(extra=1)
        del e["kind"]
        rc, err = self.run_check({"schema_version": 1, "entries": [e]})
        self.assertEqual(rc, 1)
        self.assertIn("missing ['kind']", err)
        self.assertIn("unknown ['extra']", err)

    def test_bad_sha_and_size(self):
        rc, err = self.run_check(
            {"schema_version": 1, "entries": [entry(sha256="xyz", size=-1)]}
        )
        self.assertEqual(rc, 1)
        self.assertIn("sha256 is not", err)
        self.assertIn("size is not", err)

    def test_non_artifact_uri(self):
        rc, err = self.run_check(
            {"schema_version": 1, "entries": [entry(uri="https://example.com/x")]}
        )
        self.assertEqual(rc, 1)
        self.assertIn("does not start with 'artifact:'", err)

    def test_storage_location_rejected(self):
        rc, err = self.run_check(
            {"schema_version": 1, "entries": [entry(name="s3://bucket/key")]}
        )
        self.assertEqual(rc, 1)
        self.assertIn("storage location", err)
        rc, err = self.run_check(
            {"schema_version": 1, "entries": [entry(name="arn:aws:s3:::b")]}
        )
        self.assertIn("storage location", err)

    def test_bytes_also_committed(self):
        data = b"committed too"
        rc, err = self.run_check(
            {"schema_version": 1, "entries": [entry(sha256=hashlib.sha256(data).hexdigest())]},
            tracked={"sim/x/a.log": data},
        )
        self.assertEqual(rc, 1)
        self.assertIn("also committed as sim/x/a.log", err)

    def test_unreadable_manifest(self):
        rc, err = self.run_check("{not json")
        self.assertEqual(rc, 1)
        self.assertIn("unreadable", err)


if __name__ == "__main__":
    unittest.main()
