#!/usr/bin/env python3
"""Unit coverage for `sim/monte-carlo-untrimmed/emit_klt_yield.py` (issue #288).

Three things this file guards, all of which were real defects rather than
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

3. **A bare re-run must not either (issue #713).** The collision check used to
   guard only the `--envelope-id` path, so `emit_klt_yield.py <record_id>` on
   a record that already had an envelope rewrote it -- and the record pair --
   in place, exit 0, nothing on stderr.

Plus a standing check on the committed evidence itself: every `*-klt-yield.json`
in the records tree must name a repo-relative `samples` document that actually
exists -- except the one pre-fix envelope, which is named explicitly here so
that a *new* leak cannot hide behind the grandfathered one.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
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


#: A stand-in `klt yield --format json` payload: just the fields the emitter
#: reads back after the run (issue #713's regression fixture).
FAKE_KLT_YIELD = json.dumps(
    {
        "samples": "sim/monte-carlo-untrimmed/records/-klt-yield-input.json",
        "status": "ok",
        "measurement_count": 1,
        "source": {"sample_count": 4},
        "measurements": [
            {
                "name": "vout_all_27c",
                "n": 4,
                "yield": {
                    "empirical": {
                        "estimate": 1.0,
                        "confidence_interval": {"low": 1.0, "high": 1.0},
                        "confidence": 0.95,
                    }
                },
                "capability": {"cpk": 1.0},
            }
        ],
    }
)


class BareEmissionIsAppendOnly(unittest.TestCase):
    """A bare `emit_klt_yield.py <record_id>` must refuse to rewrite an envelope.

    Issue #713: the collision check used to run only on the `--envelope-id`
    path, so a second bare run on a record that already had an envelope
    rewrote `<record_id>-klt-yield{-input}.json` *and* the record pair in
    place -- exit 0, nothing on stderr. That is the in-place rewrite of
    signoff-cited evidence that `sim/README.md`'s append-only rule exists to
    prevent. The fixture is the signoff-cited record itself, copied into a
    scratch tree, so the test can let a misbehaving emitter go all the way to
    its writes without committed evidence ever being at risk.
    """

    RECORD = "20260817-121131-d7d85b6"
    INPUT = f"{RECORD}-klt-yield-input.json"
    ENVELOPE = f"{RECORD}-klt-yield.json"
    NEW_ID = "20990101-000000-0000713"

    def _scratch(self, root: Path, *envelope_files: str) -> Path:
        """A scratch tree holding the real record pair plus the named envelope
        files, and synthetic converged corner samples so that an emission
        which *does* go ahead has everything it needs to reach its writes --
        the regression must fail because bytes changed, not because some
        unrelated input was missing."""
        records = root / "records"
        records.mkdir()
        for name in (f"{self.RECORD}.json", f"{self.RECORD}.md", *envelope_files):
            shutil.copy2(RECORDS_DIR / name, records / name)
        corners = root / "corners" / self.RECORD
        corners.mkdir(parents=True)
        for t in emit_klt_yield.TEMPS_C:
            (corners / f"{emit_klt_yield.corner_id_for(t)}.samples.json").write_text(
                json.dumps({"samples": [{"vout": 1.2, "vgdrv": 2.0}] * 4})
            )
        return records

    @staticmethod
    def _tree(root: Path) -> dict[str, bytes]:
        return {
            str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob("*"))
            if p.is_file()
        }

    def _run(self, root: Path, argv: list[str]) -> tuple[int, str, str, set[str]]:
        """`main(argv)` against the scratch tree with `klt` present and `klt
        yield` stubbed, so a run that is *not* refused goes all the way to
        its writes. Returns `(rc, stdout, stderr, stages that ran)`."""
        ran: set[str] = set()

        def fake_which(name: str) -> str:
            ran.add("which")
            return "/fake/bin/klt"

        def fake_klt_yield(sample_set_path: Path) -> subprocess.CompletedProcess[str]:
            ran.add("klt_yield")
            return subprocess.CompletedProcess([], 0, stdout=FAKE_KLT_YIELD + "\n", stderr="")

        real_here, real_which, real_run = (
            emit_klt_yield.HERE,
            emit_klt_yield.shutil.which,
            emit_klt_yield.run_klt_yield,
        )
        emit_klt_yield.HERE = root
        emit_klt_yield.shutil.which = fake_which
        emit_klt_yield.run_klt_yield = fake_klt_yield
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = emit_klt_yield.main(argv)
        finally:
            emit_klt_yield.HERE = real_here
            emit_klt_yield.shutil.which = real_which
            emit_klt_yield.run_klt_yield = real_run
        return rc, out.getvalue(), err.getvalue(), ran

    def test_bare_rerun_refuses_and_rewrites_nothing(self):
        """The issue #713 regression: record plus envelope already on disk."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._scratch(root, self.INPUT, self.ENVELOPE)
            before = self._tree(root)
            rc, _out, err, ran = self._run(root, [self.RECORD])
            self.assertEqual(rc, 1)
            self.assertIn("append-only", err)
            self.assertIn(self.INPUT, err)
            self.assertIn("--envelope-id <new_id>", err)
            self.assertIn("delete the uncommitted file", err)
            # Refused before the `klt` probe and before any write -- the
            # record pair's re-render included.
            self.assertEqual(ran, set())
            self.assertEqual(self._tree(root), before, "a bare re-run wrote something")

    def test_envelope_alone_is_a_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._scratch(root, self.ENVELOPE)
            before = self._tree(root)
            rc, _out, err, ran = self._run(root, [self.RECORD])
            self.assertEqual(rc, 1)
            self.assertIn(self.ENVELOPE, err)
            self.assertNotIn(self.INPUT, err)
            self.assertEqual(ran, set())
            self.assertEqual(self._tree(root), before)

    def test_input_sidecar_alone_is_a_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._scratch(root, self.INPUT)
            before = self._tree(root)
            rc, _out, err, ran = self._run(root, [self.RECORD])
            self.assertEqual(rc, 1)
            self.assertIn(self.INPUT, err)
            self.assertNotIn(self.ENVELOPE, err)
            self.assertEqual(ran, set())
            self.assertEqual(self._tree(root), before)

    def test_first_emission_proceeds_as_before(self):
        """No envelope on disk: the guard stays out of the way, and the bare
        emission still writes the envelope and completes the record pair."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = self._scratch(root)
            rc, out, err, ran = self._run(root, [self.RECORD])
            self.assertEqual(rc, 0, err)
            self.assertEqual(ran, {"which", "klt_yield"})
            for name in (self.INPUT, self.ENVELOPE):
                self.assertTrue((records / name).is_file(), f"{name} was not written")
            self.assertIn("record updated:", out)

    def test_the_advised_remint_under_a_new_id_succeeds(self):
        """The refusal points at `--envelope-id <new_id>`: following it must
        mint the new envelope beside the old one and touch nothing else."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = self._scratch(root, self.INPUT, self.ENVELOPE)
            before = self._tree(root)
            rc, _out, err, ran = self._run(root, [self.RECORD, "--envelope-id", self.NEW_ID])
            self.assertEqual(rc, 0, err)
            self.assertEqual(ran, {"which", "klt_yield"})
            for name in (
                f"{self.NEW_ID}-klt-yield-input.json",
                f"{self.NEW_ID}-klt-yield.json",
                f"{self.NEW_ID}-klt-yield.md",
            ):
                self.assertTrue((records / name).is_file(), f"{name} was not written")
            after = self._tree(root)
            for path, content in before.items():
                self.assertEqual(after[path], content, f"{path} was rewritten by a re-mint")


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
