#!/usr/bin/env python3
"""Emit a `klt yield` JSON envelope for a `run_mc_untrimmed.py` record (issue #180).

`klt yield` (klayout-tools 0.2.0, pinned by `layout/requirements.txt`) turns a
Monte Carlo sample set + spec limits into a yield estimate that always
carries its confidence interval, Cpk/sigma-to-spec, and a sample-size
verdict -- a machine-checkable envelope alongside this experiment's own
ngspice-driven `record.md`/`record.json` pair, per issue #180's acceptance
criteria and `klt signoff`'s aggregation contract.

This is a post-hoc reader, not part of the simulation run: `klt yield`
consumes a plain sample-set document ({"measurements": [{"name", "samples",
"limits"}, ...]}), which this script builds by re-parsing the `all`-config
mismatch points' raw per-sample `vout` values out of the record's own
`corners/<record_id>/*.log` files (the same files `run_mc_untrimmed.py`
already wrote and the record already cites) -- no new simulation, no new
netlist. Only the `all` config (every family's mismatch active at once) is
included: that is the spec-relevant row the record's own tables single out;
the `pnp`/`resistor`/`mos` isolated re-runs are contributor-breakdown
diagnostics, not independent yield claims (see the record's own caption).
Only *converged* samples are included -- the same `mc_solve_yield` exclusion
`run_mc_untrimmed.py` applies (issue #10's startup artifact is not a
mismatch datum) -- so the sample count and yield figure this emits are
directly comparable to the record's own table, not a re-definition of it.

Usage
-----
    sim/monte-carlo-untrimmed/emit_klt_yield.py <record_id>
    sim/monte-carlo-untrimmed/emit_klt_yield.py <record_id> --envelope-id <new_id>

Writes `sim/monte-carlo-untrimmed/records/<record_id>-klt-yield.json` (the
raw `klt yield --format json` payload) and prints a one-line summary per
temperature. Exit status: 0 on success, 1 if `klt` or its native extension is
unavailable (in which case the record must say so per issue #180's
acceptance criteria) or the expected corner logs are missing, 2 if `klt
yield` itself reports an error.

Repo-relative provenance (issue #288)
-------------------------------------
`klt yield` echoes the sample-set path it was *invoked with* straight back
into its own report's top-level `samples` field, so invoking it with an
absolute path bakes a machine-local path into committed evidence -- exactly
the hazard `signoff/design-evidence-tiers.md`'s "Provenance hygiene in
evidence records" section warns about, and enough on its own to make the
envelope uncitable from `signoff/block-manifest.json` (`klt signoff` cannot
resolve that path on any other machine). This script therefore runs `klt
yield` with ``cwd=REPO_ROOT`` and hands it the sample set's **repo-relative**
path, so `samples` is portable by construction rather than by post-hoc
scrubbing.

Re-minting (issue #288)
-----------------------
`records/*` is append-only (`sim/README.md`), so a previously committed
envelope is never rewritten in place. ``--envelope-id <new_id>`` re-mints the
envelope for an already-committed record's corner logs under a *new* record
id -- writing `<new_id>-klt-yield-input.json`, `<new_id>-klt-yield.json` and a
`<new_id>-klt-yield.md` note that names the source record and the envelope it
supersedes -- and leaves the source record's own `.json`/`.md` (and any
earlier envelope) untouched. It refuses to overwrite an existing file.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE.parent
REPO_ROOT = SIM_DIR.parent

sys.path.insert(0, str(SIM_DIR / "bin"))
from sim_common import parse_samples, partition_by_window  # noqa: E402

sys.path.insert(0, str(HERE))
import run_mc_untrimmed as record_mod  # noqa: E402

# Mirrors run_mc_untrimmed.py's own module-level constants -- kept in sync by
# hand (both are small, stable, and cited by the same record).
SPEC_WINDOW_V = (1.176, 1.224)
OPERATING_VOUT_V = (0.9, 1.5)
TEMPS_C = [-40.0, 27.0, 125.0]
SUPPLY_V = 3.3
MM_SECTION = "tt_mm"

#: `<YYYYMMDD>-<HHMMSS>-<short-sha>`, this repo's record-id shape (see
#: `sim/README.md`). Applied to `--envelope-id` too, so a re-minted envelope
#: is named the same way every other record in this tree is.
RECORD_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]+$")


def corner_id_for(temp_c: float) -> str:
    return f"{MM_SECTION}_all_{temp_c:g}c_{SUPPLY_V:.2f}v"


def measurement_name(temp_c: float) -> str:
    sign = "m" if temp_c < 0 else ""
    return f"vout_all_{sign}{abs(temp_c):g}c"


def load_vout_samples(log_path: Path) -> list[float]:
    if not log_path.is_file():
        raise SystemExit(f"error: missing corner log: {log_path}")
    text = log_path.read_text()
    parsed = parse_samples(text, ("vout", "vgdrv"))
    if not parsed:
        raise SystemExit(f"error: no Monte Carlo samples parsed from {log_path}")
    converged, _excluded = partition_by_window(parsed, "vout", OPERATING_VOUT_V)
    return [s["vout"] for s in converged]


def build_sample_set(record_id: str) -> dict:
    corners_dir = HERE / "corners" / record_id
    measurements = []
    for t in TEMPS_C:
        corner_id = corner_id_for(t)
        samples = load_vout_samples(corners_dir / f"{corner_id}.log")
        measurements.append(
            {
                "name": measurement_name(t),
                "unit": "V",
                "samples": samples,
                "limits": {"min": SPEC_WINDOW_V[0], "max": SPEC_WINDOW_V[1]},
                "source_corners": [corner_id],
            }
        )
    return {"measurements": measurements}


def rel_to_repo(path: Path) -> str:
    """``path`` as a repo-relative string, or its own string if it is outside.

    Only ever used for human-facing messages. Never raises: a caller pointing
    this harness at a records directory outside the repo (a test fixture, a
    scratch copy) should get the message it asked for, not a traceback from
    ``Path.relative_to``.
    """
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def run_klt_yield(sample_set_path: Path) -> subprocess.CompletedProcess[str]:
    """Invoke `klt yield` on ``sample_set_path`` from the repo root, passing a
    **repo-relative** path (issue #288).

    `klt yield` copies the path it was invoked with verbatim into its report's
    own top-level ``samples`` field. Handing it an absolute path therefore
    leaks the producing machine's directory layout into committed evidence and
    makes the envelope unresolvable -- and so uncitable -- anywhere else. The
    relative path is only meaningful with a matching working directory, hence
    ``cwd=REPO_ROOT``: the two must be changed together.
    """
    return subprocess.run(
        [
            "klt",
            "yield",
            str(sample_set_path.resolve().relative_to(REPO_ROOT)),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def render_remint_note(
    *, envelope_id: str, record_id: str, payload: dict, superseded: Path | None
) -> str:
    """The `<envelope_id>-klt-yield.md` breadcrumb for a re-minted envelope.

    `sim/README.md`'s append-only rule requires a correction to mint a *new*
    record that names the prior one via **Supersedes** rather than edit it, so
    a re-mint that writes only JSON would lose the reason it exists.
    """
    lines = [
        f"# `klt yield` envelope re-mint — `{envelope_id}`",
        "",
        f"- **Envelope record id**: `{envelope_id}`",
        f"- **Source record**: [`{record_id}`](./{record_id}.md) — this envelope is",
        f"  derived from that record's own committed `all`-config corner logs",
        f"  (`corners/{record_id}/`). No new simulation was run; the sample set is",
        "  re-parsed from those logs by `sim/monte-carlo-untrimmed/emit_klt_yield.py`.",
        "- **Supersedes**: "
        + (
            f"`{superseded.name}` (same source record; re-minted, not edited)"
            if superseded is not None
            else "(none)"
        ),
        "- **Why re-minted**: the superseded envelope's own top-level `samples`",
        "  field recorded an **absolute, machine-local** path, because `klt yield`",
        "  echoes back the path it was invoked with and the harness invoked it with",
        "  an absolute one. `klt signoff` cannot resolve such a path on any other",
        "  machine, so that envelope could not be cited from",
        "  `signoff/block-manifest.json` (T1 item 6). Issue #288 fixed the harness to",
        "  invoke `klt yield` from the repo root with a repo-relative path; this",
        "  envelope is the first minted under the fix. The superseded envelope stays",
        "  committed and unmodified, per `sim/README.md`'s append-only rule.",
        f"- **`samples` (this envelope)**: `{payload.get('samples')}`",
        f"- **Status**: `{payload.get('status')}` — "
        f"{payload.get('measurement_count')} measurements, "
        f"{(payload.get('source') or {}).get('sample_count')} samples.",
        "",
        "## Measurements",
        "",
        "| measurement | n | empirical yield | 95% CI | Cpk |",
        "|---|---|---|---|---|",
    ]
    for m in payload.get("measurements", []):
        emp = (m.get("yield") or {}).get("empirical") or {}
        ci = emp.get("confidence_interval") or {}
        cap = m.get("capability") or {}
        lines.append(
            f"| `{m.get('name')}` | {m.get('n')} | {emp.get('estimate'):.4f} | "
            f"[{ci.get('low'):.4f}, {ci.get('high'):.4f}] | {cap.get('cpk'):.4f} |"
        )
    lines += [
        "",
        "These figures are the superseded envelope's figures unchanged — the fix",
        "was to the *path* `klt yield` was invoked with, not to the sample set or",
        "the statistics computed from it.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Emit a `klt yield` JSON envelope for a run_mc_untrimmed.py record."
    )
    parser.add_argument("record_id", help="the Monte Carlo record whose corner logs to read")
    parser.add_argument(
        "--envelope-id",
        default=None,
        metavar="ID",
        help=(
            "re-mint the envelope under this new record id instead of the source "
            "record's own, leaving the source record and any earlier envelope "
            "untouched (records/* is append-only -- see sim/README.md)"
        ),
    )
    args = parser.parse_args(argv)

    record_id = args.record_id
    if not RECORD_ID_RE.match(record_id):
        parser.error(f"record_id must look like <YYYYMMDD>-<HHMMSS>-<short-sha>; got {record_id!r}")
    envelope_id = args.envelope_id or record_id
    if not RECORD_ID_RE.match(envelope_id):
        parser.error(
            f"--envelope-id must look like <YYYYMMDD>-<HHMMSS>-<short-sha>; got {envelope_id!r}"
        )
    remint = envelope_id != record_id

    record_json = HERE / "records" / f"{record_id}.json"
    if not record_json.is_file():
        print(f"error: no such record: {record_json}", file=sys.stderr)
        return 1

    sample_set_path = HERE / "records" / f"{envelope_id}-klt-yield-input.json"
    out_path = HERE / "records" / f"{envelope_id}-klt-yield.json"
    note_path = HERE / "records" / f"{envelope_id}-klt-yield.md"
    if remint:
        # Append-only: a re-mint adds a record, it never overwrites one. Refuse
        # rather than clobber, including the note -- a colliding id is a caller
        # mistake, not something to resolve silently. Checked before the `klt`
        # probe below: a colliding id is wrong whether or not `klt` is
        # installed, and reporting the missing tool first would hide it.
        for path in (sample_set_path, out_path, note_path):
            if path.exists():
                print(
                    f"error: {rel_to_repo(path)} already exists; "
                    "records/* is append-only (sim/README.md) -- pick an unused "
                    "--envelope-id",
                    file=sys.stderr,
                )
                return 1

    if not shutil.which("klt"):
        print(
            "klt not found on PATH -- cannot emit a klt yield envelope; the "
            "record must state this rather than silently omitting it (issue #180)",
            file=sys.stderr,
        )
        return 1

    sample_set = build_sample_set(record_id)
    sample_set_path.write_text(json.dumps(sample_set, indent=2) + "\n")

    proc = run_klt_yield(sample_set_path)
    if proc.returncode != 0:
        print(proc.stdout, file=sys.stdout)
        print(proc.stderr, file=sys.stderr)
        print(
            f"error: klt yield exited {proc.returncode} -- see stderr above; the "
            "record must disclose this rather than silently omitting the envelope",
            file=sys.stderr,
        )
        return 2

    out_path.write_text(proc.stdout if proc.stdout.endswith("\n") else proc.stdout + "\n")
    payload = json.loads(proc.stdout)

    if remint:
        prior = HERE / "records" / f"{record_id}-klt-yield.json"
        note_path.write_text(
            render_remint_note(
                envelope_id=envelope_id,
                record_id=record_id,
                payload=payload,
                superseded=prior if prior.is_file() else None,
            )
        )
    else:
        # Complete the record: this envelope is meant to sit "alongside" the
        # ngspice-driven record (issue #180's acceptance criteria), so fold its
        # links and a summary table into record.md/record.json now that it
        # exists -- both files are otherwise still exactly what
        # run_mc_untrimmed.py wrote a moment ago in the same, still-uncommitted
        # run; this is completing that record's generation, not editing a
        # published one (see sim/README.md's append-only rule, which governs
        # already-committed records). A `--envelope-id` re-mint deliberately
        # skips this step: by then the source record IS published.
        record = json.loads(record_json.read_text())
        for key, value in record_mod.klt_yield_links(record_id):
            record["links"][key] = value
        record_json.write_text(json.dumps(record, indent=2) + "\n")
        record_md = HERE / "records" / f"{record_id}.md"
        record_md.write_text(record_mod.render_record(record))
        print(f"record updated:             {rel_to_repo(record_md)}")

    print(f"klt yield envelope written: {rel_to_repo(out_path)}")
    print(f"sample-set input written:   {rel_to_repo(sample_set_path)}")
    print(f"envelope samples field:     {payload.get('samples')}")
    if remint:
        print(f"re-mint note written:       {rel_to_repo(note_path)}")
    for m in payload.get("measurements", []):
        emp = m.get("yield", {}).get("empirical", {})
        print(
            f"  {m['name']:<16} n={m.get('n')} "
            f"empirical yield={emp.get('estimate'):.4f} "
            f"CI=[{emp.get('confidence_interval', {}).get('low'):.4f}, "
            f"{emp.get('confidence_interval', {}).get('high'):.4f}] "
            f"(confidence={emp.get('confidence')})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
