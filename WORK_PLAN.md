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

- **#306**: Reduce the startup injector's supply-dependent GDRV load so PSRR clears DR-006's 60 dB floor (design cause confirmed by #300)
- **#315**: Complete #306's circuit fix (startup injector PSRR) and the post-fix layout cycle
- **#368**: Design a state-dependent startup-injector reference-stack element that clears the 60 dB PSRR floor at ff/125/3.63 and sf/27/2.97
- **#435**: T1 item 6 (Monte Carlo): mint a sufficiently sized untrimmed-Vref klt yield campaign with a declared negative control
- **#444**: monte-carlo-untrimmed: real-fleet smoke run of --backend batch (AC4 of #437)

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#560**: Re-run the five post-layout benches that resolve the klt 0.8.0 parasitics snapshot

## In Progress

Issues currently being built (`loom:building`).

- **#541**: pex-native: second record with --critical-net VB --critical-net VBQ --distributed-rc to split star-model allocation from the net total R
- **#544**: Dedup the batch CLI flag block onto sim_common.add_common_args() (6 harnesses, help text already drifted into 3 wordings)
- **#547**: Dedup the last bare file-hash copy: qualify_dr005._sha() duplicates content_hash.sha256_file()
- **#549**: batch_sim records 1149 copies of 2 distinct worker_environment blocks: 1.4 MB of redundant fleet attestation in sim/ records
- **#552**: Consolidate 13 never-loaded *_NOTE constants (299 lines) out of layout/bin: the records that cite them by name never carry their text
- **#557**: Split the psrr-injector-only surface out of sim_common.py: 359 of its 1776 lines serve exactly two benches
- **#562**: Retire the last reachable HASHLIB_ALLOWED entry: run_trim_lsb_chained.py:270 hand-rolls content_hash.sha256_text()

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#509**: sim: record level-flag injector fails startup-stability standing current; latched revision loses eviction (DR-022)
- **#539**: docs: roadmap as of 2026-11-14
- **#548**: refactor(sim): one shared batch CLI flag block for all six harnesses
- **#558**: refactor(sim): store each fleet worker_environment once in a record table
- **#564**: feat(pex-native): distributed-RC record refutes the star-allocation hypothesis

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#566**: refactor(layout): move 13 never-loaded *_NOTE constants into anchored layout/generator-notes.md
- **#569**: refactor: route qualify_dr005.py file digests through content_hash.sha256_file
- **#570**: refactor(sim): hash the trim-lsb netlist body via content_hash.sha256_text

## Proposed

Issues carrying `loom:curated`.

- **#306**: Reduce the startup injector's supply-dependent GDRV load so PSRR clears DR-006's 60 dB floor (design cause confirmed by #300) *(curated)*
- **#315**: Complete #306's circuit fix (startup injector PSRR) and the post-fix layout cycle *(curated)*
- **#368**: Design a state-dependent startup-injector reference-stack element that clears the 60 dB PSRR floor at ff/125/3.63 and sf/27/2.97 *(curated)*
- **#370**: Re-qualify reference records under open_pdks f6eeac7 (follow-up to #369) *(curated)*
- **#432**: Follow-on from PR #431: first live routed-flow run with artifact broker *(curated)*
- **#435**: T1 item 6 (Monte Carlo): mint a sufficiently sized untrimmed-Vref klt yield campaign with a declared negative control *(curated)*
- **#444**: monte-carlo-untrimmed: real-fleet smoke run of --backend batch (AC4 of #437) *(curated)*
- **#541**: pex-native: second record with --critical-net VB --critical-net VBQ --distributed-rc to split star-model allocation from the net total R *(curated)*
- **#543**: signoff/README.md and README status text disagree with the committed signoff report and pins *(curated)*
- **#547**: Dedup the last bare file-hash copy: qualify_dr005._sha() duplicates content_hash.sha256_file() *(curated)*
- **#560**: Re-run the five post-layout benches that resolve the klt 0.8.0 parasitics snapshot *(curated)*
- **#562**: Retire the last reachable HASHLIB_ALLOWED entry: run_trim_lsb_chained.py:270 hand-rolls content_hash.sha256_text() *(curated)*

## Proposed (Architect / Hermit)

- **#517**: Shrink layout/bin/met2_drc.py to its orphan-via check: pinned klt 0.8.0 already checks the met2/via rules it duplicates *(hermit)*
- **#545**: Consolidate the VREF accuracy window: 4 copies of DR-005's ratified band under 4 names, plus 2 live gates still on the superseded draft band *(hermit)*
- **#555**: Dedup the hand-rolled importlib loader: 15 copies across 13 files, only one honors the documented #267 contract *(hermit)*
- **#568**: Dedup MC batch helpers shared by the amp-offset and mc-untrimmed sim runners *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 0 |
| Important | 5 |
| Ready (`loom:issue`) | 1 |
| In Progress (`loom:building`) | 7 |
| PRs awaiting review | 5 |
| Approved PRs awaiting merge | 3 |
| Curated | 12 |
| Architect / Hermit proposals | 4 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
