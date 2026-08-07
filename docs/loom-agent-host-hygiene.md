# Loom agent-host hygiene: keep the dispatch checkout current

Operational note for this repo's Loom automation. Nothing here is
design/spec content — it is about the *hosts* that run Loom agents.

**One-line rule:** the checkout a Loom agent host dispatches from **is** the
agent's role definition and toolbox. If that checkout is behind
`origin/main`, every agent it dispatches runs the older rules, silently and
indefinitely. Restarting the agent does not help; only advancing the
checkout does.

This document exists because that failure actually happened here — see the
worked example below.

## Why this doc lives in `docs/` and not `.loom/docs/`

`.loom/docs/`, `.loom/scripts/`, and `.claude/commands/loom/` in this
repository are **machine-managed installed surfaces**. Every change they have
ever received arrived through a Loom install/upgrade commit
(`8acbbb2`, `bf21f3b`, `496ab43`, `1b62544`) which rewrites them wholesale
from upstream. A repo-local edit there is silently overwritten at the next
Loom upgrade.

So the durable copy of this finding lives here, under repo-owned `docs/`.
`.loom/docs/troubleshooting.md` carries a shorter operator-facing version
(that is where an operator will grep first), and points back here.

## Detection

Run this on any host that dispatches Loom agents, from the workspace the
daemon is configured against:

```sh
git -C <workspace> fetch origin main -q
git -C <workspace> rev-list --left-right --count HEAD...origin/main
# left = local-only commits, right = commits the host has NOT got
```

Anything nonzero on the right means agents on that host are running stale
role prompts. Two spot checks that turn "stale" into "stale in a way that
matters":

```sh
# Does the role prompt the agent will actually read know about the guard?
grep -c judge-fallback-guard <workspace>/.claude/commands/loom/judge.md

# Is the guard script the prompt calls even installed?
ls <workspace>/.loom/scripts/judge-fallback-guard.sh
```

A `0` / `No such file` from a host that is behind `origin/main` is the
signature described below.

## Remedy

Advance the checkout, then re-run the Loom install if the upgrade touched
installed surfaces:

```sh
git -C <workspace> pull --ff-only origin main
```

Restarting the daemon or the agent session is **not** the fix on its own.
Loom's slash commands are read from disk at dispatch time — a fresh session
on a stale checkout reads exactly the same stale prompt. (There is no
user-scope override on this host: `~/.claude/commands/loom/` does not exist,
so `/loom:<role>` resolves to the workspace copy.) Restart only *after* the
checkout has moved.

## Worked example: 9 duplicate fallback reviews on PR #114 (issue #117)

**Symptom.** PR #114 carries no `loom:` labels, so every Judge tick fell
through to the fallback (unlabeled-PR) queue and re-reviewed it. Between
2026-08-07T02:15Z and 08:15Z it collected **10 fallback-mode review
comments** for a single unchanged head SHA
(`93b9caed99890506937b52110b57e0827dc50e56`), each re-deriving the same
verdict.

This looks like a missing idempotency check, and issue #117 was originally
filed as one. It is not. The idempotency mechanism already existed:
`.loom/scripts/judge-fallback-guard.sh` implements bot-author skip, a
per-PR-lifetime marker cap, and exactly the SHA dedup that was "missing".

**Root cause.** The daemon host dispatching `/loom:judge` was running a
checkout 33 commits behind `origin/main`:

| Fact | Value |
|---|---|
| Host checkout last advanced | 2026-08-04T02:50Z (`348c178`, per `git reflog show main`) |
| Guard script landed on `origin/main` | 2026-08-06T05:04Z (`1b62544`) |
| Incident window | 2026-08-07T02:15Z – 08:15Z |
| `judge-fallback-guard.sh` present on host | no — absent from the worktree *and* from local `HEAD` |
| `judge.md` mentions of the guard on host | 0 |

The host's `.claude/commands/loom/judge.md` (mtime 2026-08-04T21:16Z) still
carried the pre-guard fallback-queue decision tree, whose only instruction
for an unlabeled PR is *"Found? → Evaluate but leave labels unchanged"* —
no dedup gate, no marker, no guard invocation. Every Judge dispatched on
that host followed those instructions correctly. The duplication was
faithful execution of stale rules, not a Judge malfunction.

**This is install lag, not session lag.** The distinction matters for the
remedy. The stale content was on disk, not merely cached in a long-lived
session's context. "Restart the agent" would have fixed nothing.

**Corroboration — two populations, one PR.** The one comment out of ten that
carried the canonical `<!-- loom:fallback-evaluated sha=… -->` marker was
authored by `loom-fleet-dispatch` (02:47:52Z), a different host/credential.
The other nine were authored by `rjwalters`, which is the `gh` identity
configured on the stale host (`gh auth status` → `rjwalters`, single config
at `~/.config/gh`). The guard-aware host emitted the marker; the stale host
did not.

**Corroboration — dispatch/comment correlation.** `.loom/logs/role-judge.log`
records 13 `loom-daemon role_runner … role=judge` dispatches on 2026-08-07,
each running `claude -p /loom:judge` with
`Workspace: /home/ubuntu/GitHub/sky130-bandgap` (the stale checkout). Each
`rjwalters` comment lands 1–3 minutes after a dispatch:

| Judge dispatch | Comment |
|---|---|
| 02:12:51 | 02:15:51 |
| 03:33:14 | 03:34:40 |
| 06:24:25 | 06:25:16 |
| 06:38:35 | 06:41:12 |
| 06:56:36 | 06:57:54 |
| 07:11:56 | 07:15:16 |
| 07:33:01 | 07:34:13 |
| 08:12:05 | 08:15:21 |

So these were formal `/loom:judge` dispatches, not ad hoc chat reviews. The
"maybe it was never the skill path" explanation is ruled out by the logs.

**Confirmation that the guard would have worked.** Run today from a
guard-aware checkout, against PR #114's real, unmodified comment history:

```
$ ./.loom/scripts/judge-fallback-guard.sh 114
DECISION=SKIP
REASON=already evaluated in fallback mode at current head SHA (no new commits)
HEAD_SHA=93b9caed99890506937b52110b57e0827dc50e56
MARKER_COUNT=1
VELOCITY_ALERT=0
VELOCITY_COUNT=0
$ echo $?
12
```

`MARKER_COUNT=1` also confirms the marker regex is correctly strict: four of
the comments carry a prose-only variant
(`<!-- Evaluated in fallback mode: PR carries no loom: labels, so no label
changes were made. -->`, no `sha=`), and none of them were counted. That
strictness is pinned by cases `(k)`/`(k2)` in
`.loom/scripts/tests/test-judge-fallback-cap.sh`.

## Takeaways

1. **Check host freshness before blaming agent logic.** A repeated,
   identical agent behaviour across many ticks is more often a stale role
   prompt than a reasoning failure. Check `rev-list --count HEAD...origin/main`
   first.
2. **A deterministic guard script only helps hosts that have it.** Moving a
   decision out of prose and into a script (as `judge-fallback-guard.sh`
   does) removes the "did the model re-derive the bash correctly" failure
   mode, but it cannot remove the "is the script installed here" one.
3. **Comment-author identity is a useful forensic axis.** When one Loom
   comment on a PR follows a convention and the rest do not, compare the
   authoring credentials — differing `gh` identities usually mean differing
   hosts, and therefore differing install states.
