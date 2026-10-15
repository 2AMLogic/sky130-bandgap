# DR-018: Startup injector — the three-high reference stack alone fails `startup-stability` at 125 °C (35/45)

- **Status**: proposed (investigation disposition, not a spec change — DR-006's
  `>= 60 dB` floor and `sim/startup-stability`'s limits are untouched and not relaxed).
- **Date**: 2026-10-15.
- **Decided by**: Loom Builder agent (issue #315), proposing per CLAUDE.md.
- **Continues**: [DR-011](DR-011-startup-injector-psrr-fix-infeasible-by-resize.md),
  whose candidate 1 (three-high `MPC1`/`MPC2`/`MPC3`, nothing else touched) this settles.

## Measurement

`design/startup_injector.sch` with `MPC3` added (same `W=1 L=20` unit, series
node `GDRV -> NC1 -> NC2 -> NG`), run through the unchanged 45-corner
`sim/startup-stability` matrix on the batch fleet (`--backend batch`, per-corner
timeout 10800 s, so no timeouts):
record `sim/startup-stability/records/20261015-133821-9f956c4.md`
(`Supersedes: 20261015-022916-ff69193`). The schematic edit was reverted after the
run; the record's netlist snapshot is the evidence for what was measured.

**35/45 PASS, 10 FAIL, `Overall: FAIL`.** Single-equilibrium (`ncross_su = 1`) holds at
all 45 corners, so the failure is not a second operating point. All 10 failures
are eviction-margin misses at **125 °C**:

| corner | failing measurements |
|---|---|
| `tt/125/2.97`, `tt/125/3.30` | `imin_off_su` 1.67e-9 / 3.16e-9 A (< 1e-8) |
| `ss/125/2.97`, `ss/125/3.30` | `itrav_min` 6.5e-10 / 7.5e-10 A (< 1e-9) and `imin_off_su` |
| `ss/125/3.63` | `itrav_min` 9.7e-10 A and `imin_off_su` 4.3e-9 A |
| `ff/125/2.97`, `sf/125/2.97`, `sf/125/3.30` | `imin_off_su` 3.9e-9 / 6.1e-9 / 7.4e-9 A |
| `fs/125/2.97`, `fs/125/3.30` | `itrav_min` 5.1e-10 / 9.7e-10 A |

(`i_off_su` also exceeds its limit at five of these.)

## Reading

1. Item 1 of #315 is conclusive: this candidate is a genuine margin regression
   (the longer stack lowers the drive `MNI` sees at hot, low-supply corners),
   not slow convergence. It cannot land as a partial fix.
2. The ten failing corners are exactly where eviction drive is weakest, so any
   follow-on (item 2: `MNI` cascode, replica bias, `MNS`/`QS` release tuning)
   must be screened for hot-corner eviction margin as well as cold-corner PSRR;
   the NG-clamp variants in DR-015..DR-017 are likewise unproven there.
3. Cost reference: the full matrix completed on the fleet in one submission.
