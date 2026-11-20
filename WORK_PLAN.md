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

- **#306**: Reduce the startup injector's supply-dependent GDRV load so PSRR clears DR-006's 60 dB floor (design cause confirmed by #300) *(held)*
- **#315**: Complete #306's circuit fix (startup injector PSRR) and the post-fix layout cycle *(held)*
- **#368**: Design a state-dependent startup-injector reference-stack element that clears the 60 dB PSRR floor at ff/125/3.63 and sf/27/2.97 *(held)*
- **#435**: T1 item 6 (Monte Carlo): mint a sufficiently sized untrimmed-Vref klt yield campaign with a declared negative control *(held)*
- **#444**: monte-carlo-untrimmed: real-fleet smoke run of --backend batch (AC4 of #437) *(held)*
- **#614**: Post-layout benches simulate temperature-flat resistors: extract with klt's --pdk model binding and retire the hand resistor translation

## Ready

Human-approved issues (`loom:issue`) ready for implementation — excluding held (`loom:blocked`/`loom:operator`/`loom:frozen`), `loom:building`, and issues closed by an open `loom:pr` PR (listed under Approved).

- **#614**: Post-layout benches simulate temperature-flat resistors: extract with klt's --pdk model binding and retire the hand resistor translation

## In Progress

Issues currently being built (`loom:building`).

- **#615**: T1 item 5 rows 3a/3b: schematic-level study of which temperature-coefficient correction fits the remaining area (the roadmap's "question first")

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#509**: sim: record level-flag injector fails startup-stability standing current; latched revision loses eviction (DR-022)

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#616**: feat: screen three bandgap temperature corrections on batch

## Proposed

Issues carrying `loom:curated`.

- **#306**: Reduce the startup injector's supply-dependent GDRV load so PSRR clears DR-006's 60 dB floor (design cause confirmed by #300) *(curated)* *(held)*
- **#315**: Complete #306's circuit fix (startup injector PSRR) and the post-fix layout cycle *(curated)* *(held)*
- **#368**: Design a state-dependent startup-injector reference-stack element that clears the 60 dB PSRR floor at ff/125/3.63 and sf/27/2.97 *(curated)* *(held)*
- **#370**: Re-qualify reference records under open_pdks f6eeac7 (follow-up to #369) *(curated)* *(held)*
- **#432**: Follow-on from PR #431: first live routed-flow run with artifact broker *(curated)* *(held)*
- **#435**: T1 item 6 (Monte Carlo): mint a sufficiently sized untrimmed-Vref klt yield campaign with a declared negative control *(curated)* *(held)*
- **#444**: monte-carlo-untrimmed: real-fleet smoke run of --backend batch (AC4 of #437) *(curated)* *(held)*
- **#614**: Post-layout benches simulate temperature-flat resistors: extract with klt's --pdk model binding and retire the hand resistor translation *(curated)*
- **#615**: T1 item 5 rows 3a/3b: schematic-level study of which temperature-coefficient correction fits the remaining area (the roadmap's "question first") *(curated)*

## Proposed (Architect / Hermit)

- **#517**: Shrink layout/bin/met2_drc.py to its orphan-via check: pinned klt 0.8.0 already checks the met2/via rules it duplicates *(hermit)* *(held)*
- **#545**: Consolidate the VREF accuracy window: 4 copies of DR-005's ratified band under 4 names, plus 2 live gates still on the superseded draft band *(hermit)* *(held)*
- **#554**: Dedup pex-native's three duck-type shims onto corner-run's Corner/Experiment/Measurement dataclasses (_C has no .id, blocking batch_sim's collectors) *(hermit)* *(held)*
- **#617**: Reuse the shared resistor-chain substitution and temperature sweep in the head-resistance bench *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 0 |
| Important | 6 |
| Ready (`loom:issue`, net of holds/building/merge-pending) | 1 |
| In Progress (`loom:building`) | 1 |
| PRs awaiting review | 1 |
| Approved PRs awaiting merge | 1 |
| Curated | 9 |
| Architect / Hermit proposals | 4 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
