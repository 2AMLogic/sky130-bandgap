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

3. **The renderers state only what is on file or what the caller said**
   (issue #708). `render_klt_yield_section` used to diagnose, from nothing
   but two absent files, that `klt` was "not available" and pinned at a
   frozen version, and to point at "Cpk figures below" that it rendered
   *above* -- so every `#444` batch-smoke record, written on a host where
   `klt` *is* on PATH, carried a false claim. `render_remint_note` hardcoded
   issue #288's one-off story ("the superseded envelope's ... absolute,
   machine-local path", "figures unchanged") into every re-mint, including
   ones with no superseded envelope at all, and `main` only ever looked for
   the source record's own envelope, never a newer re-mint of it.

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
from unittest import mock

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


#: A minimal `klt yield --format json` payload: just the fields the renderers
#: read. Shape per the committed envelopes under records/.
PAYLOAD = {
    "samples": "sim/monte-carlo-untrimmed/records/20260923-062524-1e38c62-klt-yield-input.json",
    "status": "reported",
    "measurement_count": 1,
    "source": {"kind": "sample-set", "sample_count": 4},
    "measurements": [
        {
            "name": "vout_all_27c",
            "n": 4,
            "yield": {
                "empirical": {"estimate": 0.75, "confidence_interval": {"low": 0.3, "high": 0.95}}
            },
            "capability": {"cpk": 0.4},
            "sample_size": {"verdict": "insufficient"},
            "warnings": ["only 4 samples"],
        }
    ],
    "warnings": [],
}

SOURCE_RECORD = "20260817-121131-d7d85b6"
FIRST_REMINT = "20260923-062524-1e38c62"
SECOND_REMINT = "20261128-120000-abcdef1"
OTHER_RECORD = "20261104-192509-4193f7c5"

#: Prose `render_klt_yield_section` used to hardcode into its no-envelope
#: branch. None of it follows from two absent files, so none may come back.
SECTION_FROZEN_CLAIMS = (
    "0.2.0",
    "not on PATH",
    "not available",
    "figures below",
    "Clopper-Pearson",
    "Cpk",
    "has not been run",
    "exited non-zero",
)

#: Issue #288's one-off re-mint story, which `render_remint_note` used to
#: hardcode into every note regardless of what was on file or why.
NOTE_FROZEN_CLAIMS = (
    "0.2.0",
    "not on PATH",
    "absolute, machine-local",
    "figures unchanged",
    "Why re-minted",
    "#288",
    "stays committed",
)


def _scratch_harness(testcase: unittest.TestCase) -> Path:
    """A stand-in for ``emit_klt_yield.HERE``: a scratch dir holding an empty
    ``records/``, removed after the test."""
    tmp = tempfile.TemporaryDirectory()
    testcase.addCleanup(tmp.cleanup)
    (Path(tmp.name) / "records").mkdir()
    return Path(tmp.name)


def _write_envelope(records: Path, envelope_id: str) -> None:
    (records / f"{envelope_id}-klt-yield-input.json").write_text("{}\n")
    (records / f"{envelope_id}-klt-yield.json").write_text(json.dumps(PAYLOAD) + "\n")


def _write_remint_note(records: Path, envelope_id: str, source: str, **kwargs) -> str:
    """Write ``<envelope_id>-klt-yield.md`` with the real renderer, so the
    provenance line `latest_prior_envelope` parses is the one actually minted."""
    note = emit_klt_yield.render_remint_note(
        envelope_id=envelope_id, record_id=source, payload=PAYLOAD, **kwargs
    )
    (records / f"{envelope_id}-klt-yield.md").write_text(note)
    return note


class RenderKltYieldSection(unittest.TestCase):
    """`run_mc_untrimmed.render_klt_yield_section` must not diagnose from absent files."""

    def _render(self, scratch: Path, record_id: str) -> str:
        with mock.patch.object(emit_klt_yield.record_mod, "HERE", scratch):
            return "\n".join(emit_klt_yield.record_mod.render_klt_yield_section(record_id))

    def test_no_envelope_states_what_is_missing_and_nothing_more(self):
        section = self._render(_scratch_harness(self), SOURCE_RECORD)
        for claim in SECTION_FROZEN_CLAIMS:
            with self.subTest(claim=claim):
                self.assertNotIn(claim, section)
        self.assertIn(f"`{SOURCE_RECORD}-klt-yield-input.json` is missing", section)
        self.assertIn(f"`{SOURCE_RECORD}-klt-yield.json` is missing", section)
        # The empirical yield table is rendered above this section; the old
        # text pointed readers "below" for figures that were never there.
        self.assertIn("yield figures in the table above", section)
        self.assertIn("ngspice empirical in-window fractions", section)
        self.assertIn("Both files are needed to display the `klt yield` cross-check", section)

    def test_present_envelope_renders_the_klt_figures(self):
        scratch = _scratch_harness(self)
        _write_envelope(scratch / "records", SOURCE_RECORD)
        section = self._render(scratch, SOURCE_RECORD)
        self.assertIn("Machine-checkable envelope emitted by", section)
        self.assertIn(
            "| `vout_all_27c` | 4 | 0.7500 | [0.3000, 0.9500] | 0.4000 | insufficient |",
            section,
        )
        self.assertIn("only 4 samples", section)
        self.assertNotIn("is missing", section)

    def test_input_only_reports_the_missing_envelope(self):
        scratch = _scratch_harness(self)
        (scratch / "records" / f"{SOURCE_RECORD}-klt-yield-input.json").write_text("{}\n")
        section = self._render(scratch, SOURCE_RECORD)
        self.assertIn(f"`{SOURCE_RECORD}-klt-yield-input.json` is present", section)
        self.assertIn(f"`{SOURCE_RECORD}-klt-yield.json` is missing", section)

    def test_envelope_only_reports_the_missing_input(self):
        scratch = _scratch_harness(self)
        (scratch / "records" / f"{SOURCE_RECORD}-klt-yield.json").write_text(json.dumps(PAYLOAD))
        section = self._render(scratch, SOURCE_RECORD)
        self.assertIn(f"`{SOURCE_RECORD}-klt-yield-input.json` is missing", section)
        self.assertIn(f"`{SOURCE_RECORD}-klt-yield.json` is present", section)

    def test_foreign_envelope_is_neither_displayed_nor_linked(self):
        scratch = _scratch_harness(self)
        records = scratch / "records"
        _write_envelope(records, OTHER_RECORD)
        _write_remint_note(records, OTHER_RECORD, SOURCE_RECORD, superseded=None)
        section = self._render(scratch, OTHER_RECORD)
        self.assertIn(SOURCE_RECORD, section)
        self.assertNotIn("vout_all_27c", section)
        with mock.patch.object(emit_klt_yield.record_mod, "HERE", scratch):
            self.assertEqual(emit_klt_yield.record_mod.klt_yield_links(OTHER_RECORD), [])


class RenderRemintNote(unittest.TestCase):
    """`render_remint_note` must not narrate a story it was not told."""

    def _render(self, **kwargs) -> str:
        return emit_klt_yield.render_remint_note(
            envelope_id=SECOND_REMINT, record_id=SOURCE_RECORD, payload=PAYLOAD, **kwargs
        )

    def test_without_superseded_envelope_invents_neither_one_nor_a_reason(self):
        note = self._render(superseded=None)
        self.assertIn("- **Supersedes**: (none", note)
        self.assertIn("- **Reason**: No reason given.\n", note)
        for claim in NOTE_FROZEN_CLAIMS:
            with self.subTest(claim=claim):
                self.assertNotIn(claim, note)
        # The old note described "the superseded envelope" two lines under
        # "Supersedes: (none)" -- a contradiction, not a breadcrumb.
        self.assertNotIn("superseded envelope", note)
        self.assertIn("| `vout_all_27c` | 4 | 0.7500 | [0.3000, 0.9500] | 0.4000 |", note)
        self.assertIn("`klt yield`'s output for this invocation", note)

    def test_with_a_portable_superseded_envelope_names_it_and_asserts_nothing_else(self):
        superseded = RECORDS_DIR / f"{FIRST_REMINT}-klt-yield.json"
        note = self._render(superseded=superseded)
        self.assertIn(f"- **Supersedes**: `{FIRST_REMINT}-klt-yield.json`", note)
        self.assertIn("this invocation leaves it untouched", note)
        for claim in NOTE_FROZEN_CLAIMS:
            with self.subTest(claim=claim):
                self.assertNotIn(claim, note)

    def test_reason_is_the_callers_verbatim(self):
        why = "klt bumped; the capability block's field set changed"
        note = self._render(superseded=None, reason=why)
        self.assertIn(f"- **Reason**: {why}", note)
        self.assertNotIn("No reason given.", note)

    def test_multiline_reason_stays_one_list_item(self):
        note = self._render(superseded=None, reason="klt bumped,\n  re-graded")
        self.assertIn("- **Reason**: klt bumped, re-graded\n", note)

    def test_blank_reason_reads_as_none_given(self):
        note = self._render(superseded=None, reason="  \n")
        self.assertIn("- **Reason**: No reason given.\n", note)

    def test_both_given(self):
        superseded = RECORDS_DIR / f"{FIRST_REMINT}-klt-yield.json"
        note = self._render(superseded=superseded, reason="klt bumped")
        self.assertIn(f"- **Supersedes**: `{FIRST_REMINT}-klt-yield.json`", note)
        self.assertIn("- **Reason**: klt bumped\n", note)


class LatestPriorEnvelope(unittest.TestCase):
    """A re-mint supersedes the newest envelope for its source record."""

    def _latest(self, scratch: Path, record_id: str):
        with mock.patch.object(emit_klt_yield, "HERE", scratch):
            return emit_klt_yield.latest_prior_envelope(record_id)

    def test_none_when_no_envelope_was_ever_minted(self):
        self.assertIsNone(self._latest(_scratch_harness(self), SOURCE_RECORD))

    def test_resolves_the_historical_issue_288_remint(self):
        scratch = _scratch_harness(self)
        records = scratch / "records"
        for name in (
            f"{SOURCE_RECORD}-klt-yield.json",
            f"{FIRST_REMINT}-klt-yield.json",
            f"{FIRST_REMINT}-klt-yield.md",
        ):
            shutil.copyfile(RECORDS_DIR / name, records / name)
        self.assertEqual(
            self._latest(scratch, SOURCE_RECORD), records / f"{FIRST_REMINT}-klt-yield.json"
        )

    def test_falls_back_to_the_source_records_own_envelope(self):
        scratch = _scratch_harness(self)
        _write_envelope(scratch / "records", SOURCE_RECORD)
        own = scratch / "records" / f"{SOURCE_RECORD}-klt-yield.json"
        self.assertEqual(self._latest(scratch, SOURCE_RECORD), own)

    def test_prefers_the_newest_remint_of_the_same_source_record(self):
        scratch = _scratch_harness(self)
        records = scratch / "records"
        _write_envelope(records, SOURCE_RECORD)
        _write_envelope(records, FIRST_REMINT)
        _write_remint_note(
            records,
            FIRST_REMINT,
            SOURCE_RECORD,
            superseded=records / f"{SOURCE_RECORD}-klt-yield.json",
        )
        self.assertEqual(
            self._latest(scratch, SOURCE_RECORD), records / f"{FIRST_REMINT}-klt-yield.json"
        )

    def test_two_remints_resolve_to_the_later(self):
        scratch = _scratch_harness(self)
        records = scratch / "records"
        for envelope_id in (SOURCE_RECORD, FIRST_REMINT, SECOND_REMINT):
            _write_envelope(records, envelope_id)
        _write_remint_note(records, FIRST_REMINT, SOURCE_RECORD, superseded=None)
        _write_remint_note(
            records,
            SECOND_REMINT,
            SOURCE_RECORD,
            superseded=records / f"{FIRST_REMINT}-klt-yield.json",
        )
        self.assertEqual(
            self._latest(scratch, SOURCE_RECORD), records / f"{SECOND_REMINT}-klt-yield.json"
        )

    def test_ignores_remints_of_other_source_records(self):
        scratch = _scratch_harness(self)
        records = scratch / "records"
        _write_envelope(records, OTHER_RECORD)
        _write_envelope(records, FIRST_REMINT)
        _write_remint_note(
            records,
            FIRST_REMINT,
            OTHER_RECORD,
            superseded=records / f"{OTHER_RECORD}-klt-yield.json",
        )
        self.assertIsNone(self._latest(scratch, SOURCE_RECORD))

    def test_a_note_without_its_envelope_is_not_a_candidate(self):
        scratch = _scratch_harness(self)
        records = scratch / "records"
        _write_envelope(records, SOURCE_RECORD)
        _write_remint_note(records, FIRST_REMINT, SOURCE_RECORD, superseded=None)
        self.assertEqual(
            self._latest(scratch, SOURCE_RECORD), records / f"{SOURCE_RECORD}-klt-yield.json"
        )

    def test_note_takes_precedence_over_a_colliding_source_id(self):
        scratch = _scratch_harness(self)
        records = scratch / "records"
        _write_envelope(records, OTHER_RECORD)
        _write_remint_note(records, OTHER_RECORD, SOURCE_RECORD, superseded=None)
        self.assertEqual(
            self._latest(scratch, SOURCE_RECORD), records / f"{OTHER_RECORD}-klt-yield.json"
        )
        self.assertIsNone(self._latest(scratch, OTHER_RECORD))


class RemintMainWiring(unittest.TestCase):
    """`main` feeds `--envelope-id` re-mints the newest prior envelope and the
    caller's `--reason`, driving a fake `klt` so nothing touches committed
    evidence or needs the real tool."""

    def _remint(self, scratch: Path, argv: list[str]) -> int:
        out, err = io.StringIO(), io.StringIO()
        fake = subprocess.CompletedProcess([], 0, stdout=json.dumps(PAYLOAD) + "\n", stderr="")
        patches = (
            mock.patch.object(emit_klt_yield, "HERE", scratch),
            mock.patch.object(emit_klt_yield.shutil, "which", return_value="/usr/bin/klt"),
            mock.patch.object(
                emit_klt_yield, "build_sample_set", return_value={"measurements": []}
            ),
            mock.patch.object(emit_klt_yield, "run_klt_yield", return_value=fake),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        )
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            return emit_klt_yield.main(argv)

    def _scratch(self) -> Path:
        scratch = _scratch_harness(self)
        (scratch / "records" / f"{SOURCE_RECORD}.json").write_text("{}\n")
        return scratch

    def test_note_names_the_newest_prior_envelope_and_the_reason(self):
        scratch = self._scratch()
        records = scratch / "records"
        _write_envelope(records, SOURCE_RECORD)
        _write_envelope(records, FIRST_REMINT)
        _write_remint_note(records, FIRST_REMINT, SOURCE_RECORD, superseded=None)
        rc = self._remint(
            scratch, [SOURCE_RECORD, "--envelope-id", SECOND_REMINT, "--reason", "klt bumped"]
        )
        self.assertEqual(rc, 0)
        note = (records / f"{SECOND_REMINT}-klt-yield.md").read_text()
        self.assertIn(f"- **Supersedes**: `{FIRST_REMINT}-klt-yield.json`", note)
        self.assertIn("- **Reason**: klt bumped\n", note)
        for claim in NOTE_FROZEN_CLAIMS:
            with self.subTest(claim=claim):
                self.assertNotIn(claim, note)
        minted = (records / f"{SECOND_REMINT}-klt-yield.json").read_text()
        self.assertEqual(minted, json.dumps(PAYLOAD) + "\n")

    def test_note_without_reason_or_prior_envelope_says_so(self):
        scratch = self._scratch()
        rc = self._remint(scratch, [SOURCE_RECORD, "--envelope-id", SECOND_REMINT])
        self.assertEqual(rc, 0)
        note = (scratch / "records" / f"{SECOND_REMINT}-klt-yield.md").read_text()
        self.assertIn("- **Supersedes**: (none", note)
        self.assertIn("- **Reason**: No reason given.\n", note)

    def test_invalid_remint_leaves_source_evidence_intact(self):
        scratch = _scratch_harness(self)
        records = scratch / "records"
        for suffix in (".json", ".md", "-klt-yield-input.json", "-klt-yield.json"):
            name = f"{SOURCE_RECORD}{suffix}"
            shutil.copyfile(RECORDS_DIR / name, records / name)

        original = {p.name: p.read_bytes() for p in records.iterdir()}
        for envelope_id in (SOURCE_RECORD, "", SECOND_REMINT + "\n"):
            with self.subTest(envelope_id=envelope_id):
                argv = [SOURCE_RECORD, "--envelope-id", envelope_id, "--reason", "regrade"]
                with self.assertRaises(SystemExit) as cm:
                    self._remint(scratch, argv)
                self.assertEqual(cm.exception.code, 2)
                self.assertEqual({p.name: p.read_bytes() for p in records.iterdir()}, original)

    def test_another_source_reserves_its_id_before_it_has_an_envelope(self):
        for suffixes in ((".json", ".md"), (".json",), (".md",)):
            with self.subTest(suffixes=suffixes):
                scratch = _scratch_harness(self)
                records = scratch / "records"
                names = [f"{SOURCE_RECORD}.json", f"{SOURCE_RECORD}.md"]
                names.extend(OTHER_RECORD + suffix for suffix in suffixes)
                for name in names:
                    shutil.copyfile(RECORDS_DIR / name, records / name)
                before = {p.name: p.read_bytes() for p in records.iterdir()}
                rc = self._remint(scratch, [SOURCE_RECORD, "--envelope-id", OTHER_RECORD])
                self.assertEqual(rc, 1)
                self.assertEqual({p.name: p.read_bytes() for p in records.iterdir()}, before)

    def test_ordinary_emission_preserves_a_foreign_remint(self):
        scratch = _scratch_harness(self)
        records = scratch / "records"
        for suffix in (".json", ".md"):
            name = OTHER_RECORD + suffix
            shutil.copyfile(RECORDS_DIR / name, records / name)
        _write_envelope(records, OTHER_RECORD)
        _write_remint_note(records, OTHER_RECORD, SOURCE_RECORD, superseded=None)
        before = {p.name: p.read_bytes() for p in records.iterdir()}
        self.assertEqual(self._remint(scratch, [OTHER_RECORD]), 1)
        self.assertEqual({p.name: p.read_bytes() for p in records.iterdir()}, before)

    def test_reason_without_envelope_id_is_a_usage_error(self):
        """Without `--envelope-id` no note is written, so a reason would be
        silently dropped -- refuse instead."""
        with contextlib.redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(SystemExit) as cm:
                emit_klt_yield.main([SOURCE_RECORD, "--reason", "klt bumped"])
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("--reason", err.getvalue())


if __name__ == "__main__":
    unittest.main()
