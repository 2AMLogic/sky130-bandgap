# Environment setup

Bootstrap steps for the open-source analog flow used by this repo: xschem
(schematic capture / netlisting) + ngspice (simulation) against the sky130
PDK (fetched/managed via [volare](https://github.com/efabless/volare)).

This doc is meant to be followed verbatim from a fresh shell on a machine
that already has the xschem/ngspice/volare binaries installed (see
"Toolchain versions" below for what a from-scratch install looks like).
klayout-tools is not covered here — it is layout-side tooling, out of
scope for this schematic/sim bootstrap.

## Toolchain versions (recorded 2026-07-29)

| Tool | Version | Install path |
|---|---|---|
| xschem | `XSCHEM V3.4.7` | `/opt/homebrew/bin/xschem` (Homebrew) |
| ngspice | `ngspice-46` | `/opt/homebrew/bin/ngspice` (Homebrew) |
| volare | `v0.20.6` | `/opt/homebrew/bin/volare` (Homebrew, via pip/pipx-managed formula) |

xschem and ngspice were already present on the shared dev machine as a
byproduct of the sibling repo's toolchain bootstrap
(`2AMLogic/gf180-bandgap#18` — xschem has no upstream Homebrew formula;
that issue's bootstrap doc, once merged, documents the exact install path
it landed on). **Do not reinstall xschem/ngspice speculatively** — verify
first:

```sh
xschem -v        # expect: XSCHEM V3.4.7 ...
ngspice --version # expect: ngspice-46 ...
```

If either is genuinely absent, check `2AMLogic/gf180-bandgap#18`'s
bootstrap doc for the install path it used before improvising a new one
(it's a shared machine-level resource, not sky130-specific).

## 1. Verify xschem works headlessly

```sh
xschem -x -n -s -q --rcfile "$PDK_ROOT/$PDK/libs.tech/xschem/xschemrc" \
  -o /tmp/smoke_netlist design/smoke_test.sch
```

(`$PDK_ROOT`/`$PDK` are set up in step 3 below — this command is shown
here for reference and re-run as the smoke test in step 4.) A bare
sanity check that doesn't need any PDK wiring at all:

```sh
xschem -n -q -x /opt/homebrew/share/doc/xschem/examples/nand2.sch -o /tmp/xschem_check
```

This should exit 0 and write a `.spice` netlist to `/tmp/xschem_check`
with no errors printed.

## 2. Fetch + enable the sky130 PDK via volare

```sh
volare ls-remote --pdk sky130   # lists open_pdks build commits, newest first
volare fetch  --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
```

**Recorded PDK version (pinned, not "latest"):**

- PDK family: `sky130`
- open_pdks build commit: `c6d73a35f524070e85faff4a6a9eef49553ebc2b`
- Fetch date: 2026-07-29
- Chosen because: this is the same open_pdks commit already fetched for
  `gf180mcu` on this shared dev machine (`2AMLogic/gf180-bandgap#18`) —
  using the same build keeps PVT/model provenance consistent across the
  2AM Logic canary ports of this block. It was also the newest commit
  returned by `volare ls-remote --pdk sky130` at fetch time.

After `volare enable`, `~/.volare` contains PDK variant symlinks. sky130's
variant naming differs from gf180mcu's A/B/C/D scheme — confirm what got
enabled:

```sh
ls -la ~/.volare | grep sky130
# sky130A -> volare/sky130/versions/c6d73a35f524070e85faff4a6a9eef49553ebc2b/sky130A
# sky130B -> volare/sky130/versions/c6d73a35f524070e85faff4a6a9eef49553ebc2b/sky130B
```

This repo standardizes on the **`sky130A`** variant.

## 3. Environment convention: `PDK_ROOT` / `PDK`

Export these two variables in any shell before running xschem/ngspice
against sky130 in this repo:

```sh
export PDK_ROOT="$(volare path)"   # -> the volare-managed PDK store root
export PDK=sky130A
```

Verify:

```sh
echo "$PDK_ROOT"          # e.g. /Users/<you>/.volare
echo "$PDK_ROOT/$PDK"     # must exist and be a real (symlinked) directory
ls "$PDK_ROOT/$PDK/libs.tech/ngspice/sky130.lib.spice"   # model include file
```

This is a plain shell convention (no repo-local script currently wraps
it) — add the two `export` lines above to your shell profile, or source
them from a small snippet before working in this repo, so they survive a
fresh shell. They must be set before invoking `xschem` with
`--rcfile "$PDK_ROOT/$PDK/libs.tech/xschem/xschemrc"` (below), since that
rcfile itself reads `$env(PDK_ROOT)` / `$env(PDK)` to resolve
`$::SKYWATER_MODELS`.

## 4. Smoke test: xschem netlist -> ngspice run against sky130 models

`design/smoke_test.sch` is a throwaway circuit — a 1:1 resistor divider
built from two `sky130_fd_pr__res_generic_po` primitives across a fixed
1.8 V source — used only to prove the toolchain end-to-end. It carries no
bandgap design content, spec values, or measurement data.

```sh
export PDK_ROOT="$(volare path)"
export PDK=sky130A

# 1. Netlist the schematic with xschem (headless, no X server needed)
xschem -x -n -s -q --rcfile "$PDK_ROOT/$PDK/libs.tech/xschem/xschemrc" \
  -o sim design/smoke_test.sch
# -> writes sim/smoke_test.spice

# 2. Run the netlist through ngspice (operating-point analysis)
ngspice -b sim/smoke_test.spice | tee sim/smoke_test.ngspice.out
```

Expected result: the run completes with exit code 0, resolves
`.lib $::SKYWATER_MODELS/sky130.lib.spice tt` to an absolute path under
`$PDK_ROOT/$PDK/libs.tech/combined/`, and prints an operating-point node
voltage table (`net1`, `net2`) plus resistor device parameters — no
`error`/`warning` lines. `sim/smoke_test.spice` (the netlist) and
`sim/smoke_test.ngspice.out` (the ngspice run output) are committed as
append-only evidence per `CLAUDE.md`.

## Troubleshooting

- **`SKYWATER_MODELS: unable to resolve variable`** / `.lib` path is
  literally `$::SKYWATER_MODELS/...` in the emitted netlist (not
  expanded to a real path): the `code.sym` block emitting the `.lib`
  line needs `format="tcleval( @value )"` so xschem evaluates the Tcl
  variable at netlist time — see `design/smoke_test.sch` for the working
  pattern.
- **`Warning: PDK_ROOT environment variable is set but path not
  found`** (printed by the PDK's own `xschemrc`): `$PDK_ROOT`/`$PDK`
  aren't exported in the shell running `xschem`, or `volare enable`
  hasn't been run for the recorded hash above.
- **xschem opens a GUI window instead of running headless**: pass `-x`
  (no X) in addition to `-n -q`.
