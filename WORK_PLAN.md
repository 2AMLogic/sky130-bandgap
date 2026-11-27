# Work Plan

<!-- guide:plan-body:start -->
_Generated: 2026-11-26T15:36:29Z (snapshot; compare against live labels)_
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

_None._

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

- **#621**: Re-extract and rerun the seven post-layout benches on the verified thick-oxide GDS *(held)*

## Important

`loom:important`; taken before unlabelled work.

- **#306**: Reduce the startup injector's supply-dependent GDRV load so PSRR clears DR-006's 60 dB floor (design cause confirmed by #300) *(held)*
- **#315**: Complete #306's circuit fix (startup injector PSRR) and the post-fix layout cycle *(held)*
- **#368**: Design a state-dependent startup-injector reference-stack element that clears the 60 dB PSRR floor at ff/125/3.63 and sf/27/2.97 *(held)*
- **#435**: T1 item 6 (Monte Carlo): mint a sufficiently sized untrimmed-Vref klt yield campaign with a declared negative control *(held)*
- **#444**: monte-carlo-untrimmed: real-fleet smoke run of --backend batch (AC4 of #437) *(held)*

## Ready

Human-approved issues (`loom:issue`) ready for implementation — excluding held (`loom:blocked`/`loom:operator`/`loom:frozen`), `loom:building`, and issues closed by an open `loom:pr` PR (listed under Approved).

_None._

## In Progress

Issues currently being built (`loom:building`).

- **#691**: Remove unconditional confirmations and triplicated control prose from the Monte Carlo runners

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#509**: sim: record level-flag injector fails startup-stability standing current; latched revision loses eviction (DR-022)

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#692**: fix(sim): derive Monte Carlo control, seed, and convergence prose from checks

## Proposed

Issues carrying `loom:curated`.

- **#306**: Reduce the startup injector's supply-dependent GDRV load so PSRR clears DR-006's 60 dB floor (design cause confirmed by #300) *(curated)* *(held)*
- **#315**: Complete #306's circuit fix (startup injector PSRR) and the post-fix layout cycle *(curated)* *(held)*
- **#368**: Design a state-dependent startup-injector reference-stack element that clears the 60 dB PSRR floor at ff/125/3.63 and sf/27/2.97 *(curated)* *(held)*
- **#370**: Re-qualify reference records under open_pdks f6eeac7 (follow-up to #369) *(curated)* *(held)*
- **#432**: Follow-on from PR #431: first live routed-flow run with artifact broker *(curated)* *(held)*
- **#435**: T1 item 6 (Monte Carlo): mint a sufficiently sized untrimmed-Vref klt yield campaign with a declared negative control *(curated)* *(held)*
- **#444**: monte-carlo-untrimmed: real-fleet smoke run of --backend batch (AC4 of #437) *(curated)* *(held)*
- **#615**: T1 item 5 rows 3a/3b: schematic-level study of which temperature-coefficient correction fits the remaining area (the roadmap's "question first") *(curated)* *(held)*
- **#621**: Re-extract and rerun the seven post-layout benches on the verified thick-oxide GDS *(curated)* *(held)*

## Proposed (Architect / Hermit)

- **#645**: Remove repeated direct-elbow attempts from the met1 detour search *(hermit)* *(held)*
- **#693**: Remove the redundant resistor rewrite from the native PEX measurement hook *(hermit)* *(held)*
- **#700**: Retire the unusable --n-r2 override in the chained trim runner *(hermit)* *(held)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 1 |
| Important | 5 |
| Ready (`loom:issue`, net of holds/building/merge-pending) | 0 |
| In Progress (`loom:building`) | 1 |
| PRs awaiting review | 1 |
| Approved PRs awaiting merge | 1 |
| Curated | 9 |
| Architect / Hermit proposals | 3 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
