# sim/ — the simulation harness and its evidence records

This directory holds the reproducible xschem + ngspice + sky130 harness and the
results it produces. Two rules from the root `CLAUDE.md` shape everything here:

- **Verification is the product.** No claim without a testbench. Every recorded
  result carries the PVT corner matrix (−40/27/125 °C, ±10 % supply, process
  corners) unless the record states why a subset was used — the runner
  *enforces* that by refusing to write a subset record without a
  `--subset-reason`.
- **`sim/` is append-only evidence.** Records are never edited or deleted. A
  re-run — even one that corrects a mistake — mints a new record id; a
  correction points at what it replaces via a `Supersedes` field. The runner
  refuses to start if the record id it would mint already exists on disk.

The directory layout, record-id scheme and summary-record fields follow the
house convention established in the sibling `gf180-bandgap` repo, so the two
ports read as one evidence trail. Extensions specific to this harness (PDK
version pin, tool versions, machine-readable `.json` twin of each record,
corner-sensitivity check) are documented below.

---

## Quick start (cold machine)

```bash
# 1. install the pinned PDK (~1 min; see sim/pdk.json for the pin)
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b

# 2. sanity-check the toolchain and PDK resolution
python3 sim/bin/corner-run.py --print-env

# 3. run the harness smoke test over the full PVT matrix (45 points, ~1 min)
python3 sim/bin/corner-run.py sim/pdk-smoke
```

Prerequisites, all machine-level (not vendored here): `ngspice`, `xschem`,
`volare`, `python3` (3.9+, standard library only). Provisioning them on a dev
box is issue #17's scope; this harness only *verifies* they are present and
records the versions it used.

### Driving the tools by hand

```bash
source sim/bin/pdk-env.sh      # exports PDK_ROOT, PDK, SKY130_MODEL_LIB, XSCHEM_RCFILE
xschem --rcfile "$XSCHEM_RCFILE" sim/pdk-smoke/testbench/tb_pdk_smoke.sch
cp sim/spiceinit ./.spiceinit  # ngspice needs these settings to read PDK libs
```

`sim/bin/pdk-env.sh` is a thin wrapper around `corner-run.py --print-env`, so
interactive sessions and the runner resolve the PDK identically.

---

## How the harness is wired

| Piece | File | Role |
|---|---|---|
| PDK pin | `sim/pdk.json` | open_pdks commit, variant, model-library path, the process-corner names that actually exist in the PDK library |
| ngspice settings | `sim/spiceinit` | `ngbehavior=hsa` etc. required to read the sky130 libs; copied into the scratch run dir as `.spiceinit` |
| xschem config | `sim/xschemrc` | project-local rc that sources the PDK's own xschemrc (so `sky130_fd_pr/*.sym` resolves) and keeps generated netlists out of the tracked tree |
| corner runner | `sim/bin/corner-run.py` | netlist → deck → ngspice → parse → record |
| env helper | `sim/bin/pdk-env.sh` | `source` it for interactive xschem/ngspice work |
| experiment | `sim/<slug>/experiment.json` | what is being claimed, which corners, which measurements and their limits |

**PDK resolution order**: `$PDK_ROOT` → `volare path` → `default_pdk_root` from
`sim/pdk.json`; variant from `$PDK` → `variant` in `sim/pdk.json`. The runner
resolves the PDK directory symlink back to its volare version hash and
**refuses to run against a version other than the pin** unless
`--allow-pdk-mismatch` is passed — in which case the record says so. That is
what makes a record re-runnable months later.

**What the runner injects** (so one testbench serves the whole matrix): the
`.lib <models> <corner>` include, `.temp`, `.param vsup=<supply>`, `.option`s
from the manifest, and the `.control` block that runs the analyses, evaluates
each measurement expression into a `meas_<name>` vector and prints it. The
testbench schematic therefore contains no corner, no temperature, no numeric
supply and no analysis block.

**Per-corner artifacts**: each corner's `.log` embeds the exact deck that was
fed to ngspice (prefixed with `|`) plus raw stdout/stderr, so a record is
auditable without regenerating anything. Scratch decks and xschem output live
in the gitignored `sim/build/`; only the netlist snapshot, the per-corner logs
and the record are committed.

---

## Directory / naming convention

```
sim/
  README.md                          # this file
  pdk.json                           # PDK version pin
  spiceinit                          # ngspice init settings
  xschemrc                           # project-local xschem config
  bin/
    corner-run.py                    # PVT corner runner
    pdk-env.sh                       # `source` for interactive use
  build/                             # gitignored scratch (decks, xschem netlists)
  <experiment-slug>/                 # e.g. pdk-smoke, output-voltage-tc, psrr-dc
    experiment.json                  # manifest: claim, corners, measurements, limits
    testbench/                       # xschem schematic(s) for this experiment
    netlist-snapshots/
      <record-id>.spice              # frozen netlist used for this record
    corners/
      <record-id>/
        <corner-id>.log              # deck + raw ngspice output per PVT point
    records/
      <record-id>.md                 # append-only summary record (human)
      <record-id>.json               # same record, machine-readable
```

- **`<experiment-slug>`** — kebab-case name for the claim under test
  (`output-voltage-tc`, `psrr-dc`, `startup`, `mc-untrimmed`, …). One directory
  per distinct claim, not per run.
- **`<record-id>`** — `<YYYYMMDD>-<HHMMSS>-<short-git-sha>` in UTC, e.g.
  `20260730-032150-080179e`. The same id ties together the netlist snapshot,
  the per-corner logs and both record files for one run. Re-runs mint a new id.
- **`<corner-id>`** — `<process>_<temp>c_<supply>v`, e.g. `ss_-40c_2.97v`,
  `tt_27c_3.30v`, `ff_125c_3.63v`.
- **`testbench/`** is not versioned per record. If a testbench change could
  affect comparability across records, say so in the new record (the frozen
  netlist snapshot is what actually pins what ran).

## Summary record fields

Each run writes `records/<record-id>.md` (and a `.json` twin with every parsed
number, limit and verdict, for tooling):

| Field | Meaning |
|---|---|
| Record ID | matches the filename, the snapshot and the `corners/` subdirectory |
| Experiment | slug + title from the manifest |
| Claim | which spec parameter/line this substantiates (`spec/<file>.md#<anchor>` once specs are ratified — see issue #1) |
| Netlist provenance | `schematic` (`design/…`, `sim/…/testbench/…`) or `extracted` (post-layout, `layout/…`) — required so post-layout re-runs are distinguishable |
| PDK | variant + open_pdks commit actually used, whether it matches `sim/pdk.json`, and the model library path |
| Tools | ngspice / xschem / OS / python versions used |
| Repo state | short sha, branch, and whether the working tree was dirty at run time |
| Corner matrix run | the (process, temperature, supply) points actually executed; must be the full PVT matrix unless a subset reason is recorded |
| Statistical convention | N samples and sigma level for distribution claims (e.g. Monte Carlo mismatch); `N/A` for corner-matrix claims |
| Result | per-corner pass/fail with measured values, plus an overall verdict |
| Links | testbench, manifest, netlist snapshot, raw logs, json record |
| Timestamp / author | UTC timestamp and who (human or agent) ran it |
| Supersedes | prior `<record-id>` this corrects or re-runs (post-layout deltas included); `(none)` otherwise |

### Append-only rule

`records/*` files are never edited or deleted after creation — this applies
even to typo fixes, because the append-only guarantee is the whole point of an
evidence trail. Corrections mint a new record that references the prior one via
**Supersedes**. This mirrors the status/supersession language used for `spec/`
decision records, so both conventions read as one house style.

---

## Writing a new experiment

1. `mkdir -p sim/<slug>/{testbench,netlist-snapshots,corners,records}`
2. Draw the testbench in xschem (`--rcfile sim/xschemrc`). Leave out the
   corner include, `.temp`, the numeric supply (use `'vsup'`) and any
   `.control` block — the runner owns those. Name the nets you intend to
   measure; connectivity by `lab_pin` label is fine.
3. Write `sim/<slug>/experiment.json`:

```json
{
  "slug": "output-voltage-tc",
  "title": "…",
  "claim": "spec/bandgap.md#output-voltage-tc — …",
  "provenance": "schematic",
  "provenance_source": "sim/output-voltage-tc/testbench/tb_vref_tc.sch",
  "schematic": "testbench/tb_vref_tc.sch",
  "statistical_convention": "N/A (corner-matrix claim)",
  "corners": {
    "process": ["tt", "ss", "ff", "sf", "fs"],
    "temperature_c": [-40, 27, 125],
    "supply_v": [2.97, 3.3, 3.63]
  },
  "quick_subset": [["tt", 27, 3.3]],
  "deck": { "options": ["wnflag=1"], "params": {}, "analyses": ["op"] },
  "measurements": [
    { "name": "vref", "expr": "v(vref)", "unit": "V", "min": 1.188, "max": 1.212 }
  ],
  "spread_checks": []
}
```

   - `analyses` is a list of ngspice `.control` commands (`op`, `dc …`,
     `tran …`) run before measurements are evaluated.
   - `measurements[].expr` is any ngspice expression valid after those
     analyses; `min`/`max` are the pass window (omit either for one-sided).
   - `spread_checks` assert that a measurement *moves* across the matrix — a
     cheap guard against a harness that silently stops applying corners.
   - Process-corner names must appear in `sim/pdk.json` `process_corners`
     (which lists what the PDK's ngspice library really defines: `tt`, `ss`,
     `ff`, `sf`, `fs`; resistor/cap skew, `*_mm` mismatch and `mc` sections
     also exist in the library and can be added there once used).
4. Run it: `python3 sim/bin/corner-run.py sim/<slug>`
5. Commit the produced record, netlist snapshot and per-corner logs. (The
   root `.gitignore` ignores `*.log` globally but un-ignores
   `sim/*/corners/**/*.log`, which is committed evidence.)

### Experiments that do not go through the corner runner

`corner-run.py` runs **one deterministic deck per PVT point**. A claim about a
*distribution* — local mismatch, circuit-level Monte Carlo — needs the same deck
resampled N times at a single process point, which is a different axis. Those
experiments ship a bespoke run script next to their testbench instead of an
`experiment.json`:

| Experiment | Script | Why not the corner runner |
|---|---|---|
| `sim/pnp-mismatch/` | `run_pnp_mismatch.py` | N = 300 Monte Carlo samples per point; the PDK's `MC_MM_SWITCH` mismatch terms are re-drawn on each ngspice `reset` |

Such a script still has to behave like the harness:

- reuse `sim/bin/corner-run.py`'s PDK resolution and **pin enforcement**
  (import it; don't re-implement it), so a record is reproducible the same way;
- mint the same `<record-id>`, refuse to overwrite anything under
  `sim/<slug>/`, and write **both** the `.md` and the `.json` twin;
- commit the netlist snapshot and one raw log per ngspice invocation, with the
  exact deck embedded in the log;
- state the process/temperature/supply subset justification **in the record
  body** — there is no `--subset-reason` flag on this path, and "the runner
  enforces it" no longer applies, so the justification is a prose obligation;
- carry a **control point that must fail if the mechanism under test is not
  actually active** (e.g. `sim/pnp-mismatch/` re-runs its deck on the plain
  `tt` section, where every σ must come back exactly 0). A Monte Carlo harness
  that silently sampled nothing would otherwise produce a plausible record.

### Runner options

| Flag | Effect |
|---|---|
| `--print-env` | print PDK env exports and exit |
| `--process tt,ss` / `--temp 27` / `--supply 3.3` | override a matrix axis (marks the run a subset) |
| `--quick` | run the manifest's `quick_subset` only |
| `--subset-reason "…"` | **required** for any subset; recorded verbatim |
| `--supersedes <record-id>` | record which prior record this replaces |
| `--author`, `--timeout` | record author (default `git config user.email`), per-corner ngspice timeout |
| `--allow-pdk-mismatch` | run against a non-pinned PDK; the record flags it |
| `--dry-run` | netlist, print the corner list and one deck, write nothing under `sim/<slug>/` |

Exit status: `0` all checks passed, `2` a record was written but something
failed, `1` harness/setup error (no record written).

---

## `pdk-smoke` — the harness's own testbench

`sim/pdk-smoke/` is not a spec claim. A 1 MΩ resistor biases a diode-connected
sky130 `nfet_g5v0d10v5` (the 5 V I/O device family the 3.3 V supply implies)
and the runner measures `vgs` and the supply current. Both quantities are
strongly process- and temperature-dependent, so this experiment proves four
things at once: the PDK models load, xschem netlists headlessly, ngspice parses
the deck, and the corner/temperature/supply knobs actually reach the
simulator (asserted by the `vgs` spread check, not just eyeballed).

Keep it green: it is the first thing to run when a testbench misbehaves, to
tell "my circuit is wrong" apart from "my harness is broken".
