#!/usr/bin/env python3
"""Re-grade the committed klt signoff block manifest and require the report to match.

This is the "CI re-runs it, so a manifest citing an artifact that has since
changed fails rather than rotting" half of issue #282's acceptance criteria.
signoff/signoff-report.json is the verdict of record; this check re-runs
`klt signoff --manifest signoff/block-manifest.json --tiers-doc
signoff/design-evidence-tiers.md --format json` with the same pinned
released klt (see signoff/regenerate.sh for why the distribution identity
matters) and requires byte-identical output. Any drift fails loudly:

  - a cited artifact whose committed content changed (layout GDS/DRC report,
    characterization report) changes a pinned content_hash check from `met`
    to `stale_evidence`,
  - a manifest/vendored-checklist edit changes rows or `source_doc` pins,
  - a grading-klt change renders differently under the same manifest.

The fix for any of those is the same one-liner: ./signoff/regenerate.sh
(then commit the refreshed report -- that is the ceremony that keeps the
mechanical verdict honest instead of hand-patched).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "signoff" / "block-manifest.json"
TIERS_DOC = REPO_ROOT / "signoff" / "design-evidence-tiers.md"
COMMITTED_REPORT = REPO_ROOT / "signoff" / "signoff-report.json"

# Keep in sync with signoff/regenerate.sh's KLT_VERSION and the `signoff`
# CI job's pip install line in .github/workflows/ci.yml.
KLT_VERSION = "0.6.0"

RENDRABLE_EXIT_CODES = {0, 3}  # 0 = tier T1; 3 = rendered, >=1 unmet item

FATAL = "\033[31m"
RESET = "\033[0m"


def fail(message: str) -> None:
    print(f"{FATAL}FATAL:{RESET} {message}", file=sys.stderr)
    sys.exit(1)


def assert_grading_build() -> None:
    """The grading klt must be the pinned *released* registry wheel.

    Same version string, different code, is a real hazard here: git-snapshot
    and full-checkout installs under the same version name can grade this
    checklist differently (observed live across the fleet for 0.5.0 -- see
    signoff/regenerate.sh). The released wheel reports the git tag it was
    built from; assert it.
    """
    run = subprocess.run(
        ["klt", "version", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if run.returncode != 0:
        fail(f"klt version exited {run.returncode}: {run.stderr.strip()}")
    info = json.loads(run.stdout)
    expected_tag = f"v{KLT_VERSION}"
    if (
        info.get("package_version") != KLT_VERSION
        or info.get("git_tag") != expected_tag
        or info.get("is_release") is not True
    ):
        fail(
            "the klt on PATH is not the pinned released grader "
            f"(expected package_version={KLT_VERSION}, git_tag={expected_tag}, "
            "is_release=true; got "
            f"package_version={info.get('package_version')}, "
            f"git_tag={info.get('git_tag')}, "
            f"is_release={info.get('is_release')}). A same-version snapshot "
            "or full-checkout install grades this checklist differently -- "
            "pip install klayout-tools==" + KLT_VERSION
        )


def render_fresh_report() -> str:
    # Repo-relative path strings, exactly as signoff/regenerate.sh passes
    # them: the report echoes the --tiers-doc path into `source_doc`, so an
    # absolute path here would make the fresh output differ from the
    # committed report on every machine.
    run = subprocess.run(
        [
            "klt",
            "signoff",
            "--manifest",
            MANIFEST.relative_to(REPO_ROOT).as_posix(),
            "--tiers-doc",
            TIERS_DOC.relative_to(REPO_ROOT).as_posix(),
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if run.returncode not in RENDRABLE_EXIT_CODES:
        detail = (run.stderr.strip() or run.stdout.strip())[:500]
        fail(
            f"klt signoff exited {run.returncode} -- not a rendered tier "
            f"report: {detail}"
        )
    return run.stdout


def summarize_item_differences(committed_text: str, fresh_text: str) -> str:
    """A compact per-item diff when both sides parse as JSON but differ."""
    try:
        committed = json.loads(committed_text)
        fresh = json.loads(fresh_text)
    except json.JSONDecodeError:
        return "reports differ and at least one side is not valid JSON"
    lines = []
    if committed.get("t1_met_count") != fresh.get("t1_met_count"):
        lines.append(
            f"T1 met count: committed {committed.get('t1_met_count')}"
            f" -> fresh {fresh.get('t1_met_count')}"
        )
    fresh_items = {
        (i.get("tier"), i.get("id"), i.get("title")): i
        for i in fresh.get("items", [])
    }
    committed_items = {
        (i.get("tier"), i.get("id"), i.get("title")): i
        for i in committed.get("items", [])
    }
    for key in sorted(
        set(fresh_items) | set(committed_items),
        key=lambda k: (str(k[0]), -1 if k[1] is None else k[1]),
    ):
        old = committed_items.get(key)
        new = fresh_items.get(key)
        if old == new:
            continue
        where = f"{key[0]} item {key[1]}" if key[1] is not None else f"{key[0]}"
        if old is None:
            lines.append(f"{where} ({key[2]}): missing from committed report")
        elif new is None:
            lines.append(f"{where} ({key[2]}): missing from fresh report")
        elif old.get("status") != new.get("status"):
            lines.append(
                f"{where} ({key[2]}): status "
                f"{old.get('status')}/{old.get('reason')} -> "
                f"{new.get('status')}/{new.get('reason')}"
            )
        else:
            lines.append(f"{where} ({key[2]}): same verdict, citation drifted")
    return "\n".join(f"  - {line}" for line in lines) or "  - byte drift only"


def main() -> None:
    for path in (MANIFEST, TIERS_DOC, COMMITTED_REPORT):
        if not path.is_file():
            fail(f"missing {path.relative_to(REPO_ROOT)}")
    assert_grading_build()

    fresh_text = render_fresh_report()
    committed_text = COMMITTED_REPORT.read_text()

    if fresh_text == committed_text:
        report = json.loads(fresh_text)
        print(
            "signoff report fresh: "
            f"{report['block']} kind={report['kind']} "
            f"T1 {report['t1_met_count']}/{report['t1_item_count']} items met, "
            "byte-identical to signoff/signoff-report.json"
        )
        return

    print(
        f"{FATAL}signoff report is stale:{RESET} re-grading "
        f"{MANIFEST.relative_to(REPO_ROOT)} does not reproduce the committed "
        f"{COMMITTED_REPORT.relative_to(REPO_ROOT)}.",
        file=sys.stderr,
    )
    print(summarize_item_differences(committed_text, fresh_text), file=sys.stderr)
    print(
        "\nA cited artifact, the manifest, the vendored checklist, or the "
        "grading klt changed since the report was committed.",
        file=sys.stderr,
    )
    print(
        "Regenerate and commit the verdict of record:  ./signoff/regenerate.sh",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
