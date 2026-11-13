# Work Plan

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

_None._

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

_None._

## Important

`loom:important`; taken before unlabelled work.

- **#315**: Complete #306's circuit fix (startup injector PSRR) and the post-fix layout cycle
- **#368**: Design a state-dependent startup-injector reference-stack element that clears the 60 dB PSRR floor at ff/125/3.63 and sf/27/2.97
- **#435**: T1 item 6 (Monte Carlo): mint a sufficiently sized untrimmed-Vref klt yield campaign with a declared negative control
- **#444**: monte-carlo-untrimmed: real-fleet smoke run of --backend batch (AC4 of #437)

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#370**: Re-qualify reference records under open_pdks f6eeac7 (follow-up to #369)

## In Progress

Issues currently being built (`loom:building`).

_None._

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#509**: sim: record level-flag injector fails startup-stability standing current; latched revision loses eviction (DR-022)

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

_None._

## Proposed

Issues carrying `loom:curated`.

- **#306**: Reduce the startup injector's supply-dependent GDRV load so PSRR clears DR-006's 60 dB floor (design cause confirmed by #300) *(curated)*
- **#315**: Complete #306's circuit fix (startup injector PSRR) and the post-fix layout cycle *(curated)*
- **#368**: Design a state-dependent startup-injector reference-stack element that clears the 60 dB PSRR floor at ff/125/3.63 and sf/27/2.97 *(curated)*
- **#370**: Re-qualify reference records under open_pdks f6eeac7 (follow-up to #369) *(curated)*
- **#432**: Follow-on from PR #431: first live routed-flow run with artifact broker *(curated)*
- **#435**: T1 item 6 (Monte Carlo): mint a sufficiently sized untrimmed-Vref klt yield campaign with a declared negative control *(curated)*
- **#444**: monte-carlo-untrimmed: real-fleet smoke run of --backend batch (AC4 of #437) *(curated)*

## Proposed (Architect / Hermit)

- **#499**: Condense layout/matching-plan.md Section 7: ~3,500 lines of per-increment changelog *(hermit)*
- **#517**: Shrink layout/bin/met2_drc.py to its orphan-via check: pinned klt 0.8.0 already checks the met2/via rules it duplicates *(hermit)*
- **#522**: Dedup collect_batch/record_tools/samples_path between the two Monte Carlo runners into batch_sim *(hermit)*
- **#525**: Dedup run_trim_lsb_chained.py's hand-rolled batch request onto batch_sim.build_adhoc_group (drifted: no remote.hosts, no ngspice_init) *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 0 |
| Important | 4 |
| Ready (`loom:issue`) | 1 |
| In Progress (`loom:building`) | 0 |
| PRs awaiting review | 1 |
| Approved PRs awaiting merge | 0 |
| Curated | 7 |
| Architect / Hermit proposals | 4 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
