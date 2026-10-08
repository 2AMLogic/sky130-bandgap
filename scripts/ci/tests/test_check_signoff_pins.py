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


FRESH_PATH = Path(__file__).resolve().parents[1] / "check_signoff_freshness.py"
_fspec = importlib.util.spec_from_file_location("check_signoff_freshness", FRESH_PATH)
assert _fspec and _fspec.loader
check_signoff_freshness = importlib.util.module_from_spec(_fspec)
_fspec.loader.exec_module(check_signoff_freshness)


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


class GraderIdentityTestCase(unittest.TestCase):
    """The single-source pin and released-wheel assertion (issue #338)."""

    def fake_klt(self, payload: dict) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "klt"
        path.write_text(
            "#!/bin/sh\ncat <<'EOF'\n" + json.dumps(payload) + "\nEOF\n"
        )
        path.chmod(0o755)
        return str(path)

    def run_main(self, args: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with redirect_stdout(out), redirect_stderr(err):
            try:
                check_signoff_freshness.main(args)
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
        return code, out.getvalue(), err.getvalue()

    def release_payload(self) -> dict:
        v = check_signoff_freshness.KLT_VERSION
        return {"package_version": v, "git_tag": f"v{v}", "is_release": True}

    def test_print_version_emits_the_pin(self) -> None:
        code, out, _ = self.run_main(["--print-version"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), check_signoff_freshness.KLT_VERSION)

    def test_assert_grader_passes_for_the_released_wheel(self) -> None:
        klt = self.fake_klt(self.release_payload())
        code, _, err = self.run_main(["--assert-grader", klt])
        self.assertEqual((code, err), (0, ""))

    def test_assert_grader_fails_for_a_wrong_version(self) -> None:
        payload = self.release_payload() | {"package_version": "0.0.1"}
        code, _, err = self.run_main(["--assert-grader", self.fake_klt(payload)])
        self.assertEqual(code, 1)
        self.assertIn("FATAL", err)

    def test_assert_grader_fails_for_a_non_release_build(self) -> None:
        payload = self.release_payload() | {"is_release": False}
        code, _, err = self.run_main(["--assert-grader", self.fake_klt(payload)])
        self.assertEqual(code, 1)
        self.assertIn("is_release=False", err)

    def test_assert_grader_fails_for_a_wrong_git_tag(self) -> None:
        payload = self.release_payload() | {"git_tag": "v0.0.0-3-gabc"}
        code, _, _ = self.run_main(["--assert-grader", self.fake_klt(payload)])
        self.assertEqual(code, 1)

    def test_assert_grader_fails_for_a_missing_executable(self) -> None:
        code, _, err = self.run_main(["--assert-grader", "/nonexistent/klt"])
        self.assertEqual(code, 1)
        self.assertIn("FATAL", err)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
