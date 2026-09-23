#!/usr/bin/env python3
"""Unit coverage for `sim/monte-carlo-untrimmed/emit_klt_yield.py` (issue #288).

Two things this file guards, both of which were real defects rather than
hypothetical ones:

1. **The `klt yield` invocation must name the sample set relative to the repo
   root, from the repo root.** `klt yield` copies the path it was invoked with
   verbatim into its report's own `samples` field, so an absolute invocation
   path becomes an absolute, machine-local path baked into permanent,
   append-only evidence -- unresolvable (and so uncitable from
   `signoff/block-manifest.json`) anywhere else. That is exactly what happened
   to `records/20260817-121131-d7d85b6-klt-yield.json`, which is why T1 item 6
   sat `unmet` with real evidence on disk. A one-line path fix with no test is
   a one-line path regression waiting to happen, so the invocation is asserted
   here directly.

2. **A re-mint must never overwrite committed evidence.** `records/*` is
   append-only (`sim/README.md`): a correction mints a new record naming the
   prior one via **Supersedes**, it does not edit one. `--envelope-id` is the
   mode that does that, and it must refuse rather than clobber.

Plus a standing check on the committed evidence itself: every `*-klt-yield.json`
in the records tree must name a repo-relative `samples` document that actually
exists -- except the one pre-fix envelope, which is named explicitly here so
that a *new* leak cannot hide behind the grandfathered one.
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_DIR = REPO_ROOT / "sim" / "monte-carlo-untrimmed"
RECORDS_DIR = HARNESS_DIR / "records"

sys.path.insert(0, str(HARNESS_DIR))
import emit_klt_yield  # noqa: E402

#: The one envelope minted before issue #288's fix. Its `samples` field
#: records an absolute path from the machine that produced it. It is
#: deliberately NOT repaired -- evidence records are append-only -- so it is
#: named here as a closed set of one rather than letting the check below be
#: weakened to "some envelopes may leak".
GRANDFATHERED_ABSOLUTE_SAMPLES = {"20260817-121131-d7d85b6-klt-yield.json"}


class RunKltYieldInvocation(unittest.TestCase):
    """`run_klt_yield` must invoke `klt yield` repo-relatively, from the root."""

    def _capture(self, sample_set_path: Path) -> tuple[list[str], Path]:
        captured: dict[str, object] = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            captured["cwd"] = kwargs.get("cwd")
            return subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")

        real_run = emit_klt_yield.subprocess.run
        emit_klt_yield.subprocess.run = fake_run
        try:
            emit_klt_yield.run_klt_yield(sample_set_path)
        finally:
            emit_klt_yield.subprocess.run = real_run
        return list(captured["argv"]), Path(str(captured["cwd"]))

    def test_sample_set_path_is_repo_relative(self):
        target = RECORDS_DIR / "20260817-121131-d7d85b6-klt-yield-input.json"
        argv, _cwd = self._capture(target)
        self.assertEqual(argv[:2], ["klt", "yield"])
        path_arg = argv[2]
        self.assertFalse(
            Path(path_arg).is_absolute(),
            f"klt yield was invoked with an absolute path ({path_arg}); it echoes "
            "that path into the evidence record's own `samples` field",
        )
        self.assertEqual(
            path_arg,
            "sim/monte-carlo-untrimmed/records/"
            "20260817-121131-d7d85b6-klt-yield-input.json",
        )

    def test_invoked_from_repo_root(self):
        """The relative path above is only meaningful with a matching cwd."""
        target = RECORDS_DIR / "20260817-121131-d7d85b6-klt-yield-input.json"
        argv, cwd = self._capture(target)
        self.assertEqual(cwd.resolve(), REPO_ROOT)
        self.assertTrue(
            (cwd / argv[2]).is_file(),
            "the path handed to klt yield does not resolve against the cwd it "
            "was handed with -- the two must be changed together",
        )


class RemintIsAppendOnly(unittest.TestCase):
    """`--envelope-id` must refuse to overwrite an existing record."""

    def test_refuses_to_clobber_an_existing_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Point the module's records dir at a scratch copy so the test
            # cannot touch committed evidence even if it misbehaves.
            scratch = Path(tmp)
            (scratch / "records").mkdir()
            (scratch / "records" / "20260101-000000-abc1234.json").write_text("{}\n")
            (scratch / "records" / "20260202-000000-def5678-klt-yield.json").write_text(
                "{}\n"
            )
            real_here = emit_klt_yield.HERE
            emit_klt_yield.HERE = scratch
            try:
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    rc = emit_klt_yield.main(
                        [
                            "20260101-000000-abc1234",
                            "--envelope-id",
                            "20260202-000000-def5678",
                        ]
                    )
            finally:
                emit_klt_yield.HERE = real_here
            self.assertIn("append-only", err.getvalue())
            self.assertEqual(rc, 1)
            self.assertEqual(
                (scratch / "records" / "20260202-000000-def5678-klt-yield.json").read_text(),
                "{}\n",
                "an existing envelope was overwritten; records/* is append-only",
            )

    def test_rejects_a_malformed_envelope_id(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            emit_klt_yield.main(
                ["20260817-121131-d7d85b6", "--envelope-id", "not-a-record-id"]
            )


class CommittedEnvelopesArePortable(unittest.TestCase):
    """Every committed yield envelope but the grandfathered one is portable."""

    def test_samples_paths_are_repo_relative_and_resolve(self):
        envelopes = sorted(RECORDS_DIR.glob("*-klt-yield.json"))
        self.assertTrue(envelopes, "no klt yield envelopes found to check")
        checked = 0
        for envelope in envelopes:
            if envelope.name in GRANDFATHERED_ABSOLUTE_SAMPLES:
                continue
            with self.subTest(envelope=envelope.name):
                samples = json.loads(envelope.read_text()).get("samples")
                self.assertIsInstance(samples, str)
                self.assertFalse(
                    Path(samples).is_absolute(),
                    f"{envelope.name} records an absolute `samples` path, which "
                    "klt signoff cannot resolve on any other machine",
                )
                self.assertTrue(
                    (REPO_ROOT / samples).is_file(),
                    f"{envelope.name}'s `samples` path does not resolve from the "
                    "repo root",
                )
                checked += 1
        self.assertGreater(checked, 0, "every envelope was grandfathered")

    def test_grandfathered_envelope_is_still_the_leaking_one(self):
        """Guards the exemption itself: it must stay a statement of fact.

        If the pre-fix envelope were ever repaired in place (violating the
        append-only rule) or re-minted under the same name, this exemption
        would silently start excusing a compliant file -- and the next real
        leak could then be added to the set without anyone noticing.
        """
        for name in GRANDFATHERED_ABSOLUTE_SAMPLES:
            path = RECORDS_DIR / name
            self.assertTrue(path.is_file(), f"{name} is missing; evidence is append-only")
            samples = json.loads(path.read_text()).get("samples")
            self.assertTrue(
                Path(samples).is_absolute(),
                f"{name} no longer leaks an absolute path -- drop it from "
                "GRANDFATHERED_ABSOLUTE_SAMPLES rather than leaving a dead exemption",
            )


if __name__ == "__main__":
    unittest.main()
