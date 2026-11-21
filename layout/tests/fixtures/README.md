# Test fixtures (layout)

Real tool output pinned byte-exactly so the unit gates can be exercised
without a `klt` install or a PDK. Each file names the committed artifact it
was produced from and the exact command that produced it; regenerate with
the pinned tools (`layout/requirements.txt`, `sim/pdk.json`) and diff.

## `20260923-070209-dbd57a9.pdk-extract.spice`

The raw, pre-translation PDK-bound extraction of the committed thin-oxide
GDS `layout/bandgap-core/reports/20260923-070209-dbd57a9/
bandgap_core_routed.gds` (sha256
`311c0f14cdd85aa5255018c590cbe755e31fd1ac81e04895d6302fea2146aae9`).
Issue #620's flavour gate must FAIL on it: every MOS card binds a
1.8 V wrapper (19 `sky130_fd_pr__nfet_01v8` + 54
`sky130_fd_pr__pfet_01v8`), none the 5 V `*_g5v0d10v5` cards the schematic
specifies. Reproduce with klt 0.8.0 and the `sim/pdk.json` PDK pin:

```bash
klt extract <that .gds> --deck sky130 --top bandgap_core_routed \
  --pdk sky130A -o raw.spice --format json > /dev/null
```

Card *models* are stable across hosts; the anonymous `$N` net names are not
(`klt extract`'s own docs say so) -- which is why the gate counts models
and never diffs netlist text.
