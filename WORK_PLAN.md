# Work Plan

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#373**: build(sim): re-pin PDK to open_pdks f6eeac7 via ciel with SOURCES revision check
- **#390**: feat(signoff): attest T1 items 1, 2, 9, 10 on klt 0.7.0

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

_None._

## Important

`loom:important`; taken before unlabelled work.

- **#315**: Complete #306's circuit fix (startup injector PSRR) and the post-fix layout cycle
- **#368**: Design a state-dependent startup-injector reference-stack element that clears the 60 dB PSRR floor at ff/125/3.63 and sf/27/2.97

## Ready

Human-approved issues ready for implementation (`loom:issue`).

_None._

## In Progress

Issues currently being built (`loom:building`).

- **#369**: Re-pin open_pdks to f6eeac7 (ciel) — fleet retires volare c6d73a3
- **#381**: Prune 12 unreferenced trivial-cell report runs; fix stale README pointer
- **#387**: T1 items 1, 2, 9, 10: move the grader to klt 0.7.0 and cite artifact-anchored inventory envelopes

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#373**: build(sim): re-pin PDK to open_pdks f6eeac7 via ciel with SOURCES revision check
- **#390**: feat(signoff): attest T1 items 1, 2, 9, 10 on klt 0.7.0
- **#392**: chore(layout): prune 8 redundant trivial-cell report runs, fix README current-record pointer

## Proposed

Issues carrying `loom:curated`.

- **#306**: Reduce the startup injector's supply-dependent GDRV load so PSRR clears DR-006's 60 dB floor (design cause confirmed by #300) *(curated)*
- **#315**: Complete #306's circuit fix (startup injector PSRR) and the post-fix layout cycle *(curated)*
- **#368**: Design a state-dependent startup-injector reference-stack element that clears the 60 dB PSRR floor at ff/125/3.63 and sf/27/2.97 *(curated)*
- **#369**: Re-pin open_pdks to f6eeac7 (ciel) — fleet retires volare c6d73a3 *(curated)*
- **#387**: T1 items 1, 2, 9, 10: move the grader to klt 0.7.0 and cite artifact-anchored inventory envelopes *(curated)*
- **#388**: T1 item 4: mint a hash-pinned LVS report now that klayout-tools#2374 is fixed, with a determinism re-measure *(curated)*

## Proposed (Architect / Hermit)

- **#335**: Produce native klt pex comparison evidence for T1 item 7 *(architect)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 2 |
| Very important | 0 |
| Important | 2 |
| Ready (`loom:issue`) | 0 |
| In Progress (`loom:building`) | 3 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 3 |
| Curated | 6 |
| Architect / Hermit proposals | 1 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
