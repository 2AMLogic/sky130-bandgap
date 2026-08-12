# `psrr-dc-post-layout` — divergence finding

Post-layout (`provenance: extracted`) re-run of `sim/psrr-dc`'s power-supply
rejection ratio claim against the routed, LVS-clean `layout/bandgap-core/`
GDS (issue #62), for issue #16. Records here are append-only and are **new**
evidence — they neither overwrite nor retire `sim/psrr-dc/`'s schematic-level
records.

This file exists because issue #16 requires any divergence from the
schematic-level result to be **documented as a finding, not reconciled
away**, and the divergence here changes the pass/fail verdict at most
corners: 34 of 45 flip from PASS (schematic) to FAIL (post-layout) on the
`psrr_1k`/`psrr_band_min` DC-1 kHz band-floor measurements. It is written
alongside the record, not into it, for the same reason
`sim/quiescent-current-post-layout/README.md` exists: the record format has
no field for a cross-record investigation.

## What the record says

Record `20260812-011520-5df01bf` — full 45-point PVT matrix, **no** collapsed
axis, `Overall: FAIL`.

| Measurement | Post-layout (extracted) range | Limit | Corners passing |
|---|---|---|---|
| `psrr_dc` (0.1 Hz edge) | 78.66 … 136.48 dB | ≥ 60 dB | 45 / 45 |
| `psrr_1k` (1 kHz edge) | 58.27 … 62.55 dB | ≥ 60 dB | 11 / 45 |
| `psrr_band_min` (DC-1 kHz interior floor, issue #127) | 58.27 … 62.55 dB | ≥ 60 dB | 11 / 45 |
| `psrr_1m` (1 MHz spot, informational) | 7.85 … 9.13 dB | none (stretch, out of scope wave 1) | n/a |
| `n_ac_points` / `f_dc` / `f_1k` / `f_1m` (index guards) | all in-window | — | 45 / 45 |

On this circuit `psrr_1k == psrr_band_min` at every one of the 45 corners
(the band floor sits at the 1 kHz edge, same monotonic-rolloff pattern the
schematic-level bench's own notes document), so the two measurements track
identically here — the extraction has not introduced an interior dip that
the two-edge check would have missed.

Every index guard, the `n_ac_points` guard, and the 45-point matrix all
resolved cleanly (no ngspice failures, no timeouts) — the FAIL verdict is a
real measured degradation, not a harness/translation failure. The
corner-sensitivity spread check (`psrr_dc` must move ≥ 0.5 dB across the
matrix; observed spread 57.8 dB) also passes, ruling out a dead/uncorner'd
run.

## The divergence

Closest schematic-level reference: `sim/psrr-dc/records/20260811-230151-84ef136`
(same bench, same manifest, same measurement expressions; `design/bandgap_core.sch`
at the current chained-array sizing).

| | schematic `psrr_band_min` range | post-layout `psrr_band_min` range |
|---|---|---|
| min .. max across 45 corners | 62.65 … 66.73 dB | 58.27 … 62.55 dB |

The schematic-level record already had thin margin above the 60 dB floor
(2.65 … 6.73 dB) — DR-006/issue #127's own notes call this out as the
motivation for the band-interior guard in the first place. Post-layout
shifts the whole distribution down by enough to cross the floor at most
corners.

Per-corner delta (`psrr_band_min` post-layout minus schematic, same 45
corner IDs in both records — same-corner comparison, not just same range):

| | value |
|---|---|
| min delta | −4.65 dB (`ss_-40c_3.63v`) |
| max delta | −3.43 dB (`ff_125c_3.63v`) |
| mean delta | **−4.05 dB** |
| population stdev of delta | **0.36 dB** |

That is a strikingly *tight* distribution — the shift is close to a constant
number of dB regardless of process corner, temperature, or supply. Contrast
with `psrr_dc` (the 0.1 Hz edge): its per-corner delta ranges from −25.0 dB
to **+48.5 dB**, because the DC point sits on the steep, highly
corner-sensitive part of the loop-gain-dominated low-frequency response
(the schematic-level record itself already shows `psrr_dc` swinging
80.98 … 136.48 dB corner to corner) — a poor place to look for a stable
signature. `psrr_band_min` (near 1 kHz) is much more diagnostic precisely
*because* it is stable: a near-constant dB offset across every PVT axis is
the signature of a fixed linear network added in the signal path (a
corner-independent R/C), not of a corner-dependent device effect (e.g. a
gain or transconductance shift, which would track process/temperature the
way `psrr_dc` does).

## Attributed cause: extracted VDD/VSS-path parasitics sit directly in the measured transfer function

This is the mechanistic difference from `sim/quiescent-current-post-layout/`'s
finding (R1 growing 55%, a *second-order* effect on the DC bias point that
Iq happens to be sensitive to via `1/R1`): PSRR's own measurement **is** the
small-signal supply-to-VREF transfer function, `-db(v(vref))` under a 1 V AC
excitation directly on the supply. Any parasitic impedance the extraction
adds between the supply pins and the circuitry that sets the rejection
(the PTAT/CTAT core and the error-amplifier's own supply-referenced nodes)
is therefore *in series with the signal path this bench characterizes*, not
a bias-point side effect — consistent with this bench's own claim tail
calling that out as the reason to expect PSRR to be the spec line most
exposed to extraction among the three post-layout benches run so far.

The shared `klt extract --parasitics` snapshot for this layout record
(`sim/output-voltage-tc-post-layout/parasitics-snapshot/20260811-221633-a0ee5e7/`,
reused unchanged by this bench — see `links`/`layout_provenance` in the
record's `.json` twin) reports **813 R + 151 C elements, 264.3 kΩ / 1.55 pF
aggregate** across the whole extracted netlist, star-connected per net
exactly as `sim/quiescent-current-post-layout/README.md` describes for the
same snapshot. A constant ~4 dB rejection loss at 1 kHz is consistent in
order of magnitude with an added real pole from that network sitting in the
supply-referenced bias path (a ~4 dB loss at a fixed frequency is what a
roughly-doubling of an existing pole's corner frequency looks like on a
single-pole rolloff, and the schematic-level PSRR curve's own ~9 dB/decade
observed slope between the 0.1 Hz and 1 kHz measurement points is close to
single-pole behavior) — but this record does not isolate *which* specific
net's R or C in the 813/151-element network is the dominant contributor, the
same kind of open item `sim/quiescent-current-post-layout/README.md` flagged
for its own R1-attribution (there, nodal analysis of the two relevant
resistor legs was tractable because Iq depends on two specific nets; PSRR's
small-signal transfer function depends on the whole network's loading of the
amplifier's loop, which is not reducible to two legs by inspection). Left as
an open item below rather than asserted past what this record supports.

## The spec line itself is not settled either way

DR-005 (amended by DR-006) ratifies the PSRR target at `> 60 dB` DC-1 kHz.
This post-layout record shows the routed layout, as currently drawn, **fails**
that target at 34 of 45 PVT corners by a small margin (worst corner
58.27 dB, 1.73 dB below the floor). This is a genuine finding about the
current routing, not an artifact to explain away — CLAUDE.md's own
instruction is that agents do not relax a ratified spec to make results
pass. Whether the fix is a routing change (shorter/wider VDD/VSS legs to the
amplifier, keeping this bench's exposed nets lower-impedance) or a
design-level rejection margin increase is a follow-up call, not this
record's.

## Follow-up: the routing-fix path is closed (issue #140)

Issue #140 picked up the "Whether the fix is a routing change... or a
design-level rejection margin increase" question this record left open and
ran the sensitivity sweep the "Known gaps" item below called for (against a
real corner deck extracted from this record, perturbed directly in
ngspice — no layout regeneration needed to test the hypothesis). Two
findings that sharpen the mechanism above:

1. **The dominant parasitic resistance is on the amplifier's own internal
   nodes** (`GDRV`/`PN`/`TAIL`/`VA`/`VB`/`VBQ`/`D1`/`D2`'s own routing, plus
   ~200 anonymous internal nets), **not the VDD/VSS supply rails** this
   record's mechanism section hypothesized. Scaling only the 11 named
   top-level pins' star-R resistors by 10x (an extreme, non-physical
   reduction) moved `tt_27c_3.30v`'s `psrr_band_min` by only +0.07 dB;
   scaling the internal-node resistors by the same 10x moved it by
   +2.03 dB.
2. **A routing-width fix does not close the gap even at the actually-tested
   DRC-clean layout.** Raising `gen_bandgap_routed.py`'s `ROUTE_WIDTH_UM`
   0.5 → 0.65 µm (+30%, verified DRC-clean and LVS-match, no bbox area
   change) — replayed as a 0.769x scale on this record's own extracted
   star-R network — still leaves the worst corner (`sf_-40c_2.97v`,
   58.27 dB baseline) 1.23 dB short of the 60 dB floor, and even an
   unrealistic >3x width increase (0.3x scale) falls 0.14 dB short there.
   The unphysical zero-resistance limit only asymptotes to ~60.3–60.5 dB at
   that corner — a ceiling too thin to trust across the corner axes this
   45-point matrix doesn't cover (mismatch, `ll`/`hh`).

Full sensitivity data, the harness-fragility side finding (raising
`ROUTE_WIDTH_UM` also changes `klt extract --parasitics`'s pin-promotion
behavior on `vsubs`, breaking `post_layout_common.py`'s fixed 11-pin
`core_port_order` assumption), and the two disposition options this leaves
(amend DR-006's floor, or fund a schematic-level amplifier PSRR margin
increase) are in
[`spec/decision-records/DR-008-psrr-post-layout-margin-proposal.md`](../../spec/decision-records/DR-008-psrr-post-layout-margin-proposal.md)
(**proposed**, not ratified — issue #140 is routed to the operator to pick
a disposition, not resolved by this finding alone).

No new record is appended to `sim/psrr-dc-post-layout/records/` by this
follow-up: no design or layout change was kept (the `ROUTE_WIDTH_UM` change
above was evaluated and reverted, not committed), so a re-run would
reproduce this same FAIL record's numbers, not new evidence. This record
(`20260812-011520-5df01bf`) remains the current, valid measurement of the
layout as drawn.

## Known gaps (not closed by this record)

- The mechanism above is a scale/order-of-magnitude argument from the
  network's aggregate R/C totals and the single-pole shape of the existing
  schematic-level curve, not a per-net attribution the way
  `sim/quiescent-current-post-layout/README.md` achieved for R1 (that
  analysis had two specific legs to inspect; this one would need either a
  sensitivity sweep of the extracted network's dominant nets or a
  reduced-order model of the amplifier's loop with the extracted parasitics
  folded in — a nontrivial follow-up, **narrowed but not fully closed** by
  the "Follow-up" section above: the dominant resistance is now localized
  to the internal-node class, but the specific worst-offender net(s), and
  the capacitive network's own role — reducing star-C by 10x measurably
  *worsened* `psrr_band_min` in a spot check, the opposite of a simple
  single-pole story — remain open; see DR-008's "Known gaps" for the exact
  numbers).
- No mid-band frequency points beyond the 8 measurement expressions
  (`psrr_dc`/`f_dc`/`psrr_1k`/`f_1k`/`psrr_band_min`/`psrr_1m`/`f_1m`/
  `n_ac_points`) are recorded per corner — the full 71-point AC sweep is not
  itself saved to the corner logs (only the deck and these evaluated
  scalars, following `sim/psrr-dc/`'s own manifest), so a shape comparison
  of the whole rolloff (not just the two edges) between the two records
  would need a re-run with `write`/vector dump added to the deck.
