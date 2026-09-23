#!/usr/bin/env python3
"""layout/bin/measure_combine_devices_determinism.py -- measure whether this
cell's committed `klt lvs` request reproduces the *same* verdict across
repeated runs of the *same* `klt` build, so a "`klt lvs` is clean" claim
rests on a re-runnable determinism measurement rather than on one lucky
invocation (issue #288).

Why this exists
---------------
`layout/bandgap-core/reports/<record-id>/lvs.combined.json` is the evidence
behind this repo's "`klt lvs`-clean (`mismatch_count: 0`)" claim. Issue #282's
signoff manifest work observed that re-running the *same committed request
document* against the *same committed netlists*, but under a newer `klt` build
than `layout/requirements.txt` pins, reported `status: mismatch`,
`mismatch_count: 12` instead. That was originally read as a version-to-version
regression (`klt` 0.2.0 -> 0.5.0/0.6.0).

It is not a clean version-to-version delta: on the newer build the verdict is
**not reproducible run to run**. This harness measures that directly -- N
repetitions of one request document, tallied -- because a verdict that is only
sometimes `match` is a different (and worse) failure than a verdict that
deterministically changed, and the two demand different responses.

What it measures
----------------
Two variants of the same committed request, differing only in
`options.combine_devices_max_attempts` (klayout-tools#1412):

    variant           combine_devices_max_attempts   combine runs against
    ----------------  -----------------------------  ------------------------
    as_committed      (absent -> the build default)  a `Netlist.dup()` copy
    max_attempts_1    1                              the netlist itself

`_combine_devices_safely`'s bounded-retry mitigation (klayout-tools#1185)
runs every attempt but the *last* against an independent `Netlist.dup()` copy
and adopts the first clean one via `Netlist.assign()`. With a budget of 1 the
only attempt IS the last one, so the combine runs directly against the netlist
and the `dup()`/`assign()` round trip never happens. Splitting the two isolates
the round trip as the variable, which is what makes this a diagnosis rather
than a flake report.

A build that predates klayout-tools#1412 *ignores* the option rather than
rejecting it, which would silently turn the isolating variant into a duplicate
of the first one; the harness probes for support and records that variant as
`unsupported` instead of running it.

It is deliberately NOT part of `run-bandgap-routed-flow.sh`'s gate: it changes
nothing, reads an existing record, and writes only its own append-only
evidence directory.

Usage
-----
    python3 layout/bin/measure_combine_devices_determinism.py \\
        --record layout/bandgap-core/reports/<record-id> \\
        --out-dir layout/bandgap-core/combine-determinism/<record-id> \\
        --trials 200

Imports `klayout_tools` directly (like
`layout/bin/measure_fixed_offset_variants.py`) rather than shelling out to the
`klt` CLI per trial: a few hundred repetitions of a pre-extracted-netlist
compare are seconds in-process and minutes through the CLI, and the verdict is
identical either way (the CLI is a thin wrapper over `run_lvs`).
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import platform
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from layout_common import git  # noqa: E402

REQUEST_NAME = "lvs.combined.request.json"

#: (label, combine_devices_max_attempts | None). `None` leaves the option out
#: of the request entirely, i.e. whatever the build's own default budget is.
VARIANTS: tuple[tuple[str, int | None], ...] = (
    ("as_committed", None),
    ("max_attempts_1", 1),
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _require(path: Path, what: str) -> Path:
    if not path.is_file():
        raise SystemExit(
            f"measure_combine_devices_determinism.py: {what} not found: {path}"
        )
    return path


def _klt_identity(repo_root: Path, declared_ref: str | None) -> dict[str, Any]:
    """The self-reported identity of the `klayout_tools` this process imported.

    A determinism measurement is only meaningful against a *named* build, and
    "0.5.0" alone does not name one: a git-snapshot install and the released
    wheel can both call themselves 0.5.0 while behaving differently (see
    `signoff/README.md`'s "Grader distribution discipline").

    Read from the *imported package*, not from `klt` on PATH: this harness is
    meant to be pointed at a specific build (e.g. `PYTHONPATH=<checkout>/src`
    to measure the `layout/requirements.txt` pin without disturbing the
    installed CLI), and a CLI-sourced identity would then name the wrong
    build.

    **Identity, not location** (`signoff/design-evidence-tiers.md`, "Provenance
    hygiene in evidence records"): an import path outside this repo is a
    machine-local fact that reproduces nothing, so it is recorded only as
    being outside, never absolutely. What pins the build behaviourally is the
    `sha256` of the `lvs.py` under measurement, which is recorded instead --
    and is decisive even for a build whose version string is ambiguous or
    whose `build_identity` module does not exist yet.
    """
    import klayout_tools  # noqa: PLC0415
    from klayout_tools import lvs  # noqa: PLC0415

    package_dir = Path(klayout_tools.__file__).resolve().parent
    try:
        location = str(package_dir.relative_to(repo_root))
    except ValueError:
        location = "(outside this repo -- pinned by lvs_module_sha256 below)"

    identity: dict[str, Any] = {
        "module_location": location,
        "lvs_module_sha256": _sha256_file(Path(lvs.__file__).resolve()),
        "declared_ref": declared_ref,
    }
    try:
        from klayout_tools.build_identity import version_report  # noqa: PLC0415

        identity.update(version_report())
    except ImportError:
        # Predates `klayout_tools.build_identity` (added after this repo's
        # current `layout/requirements.txt` pin). Do NOT fall back to `klt
        # version` on PATH here -- that would name the *installed* CLI's
        # build, which is exactly the build this harness may have been
        # pointed away from via PYTHONPATH.
        identity["version"] = getattr(klayout_tools, "__version__", "unknown")
        identity["build_identity_available"] = False
    return identity


def _supports_max_attempts() -> tuple[bool, str]:
    """Whether this build implements `options.combine_devices_max_attempts`.

    A build predating klayout-tools#1412 does not *reject* the option -- it
    ignores it silently, which would make the `max_attempts_1` variant a
    duplicate of `as_committed` masquerading as an isolating control. Probe
    the module instead of inferring from the numbers, so an unsupported
    build is recorded as unsupported rather than as corroboration.
    """
    from klayout_tools import lvs  # noqa: PLC0415

    if hasattr(lvs, "_parse_combine_devices_max_attempts"):
        return True, ""
    if not hasattr(lvs, "_COMBINE_DEVICES_MAX_ATTEMPTS"):
        return False, (
            "this build predates klayout-tools#1185 entirely -- it has no "
            "combine retry budget and never runs combine_devices() against a "
            "Netlist.dup() copy, so there is no round trip to isolate"
        )
    return False, (
        "this build has klayout-tools#1185's retry but predates #1412, so "
        "options.combine_devices_max_attempts is ignored rather than honoured"
    )


def _variant_request(
    committed: dict[str, Any], record: Path, max_attempts: int | None, work: Path, label: str
) -> Path:
    """A copy of the committed request with absolute netlist paths.

    `klt lvs` resolves a request's relative paths against the request file's
    own directory, so a copy written outside the record directory has to name
    the netlists absolutely. Nothing else is altered -- `hints`, `engine`,
    `reference.top` and `options.combine_devices` are carried through verbatim,
    so a variant differs from the committed request in exactly one field.
    """
    request = json.loads(json.dumps(committed))
    for side in ("layout", "reference"):
        netlist = request.get(side, {}).get("netlist")
        if netlist is not None:
            request[side]["netlist"] = str((record / netlist).resolve())
    if max_attempts is not None:
        request.setdefault("options", {})["combine_devices_max_attempts"] = max_attempts
    path = work / f"lvs.{label}.request.json"
    path.write_text(json.dumps(request, indent=2) + "\n")
    return path


def _run_variant(*, label: str, request_path: Path, trials: int) -> dict[str, Any]:
    from klayout_tools.lvs import LvsError, run_lvs  # noqa: PLC0415

    counts: collections.Counter[int] = collections.Counter()
    statuses: collections.Counter[str] = collections.Counter()
    categories: collections.Counter[str] = collections.Counter()
    # Which devices/parameters the findings land on, tallied across trials.
    # Decisive for telling "the tool mis-combined something" apart from "the
    # layout genuinely disagrees with the reference": a flake confined to one
    # device class, with every other class matched every time, is not a
    # newly-detected layout defect.
    findings: collections.Counter[str] = collections.Counter()
    for _ in range(trials):
        try:
            report = run_lvs(str(request_path))
        except LvsError as exc:
            return {
                "variant": label,
                "supported": False,
                "detail": str(exc),
                "trials": 0,
            }
        counts[report.get("mismatch_count")] += 1
        statuses[str(report.get("status"))] += 1
        for name, n in (report.get("category_counts") or {}).items():
            categories[name] += n
        for mismatch in report.get("mismatches") or []:
            device = mismatch.get("device") or {}
            prop = mismatch.get("property") or {}
            findings[
                "{category}/{cls}/{ref}/{param}".format(
                    category=mismatch.get("category"),
                    cls=device.get("class") or "-",
                    ref=device.get("reference") or "-",
                    param=prop.get("name") or "-",
                )
            ] += 1
    distinct = sorted(counts)
    return {
        "variant": label,
        "supported": True,
        "trials": trials,
        "deterministic": len(distinct) == 1,
        "mismatch_counts": {str(k): counts[k] for k in distinct},
        "statuses": dict(statuses),
        "category_totals": dict(categories),
        "finding_totals": dict(sorted(findings.items())),
        "clean_fraction": counts.get(0, 0) / trials if trials else None,
    }


def _conclusion_lines(payload: dict[str, Any]) -> list[str]:
    """Render the conclusion from THIS run's numbers, not a fixed narrative.

    Same discipline as `measure_fixed_offset_variants.py`: a future re-run
    against a fixed `klt` must not leave a stale "still broken" claim behind,
    so every sentence below is derived from the tallies above it.
    """
    by_label = {row["variant"]: row for row in payload["variants"]}
    committed = by_label.get("as_committed", {})
    pinned = by_label.get("max_attempts_1", {})
    lines: list[str] = []

    if not committed.get("supported"):
        return ["The `as_committed` variant could not run: " + str(committed.get("detail"))]

    if committed.get("deterministic"):
        only = next(iter(committed["mismatch_counts"]))
        lines += [
            f"The committed request is **deterministic** on this build: "
            f"{committed['trials']}/{committed['trials']} trials reported "
            f"`mismatch_count` = {only}. Whatever this record's verdict is, it "
            "is reproducible, and a single run of it is citable evidence.",
        ]
        if not pinned.get("supported"):
            lines += [
                "",
                "The isolating `max_attempts_1` variant was not run on this build: "
                + str(pinned.get("detail"))
                + ".",
            ]
            return lines
        if pinned.get("deterministic") and pinned["mismatch_counts"] == committed["mismatch_counts"]:
            lines += [
                "",
                "`combine_devices_max_attempts: 1` reports the same verdict, so the "
                "`Netlist.dup()`/`Netlist.assign()` round trip klayout-tools#1185's "
                "retry mitigation introduces is not perturbing this compare.",
            ]
        return lines

    clean = committed["clean_fraction"]
    lines += [
        f"The committed request is **not deterministic** on this build: across "
        f"{committed['trials']} repetitions of the *same* request document against "
        f"the *same* committed netlists it reported "
        + ", ".join(
            f"`mismatch_count` = {k} on {v} trials"
            for k, v in committed["mismatch_counts"].items()
        )
        + f" ({clean:.1%} clean). Nothing about the inputs changed between trials.",
        "",
        "A verdict that is only sometimes `match` cannot be cited as signoff "
        "evidence in either direction: the clean runs do not establish that the "
        "layout matches, and the dirty runs do not establish that it does not.",
    ]
    if not pinned.get("supported"):
        lines += [
            "",
            "The isolating `max_attempts_1` variant was not run on this build: "
            + str(pinned.get("detail"))
            + ".",
        ]
        return lines
    if pinned.get("deterministic"):
        only = next(iter(pinned["mismatch_counts"]))
        lines += [
            "",
            f"Setting `options.combine_devices_max_attempts: 1` restores determinism: "
            f"{pinned['trials']}/{pinned['trials']} trials reported `mismatch_count` = "
            f"{only}. A budget of 1 makes the only combine attempt the *last* one, "
            "which klayout-tools#1185's `_combine_devices_safely` runs directly "
            "against the netlist instead of against a `Netlist.dup()` copy adopted "
            "back via `Netlist.assign()`. The variable is therefore that round trip, "
            "not the netlists, the request, or the comparer.",
        ]
    else:
        lines += [
            "",
            "`options.combine_devices_max_attempts: 1` is **also** nondeterministic "
            "here, so the `Netlist.dup()` round trip is not the whole story on this "
            "build -- re-open the investigation rather than assuming the mechanism "
            "recorded in `layout/matching-plan.md` Section 7ff still holds.",
        ]
    return lines


def _render_record(payload: dict[str, Any]) -> str:
    lines = [
        "# `klt lvs` combine-determinism measurement",
        "",
        f"- Record ID: `{payload['record_id']}`",
        f"- Source layout record: `{payload['source_record']}`",
        f"- Request measured: `{payload['request']}` (committed, unmodified)",
        f"- Trials per variant: {payload['trials']}",
        f"- `klt` build measured: `{payload['klt_version'].get('version')}` "
        f"(`git_commit` `{payload['klt_version'].get('git_commit')}`, "
        f"`is_release` `{payload['klt_version'].get('is_release')}`), "
        f"klayout `{payload['klt_version'].get('klayout_version')}`",
        f"- `klayout_tools` imported from: "
        f"`{payload['klt_version'].get('module_location')}`",
        f"- `klayout_tools/lvs.py` `sha256`: "
        f"`{payload['klt_version'].get('lvs_module_sha256')}`"
        + (
            f" (declared as `{payload['klt_version']['declared_ref']}`)"
            if payload["klt_version"].get("declared_ref")
            else ""
        ),
        f"- `layout/requirements.txt` pin: `{payload['klt_pin']}`",
        f"- Repo state: `{payload['repo_sha']}`",
        f"- Host python: `{payload['python_version']}`",
        "",
        "Generated by `layout/bin/measure_combine_devices_determinism.py`. Re-runs",
        "the source record's own committed `klt lvs` request document N times and",
        "tallies the verdict, under two `options.combine_devices_max_attempts`",
        "settings. Nothing here feeds the routed flow's gate.",
        "",
        "| variant | `combine_devices_max_attempts` | deterministic | verdict tally |",
        "| --- | --- | --- | --- |",
    ]
    for row in payload["variants"]:
        budget = "build default" if row["variant"] == "as_committed" else "1"
        if not row["supported"]:
            lines.append(f"| `{row['variant']}` | {budget} | n/a | unsupported by this build |")
            continue
        tally = ", ".join(f"{v}x `{k}`" for k, v in row["mismatch_counts"].items())
        lines.append(
            f"| `{row['variant']}` | {budget} | "
            f"{'**yes**' if row['deterministic'] else '**NO**'} | {tally} |"
        )
    lines += [
        "",
        "`verdict tally` counts trials by the `mismatch_count` they reported.",
        "",
    ]
    findings = {
        row["variant"]: row.get("finding_totals") or {}
        for row in payload["variants"]
        if row.get("supported")
    }
    if any(findings.values()):
        lines += [
            "## Where the findings land",
            "",
            "Summed over all trials, keyed "
            "`<category>/<device class>/<reference device>/<parameter>`. A flake "
            "confined to one device class, with every other class matched on "
            "every trial, is a mis-combine rather than a newly-detected layout "
            "defect.",
            "",
            "| variant | finding | total across trials |",
            "| --- | --- | --- |",
        ]
        for variant, totals in findings.items():
            for key, n in sorted(totals.items()):
                lines.append(f"| `{variant}` | `{key}` | {n} |")
        lines.append("")
    lines += [
        "## Conclusion recorded by this run",
        "",
        *_conclusion_lines(payload),
        "",
        "See `layout/matching-plan.md` Section 7ff for the disposition this",
        "measurement supports, and `signoff/README.md`'s item-4 row for what it",
        "means for the T1 checklist.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", required=True, type=Path, help="layout record directory to read")
    parser.add_argument("--out-dir", required=True, type=Path, help="where to write the evidence record")
    parser.add_argument("--trials", type=int, default=200, help="repetitions per variant (default 200)")
    parser.add_argument("--record-id", default=None)
    parser.add_argument(
        "--build-ref",
        default=None,
        help=(
            "caller-declared name for the klt build being measured (e.g. the "
            "git commit a PYTHONPATH checkout was taken at) -- recorded "
            "verbatim alongside, never instead of, the measured lvs.py sha256"
        ),
    )
    parser.add_argument(
        "--tag",
        default=None,
        help=(
            "suffix for this run's output files (determinism.<tag>.json / "
            "record.<tag>.md), so one evidence directory can hold the same "
            "measurement taken against several klt builds"
        ),
    )
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)

    if args.trials < 1:
        parser.error("--trials must be at least 1")

    record = args.record.resolve()
    request_path = _require(record / REQUEST_NAME, "committed LVS request")
    committed = json.loads(request_path.read_text())

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    record_id = args.record_id or out_dir.name

    repo_root = args.repo_root.resolve()
    repo_sha = git(repo_root, "rev-parse", "HEAD")
    pin_line = ""
    requirements = repo_root / "layout" / "requirements.txt"
    if requirements.is_file():
        for line in requirements.read_text().splitlines():
            if line.strip().startswith("klayout-tools @"):
                pin_line = line.strip()

    supports_budget, budget_detail = _supports_max_attempts()

    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="combine-determinism-") as tmp:
        work = Path(tmp)
        for label, max_attempts in VARIANTS:
            print(
                f"measure_combine_devices_determinism.py: {label} "
                f"({args.trials} trials) ...",
                flush=True,
            )

            if max_attempts is not None and not supports_budget:
                rows.append(
                    {
                        "variant": label,
                        "supported": False,
                        "detail": budget_detail,
                        "trials": 0,
                    }
                )
                continue
            if max_attempts is None:
                # The committed document itself, byte-for-byte -- no copy, no
                # rewritten paths, nothing this harness could have perturbed.
                variant_request = request_path
            else:
                variant_request = _variant_request(committed, record, max_attempts, work, label)
            rows.append(
                _run_variant(label=label, request_path=variant_request, trials=args.trials)
            )

    payload = {
        "schema_version": 1,
        "harness": "layout/bin/measure_combine_devices_determinism.py",
        "record_id": record_id,
        "source_record": str(record.relative_to(repo_root)),
        "request": str(request_path.relative_to(repo_root)),
        "repo_sha": repo_sha,
        "klt_pin": pin_line,
        "klt_version": _klt_identity(repo_root, args.build_ref),
        "python_version": platform.python_version(),
        "tag": args.tag,
        "trials": args.trials,
        "variants": rows,
    }
    suffix = f".{args.tag}" if args.tag else ""
    (out_dir / f"determinism{suffix}.json").write_text(json.dumps(payload, indent=2) + "\n")
    (out_dir / f"record{suffix}.md").write_text(_render_record(payload))
    print(f"measure_combine_devices_determinism.py: wrote {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
