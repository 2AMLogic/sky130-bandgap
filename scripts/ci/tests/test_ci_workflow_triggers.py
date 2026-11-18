#!/usr/bin/env python3
"""Unit coverage for the CI workflow's merge-queue readiness (issue #609).

This repo's required checks (ruleset `required-checks`) are the two contexts
reported by the `checks` and `signoff` jobs of .github/workflows/ci.yml. When
the repo joins a merge queue, GitHub fires `merge_group` (`checks_requested`)
events instead of `pull_request` ones -- so the workflow must declare the
`merge_group` trigger, and every required job must run on it. The failure
mode the queue punishes hardest is silent: a job whose `if:` evaluates false
on a merge_group run is *skipped*, and a skipped required check can stall or
wedge the queue entry rather than fail it loudly.

What this file pins against the committed workflow:

  1. `merge_group` is declared as a trigger, unfiltered (no branches/paths/
     types) -- without it the operator's `repo-ruleset-policy.py
     --merge-queue-repo` verdict stays `queue=REFUSED`.
  2. `checks` and `signoff` carry no job-level `if:` at all, so nothing can
     evaluate false on a queue entry.
  3. `pdk-smoke` keeps its opt-in `if:` and that expression never admits a
     merge_group event: the job is nightly/dispatch/label-gated by design and
     pulls a ~1 GB PDK, which must not run on every queue entry (issue #609).

The workflow is parsed with a small indentation walker (stdlib only -- CI
installs no PyYAML). Every invariant lives in one function,
`assert_merge_queue_ready(text)`, so the negative controls below can feed it
mutated copies of the real workflow and watch it fail: the committed repo
state never exhibits these regressions, so -- as in test_check_signoff_pins.py
-- the cases that prove the guard works cannot live in the repo's own files.

Run directly (`python3 scripts/ci/tests/test_ci_workflow_triggers.py`) or via
`npm run test:unit`.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# The jobs whose contexts the repo's ruleset marks required (issue #609).
REQUIRED_QUEUE_JOBS = ("checks", "signoff")

# pdk-smoke is opt-in by design; its `if:` must never admit a queue entry.
OPT_IN_JOB = "pdk-smoke"


def _section_lines(text: str, key: str) -> list[tuple[int, str]]:
    """Return (indent, stripped content) for each non-blank, non-comment line
    inside the body of a top-level `key:` block, in file order. The walk stops
    at the next zero-indent line (the next top-level key)."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(rf"^{re.escape(key)}:\s*(#.*)?$", line):
            start = i + 1
            break
    assert start is not None, f"no top-level `{key}:` block found"
    body: list[tuple[int, str]] = []
    for line in lines[start:]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            break
        body.append((indent, line.strip()))
    return body


def triggers(text: str) -> dict[str, list[str]]:
    """Map each `on:` trigger to its child lines (empty list = bare trigger)."""
    result: dict[str, list[str]] = {}
    current: str | None = None
    for indent, content in _section_lines(text, "on"):
        if indent <= 2:
            current = content.partition(":")[0].strip()
            result[current] = []
        elif current is not None:
            result[current].append(content)
    return result


def job_ifs(text: str) -> dict[str, str | None]:
    """Map each top-level job key to its job-level `if:` expression.

    Block scalars (`if: >-`) are folded with their continuation lines. `None`
    means the job has no `if:` at all.
    """
    result: dict[str, str | None] = {}
    current: str | None = None
    in_if = False
    for indent, content in _section_lines(text, "jobs"):
        if indent <= 2:
            current = content.rstrip(":").strip()
            result[current] = None
            in_if = False
        elif indent == 4 and current is not None:
            if content.startswith("if:"):
                result[current] = content.partition(":")[2].strip()
                in_if = True
            else:
                in_if = False
        elif indent > 4 and current is not None and in_if:
            result[current] += "\n" + content
    return result


def assert_merge_queue_ready(text: str) -> None:
    """Raise AssertionError unless the workflow text is merge-queue ready."""
    trig = triggers(text)
    assert "merge_group" in trig, (
        "ci.yml must declare the merge_group trigger: GitHub's merge queue "
        "fires merge_group (checks_requested) events, and without the "
        "trigger the queue has no checks to await "
        "(repo-ruleset-policy.py: queue=REFUSED ... no merge_group; "
        "issue #609)"
    )
    assert trig["merge_group"] == [], (
        "merge_group must stay unfiltered (no branches/paths/types): the "
        "queue's entries must reach every required job (issue #609)"
    )
    jobs = job_ifs(text)
    for job in REQUIRED_QUEUE_JOBS:
        assert job in jobs, f"required job `{job}` missing from ci.yml"
        assert jobs[job] is None, (
            f"required job `{job}` must not carry a job-level `if:`: one "
            "that evaluates false on a merge_group run would silently drop "
            "the required check, not pass it (issue #609)"
        )
    opt_in_if = jobs.get(OPT_IN_JOB)
    assert opt_in_if, (
        f"`{OPT_IN_JOB}` must keep its opt-in `if:`; without one it would "
        "run on every merge_group entry (issue #609)"
    )
    assert "merge_group" not in opt_in_if, (
        f"`{OPT_IN_JOB}` must stay opt-in (nightly/dispatch/label only): "
        "admitting merge_group would run its ~1 GB PDK job on every queue "
        "entry (issue #609)"
    )


class MergeQueueReadinessTest(unittest.TestCase):
    """Committed state passes; mutated regressions fail (issue #609)."""

    def setUp(self) -> None:
        self.workflow = WORKFLOW_PATH.read_text()

    def test_committed_workflow_is_merge_queue_ready(self) -> None:
        assert_merge_queue_ready(self.workflow)

    def test_removing_merge_group_trigger_fails(self) -> None:
        text = re.sub(r"(?m)^  merge_group:\n", "", self.workflow)
        self.assertNotEqual(text, self.workflow, "mutation removed nothing")
        with self.assertRaises(AssertionError):
            assert_merge_queue_ready(text)

    def test_filtering_merge_group_trigger_fails(self) -> None:
        text = self.workflow.replace(
            "  merge_group:\n",
            "  merge_group:\n    branches: [main]\n",
        )
        self.assertNotEqual(text, self.workflow, "mutation changed nothing")
        with self.assertRaises(AssertionError):
            assert_merge_queue_ready(text)

    def test_if_on_required_job_fails(self) -> None:
        text = self.workflow.replace(
            "jobs:\n"
            "  checks:\n"
            "    name: Repo checks (headless, no PDK)\n",
            "jobs:\n"
            "  checks:\n"
            "    name: Repo checks (headless, no PDK)\n"
            "    if: github.event_name == 'pull_request'\n",
        )
        self.assertNotEqual(text, self.workflow, "mutation changed nothing")
        with self.assertRaises(AssertionError):
            assert_merge_queue_ready(text)

    def test_pdk_smoke_if_admitting_merge_group_fails(self) -> None:
        text = self.workflow.replace(
            "github.event_name == 'schedule' ||",
            "github.event_name == 'merge_group' ||\n"
            "      github.event_name == 'schedule' ||",
        )
        self.assertNotEqual(text, self.workflow, "mutation changed nothing")
        with self.assertRaises(AssertionError):
            assert_merge_queue_ready(text)

    def test_removing_pdk_smoke_if_fails(self) -> None:
        text = re.sub(
            r"(?m)^    if: >-\n"
            r"(^      .*\n)+",
            "",
            self.workflow,
            count=1,
        )
        self.assertNotEqual(text, self.workflow, "mutation changed nothing")
        with self.assertRaises(AssertionError):
            assert_merge_queue_ready(text)


if __name__ == "__main__":
    unittest.main()
