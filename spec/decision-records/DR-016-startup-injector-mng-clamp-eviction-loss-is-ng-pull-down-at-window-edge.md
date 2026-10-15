# DR-016: Startup injector — the `MNG` clamp's 27 °C eviction loss is `NG` being pulled below `MNI`'s turn-on at the window edge

- **Status**: proposed (investigation disposition, not a spec change — DR-006's
  `>= 60 dB` floor and `sim/startup-stability`'s `itrav_min >= 1e-9 A` are
  untouched and not relaxed).
- **Date**: 2026-10-15.
- **Decided by**: Loom Builder agent (issue #315), proposing per CLAUDE.md.
- **Continues**: [DR-015](DR-015-startup-injector-psrr-ng-clamp-and-weak-stack-fail-room-temp-eviction-margin.md),
  whose "mechanism not identified" item this addresses.

## Measurement

`sim/psrr-injector-candidates/probe_itrav.py ... nodes` (new mode; same deck as
the `itrav` orientation probe, 6 alpha points). `tt / 27 °C / 2.97 V`, single
corner, local run. Orientation, not evidence.

| alpha | stock `ifsu` A | stock `v(NG)` V | `+MNG` `ifsu` A | `+MNG` `v(NG)` V |
|---|---|---|---|---|
| 0.75 | 8.96e-9 | 0.402 | **1.96e-10** | 0.185 |
| 0.80 | 2.21e-5 | 0.845 | 4.99e-7 | 0.620 |
| 0.85 | 2.77e-4 | 1.172 | 7.36e-5 | 0.947 |
| 0.90 | 3.51e-4 | 1.234 | 2.07e-4 | 1.100 |
| 1.00 | 8.05e-4 | 1.584 | 7.29e-4 | 1.527 |

(`v(GD)`/`v(VREFD)` are identical between bodies to 4 digits at every point.)

## Reading

1. The forced current at alpha = 0.75 is already near zero for the **stock**
   body (8.96e-9 A against a 1e-9 A floor): the window edge sits just above a
   sign change of the injector's current into `GDRV`. `itrav_min` is therefore
   set by how far `NG` is from `MNI`'s turn-on at that edge, not by a
   conduction-strength figure.
2. `MNG` lowers `v(NG)` by 0.22 V at alpha = 0.75 (0.402 -> 0.185) and
   0.22–0.25 V through alpha = 0.80–0.85. `v(NE)` moves 0.14 V at the edge and
   < 0.01 V at alpha = 0.80, so `MNS`/`QS` do not explain it. Consistent with
   `MNG` acting as a shunt on `NG` that takes a *large* fraction of the `MPC`
   stack's few-nA drive exactly where that drive is smallest (the window
   edge). Not separately verified (no `i(XMNG)` probe).
3. The effect fades with alpha (0.185 -> 1.10 V at 0.90), which is why
   DR-012's single probe at `ss/125` (where the stock margin is large relative
   to the leak) missed it and why the loss shows at 27 °C, where the stack
   drive at the edge is smallest.
4. This explains DR-015 item 1 and also why stack changes (DR-013) and `MNG`
   fail by the **same** route: both reduce `NG`'s edge drive.

## What this changes

A clamp must remove `NG`'s **cold-corner** residual without shunting `NG` at
alpha ≈ 0.75. A fixed `W = 1, L = 20` shunt with gate on `VSENSE` cannot (its
gate sits at `VREFD` ≈ 0.24–0.46 V across the window, so it conducts weakly
throughout; that weak conduction is the suspected loss). Untried and now motivated: a clamp whose gate is driven by a node
that is **low at the cold corner and does not conduct at the edge**, e.g. gated
by `NG`-relative level shifting, or the `MNS`/`QS` release-threshold knob
(issue item 2, third bullet), which moves `NG` by threshold, not by shunting.

## Disposition

No circuit change lands; `design/startup_injector.sch` unchanged; no spec line
moves; no `sim/` record is added or modified. The only code change is the
`nodes` mode in the orientation probe. #315 stays open; items 3–4 remain blocked
on a landed circuit change.

## Alternatives considered

- **Certify `+MNG` on the 45-corner batch path.** Rejected: DR-015 already shows
  conclusive sub-floor values; this record explains why.
- **Resize `MNG` (smaller W / longer L).** Not available: `L = 20` is the
  longest binned channel at `W = 1` for this device (DR-015 item 3), and
  narrower W cuts clamp strength at the cold corner by the same factor it cuts
  the leak.

## Spec lines affected

None.
