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

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#335**: Produce native klt pex comparison evidence for T1 item 7

## In Progress

Issues currently being built (`loom:building`).

- **#332**: Guard decision review: Review historical variable resolution for scoped scratch writes
- **#476**: publish_corner_evidence: skip staged files whose bytes are already tracked in git

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#477**: docs: add inert guard replay report and script for write-confinement review

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

_None._

## Proposed

Issues carrying `loom:curated`.

- **#306**: Reduce the startup injector's supply-dependent GDRV load so PSRR clears DR-006's 60 dB floor (design cause confirmed by #300) *(curated)*
- **#315**: Complete #306's circuit fix (startup injector PSRR) and the post-fix layout cycle *(curated)*
- **#332**: Guard decision review: Review historical variable resolution for scoped scratch writes *(curated)*
- **#335**: Produce native klt pex comparison evidence for T1 item 7 *(curated)*
- **#368**: Design a state-dependent startup-injector reference-stack element that clears the 60 dB PSRR floor at ff/125/3.63 and sf/27/2.97 *(curated)*
- **#395**: Enable --backend batch for remaining pre-layout corner-run benches (prereq of #370) *(curated)*
- **#432**: Follow-on from PR #431: first live routed-flow run with artifact broker *(curated)*
- **#435**: T1 item 6 (Monte Carlo): mint a sufficiently sized untrimmed-Vref klt yield campaign with a declared negative control *(curated)*
- **#444**: monte-carlo-untrimmed: real-fleet smoke run of --backend batch (AC4 of #437) *(curated)*
- **#476**: publish_corner_evidence: skip staged files whose bytes are already tracked in git *(curated)*

## Proposed (Architect / Hermit)

_None._

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 0 |
| Important | 2 |
| Ready (`loom:issue`) | 1 |
| In Progress (`loom:building`) | 2 |
| PRs awaiting review | 1 |
| Approved PRs awaiting merge | 0 |
| Curated | 10 |
| Architect / Hermit proposals | 0 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
