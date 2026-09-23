#!/usr/bin/env python3
"""Unit coverage for scripts/ci/check_signoff_pins.py (issue #292).

The check's whole job is to *fail* in cases the committed repo state never
exhibits — so the negative controls that prove it works cannot live in the
repo's own files. They live here, against a synthetic manifest/envelope/
artifact tree in a temp directory, so the failure paths stay exercised on
every `npm run check:ci` instead of only in the PR that introduced them.

Run directly (`python3 scripts/ci/tests/test_check_signoff_pins.py`) or via
`npm run test:unit`.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

CHECK_PATH = Path(__file__).resolve().parents[1] / "check_signoff_pins.py"
_spec = importlib.util.spec_from_file_location("check_signoff_pins", CHECK_PATH)
assert _spec and _spec.loader
check_signoff_pins = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_signoff_pins)


def sha256_of(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode()).hexdigest()}"


class PinCheckTestCase(unittest.TestCase):
    """Builds a synthetic repo tree and runs the check against it."""

    ARTIFACT = "layout/reports/r1/block.gds"
    ENVELOPE = "layout/reports/r1/drc.json"
    ARTIFACT_BODY = "pretend this is a GDS stream\n"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / "signoff").mkdir()
        (self.root / "layout" / "reports" / "r1").mkdir(parents=True)
        self.write(self.ARTIFACT, self.ARTIFACT_BODY)
        self.pin = sha256_of(self.ARTIFACT_BODY)
        self.write_json(
            self.ENVELOPE,
            {"kind": "drc", "provenance": {"input": {"content_hash": self.pin}}},
        )

    def write(self, rel: str, body: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)

    def write_json(self, rel: str, payload: object) -> None:
        self.write(rel, json.dumps(payload, indent=2) + "\n")

    def write_manifest(self, evidence: dict) -> None:
        self.write_json(
            "signoff/block-manifest.json",
            {"block": "synthetic", "kind": "analog", "evidence": evidence},
        )

    def write_pinned_inputs(self, pins: list[dict]) -> None:
        self.write_json("signoff/pinned-inputs.json", {"schema_version": 1, "pins": pins})

    def run_check(self) -> tuple[int, str]:
        """Run main() against the synthetic tree; return (exit code, output)."""
        module = check_signoff_pins
        saved = (module.REPO_ROOT, module.MANIFEST, module.PINNED_INPUTS)
        module.REPO_ROOT = self.root
        module.MANIFEST = self.root / "signoff" / "block-manifest.json"
        module.PINNED_INPUTS = self.root / "signoff" / "pinned-inputs.json"
        out, err = io.StringIO(), io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = module.main()
        finally:
            module.REPO_ROOT, module.MANIFEST, module.PINNED_INPUTS = saved
        return code, out.getvalue() + err.getvalue()

    # -- the state the repo is actually in -------------------------------

    def test_passes_when_every_pin_matches(self) -> None:
        self.write_manifest({"3": {"file": self.ENVELOPE, "content_hash": self.pin}})
        self.write_pinned_inputs([{"item": "3", "describes": self.ARTIFACT}])
        code, output = self.run_check()
        self.assertEqual(code, 0, output)
        self.assertIn("1/1 pinned citations", output)

    def test_unpinned_citation_is_skipped_not_ignored(self) -> None:
        """Item 11's lvs entry carries no content_hash; it must be reported."""
        self.write_manifest(
            {
                "11": [
                    {"file": self.ENVELOPE, "content_hash": self.pin},
                    {"file": self.ENVELOPE},
                ]
            }
        )
        self.write_pinned_inputs(
            [{"item": "11", "index": 0, "describes": self.ARTIFACT}]
        )
        code, output = self.run_check()
        self.assertEqual(code, 0, output)
        self.assertIn("item 11[1]", output)

    # -- the failures this check exists for ------------------------------

    def test_fails_when_the_described_artifact_changed(self) -> None:
        """The AC1 case: the artifact a pin describes is rewritten."""
        self.write_manifest({"3": {"file": self.ENVELOPE, "content_hash": self.pin}})
        self.write_pinned_inputs([{"item": "3", "describes": self.ARTIFACT}])
        self.write(self.ARTIFACT, self.ARTIFACT_BODY + "one more polygon\n")
        code, output = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("no longer matches the pin", output)

    def test_fails_when_a_pin_is_undeclared(self) -> None:
        """A new pinned citation must say what its hash describes."""
        self.write_manifest({"3": {"file": self.ENVELOPE, "content_hash": self.pin}})
        self.write_pinned_inputs([])
        code, output = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("undeclared", output)

    def test_fails_on_a_stale_declaration(self) -> None:
        """A declaration outliving its citation must not rot silently."""
        self.write_manifest({})
        self.write_pinned_inputs([{"item": "3", "describes": self.ARTIFACT}])
        code, output = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("no such pinned citation", output)

    def test_fails_when_envelope_and_manifest_disagree(self) -> None:
        """The three-way agreement: envelope's recorded hash must match too."""
        self.write_manifest({"3": {"file": self.ENVELOPE, "content_hash": self.pin}})
        self.write_pinned_inputs([{"item": "3", "describes": self.ARTIFACT}])
        self.write_json(
            self.ENVELOPE,
            {"kind": "drc", "provenance": {"input": {"content_hash": sha256_of("other")}}},
        )
        code, output = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("records a different input hash", output)

    def test_fails_when_the_described_artifact_is_missing(self) -> None:
        self.write_manifest({"3": {"file": self.ENVELOPE, "content_hash": self.pin}})
        self.write_pinned_inputs([{"item": "3", "describes": "layout/reports/r1/gone.gds"}])
        code, output = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("is missing", output)

    def test_fails_when_the_cited_envelope_is_missing(self) -> None:
        self.write_manifest(
            {"3": {"file": "layout/reports/r1/gone.json", "content_hash": self.pin}}
        )
        self.write_pinned_inputs([{"item": "3", "describes": self.ARTIFACT}])
        code, output = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("cited evidence file is missing", output)

    def test_fails_on_an_incomplete_declaration(self) -> None:
        self.write_manifest({"3": {"file": self.ENVELOPE, "content_hash": self.pin}})
        self.write_pinned_inputs([{"item": "3"}])
        code, output = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("needs both", output)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
