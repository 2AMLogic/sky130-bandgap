# DR-019: Startup injector — the VBE-raised NG clamp (`mngq`) fails the 60 dB PSRR floor at 2.97 V

- **Status**: proposed (investigation disposition, not a spec change — DR-006's
  `>= 60 dB` floor is untouched and not relaxed).
- **Date**: 2026-10-15.
- **Decided by**: Loom Builder agent (issue #315), proposing per CLAUDE.md.
- **Continues**: [DR-017](DR-017-startup-injector-vbe-raised-ng-clamp-restores-edge-eviction.md)
  (which restores the eviction floor with `mngq` but measured only 26.89 dB at
  `ff/125/3.63`) and [DR-018](DR-018-startup-injector-three-high-stack-alone-fails-startup-stability-at-125c.md).

## Measurement

`sim/psrr-injector-candidates/run_psrr_injector_candidates.py --explore
--backend batch --variants mngq`, all 45 corners, on the Spot batch fleet
(`klt sim --backend batch`, each request sharded with the new `--batch-hosts 3`
so the serial job bound fits the fleet ceiling). Explore mode writes nothing
under `sim/`; the numbers below are this DR's evidence.

The fleet was at its `BATCH_MAX_CONCURRENT_INSTANCES=8` cap during the run, so
only the **2.97 V** supply's requests were admitted; the 3.30 V and 3.63 V
requests came back `lost_shard` (launch refused, no local fallback). The 15
corners at 2.97 V are complete:

| corner | `psrr_band_min` (dB) |
|---|---|
| `sf/27/2.97` | **49.01** (FAIL) |
| `ff/27/2.97` | **57.21** (FAIL) |
| `sf/-40/2.97` | **58.89** (FAIL) |
| `tt/27/2.97` | 63.92 |
| `ff/125/2.97` | 64.91 |
| `ff/-40/2.97` | 65.38 |
| other nine | 66.0 – 73.0 |

## Reading

1. `mngq` cannot reach 45/45 against DR-006: three of the fifteen 2.97 V corners
   already miss 60 dB, independent of the unmeasured 3.30/3.63 V supplies.
   Together with DR-017's 26.89 dB at `ff/125/3.63` it fails at both ends of the
   supply range, so it is dead as a stand-alone fix.
2. The failures are at 27 °C and -40 °C where `NG` sits near 0.31–0.40 V, i.e. the
   clamp's raised source leaves `MNI` partly conducting there; this trades the
   cold-corner residual DR-017 closed at 3.63 V for a room-temperature one at
   2.97 V.
3. Not measured here: 3.30 V / 3.63 V for `mngq`, and any variant with a
   state-dependent element that lowers the reference stack's running-state
   conductance. Those need fleet capacity (the screen is submittable now) and a
   design idea; per #315's own note, a new design follow-up should be split
   rather than extending this issue.
