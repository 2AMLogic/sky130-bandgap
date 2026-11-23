# Work Plan

<!-- guide:plan-body:start -->
_Generated: 2026-11-23T13:11:08Z (snapshot; compare against live labels)_
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
- **#620**: Generate and verify the thick-oxide MOS geometry in the routed bandgap core

## Ready

Human-approved issues (`loom:issue`) ready for implementation — excluding held (`loom:blocked`/`loom:operator`/`loom:frozen`), `loom:building`, and issues closed by an open `loom:pr` PR (listed under Approved).

_None._

## In Progress

Issues currently being built (`loom:building`).

- **#545**: Consolidate the VREF accuracy window: 4 copies of DR-005's ratified band under 4 names, plus 2 live gates still on the superseded draft band
- **#614**: Post-layout benches simulate temperature-flat resistors: extract with klt's --pdk model binding and retire the hand resistor translation
- **#620**: Generate and verify the thick-oxide MOS geometry in the routed bandgap core
- **#633**: generator-notes.md MET2_ESCAPE_NOTE: qualify the "what klt drc passes clean" sentence with the stricter-enclosure difference
- **#638**: Remove unconditional confirmation from the resistor head-resistance report

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#509**: sim: record level-flag injector fails startup-stability standing current; latched revision loses eviction (DR-022)
- **#622**: Bind post-layout extraction to the PDK: temperature-behaved resistors on the extracted side (rows 1b/3b, item 7)
- **#627**: feat(layout): draw the MOS blocks at 5 V thick-oxide and gate flavour, HV DRC and supply ERC in the routed flow
- **#640**: fix(sim): derive res-array-head-resistance determination from its checks

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#635**: refactor: consolidate DR-005's ratified VREF window into sim_common; rename the draft band DRAFT_VREF_WINDOW_V
- **#639**: docs: qualify met2 escape note's klt-drc pass-clean claim

## Proposed

Issues carrying `loom:curated`.

- **#306**: Reduce the startup injector's supply-dependent GDRV load so PSRR clears DR-006's 60 dB floor (design cause confirmed by #300) *(curated)* *(held)*
- **#315**: Complete #306's circuit fix (startup injector PSRR) and the post-fix layout cycle *(curated)* *(held)*
- **#368**: Design a state-dependent startup-injector reference-stack element that clears the 60 dB PSRR floor at ff/125/3.63 and sf/27/2.97 *(curated)* *(held)*
- **#370**: Re-qualify reference records under open_pdks f6eeac7 (follow-up to #369) *(curated)* *(held)*
- **#432**: Follow-on from PR #431: first live routed-flow run with artifact broker *(curated)* *(held)*
- **#435**: T1 item 6 (Monte Carlo): mint a sufficiently sized untrimmed-Vref klt yield campaign with a declared negative control *(curated)* *(held)*
- **#444**: monte-carlo-untrimmed: real-fleet smoke run of --backend batch (AC4 of #437) *(curated)* *(held)*
- **#545**: Consolidate the VREF accuracy window: 4 copies of DR-005's ratified band under 4 names, plus 2 live gates still on the superseded draft band *(curated)*
- **#614**: Post-layout benches simulate temperature-flat resistors: extract with klt's --pdk model binding and retire the hand resistor translation *(curated)*
- **#615**: T1 item 5 rows 3a/3b: schematic-level study of which temperature-coefficient correction fits the remaining area (the roadmap's "question first") *(curated)* *(held)*
- **#620**: Generate and verify the thick-oxide MOS geometry in the routed bandgap core *(curated)*
- **#633**: generator-notes.md MET2_ESCAPE_NOTE: qualify the "what klt drc passes clean" sentence with the stricter-enclosure difference *(curated)*

## Proposed (Architect / Hermit)

- **#554**: Dedup pex-native's three duck-type shims onto corner-run's Corner/Experiment/Measurement dataclasses (_C has no .id, blocking batch_sim's collectors) *(hermit)* *(held)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 0 |
| Important | 7 |
| Ready (`loom:issue`, net of holds/building/merge-pending) | 0 |
| In Progress (`loom:building`) | 5 |
| PRs awaiting review | 4 |
| Approved PRs awaiting merge | 2 |
| Curated | 12 |
| Architect / Hermit proposals | 1 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
