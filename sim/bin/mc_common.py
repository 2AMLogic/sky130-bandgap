#!/usr/bin/env python3
"""Shared orchestration and record-rendering helpers for the Monte Carlo
mismatch runners (`sim/error-amp-offset-mc/run_amp_offset_mc.py`,
`sim/monte-carlo-untrimmed/run_mc_untrimmed.py`, and — for `## Checks` and the
record footer — `sim/pnp-mismatch/run_pnp_mismatch.py`) (issue #722).

Follows `sim/bin/sim_common.py`'s sibling-module rule for bench families
(alongside `post_layout_common.py` and `injector_common.py`). What stays
per-bench, deliberately: `build_points()`, `build_deck()`,
`build_batch_groups()`, `collect_batch()`, `evaluate()`, bench-specific record
tables/prose, `run_mc_untrimmed.py`'s `klt_yield_links` merge and
`render_klt_yield_section()`, and `run_pnp_mismatch.py`'s local-only runner
loop.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path

import batch_sim  # noqa: E402  (importers put sim/bin on sys.path first)
from sim_common import (  # noqa: E402
    REPO_DIR,
    SPICEINIT_FILE,
    _cr,
    parse_samples as _default_parse_samples,
    partition_by_window,
    publish_run_evidence,
    run_ngspice,
)


def _display_path(path: Path) -> Path:
    try:
        return path.relative_to(REPO_DIR)
    except ValueError:
        return path


def handle_mc_dry_run(
    args,
    *,
    slug: str,
    pin,
    pdk,
    body,
    points,
    build_dir: Path,
    build_batch_groups,
    build_deck,
    control_block,
    deck_head_lines: int,
) -> bool:
    """Handle `--dry-run` for a batch-capable Monte Carlo runner.

    Returns `True` when `args.dry_run` is set (caller should `return 0`) and
    `False` otherwise. Batch dry runs build the `klt sim` requests and print
    through `batch_sim.print_mc_batch_dry_run()`; local dry runs print the
    first `deck_head_lines` lines of `points[0]`'s deck plus its control block.
    """
    if not args.dry_run:
        return False
    if args.backend == "batch":
        groups = build_batch_groups(
            pin, body, points, SPICEINIT_FILE.read_text(), build_dir / "batch", args
        )
        batch_sim.print_mc_batch_dry_run(groups, slug)
        return True
    print("\n-- deck head + control block for the first point --")
    deck = build_deck(pdk, points[0], body)
    print("\n".join(deck.splitlines()[:deck_head_lines]))
    print("...")
    print(control_block(points[0]))
    print(f"(dry run: nothing written under sim/{slug}/)")
    return True


def run_local_mc_point(
    point,
    *,
    pdk,
    body,
    build_dir: Path,
    corners_dir: Path,
    record_id: str,
    stamp,
    timeout: int,
    build_deck,
    write_log,
) -> tuple[str, int, bool, Path]:
    """Build one local MC deck, run ngspice, write its corner log, and return
    `(raw, rc, timed_out, log_path)`."""
    run_dir = build_dir / record_id / point.corner_id
    deck = build_deck(pdk, point, body)
    raw, rc, timed_out = run_ngspice(run_dir, point.corner_id, deck, timeout)
    log_path = write_log(corners_dir, point, pdk, record_id, stamp, deck, raw, rc, timed_out)
    return raw, rc, timed_out, log_path


def collect_operating_samples(
    points,
    *,
    batch: bool,
    collect_batch,
    run_local_point,
    vectors,
    operating_window: tuple[float, float],
    parse_samples=_default_parse_samples,
    enrich=None,
) -> tuple[dict | None, Iterator[tuple[int, object, list[dict[str, float]], list[dict[str, float]]]]]:
    """Run or collect every MC point and yield `(index, point, samples, excluded)`.

    Returns `(execution, point_iter)`: batch collection runs immediately so its
    `execution` block is available up front, while local points execute lazily
    as the caller iterates and prints per-point progress.
    """
    cr = _cr()
    execution: dict | None = None
    batch_parsed: dict[str, list] = {}
    if batch:
        batch_parsed, execution = collect_batch()

    def _iter_points():
        for i, point in enumerate(points, start=1):
            if batch:
                parsed = batch_parsed[point.corner_id]
            else:
                raw, rc, timed_out, log_path = run_local_point(point)
                if rc != 0 or timed_out:
                    raise cr.HarnessError(
                        f"ngspice exit {rc}{' (timeout)' if timed_out else ''} for "
                        f"{point.corner_id}; see {_display_path(log_path)}"
                    )
                parsed = parse_samples(raw, vectors)
            if enrich is not None:
                enrich(parsed)
            if not parsed:
                raise cr.HarnessError(
                    f"no Monte Carlo samples parsed for {point.corner_id} — see the log"
                )
            samples, excluded = partition_by_window(parsed, "vout", operating_window)
            if len(samples) < 2:
                raise cr.HarnessError(
                    f"only {len(samples)} of {len(parsed)} draws for {point.corner_id} "
                    f"converged to the operating solution — nothing to compute a sigma from; "
                    f"see the log"
                )
            yield i, point, samples, excluded

    return execution, _iter_points()


def write_mc_record(
    record: dict,
    *,
    render_record,
    corners_dir: Path,
    records_dir: Path,
    record_json: Path,
    record_md: Path,
    overall: bool,
) -> int:
    """Publish raw evidence, write the JSON + Markdown record pair, print their
    paths, and return the CLI exit code (0 PASS / 2 FAIL)."""
    publish_run_evidence(corners_dir)
    records_dir.mkdir(parents=True, exist_ok=True)
    record_json.write_text(json.dumps(record, indent=2) + "\n")
    record_md.write_text(render_record(record))
    print(f"\nrecord: {_display_path(record_md)}")
    print(f"        {_display_path(record_json)}")
    return 0 if overall else 2


def run_cli(main_fn, argv: list[str] | None = None) -> None:
    """Invoke a Monte Carlo runner's `main(argv)`, translating `HarnessError`
    into `error: <msg>` on stderr and exit code 1."""
    cr = _cr()
    try:
        sys.exit(main_fn(sys.argv[1:] if argv is None else argv))
    except cr.HarnessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


def render_mc_checks(r: dict, *, point_label=None) -> list[str]:
    """Render the shared `## Checks` section for a Monte Carlo record.

    `point_label(p)`, if given, formats the parenthetical label after
    `` `{p['corner_id']}` ``; the default is `p['role']` (used by
    `run_amp_offset_mc.py` and `run_pnp_mismatch.py`), while
    `run_mc_untrimmed.py` appends its `config` axis.
    """
    lines = ["## Checks", ""]
    for p in r["points"]:
        label = p["role"] if point_label is None else point_label(p)
        lines.append(f"- `{p['corner_id']}` ({label}): **{'PASS' if p['pass'] else 'FAIL'}**")
        for c in p["checks"]:
            lines.append(
                f"  - {'PASS' if c['pass'] else 'FAIL'} `{c['name']}` — {c['detail']}"
            )
    for c in r["cross_point_checks"]:
        lines.append(
            f"- {'PASS' if c['pass'] else 'FAIL'} `{c['name']}` — {c['detail']}"
        )
    lines.append(f"- **Overall: {'PASS' if r['overall_pass'] else 'FAIL'}**")
    lines.append("")
    return lines


def render_mc_footer(
    r: dict, *, links: dict[str, str] | None = None, runner_path: str
) -> list[str]:
    """Render the shared `- **Links**:` / timestamp / supersedes / append-only
    footer for a Monte Carlo record.

    `links`, when passed, overrides `r["links"]` (used by `run_mc_untrimmed.py`
    after merging its dynamic `klt_yield_links`).
    """
    link_map = r["links"] if links is None else links
    lines = ["- **Links**:"]
    for key, value in link_map.items():
        lines.append(f"  - {key}: `{value}`")
    lines.append(f"- **Timestamp / author**: {r['timestamp']}, {r['author']}")
    supersedes = r["supersedes"] or "(none — first record for this claim)"
    lines.append(f"- **Supersedes**: {supersedes}")
    lines.append("")
    lines.append(
        f"Written by `{runner_path}`. Append-only: never edit this "
        "file — a correction is a new record with a `Supersedes` field (see "
        "`sim/README.md`)."
    )
    lines.append("")
    return lines
