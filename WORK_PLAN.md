# Work Plan

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

_None._

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

- **#542**: T1 item 7: cite the klt pex pilot in the signoff manifest, or record why the pinned grader refuses it

## Important

`loom:important`; taken before unlabelled work.

- **#315**: Complete #306's circuit fix (startup injector PSRR) and the post-fix layout cycle
- **#368**: Design a state-dependent startup-injector reference-stack element that clears the 60 dB PSRR floor at ff/125/3.63 and sf/27/2.97
- **#435**: T1 item 6 (Monte Carlo): mint a sufficiently sized untrimmed-Vref klt yield campaign with a declared negative control
- **#444**: monte-carlo-untrimmed: real-fleet smoke run of --backend batch (AC4 of #437)
- **#540**: Re-extract parasitics at the pinned klt 0.8.0 and re-measure row 1b (klayout-tools#2359 is closed)

## Ready

Human-approved issues ready for implementation (`loom:issue`).

_None._

## In Progress

Issues currently being built (`loom:building`).

- **#533**: Share the four duplicated batch/seed predicates between the two Monte Carlo runners
- **#538**: Consolidate the 10 copies of sha256_file(): two incompatible return conventions share one name
- **#544**: Dedup the batch CLI flag block onto sim_common.add_common_args() (6 harnesses, help text already drifted into 3 wordings)

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#509**: sim: record level-flag injector fails startup-stability standing current; latched revision loses eviction (DR-022)
- **#537**: refactor(sim): move the four batch/seed predicates into batch_sim
- **#546**: refactor: one sha256 helper, with a separate name per return convention

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
- **#533**: Share the four duplicated batch/seed predicates between the two Monte Carlo runners *(curated)*
- **#536**: Share the duplicated Monte Carlo batch-collector test fixture between the two MC bench test files *(curated)*
- **#540**: Re-extract parasitics at the pinned klt 0.8.0 and re-measure row 1b (klayout-tools#2359 is closed) *(curated)*
- **#542**: T1 item 7: cite the klt pex pilot in the signoff manifest, or record why the pinned grader refuses it *(curated)*
- **#543**: signoff/README.md and README status text disagree with the committed signoff report and pins *(curated)*

## Proposed (Architect / Hermit)

- **#517**: Shrink layout/bin/met2_drc.py to its orphan-via check: pinned klt 0.8.0 already checks the met2/via rules it duplicates *(hermit)*
- **#536**: Share the duplicated Monte Carlo batch-collector test fixture between the two MC bench test files *(hermit)*
- **#545**: Consolidate the VREF accuracy window: 4 copies of DR-005's ratified band under 4 names, plus 2 live gates still on the superseded draft band *(hermit)*
- **#549**: batch_sim records 1149 copies of 2 distinct worker_environment blocks: 1.4 MB of redundant fleet attestation in sim/ records *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 1 |
| Important | 5 |
| Ready (`loom:issue`) | 0 |
| In Progress (`loom:building`) | 3 |
| PRs awaiting review | 3 |
| Approved PRs awaiting merge | 0 |
| Curated | 12 |
| Architect / Hermit proposals | 4 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
