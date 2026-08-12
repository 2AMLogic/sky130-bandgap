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

## Known gaps (not closed by this record)

- The mechanism above is a scale/order-of-magnitude argument from the
  network's aggregate R/C totals and the single-pole shape of the existing
  schematic-level curve, not a per-net attribution the way
  `sim/quiescent-current-post-layout/README.md` achieved for R1 (that
  analysis had two specific legs to inspect; this one would need either a
  sensitivity sweep of the extracted network's dominant nets or a
  reduced-order model of the amplifier's loop with the extracted parasitics
  folded in — a nontrivial follow-up, not attempted here).
- No mid-band frequency points beyond the 8 measurement expressions
  (`psrr_dc`/`f_dc`/`psrr_1k`/`f_1k`/`psrr_band_min`/`psrr_1m`/`f_1m`/
  `n_ac_points`) are recorded per corner — the full 71-point AC sweep is not
  itself saved to the corner logs (only the deck and these evaluated
  scalars, following `sim/psrr-dc/`'s own manifest), so a shape comparison
  of the whole rolloff (not just the two edges) between the two records
  would need a re-run with `write`/vector dump added to the deck.
