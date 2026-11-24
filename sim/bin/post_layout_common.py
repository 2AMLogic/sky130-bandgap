#!/usr/bin/env python3
"""Shared helpers for post-layout (extracted-netlist) `sim/*-post-layout/`
experiment scripts (issue #16).

Post-layout re-verification needs a `bandgap_core` netlist body that is
genuinely derived from the routed layout (`layout/bandgap-core/`,
issue #62) rather than `design/bandgap_core.sch` -- otherwise a "post-layout"
record would just be a relabeled schematic run, the exact failure mode
issue #16's own history (the reversed 2026-08-03 Champion promotion) warns
against. (Since issue #621 the layout inputs themselves resolve through the
record's artifact manifest when the record is store-backed -- see
`resolve_latest_layout` -- and the selected record's actual LVS verdict,
flavour gate and input digests are carried in every record's
`layout_provenance` instead of an "LVS-clean" assertion in the claim.)
Building that netlist takes three steps, each with its own
non-obvious wrinkle this module documents and handles once:

1. **Extract parasitics from the composed GDS**
   (`run_klt_extract_parasitics`): `klt extract --parasitics` writes a
   flat, device-level SPICE netlist with a real per-net star RC network
   already spliced in (one series R per device terminal to a net "hub" plus
   one lumped ground capacitance at the hub, from the deck's curated
   sheet-resistance/capacitance table) -- see `docs/cli/extract.md` in
   `2AMLogic/klayout-tools`. This is a genuinely distributed parasitic
   model, not a single lumped R+C per net.

2. **Translate the device classes to simulatable vendor models**
   (`translate_extracted_netlist`): `klt extract`'s own SPICE output uses
   generic LVS device-class placeholder model names (`nfet`, `pfet`, `pnp`,
   `res_high_po`) that are NOT names ngspice's sky130 model library
   recognizes -- they exist purely for `klt lvs`'s own comparator. There is
   no `klt` flag or documented path to a directly ngspice-simulatable
   extracted netlist. This is exactly the kind of tool gap CLAUDE.md's
   friction protocol asks to surface -- see the PR this module ships with
   for the filed issue.

   The translation this module performs is deliberately narrow, scoped to
   what THIS design's own extracted device set actually contains (verified
   empirically against `layout/bandgap-core/reports/LATEST`, not assumed):

   - `nfet`/`pfet` (M-card, `L=`/`W=`/`AS=`/`AD=`/`PS=`/`PD=` only) ->
     `X`-line instantiating `sky130_fd_pr__nfet_g5v0d10v5` /
     `..._pfet_g5v0d10v5` (the same vendor subckt `design/bandgap_core.sch`
     and `design/error_amp.sch` already instantiate) with the SAME drawn
     geometry the layout extraction reports -- real per-instance diffusion
     area/perimeter, not the schematic's formulaic approximation. Adds
     `nrd`/`nrs` at the schematic's own `0.29/W_um` convention (a
     second-order diffusion series-resistance term the extracted netlist
     does not itself carry) and pins `sa=sb=sd=0` (LOD stress off, matching
     every schematic instance) since the extraction has no stress-geometry
     data to offer instead.
   - `pnp` (Q-card, `AE=`/`PE=`/... geometry, class always `pnp`) -> `X`-line
     instantiating the real vendor macro cell. sky130's PNPs are FIXED,
     non-parametric macros (`sky130_fd_pr__pnp_05v5_W0p68L0p68` /
     `..._W3p40L3p40`) with no W/L/area argument at all -- see
     `layout/bandgap-core/reports/LATEST/record.md`'s "PNP ae/pe/ne
     transcription gap" note. This design draws exactly two unit sizes
     (`AE=0.4624` um^2 small/CTAT, `AE=11.56` um^2 large/PTAT -- 8 units
     each, confirmed by direct inspection of every extracted `Q$` line),
     so `AE` alone (a simple `< 1.0` threshold) selects the right macro;
     `AE`/`PE`/etc. are otherwise discarded (the macro does not take them).
   - `res_high_po` (3-terminal `R<name> a b bulk value res_high_po`) -> a
     plain 2-terminal `R<name> a b value` primitive, at the SAME per-unit
     value `klt extract` already resolved (independently cross-checked
     against `sim/trim-lsb-chained`'s own `HEAD_OHM`/`BODY_OHM_PER_UM`
     model: the extracted 2003.841367 ohm / 5 um coarse unit and 542.118769
     ohm / 0.5 um fine unit both reproduce that model's
     `HEAD_OHM + BODY_OHM_PER_UM * length_um` formula exactly). Dropping the
     bulk terminal loses body-effect/leakage coupling to substrate, a
     documented, deliberate first-order simplification -- the star RC
     network from step 1 already carries the dominant layout-vs-schematic
     delta (real routing parasitics), and every unit's own value already
     includes its real per-instance head resistance.
   - `vsubs` (the parasitic network's synthesized substrate/ground-plane
     net, one shunt capacitor endpoint per named net) -> tied to `VSS`
     directly (text substitution), per the same substrate-identity finding
     `layout/bandgap-core/reports/LATEST/record.md`'s SUBSTRATE_NET_NOTE
     already established for device bulk terminals: this design's real
     substrate is the drawn `VSS` net, not an independent global.

  **The PDK-bound dialect (issue #614).** Since #614 the shared path
  extracts with `--pdk <variant>`, and klt writes each device already
  bound to its PDK subcircuit; `translate_extracted_netlist` passes bound
  resistor and PNP cards through UNCHANGED (they carry the bulk terminal,
  the drawn geometry and the model's own temperature behaviour, which the
  fixed `R` card above is provably flat on -- sim/pex-native/README.md's
  "Resistor value and temperature behaviour" table) and rewrites only the
  bound MOS cards, because the binding keys the MOS flavour off the drawn
  `hvi` marker and this layout draws none, so klt binds `_01v8` while the
  design instantiates `g5v0d10v5` -- see `_X_BOUND_RES_RE`'s block comment
  for the full story and the filed issues. The generic-card translation
  above stays live for the committed klt-0.5.0 snapshot
  `sim/startup-time-post-layout/` pins for layout record 20260923-070209-dbd57a9.

3. **A discovered ngspice/sky130-model quirk this module works around**:
   sky130's `g5v0d10v5` MOS models are BSIM4 BINNED models
   (`nhv_model.1..N` / `phv_model.1..N`, selected by `L`/`W` range). Giving
   an INSTANCE's `L=`/`W=`/`AS=`/`AD=`/`PS=`/`PD=` an explicit unit suffix
   (`L=20u`, `AS=3.36p` -- exactly the form `klt extract` writes) makes
   ngspice's bin-selection fail with "could not find a valid modelname",
   reproduced in isolation down to a single-device deck, REGARDLESS of
   nesting depth -- while the bare, suffix-less form
   (`L=20`, relying on the deck's ambient `.option scale=1e-6`, which is
   exactly how `design/bandgap_core.sch`'s own xschem netlisting writes
   every `XM*` line) resolves the identical scaled value correctly. This is
   an ngspice/sky130-PDK interaction, not a `klt` gap, so it is not filed
   upstream -- `translate_extracted_netlist` strips the suffix instead.

Callers chain these three pieces plus
`build_core_wrapper`/`strip_schematic_subckts` to produce a `bandgap_core`
netlist body that is a drop-in replacement for `design/bandgap_core.sym` in
ANY existing `sim/*/testbench/*.sch` that instantiates it (same 4-pin
interface: `VOUT GDRV VDD VSS`) -- this is what lets a follow-on increment
of issue #16 reuse this module for `psrr-dc`, `line-regulation`,
`quiescent-current`, `startup-time`, `startup-stability`, `startup-ramp`
without re-deriving any of the above.

4. **One generic per-bench runner** (`run_post_layout_experiment`): the
   chaining itself, the record minting, the append-only refusal, the corner
   loop and the `provenance: extracted` record schema are IDENTICAL for
   every bench -- the only per-bench variables are the experiment slug, its
   testbench, the claim sentence and whether that bench's own manifest matrix
   is collapsed on an axis the deck sweeps internally. So each
   `sim/<slug>-post-layout/run_*.py` is a ~40-line declaration of those
   variables, not a copy of the runner (`sim/README.md`'s "copy this script"
   note predates this distillation; copying is no longer the pattern).

   Most post-layout benches WRAP their schematic-level sibling's manifest and
   testbench unchanged, so the only variable between the two benches' records
   is the DUT body. Two of them cannot, and carry their own `experiment.json`
   + `testbench/` instead (issue #299): `sim/startup-stability-post-layout/`
   and `sim/startup-ramp-post-layout/`, whose schematic-level siblings measure
   quantities that are differences against a BARE-CORE control instance --
   and since issue #285 drew `design/startup_injector.sch` into the composed
   cell, no bare extracted core exists to be that control. Those two pass
   `claim_tail=None`; see `run_post_layout_experiment`'s own docstring.

5. **The parasitics extraction is shared across benches**
   (`resolve_parasitics_snapshot`): every post-layout record for a given
   `layout/bandgap-core/reports/<record-id>` must measure the SAME extracted
   netlist, otherwise cross-bench comparisons (Iq at the operating point
   `output-voltage-tc` reported, say) would silently be against different
   DUTs. The first bench to run for a layout record commits the snapshot
   under its own `parasitics-snapshot/<layout-record-id>-pdk/`; later benches
   find and reuse it in place rather than re-extracting a second copy.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "ci"))
from content_hash import sha256_file  # noqa: E402

import batch_sim
import sim_common


class PostLayoutError(RuntimeError):
    """A problem the operator has to fix; never produces a record."""


# --------------------------------------------------------------------------
# layout resolution
# --------------------------------------------------------------------------


def resolve_latest_layout(
    bandgap_core_dir: Path, cache_root: Path | None = None
) -> tuple[str, Path, Path, dict]:
    """Resolve `layout/bandgap-core/reports/LATEST` to
    (record_id, record_dir, gds, gds_source).

    Reference-only reads under `layout/` -- never writes there (issue #16's
    Affected Files scope: `layout/` is reference-only).

    The routed GDS is resolved in either of the two forms a record ships
    (issue #621): a historical in-tree record carries
    `bandgap_core_routed.gds` inside its own report directory, while a
    store-backed record (issue #440's operator ruling) keeps the bytes in
    the fleet artifact store and git keeps only the manifest -- so the GDS
    is fetched with `klt artifact get <manifest>#<entry>` into a cache under
    `sim/build/layout-artifacts/` (gitignored harness scratch), digest-
    verified against the manifest both by `klt` itself and again here. A
    missing artifact or digest mismatch raises naming the failing record,
    before any simulation is spent.

    `gds_source` records which form resolved and the durable citation (the
    manifest path, entry name and sha256 for store-backed records; the
    in-tree repo-relative path for historical ones) so a record's
    provenance can repeat the run even when the download directory differs.
    """
    latest_file = bandgap_core_dir / "reports" / "LATEST"
    if not latest_file.is_file():
        raise PostLayoutError(f"no LATEST pointer at {latest_file}")
    record_id = latest_file.read_text().strip()
    record_dir = bandgap_core_dir / "reports" / record_id
    gds, gds_source = resolve_record_gds(
        bandgap_core_dir, record_id, record_dir, cache_root=cache_root
    )
    return record_id, record_dir, gds, gds_source


def _sha256_of(path: Path) -> str:
    """Bare-hex SHA-256 of a file, via the repo's one implementation
    (`scripts/ci/content_hash.py`, issue #538) -- the form manifest `sha256`
    fields and the `*_sha256` provenance keys carry."""
    return sha256_file(path)


def layout_artifact_manifest_relpath(record_id: str) -> str:
    """Repo-relative path of a bandgap-core record's artifact manifest
    (`manifests/artifacts/layout-bandgap-core-<record-id>.manifest.json`,
    the name `layout/`'s own flow writes)."""
    return f"manifests/artifacts/layout-bandgap-core-{record_id}.manifest.json"


def _manifest_gds_entry(manifest: dict, record_id: str) -> dict:
    """The record's own `bandgap_core_routed.gds` entry from its manifest.

    Preferred by the exact staging name
    `layout/bandgap-core/staging/<record-id>/bandgap_core_routed.gds`;
    a unique basename match is accepted so a renamed staging prefix still
    resolves. Anything else raises naming the record.
    """
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise PostLayoutError(
            f"layout record {record_id}: artifact manifest "
            f"{layout_artifact_manifest_relpath(record_id)} has no entries[] list"
        )
    wanted = f"layout/bandgap-core/staging/{record_id}/bandgap_core_routed.gds"
    for entry in entries:
        if isinstance(entry, dict) and entry.get("name") == wanted:
            return entry
    by_basename = [
        entry
        for entry in entries
        if isinstance(entry, dict)
        and Path(str(entry.get("name", ""))).name == "bandgap_core_routed.gds"
    ]
    if len(by_basename) == 1:
        return by_basename[0]
    raise PostLayoutError(
        f"layout record {record_id}: no bandgap_core_routed.gds entry in artifact "
        f"manifest {layout_artifact_manifest_relpath(record_id)}, and no routed GDS "
        "in the record directory -- cannot resolve the layout input"
    )


def fetch_record_gds_from_store(
    repo_root: Path, record_id: str, entry: dict, cache_root: Path
) -> Path:
    """Fetch one record's routed GDS through `klt artifact get`, into
    `cache_root/<record-id>/bandgap_core_routed.gds`.

    `klt artifact get` itself refuses to write bytes whose recomputed
    sha256 does not match the manifest's; the digest is re-checked here so
    a tampered cache file that somehow landed cannot ride through either.
    A cache file whose digest no longer matches (a stale or partial
    download) is replaced via `--force` rather than trusted.
    """
    name = str(entry.get("name", ""))
    expected_sha = entry.get("sha256")
    cache = cache_root / record_id / "bandgap_core_routed.gds"
    if cache.is_file() and (expected_sha is None or _sha256_of(cache) == expected_sha):
        return cache
    cache.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["klt", "artifact", "get", f"{layout_artifact_manifest_relpath(record_id)}#{name}"]
    if cache.is_file():
        cmd.append("--force")
    cmd += ["-o", str(cache)]
    try:
        proc = subprocess.run(
            cmd, cwd=str(repo_root), capture_output=True, text=True, timeout=600
        )
    except FileNotFoundError as exc:
        raise PostLayoutError(f"klt not found on PATH: {exc}") from exc
    if proc.returncode != 0:
        raise PostLayoutError(
            f"layout record {record_id}: klt artifact get failed for '{name}' "
            f"(rc={proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}"
        )
    if not cache.is_file():
        raise PostLayoutError(
            f"layout record {record_id}: klt artifact get reported success for "
            f"'{name}' but no file landed at {cache}"
        )
    if expected_sha is not None:
        got = _sha256_of(cache)
        if got != expected_sha:
            raise PostLayoutError(
                f"layout record {record_id}: fetched GDS digest {got} does not match "
                f"the manifest's {expected_sha} for '{name}'"
            )
    return cache


def resolve_record_gds(
    bandgap_core_dir: Path,
    record_id: str,
    record_dir: Path,
    cache_root: Path | None = None,
) -> tuple[Path, dict]:
    """Resolve one record's routed GDS: in-tree first, then the store.

    Returns (gds_path, source) where source names the form that resolved
    (see `resolve_latest_layout`). Historical in-tree records (issue #16's
    era, GDS committed beside the verdict JSONs) resolve exactly as they
    always did; store-backed records (issue #440 onward) resolve through
    the artifact manifest and need `$KLT_ARTIFACT_BROKER` reachability.
    """
    in_tree = record_dir / "bandgap_core_routed.gds"
    if in_tree.is_file():
        return in_tree, {"kind": "in-tree", "sha256": _sha256_of(in_tree)}
    repo_root = bandgap_core_dir.parent.parent
    if cache_root is None:
        cache_root = SIM_DIR / "build" / "layout-artifacts"
    manifest_path = repo_root / layout_artifact_manifest_relpath(record_id)
    if not manifest_path.is_file():
        raise PostLayoutError(
            f"layout record {record_id}: no routed GDS in the record directory and no "
            f"artifact manifest at {layout_artifact_manifest_relpath(record_id)} -- a "
            "fresh checkout cannot resolve this record's layout input (historical "
            "records carry bandgap_core_routed.gds in the record directory; "
            "store-backed records need their manifest and $KLT_ARTIFACT_BROKER)"
        )
    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as exc:
        raise PostLayoutError(
            f"layout record {record_id}: artifact manifest "
            f"{layout_artifact_manifest_relpath(record_id)} is not valid JSON: {exc}"
        ) from exc
    entry = _manifest_gds_entry(manifest, record_id)
    gds = fetch_record_gds_from_store(repo_root, record_id, entry, cache_root)
    try:
        cache_rel = str(gds.relative_to(repo_root))
    except ValueError:
        cache_rel = str(gds)
    source = {
        "kind": "artifact-store",
        "manifest": layout_artifact_manifest_relpath(record_id),
        "entry": entry.get("name"),
        "sha256": entry.get("sha256"),
        "size": entry.get("size"),
        "cache": cache_rel,
    }
    return gds, source


#: A companion summary's "Not stored (identical bytes are already tracked
#: in git)" row for the reference netlist:
#: `| reference.spice | <sha256> | \`<repo-relative tracked path>\` |`.
#: The tracked path and the digest the injector check verifies both come
#: from this row -- the record's own summary is the authority for which
#: committed file states its reference netlist (issue #621).
_COMPANION_REFERENCE_ROW_RE = re.compile(
    r"^\|\s*reference\.spice\s*\|\s*([0-9a-f]{64})\s*\|\s*`([^`]+)`\s*\|\s*$",
    re.M,
)


def resolve_record_reference(
    bandgap_core_dir: Path, record_id: str, record_dir: Path
) -> tuple[Path, dict]:
    """Resolve one record's reference netlist: in-tree first, then the
    tracked copy named by the record's companion artifact-store summary.

    Returns (reference_path, source). The store-backed records commit no
    `reference.spice` beside their verdicts (the bytes are unchanged and
    already tracked), so the companion summary's "Not stored" row names the
    tracked path and the sha256 it must hash to -- verified BEFORE the
    injector check reads the file, so a drifted `layout/bandgap-core/
    reference.spice` cannot silently change what `layout_record_draws_injector`
    reports about a record.
    """
    in_tree = record_dir / "reference.spice"
    if in_tree.is_file():
        return in_tree, {"kind": "in-tree"}
    repo_root = bandgap_core_dir.parent.parent
    summary_rel = f"manifests/artifacts/layout-bandgap-core-{record_id}.md"
    summary_path = repo_root / summary_rel
    if not summary_path.is_file():
        raise PostLayoutError(
            f"no reference.spice in layout record {record_dir} and no companion "
            f"summary at {summary_rel} to resolve a tracked copy"
        )
    m = _COMPANION_REFERENCE_ROW_RE.search(summary_path.read_text())
    if not m:
        raise PostLayoutError(
            f"layout record {record_id}: companion summary {summary_rel} lists no "
            "tracked reference.spice row (expected a "
            "'| reference.spice | <sha256> | `<repo path>` |' entry)"
        )
    sha_hex, tracked = m.group(1), m.group(2)
    tracked_path = repo_root / tracked
    if not tracked_path.is_file():
        raise PostLayoutError(
            f"layout record {record_id}: tracked reference netlist {tracked} (named by "
            f"{summary_rel}) is not a file in this checkout"
        )
    got = _sha256_of(tracked_path)
    if got != sha_hex:
        raise PostLayoutError(
            f"layout record {record_id}: tracked reference {tracked} hashes to {got}, "
            f"but the companion summary pins {sha_hex} -- the committed reference "
            "netlist has drifted from the one this record's verdicts were made against"
        )
    return tracked_path, {"kind": "tracked", "path": tracked, "sha256": sha_hex}


#: Device cards `layout/bandgap-core/reference.spice` states for the startup
#: injector (issue #285). The layout flow copies its reference netlist into
#: every record directory, so the record itself says whether the cell it
#: describes draws the injector -- no GDS parsing needed.
_INJECTOR_REFERENCE_CARDS = ("MMPC1", "MMPC2", "MMNS", "MMNI", "MMNC", "QQS")


def layout_record_draws_injector(
    record_dir: Path, bandgap_core_dir: Path | None = None
) -> bool:
    """True if this layout record's own reference netlist carries the startup
    injector's devices, i.e. the composed cell draws it (issue #285).

    `bandgap_core_dir` defaults to the repo's `layout/bandgap-core/` (the
    module constant); pass it explicitly when `record_dir` is not under the
    default one, as the synthetic-record tests do.
    """
    if bandgap_core_dir is None:
        bandgap_core_dir = LAYOUT_BANDGAP_CORE_DIR
    reference, _source = resolve_record_reference(
        bandgap_core_dir, record_dir.name, record_dir
    )
    text = reference.read_text()
    return all(re.search(rf"^{card}\s", text, re.M) for card in _INJECTOR_REFERENCE_CARDS)


def require_layout_draws_injector(slug: str) -> None:
    """Abort a startup bench whose whole claim is about the COMPOSED cell --
    core + injector as drawn -- if the layout record under test does not draw
    the injector (issue #299).

    This is the structural precondition that replaced the bare-core CONTROL
    instances `sim/startup-stability-post-layout/` and
    `sim/startup-ramp-post-layout/` used to carry. Until issue #285 those
    benches wrapped their schematic-level testbench unchanged: the extracted
    core swapped in for every `design/bandgap_core.sym` instance while the
    testbench's own separately netlisted `design/startup_injector.sym`
    instances stayed schematic-level, and its bare-core control instances
    stayed bare. #285 drew the injector into the composed cell, which
    falsifies both halves of that construction at once -- the DUT instances
    would carry TWO injectors and the controls would silently become
    injector-equipped, with nothing in the output saying so.

    The restructured benches (issue #299) instantiate `design/bandgap_core.sym`
    ALONE and rely on the extracted body to supply the injector, so the
    dangerous direction is now the opposite one: running them against a
    core-only layout record would quietly measure an unprotected core and
    report it as the composed cell. Hence this guard, which is the mirror image
    of the `refuse_if_layout_draws_injector()` guard it replaces.

    A missing injector would also fail those benches' own bounds
    (`imin_off_su`/`i_off_su` collapse to leakage level; `t_start_g` finds no
    VREF crossing at all) -- but a precondition that names the cause beats a
    corner matrix full of unexplained FAILs, and it fires before any ngspice
    time is spent.
    """
    record_id, record_dir, _gds, _gds_source = resolve_latest_layout(LAYOUT_BANDGAP_CORE_DIR)
    if layout_record_draws_injector(record_dir, LAYOUT_BANDGAP_CORE_DIR):
        return
    raise PostLayoutError(
        f"{slug}: refusing to run against layout record {record_id}, whose own "
        "reference netlist does NOT state the startup injector's six device "
        "cards (MPC1, MPC2, MNS, MNI, MNC, QS). This bench's DUT is the "
        "COMPOSED cell: its testbench instantiates design/bandgap_core.sym "
        "alone and expects the extracted body to supply the injector, so "
        "running against a core-only layout record would measure an "
        "unprotected core and record it as the composed cell (issue #299). "
        "Re-run against a layout record that draws the injector (issue #285), "
        "or use the schematic-level bench for a bare-core claim."
    )


# --------------------------------------------------------------------------
# klt extract --parasitics
# --------------------------------------------------------------------------


def _has_existing_snapshot_target(path: Path) -> bool:
    """True when `path` already holds non-empty evidence (or is a file/symlink).

    An empty directory carries no snapshot evidence and may be atomically
    replaced by a fresh staged extraction; a non-empty directory, regular file,
    or symlink is preserved per `sim/`'s append-only rule.
    """
    if path.is_symlink():
        return True
    if not path.exists():
        return False
    return (not path.is_dir()) or any(path.iterdir())


def _recorded_pdk_commit(summary: dict) -> str | None:
    """Extract the `open_pdks <commit>` revision from `provenance.pdk.version`.

    `klt` joins non-empty lines of `<pdk>/SOURCES` with `"; "`. Returns None
    when `provenance.pdk.version` is absent or carries no `open_pdks` entry.
    """
    version = ((summary.get("provenance") or {}).get("pdk") or {}).get("version")
    if not isinstance(version, str):
        return None
    for entry in version.split(";"):
        fields = entry.split()
        if len(fields) >= 2 and fields[0] == "open_pdks":
            return fields[1]
    return None


def _snapshot_key_tag(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", value)


def run_klt_extract_parasitics(
    gds: Path,
    out_dir: Path,
    deck: str = "sky130",
    top: str = "bandgap_core_routed",
    timeout: int = 300,
    pdk_variant: str | None = None,
    pdk_root: str | None = None,
) -> tuple[Path, dict]:
    """Run `klt extract --parasitics` against `gds`, writing the SPICE
    netlist + JSON summary into `out_dir`. Returns (spice_path, json_dict).

    With `pdk_variant` (issue #614) the extraction also passes `--pdk` (and
    `--pdk-root` when given), so klt binds every device card to its PDK
    subcircuit (``X$.. sky130_fd_pr__res_high_po l=5 w=1`` with geometry and
    bulk terminal, the fixed PNP macros, and the ``_01v8``/``g5v0d10v5`` MOS
    wrappers by drawn flavour marker) instead of writing generic LVS class
    cards. The summary's ``provenance.pdk`` records the resolved install.

    Extraction is staged in a sibling temporary directory and atomically
    published to `out_dir` only once both `.pex.spice` and `.pex.json` are
    valid, so a failed or interrupted attempt leaves no partial or empty
    `out_dir` blocking a retry while existing non-empty evidence stays
    append-only.
    """
    if _has_existing_snapshot_target(out_dir):
        raise PostLayoutError(
            f"{out_dir} already exists and is non-empty; "
            "snapshots are append-only, refusing to overwrite"
        )
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    stage_dir = Path(tempfile.mkdtemp(prefix=f".{out_dir.name}.tmp-", dir=out_dir.parent))
    spice_out = out_dir / f"{top}.pex.spice"
    try:
        spice_stage = stage_dir / f"{top}.pex.spice"
        cmd = [
            "klt",
            "extract",
            str(gds),
            "--deck",
            deck,
            "--top",
            top,
            "--parasitics",
            "--format",
            "json",
            "-o",
            str(spice_stage),
        ]
        if pdk_variant:
            cmd += ["--pdk", pdk_variant]
            if pdk_root:
                cmd += ["--pdk-root", pdk_root]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError as exc:
            raise PostLayoutError(f"klt not found on PATH: {exc}") from exc
        if proc.returncode != 0:
            raise PostLayoutError(
                f"klt extract --parasitics failed (rc={proc.returncode})\n"
                f"  cmd: {' '.join(cmd)}\n  stdout: {proc.stdout}\n  stderr: {proc.stderr}"
            )
        if not spice_stage.is_file():
            raise PostLayoutError(f"klt extract did not produce {spice_stage}")
        try:
            summary = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise PostLayoutError(
                f"klt extract --format json did not print valid JSON: {exc}"
            ) from exc
        if not isinstance(summary, dict):
            raise PostLayoutError(
                f"klt extract --format json did not print a JSON object: {type(summary).__name__}"
            )
        if summary.get("netlist_path") in (str(spice_stage), str(spice_stage.resolve())):
            summary["netlist_path"] = str(spice_out)
        json_stage = stage_dir / f"{top}.pex.json"
        json_stage.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        if _has_existing_snapshot_target(out_dir):
            raise PostLayoutError(
                f"{out_dir} appeared while extracting; "
                "snapshots are append-only, refusing to overwrite"
            )
        try:
            stage_dir.replace(out_dir)
        except OSError as exc:
            raise PostLayoutError(
                f"failed to publish parasitics snapshot to {out_dir}: {exc}"
            ) from exc
    except BaseException:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise
    return spice_out, summary


# --------------------------------------------------------------------------
# device-class translation (generic LVS placeholders -> simulatable vendor models)
# --------------------------------------------------------------------------

_MOS_GEOMETRY_UNIT_RE = re.compile(
    r"(?<!\S)((?:L|W|AS|AD|PS|PD)\s*=\s*[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?)[UP]\b",
    re.I,
)
_M_RE = re.compile(r"^(M\$\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(nfet|pfet)\s+(.*)$")
_Q_RE = re.compile(r"^(Q\$\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+pnp\s+AE=([0-9.]+)P.*$")
# Trailing device parameters after the model name are OPTIONAL and ignored.
# They have to be: KLayout 0.30.10 wrote `R$n <a> <b> <bulk> <value>
# res_high_po` and 0.30.12 writes `... res_high_po L=5U W=1U`, and this
# pattern was anchored on `res_high_po$`. Against the newer writer it matched
# nothing at all, so every resistor fell through untranslated and
# `run_post_layout_experiment`'s own translation-coverage guard aborted the
# run (`translated ... res=0, extraction reports ... res_high_po=145`) --
# which is the guard doing its job, but it stopped every post-layout bench in
# the suite from running at all. The geometry is not needed either way: the
# translated card is a plain ngspice resistor stated at the extracted
# `<value>` in ohms, so L/W carry no information the value does not already
# carry. Reproduced on the unmodified pre-issue-#285 layout record, i.e. this
# is an environment/KLayout-version brittleness, not a layout change.
_R_RE = re.compile(
    r"^(R\$\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+([0-9.]+)\s+res_high_po\b.*$"
)

# klt 0.8.0 (issue #540) emits the SAME resistor as a subcircuit-style card
# with an `X` prefix and the value moved into a NAMED parameter, after the
# device-class name rather than before it:
#
#   klt 0.5.0:  R$98 <a> <b> <bulk> 2003.841367 res_high_po L=5U W=1U
#   klt 0.8.0:  X$98 <a> <b> <bulk> res_high_po r=2003.841367 L=5U W=1U
#
# `_R_RE` matches neither prefix nor parameter shape there, so against a
# 0.8.0 extraction all 145 resistors fell through untranslated and
# `build_extracted_body`'s coverage guard aborted the run (`translated ...
# res=0, extraction reports ... res_high_po=145`) -- the guard working, but
# it blocks the bench entirely. This is the THIRD resistor card shape this
# translator has had to absorb (see `_R_RE`'s own 0.30.10-vs-0.30.12 note):
# the extracted netlist's per-device card syntax is not a stable contract
# across klt releases, filed generically as the tool gap
# 2AMLogic/klayout-tools#5741.
#
# `sim/pex-native/pexlib.normalize_klt_resistors` (issue #335) already
# absorbs this same 0.8.0 dialect by pre-normalising the card back to the
# `R$` form, deliberately "instead of editing the shared translator" --
# correct while that pilot was the only consumer of a 0.8.0 extraction.
# Issue #540 brings a 0.8.0 extraction onto the SHARED post-layout path, so
# the shared translator now has to recognise the dialect natively; the
# pilot's local normaliser is left exactly as it is (it feeds its own flow,
# and `sim/pex-native/` is #335's and #541's area, not this issue's). The
# value character class is copied from that normaliser's `_X_RES_RE` rather
# than from `_R_RE`, so an exponent-form value parses on this path too.
#
# Matched ADDITIVELY, as a second pattern rather than a rewrite of `_R_RE`:
# `sim/startup-time-post-layout/` still reads its committed klt 0.5.0
# snapshot (it resolves its own local snapshot at step 1, before the
# sibling glob; issue #560 moved the other five and disclosed it there), so
# the old shape has to keep translating byte-identically. A 0.5.0 snapshot
# contains no `X$` cards at all and a 0.8.0 snapshot no `R$` cards, so the
# two patterns are mutually exclusive by construction.
# Device-instance numbers are unique across classes, so renaming `X$98` to
# `R$98` cannot collide with the `X$`-prefixed MOS/PNP cards this function
# emits. The dropped bulk terminal and the discarded L/W are the same
# deliberate simplifications `_R_RE` documents, for the same reason.
_R_SUBCKT_RE = re.compile(
    r"^X(\$\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+res_high_po\s+r=([0-9.eE+-]+)\b.*$"
)

# --------------------------------------------------------------------------
# PDK-BOUND cards (issue #614): `klt extract --parasitics --pdk <variant>`
# binds each device to its PDK subcircuit instead of a generic class card,
# so the resistor rewrite above is retired for these netlists -- the bound
# card IS the vendor model, with its bulk terminal and drawn geometry, and
# it carries the model's own temperature behaviour (the fixed `R` card the
# legacy translation emits is temperature-flat, which made the extracted
# side's vref_min/vref_max/box-TC observables not like-for-like against the
# schematic side; sim/pex-native/README.md's "Resistor value and temperature
# behaviour" table measured the split: the model moves +5.2 % / -2.4 % over
# -40..125 C while the card stayed flat). Bound dialects (klt 0.8.0):
#
#   X$98 <a> <b> <bulk> sky130_fd_pr__res_high_po l=5 w=1
#   X$74 <c> <b> <e> sky130_fd_pr__pnp_05v5_W0p68L0p68 | ..._W3p40L3p40
#   X$1  <d> <g> <s> <b> sky130_fd_pr__nfet_01v8 L=20 W=8 AS=3.36 ...
#
# Resistors and PNPs pass through UNCHANGED (counted, so the coverage guard
# still holds). MOS cards are the one class still rewritten: the binding
# keys the MOS flavour off the drawn `hvi` marker layer (75/20), and this
# design's routed GDS draws none, so klt binds every MOS to the thin-oxide
# `_01v8` pair while the design's own schematics instantiate the 5 V
# `g5v0d10v5` pair for all 73 devices (the layout-record finding is filed as
# its own issue; the binding has no flavour override, filed generically at
# 2AMLogic/klayout-tools). Simulating the bound `_01v8` cards as-is would
# swap the extracted side's transistors to a different oxide flavour than
# the schematic side's, a far larger like-for-like artefact than the one
# this issue removes -- so per the issue's step 4 the MOS class keeps the
# local translation. A marked device already has the intended model. Both
# dialects preserve geometry and explicit parameters. Missing nrd/nrs take
# this design's `0.29/w` convention (the PDK wrapper defaults to `0.14/w`).
#
# The `l=`/`w=` parameter names (lowercase, no unit suffix) are the
# convention `sky130_fd_pr__res_high_po`'s own `.subckt` declares; the
# PDK's model library sets `.option scale=1.0u` globally
# (continuous/models_global.spice), so the bare micrometre numbers resolve
# exactly as the schematic's `W=1 L=5` calls do -- verified by probe at the
# 0.8.0 pin: 1955.24 / 2003.84 / 2108.60 ohm at -40 / 27 / 125 C, tt,
# against 2003.843 ohm extracted at 27 C.
_X_BOUND_RES_RE = re.compile(
    r"^(X\$\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+sky130_fd_pr__res_high_po\s+"
    r"l=([0-9.]+)\s+w=([0-9.]+)\s*$"
)
#: The two fixed PNP macros are whitelisted by name: a bound netlist whose
#: PNP picked any other macro must fail the coverage guard, not pass an
#: unknown subckt silently on to ngspice.
_X_BOUND_PNP_RE = re.compile(
    r"^(X\$\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+"
    r"sky130_fd_pr__pnp_05v5_W(?:0p68L0p68|3p40L3p40)\s*$"
)
_X_BOUND_M_RE = re.compile(
    r"^(X\$\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+"
    r"sky130_fd_pr__(nfet|pfet)_(?:01v8|g5v0d10v5)\s+(.*)$"
)

# Boundary between the two PNP unit sizes this design draws (0.4624 um^2
# small/CTAT vs 11.56 um^2 large/PTAT) -- see module docstring point 2.
_PNP_AE_SMALL_LARGE_BOUNDARY_UM2 = 1.0

# design/bandgap_core.sch's / design/error_amp.sch's own nrd=nrs=0.29/W_um
# diffusion-series-resistance convention (reproduced by inspection of every
# XM* line in both schematics: 0.03625 @ W=8, 0.0145 @ W=20, 0.048333 @ W=6,
# 0.0096667 @ W=30 all solve k=0.29 exactly).
_NRD_NRS_K = 0.29


def translate_extracted_netlist(text: str) -> tuple[str, dict[str, int]]:
    """Translate `klt extract --parasitics`'s generic device-class SPICE
    into a directly ngspice-simulatable netlist against the pinned sky130
    PDK. See the module docstring for the full rationale per device class.

    Returns (translated_text, counts) where counts tallies how many of each
    device class were translated (a bound card that passes through unchanged
    counts the same as a legacy card that is rewritten) -- callers should
    assert this against the layout record's own documented device_counts as
    a translation-coverage guard (a class this function doesn't recognize is
    left untouched and will fail loudly at ngspice load time, but a SILENT
    undercount would not).
    """
    lines = text.splitlines()
    joined: list[str] = []
    for ln in lines:
        if ln.startswith("+") and joined:
            joined[-1] += " " + ln[1:].strip()
        else:
            joined.append(ln)

    out: list[str] = []
    counts = {"mos": 0, "pnp": 0, "res": 0}
    for ln in joined:
        s = ln.strip()

        m = _M_RE.match(s) or _X_BOUND_M_RE.match(s)
        if m:
            name, d, g, src, b, cls, rest = m.groups()
            model = f"sky130_fd_pr__{cls}_g5v0d10v5"
            geometry = _MOS_GEOMETRY_UNIT_RE.sub(r"\1", rest)
            supplied = dict(re.findall(r"(?<!\S)(\w+)\s*=\s*(\S+)", geometry.lower()))
            defaults = {}
            if "nrd" not in supplied or "nrs" not in supplied:
                squares = _NRD_NRS_K / float(supplied.get("w", "1"))
                defaults.update(nrd=f"{squares:.6f}", nrs=f"{squares:.6f}")
            defaults.update(nf=1, mult=1, sa=0, sb=0, sd=0)
            missing = [f"{key}={value}" for key, value in defaults.items() if key not in supplied]
            out.append(" ".join([f"X{name[1:]} {d} {g} {src} {b} {model}", geometry, *missing]))
            counts["mos"] += 1
            continue

        m = _Q_RE.match(s)
        if m:
            name, c, b, e, ae = m.groups()
            ae_um2 = float(ae)
            model = (
                "sky130_fd_pr__pnp_05v5_W0p68L0p68"
                if ae_um2 < _PNP_AE_SMALL_LARGE_BOUNDARY_UM2
                else "sky130_fd_pr__pnp_05v5_W3p40L3p40"
            )
            out.append(f"X{name[1:]} {c} {b} {e} {model} m=1")
            counts["pnp"] += 1
            continue

        m = _X_BOUND_PNP_RE.match(s)
        if m:
            out.append(s)
            counts["pnp"] += 1
            continue

        m = _R_RE.match(s)
        if m:
            name, a, b, _bulk, val = m.groups()
            out.append(f"{name} {a} {b} {val}")
            counts["res"] += 1
            continue

        m = _R_SUBCKT_RE.match(s)
        if m:
            name, a, b, _bulk, val = m.groups()
            out.append(f"R{name} {a} {b} {val}")
            counts["res"] += 1
            continue

        m = _X_BOUND_RES_RE.match(s)
        if m:
            out.append(s)
            counts["res"] += 1
            continue

        out.append(ln)

    result = "\n".join(out)
    result = re.sub(r"\bvsubs\b", "VSS", result)
    return result, counts


# --------------------------------------------------------------------------
# MOS flavour gate (issue #621): the PDK-bound extraction itself must bind
# the thick-oxide wrappers, BEFORE any local translation runs
# --------------------------------------------------------------------------

#: The wrapper cards a PDK-bound `klt extract --pdk sky130A` must emit for
#: every MOS finger once the geometry is thick-oxide, by polarity -- the
#: same mapping `layout/bin/gen_bandgap_routed.py`'s flavour gate (issue
#: #620) scores the layout flow's own raw extraction against.
_HVI_MOS_WRAPPER_MODELS = {
    "nfet": "sky130_fd_pr__nfet_g5v0d10v5",
    "pfet": "sky130_fd_pr__pfet_g5v0d10v5",
}

#: 0-based token index of a bound subckt-wrapper card's model name
#: (`X<name> d g s b <model> ...`) -- the same field
#: `layout/bin/gen_bandgap_routed.py`'s `X_CARD_MODEL_FIELD` reads.
_X_CARD_MODEL_FIELD = 5


def bound_mos_wrapper_census(netlist_text: str) -> dict[str, int]:
    """Count subckt-wrapper `X` cards per `sky130_fd_pr__*fet*` model name.

    The same census `layout/bin/gen_bandgap_routed.py`'s
    `raw_mos_card_counts()` performs on the layout flow's raw PDK-bound
    extraction, applied here to the parasitics snapshot the benches
    simulate: resistors (`res_high_po`) and PNPs never contain `fet`, so
    the count is a MOS-only census by construction.
    """
    counts: dict[str, int] = {}
    for line in netlist_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped[0] not in "Xx":
            continue  # '+' continuation lines never carry another card
        tokens = stripped.split()
        if len(tokens) <= _X_CARD_MODEL_FIELD:
            continue
        model = tokens[_X_CARD_MODEL_FIELD]
        if "sky130_fd_pr__" in model and "fet" in model:
            counts[model] = counts.get(model, 0) + 1
    return counts


def check_parasitics_mos_flavour(
    pex_text: str, expected: dict[str, int], record_id: str
) -> dict:
    """Gate the snapshot's raw MOS wrapper binding against the record's
    geometry-derived flavour counts, before `translate_extracted_netlist`
    rewrites a single MOS card (issue #621).

    `expected` is the record's own `flavour.json` `expected` block -- the
    finger counts #620 derived from `reference.spice`'s `m=` per polarity
    and confirmed on the raw PDK-bound extraction of this very GDS. The
    parasitics snapshot is extracted from the same GDS with the same
    `--pdk` binding, so its census must agree. Both halves of the check
    catch a SINGLE wrong card: one thin-oxide card among otherwise-correct
    devices leaves its polarity one short (caught by the exact-count
    comparison) even when the total MOS count still agrees, and adds one
    unexpected model to the census. A simulation-only model substitution
    cannot establish the oxide flavour -- the extraction must.
    """
    census = bound_mos_wrapper_census(pex_text)
    observed = {
        polarity: census.get(model, 0)
        for polarity, model in _HVI_MOS_WRAPPER_MODELS.items()
    }
    unexpected = {
        model: n
        for model, n in sorted(census.items())
        if model not in _HVI_MOS_WRAPPER_MODELS.values()
    }
    mismatches = {
        polarity: {"expected": expected[polarity], "observed": observed[polarity]}
        for polarity in _HVI_MOS_WRAPPER_MODELS
        if observed[polarity] != expected[polarity]
    }
    result = {
        "clean": not mismatches and not unexpected,
        "expected": dict(expected),
        "observed": observed,
        "unexpected_mos_models": unexpected,
        "mismatches": mismatches,
    }
    if not result["clean"]:
        detail = f"expected {expected}, observed {observed}"
        if unexpected:
            detail += f", unexpected wrapper models {unexpected}"
        raise PostLayoutError(
            f"layout record {record_id}: the PDK-bound parasitics snapshot's MOS "
            f"wrapper binding does not agree with the record's geometry-derived "
            f"flavour counts (flavour.json): {detail}. A single wrong-flavour card "
            "fails even when the total MOS count agrees, and a simulation-only "
            "model substitution cannot establish the oxide flavour (issue #621) -- "
            "the extraction itself must bind the thick-oxide wrappers"
        )
    return result


def layout_record_lvs_status(record_dir: Path, record_id: str) -> dict | None:
    """Read a record's committed combined LVS verdict, for provenance and
    the claim guard. Returns None when the record predates
    `lvs.combined.json` (the field stays null, as before); a present but
    unparseable verdict is an error naming the record, not a silent null.
    """
    path = record_dir / "lvs.combined.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise PostLayoutError(
            f"layout record {record_id}: lvs.combined.json is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise PostLayoutError(
            f"layout record {record_id}: lvs.combined.json is not a JSON object"
        )
    return {
        "status": data.get("status"),
        "mismatch_count": data.get("mismatch_count"),
        "report": f"layout/bandgap-core/reports/{record_id}/lvs.combined.json",
    }


def extract_subckt_block(text: str, name: str) -> str:
    """Pull out one `.SUBCKT <name> ... .ENDS <name>` block (case-insensitive)."""
    m = re.search(
        rf"(\.SUBCKT\s+{re.escape(name)}\b.*?\.ENDS\s+{re.escape(name)})",
        text,
        re.S | re.I,
    )
    if not m:
        raise PostLayoutError(f"no .SUBCKT {name} ... .ENDS block found")
    return m.group(1)


def parse_subckt_ports(text: str, name: str) -> tuple[str, ...]:
    """Parse the actual, as-extracted `.SUBCKT <name> <port> <port> ...`
    header's port list, in declaration order.

    `klt extract --parasitics` does not always promote the same top-level
    pin set `klt extract`'s plain (non-parasitics) pass does: a wider
    `ROUTE_WIDTH_UM` layout has been observed to additionally promote the
    synthesized substrate net (`vsubs`) to an explicit 12th `.SUBCKT` port
    that the plain-extraction 11-pin set (`D1 D2 GDRV PN TAIL VA VB VBQ VDD
    VOUT VSS`) does not carry -- see
    `spec/decision-records/DR-008-psrr-post-layout-margin-proposal.md`'s
    harness-fragility side finding. A caller that hardcodes the 11-pin order
    (`build_core_wrapper`'s previous default) silently mis-binds `XCORE`'s
    positional node list against a 12-port header in that case (ngspice then
    fails to resolve the call, reporting an "unknown subckt" style error
    instead of the real PSRR numbers) -- parsing the header actually written
    by this run's own extraction avoids assuming a fixed pin count.

    Ports may repeat (e.g. the promoted `vsubs` port, after
    `translate_extracted_netlist`'s blanket `vsubs` -> `VSS` text
    substitution, becomes a second literal `VSS` entry) -- this returns the
    header exactly as declared, duplicates included: `X<inst> <nodes...>
    <subckt>` binds a call to a `.SUBCKT` by POSITION, so a caller must
    supply as many actual nodes as the header lists, in the same positions,
    not a de-duplicated set.
    """
    m = re.search(
        rf"^\.subckt\s+{re.escape(name)}\s+(.+)$",
        text,
        re.I | re.M,
    )
    if not m:
        raise PostLayoutError(f"no .SUBCKT {name} header line found to parse ports from")
    return tuple(m.group(1).split())


def build_core_wrapper(
    core_subckt: str = "bandgap_core_routed",
    core_port_order: tuple[str, ...] = (
        "D1", "D2", "GDRV", "PN", "TAIL", "VA", "VB", "VBQ", "VDD", "VOUT", "VSS",
    ),
    exposed: tuple[str, ...] = ("VOUT", "GDRV", "VDD", "VSS"),
) -> str:
    """`.subckt bandgap_core VOUT GDRV VDD VSS ... .ends` wrapping the
    extracted, translated `bandgap_core_routed` netlist.

    `design/bandgap_core.sym` (and therefore every existing
    `sim/*/testbench/*.sch` that instantiates it) exposes exactly 4 pins:
    VOUT, GDRV, VDD, VSS (see `design/bandgap_core.sym`'s own header
    comment: "Pin order below is the order xschem emits into @pinlist").
    The routed layout promotes 11 top-level pins -- the same 4 plus 7
    amp-internal nodes (D1, D2, PN, TAIL, VA, VB, VBQ) the layout labels
    for LVS visibility (INTERNAL_NODE_LABEL_NOTE,
    `layout/bandgap-core/reports/LATEST/record.md`) but that
    `design/error_amp.sch` never exposes past `design/bandgap_core.sch`'s
    own boundary either. This wrapper maps the 4 real external pins through
    and gives the other 7 fresh, wrapper-local internal net names -- SPICE
    subckt scoping makes them genuinely internal to this one instance, byte
    for byte the same electrical topology `design/bandgap_core.sch` already
    keeps internal to its own `XAMP` call.

    `core_port_order` defaults to the usual 11-pin set but callers should
    pass the header actually parsed from this run's own extraction
    (`parse_subckt_ports`) rather than rely on the default -- see that
    function's docstring for why the promoted pin set is not always the
    same 11 (e.g. a wider `ROUTE_WIDTH_UM` layout promoting `vsubs` as a
    12th port). This function itself is agnostic to the exact count/order:
    it maps every port not in `exposed` to a fresh wrapper-local internal
    name and calls `XCORE` positionally against however many (and whichever)
    ports `core_port_order` actually lists, duplicates included.
    """
    unexposed = [p for p in core_port_order if p not in exposed]
    port_map = {p: p for p in exposed}
    port_map.update({p: f"{p}_INT" for p in unexposed})
    call_ports = " ".join(port_map[p] for p in core_port_order)
    exposed_ordered = [p for p in ("VOUT", "GDRV", "VDD", "VSS") if p in exposed]
    return (
        f".subckt bandgap_core {' '.join(exposed_ordered)}\n"
        f"XCORE {call_ports} {core_subckt}\n"
        f".ends bandgap_core\n"
    )


def strip_schematic_subckts(body_text: str, names: tuple[str, ...]) -> str:
    """Remove xschem-emitted `.subckt <name> ... .ends` blocks (with their
    `* expanding ... symbol: design/<name>.sym` header) from a netlisted
    testbench body, so a translated-layout replacement can be appended
    instead.

    The header's `.*?` gap between `expanding` and `symbol:` MUST stay tight
    (whitespace only, not DOTALL-wildcard) -- a testbench that netlists a
    THIRD schematic-level `.sym` whose own `* expanding ... symbol: ...`
    header sits between two names being stripped (e.g. the mixed-provenance
    startup benches, which also netlist `design/startup_injector.sym`
    unmodified alongside `bandgap_core`/`error_amp`) would otherwise let a
    lazy wildcard gap match starting at that THIRD header and swallow every-
    thing up to the target name's real header, deleting the third subckt's
    block as collateral damage. Reproduced and root-caused while wiring
    `sim/startup-stability-post-layout/`, issue #16: after stripping
    `bandgap_core` alone, the leftmost remaining `* expanding` line in the
    text was `design/startup_injector.sym`'s, and the old
    `\\* expanding.*?symbol:...design/error_amp\\.sym` pattern happily bound
    its start there instead of at `error_amp`'s own header, deleting the
    entire `startup_injector` block in the process. Anchoring the gap to
    `\\s+` (the fixed `* expanding   symbol:  design/<name>.sym` spacing
    xschem actually emits) makes the header match name-specific instead of
    "the nearest earlier expanding-header, whichever symbol it names".
    """
    text = body_text
    for name in names:
        pattern = (
            rf"\n\* expanding\s+symbol:\s*design/{re.escape(name)}\.sym\b.*?"
            rf"\n\.subckt\s+{re.escape(name)}\b.*?\n\.ends\n"
        )
        new_text, n = re.subn(pattern, "\n", text, flags=re.S | re.I)
        if n == 0:
            raise PostLayoutError(f"no .subckt {name} ... .ends block found to strip")
        text = new_text
    return text


# --------------------------------------------------------------------------
# generic per-bench post-layout runner (module docstring points 4 and 5)
# --------------------------------------------------------------------------

SIM_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SIM_DIR.parent
LAYOUT_BANDGAP_CORE_DIR = REPO_ROOT / "layout" / "bandgap-core"

PEX_TOP = "bandgap_core_routed"
PEX_SPICE_NAME = f"{PEX_TOP}.pex.spice"
PEX_JSON_NAME = f"{PEX_TOP}.pex.json"

# The two `.subckt` blocks xschem emits for `design/bandgap_core.sym` in every
# bench that instantiates it (`bandgap_core` calls `error_amp`); both are
# replaced wholesale by the extracted layout body, which is flat.
SCHEMATIC_SUBCKTS_TO_REPLACE = ("bandgap_core", "error_amp")


def resolve_parasitics_snapshot(
    local_snapshot_root: Path,
    gds: Path,
    layout_record_id: str,
    pdk_variant: str | None = None,
    pdk_root: str | None = None,
    legacy_layout_record_id: str | None = None,
    pinned_variant: str | None = None,
    pdk_commit: str | None = None,
    pinned_commit: str | None = None,
) -> tuple[Path, dict, str]:
    """Find (or produce) the `klt extract --parasitics --pdk` snapshot for one
    layout record. Returns (snapshot_dir, summary, source).

    Startup passes its committed klt-0.5.0 layout record ID to reuse that
    specific local snapshot. A missing snapshot or a different layout ID
    follows the normal PDK-bound resolution below.

    Default resolution order, per module docstring point 5, over the PDK-BOUND
    snapshot key `<layout_record_id>-pdk` (issue #614):

    1. `<local_snapshot_root>/<layout_record_id>-pdk/` -- this bench already
       ran against this layout record (`sim/` is append-only: never re-extract
       over an existing snapshot).
    2. any sibling `sim/*/parasitics-snapshot/<layout_record_id>-pdk/` --
       another post-layout bench already extracted this exact layout record;
       reuse it IN PLACE so every post-layout record for a given layout record
       measures the same extracted netlist (and so the ~320 kB snapshot is
       committed once, not once per bench).
    3. otherwise run `klt extract --parasitics --pdk <variant>` and commit the
       result here.

    The `-pdk` suffix keeps the bound snapshot a DISTINCT append-only artifact
    from the unbound snapshots the committed records cite: reusing the bare
    `<layout_record_id>` key would either overwrite a committed snapshot
    (refused by `sim/`'s append-only rule) or silently simulate fixed
    resistor cards from an unbound netlist. The pre-#614 unbound snapshots stay where they are:
    the committed records that measured them keep pointing at them.
    """
    if layout_record_id == legacy_layout_record_id:
        local = local_snapshot_root / layout_record_id
        if (local / PEX_SPICE_NAME).is_file() and (local / PEX_JSON_NAME).is_file():
            summary = json.loads((local / PEX_JSON_NAME).read_text())
            return local, summary, "local"

    resolved_commit = pdk_commit
    if resolved_commit is None and pdk_variant and pdk_root:
        pdk_dir = Path(pdk_root).expanduser() / pdk_variant
        if pdk_dir.is_dir():
            resolved_commit = sim_common.load_corner_run().installed_commit(pdk_dir)

    # The default key `<id>-pdk` belongs to the PINNED variant and PINNED
    # revision. A snapshot is only reusable when its recorded provenance.pdk
    # matches both the variant and the resolved open_pdks revision; under a
    # `PDK=<other>` or `--allow-pdk-mismatch` override the lookup moves to a
    # distinct key so committed pinned snapshots stay put and unpinned runs
    # never populate `<id>-pdk` for a later graded run.
    default_key = f"{layout_record_id}-pdk"
    key_parts = [default_key]
    if pdk_variant and pinned_variant and pdk_variant != pinned_variant:
        key_parts.append(_snapshot_key_tag(pdk_variant))
    if resolved_commit and pinned_commit and resolved_commit != pinned_commit:
        key_parts.append(_snapshot_key_tag(resolved_commit))
    bound_key = "-".join(key_parts)

    def _pdk_ok(summary: dict) -> bool:
        pdk_meta = (summary.get("provenance") or {}).get("pdk") or {}
        if pdk_variant and pdk_meta.get("name") != pdk_variant:
            return False
        if resolved_commit is not None:
            if resolved_commit == "unknown":
                return False
            if _recorded_pdk_commit(summary) != resolved_commit:
                return False
        return True

    local = local_snapshot_root / bound_key
    if (local / PEX_SPICE_NAME).is_file() and (local / PEX_JSON_NAME).is_file():
        summary = json.loads((local / PEX_JSON_NAME).read_text())
        if _pdk_ok(summary):
            return local, summary, "local"

    for candidate in sorted(SIM_DIR.glob(f"*/parasitics-snapshot/{bound_key}")):
        if (candidate / PEX_SPICE_NAME).is_file() and (candidate / PEX_JSON_NAME).is_file():
            summary = json.loads((candidate / PEX_JSON_NAME).read_text())
            if _pdk_ok(summary):
                return candidate, summary, f"reused:{candidate.relative_to(REPO_ROOT)}"

    if not pdk_variant:
        raise PostLayoutError(
            f"no PDK-bound parasitics snapshot for layout record {layout_record_id} "
            f"under any sim/*/parasitics-snapshot/{bound_key}/, and no PDK variant "
            "was passed to extract one (issue #614: the post-layout path extracts "
            "with --pdk so device cards bind to the PDK models)"
        )
    if _has_existing_snapshot_target(local):
        expected_pdk = (
            f"{pdk_variant}@{resolved_commit}" if resolved_commit else pdk_variant
        )
        raise PostLayoutError(
            f"{local} exists but does not match expected PDK provenance "
            f"({expected_pdk}); snapshots are append-only, refusing to extract over it"
        )
    _spice, summary = run_klt_extract_parasitics(
        gds, local, top=PEX_TOP, pdk_variant=pdk_variant, pdk_root=pdk_root
    )
    return local, summary, "extracted"


def build_extracted_body(
    cr,
    pdk,
    run_dir: Path,
    local_snapshot_root: Path,
    wrapped_schematic: str,
    legacy_layout_record_id: str | None = None,
) -> tuple[list[str], dict]:
    """Netlist the (unmodified) schematic testbench, then swap its
    `bandgap_core`/`error_amp` subckt definitions for the translated,
    extracted, parasitics-included routed layout. Returns (body, provenance).
    """
    layout_record_id, layout_record_dir, gds, gds_source = resolve_latest_layout(
        LAYOUT_BANDGAP_CORE_DIR
    )
    _reference, reference_source = resolve_record_reference(
        LAYOUT_BANDGAP_CORE_DIR, layout_record_id, layout_record_dir
    )
    pex_dir, pex_summary, pex_source = resolve_parasitics_snapshot(
        local_snapshot_root,
        gds,
        layout_record_id,
        pdk_variant=pdk.variant,
        pdk_root=str(pdk.root),
        legacy_layout_record_id=legacy_layout_record_id,
        pinned_variant=pdk.pin["variant"],
        pdk_commit=pdk.installed_commit,
        pinned_commit=pdk.pin["open_pdks_commit"],
    )
    spice_path = pex_dir / PEX_SPICE_NAME
    pex_text = spice_path.read_text()

    # Flavour gate (issue #621): score the RAW PDK-bound wrapper binding of
    # this very snapshot against the record's geometry-derived counts,
    # BEFORE translate_extracted_netlist rewrites any MOS card. Only a
    # record that carries flavour.json (issue #620 onward) has a
    # geometry-derived expectation to gate against; the legacy unbound
    # klt-0.5.0 snapshot has no wrapper cards at all, so there is nothing
    # to score on that path either -- both cases are disclosed in the
    # provenance instead of silently passing.
    flavour_gate: dict = {"status": "not-gated"}
    flavour_path = layout_record_dir / "flavour.json"
    if flavour_path.is_file():
        try:
            flavour_expected = (json.loads(flavour_path.read_text()) or {}).get("expected")
        except json.JSONDecodeError as exc:
            raise PostLayoutError(
                f"layout record {layout_record_id}: flavour.json is not valid JSON: {exc}"
            ) from exc
        if isinstance(flavour_expected, dict) and bound_mos_wrapper_census(pex_text):
            flavour_gate = check_parasitics_mos_flavour(
                pex_text, flavour_expected, layout_record_id
            )
        else:
            flavour_gate = {
                "status": "not-gated",
                "reason": (
                    "snapshot carries no PDK-bound MOS wrapper cards "
                    "(legacy unbound extraction); no oxide-flavour evidence on this path"
                ),
            }
    else:
        flavour_gate = {
            "status": "not-gated",
            "reason": "record predates issue #620's flavour.json; no geometry-derived "
            "expectation to gate against",
        }

    translated, counts = translate_extracted_netlist(pex_text)

    expected = pex_summary.get("device_counts", {})
    expected_mos = expected.get("nfet", 0) + expected.get("pfet", 0)
    expected_pnp = expected.get("pnp", 0)
    expected_res = expected.get("res_high_po", 0)
    if (counts["mos"], counts["pnp"], counts["res"]) != (expected_mos, expected_pnp, expected_res):
        raise PostLayoutError(
            "translation coverage mismatch against the extraction's own device_counts: "
            f"translated mos={counts['mos']} pnp={counts['pnp']} res={counts['res']}, "
            f"extraction reports nfet+pfet={expected_mos} pnp={expected_pnp} res_high_po={expected_res} "
            "-- a device class this translator doesn't recognize may have been silently skipped"
        )

    core_block = extract_subckt_block(translated, PEX_TOP)
    core_port_order = parse_subckt_ports(core_block, PEX_TOP)
    wrapper = build_core_wrapper(core_subckt=PEX_TOP, core_port_order=core_port_order)

    testbench = REPO_ROOT / wrapped_schematic
    netlist = cr.netlist_with_xschem(testbench, run_dir, pdk)
    tb_body_text = "\n".join(cr.netlist_body(netlist))
    tb_body_text = strip_schematic_subckts(tb_body_text, SCHEMATIC_SUBCKTS_TO_REPLACE)

    body = (tb_body_text + "\n\n" + wrapper + "\n" + core_block + "\n").splitlines()

    lvs_status = layout_record_lvs_status(layout_record_dir, layout_record_id)
    provenance = {
        "layout_record_id": layout_record_id,
        "layout_record": str((layout_record_dir / "record.md").relative_to(REPO_ROOT)),
        "layout_gds": str(gds.relative_to(REPO_ROOT)),
        "layout_gds_source": gds_source,
        "layout_reference": reference_source,
        "layout_lvs": lvs_status,
        "parasitics_snapshot": {
            "spice": str(spice_path.relative_to(REPO_ROOT)),
            "json": str((pex_dir / PEX_JSON_NAME).relative_to(REPO_ROOT)),
            "source": pex_source,
            "pex_spice_sha256": _sha256_of(spice_path),
            "r_count": pex_summary.get("parasitics", {}).get("r_count"),
            "c_count": pex_summary.get("parasitics", {}).get("c_count"),
            "total_resistance_ohm": pex_summary.get("parasitics", {}).get("total_resistance_ohm"),
            "total_capacitance_ff": pex_summary.get("parasitics", {}).get("total_capacitance_ff"),
        },
        "mos_flavour_gate": flavour_gate,
        "device_translation_counts": counts,
        # The selected record's own combined LVS verdict (issue #621): null
        # only for records that predate lvs.combined.json.
        "lvs_mismatch_count_at_extraction": (lvs_status or {}).get("mismatch_count"),
        "core_port_order": list(core_port_order),  # as actually parsed from this run's own extraction header
    }
    return body, provenance


def parse_post_layout_args(argv: list[str], doc: str = "") -> argparse.Namespace:
    """The flag set every `sim/*-post-layout/run_*.py` accepts (the subset of
    `corner-run.py`'s flags that is meaningful when the matrix, measurements
    and deck all come from the wrapped experiment's own manifest).

    `--process` / `--temp` / `--supply` / `--subset-reason` mirror
    `corner-run.py`'s flags of the same names and exist for the same reason
    (issue #284): a post-layout bench that declares a full matrix in its own
    runner script previously had NO way to be re-run over fewer points without
    editing that script, so a host too slow to carry the full matrix serially
    left the bench un-re-runnable rather than re-runnable-with-a-stated-reason.
    They are opt-in and change no default: omit them and the bench resolves
    exactly the matrix it always did. `sim/README.md`'s subset rule is enforced
    on this path the same way it is on `corner-run.py`'s -- `--subset-reason` is
    REQUIRED as soon as the resolved matrix is a subset, and the reason is
    written into the record body.

    Note the argparse gotcha these flags inherit from `corner-run.py`: a
    negative temperature must be passed as `--temp=-40` (with the `=`), because
    a bare `--temp -40` is read as a missing argument followed by an unknown
    option.

    `-j`/`--jobs` also mirrors `corner-run.py`'s flag of the same name (issue
    #308): default `1` runs the matrix serially (today's unchanged behavior),
    `> 1` runs that many corners concurrently via
    `run_matrix_and_write_record()`'s shared implementation.
    """
    p = argparse.ArgumentParser(description=doc)
    p.add_argument("--supersedes", default="")
    p.add_argument("--author", default="")
    p.add_argument(
        "--timeout",
        type=int,
        default=None,
        help=(
            "per-corner ngspice timeout in seconds (default: 300 locally, "
            f"{batch_sim.POST_LAYOUT_BATCH_TIMEOUT_S} with --backend batch). With "
            "--backend batch a value whose per-shard job bound cannot fit the fleet's "
            f"whole-job ceiling ({batch_sim.FLEET_JOB_CEILING_S} s, i.e. more than "
            f"{batch_sim.FLEET_JOB_CEILING_S - batch_sim.FLEET_JOB_OVERHEAD_S} s per corner) "
            "is an error, not a warning"
        ),
    )
    sim_common.add_batch_args(
        p,
        backend_help=(
            "where corners run (default: local). 'batch' sends the matrix to the Spot batch "
            "fleet through `klt sim --backend batch`; available for "
            f"{sorted(batch_sim.POST_LAYOUT_BATCH_ENABLED_SLUGS)} only (see sim/README.md). "
            "A failed batch submission is an error -- it never falls back to a local run"
        ),
    )
    p.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=1,
        help=(
            "run up to N corners concurrently (default: 1, serial -- today's "
            "behavior). Each corner is an independent ngspice process with its "
            "own --timeout, enforced per-process either way"
        ),
    )
    p.add_argument("--allow-pdk-mismatch", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--process",
        type=sim_common.csv_list,
        default=None,
        help="process corners (default: the wrapped manifest's, or this bench's own pin)",
    )
    p.add_argument(
        "--temp",
        type=sim_common.csv_floats,
        default=None,
        help="temperatures in C, e.g. --temp=-40,125 (default: as above)",
    )
    p.add_argument(
        "--supply",
        type=sim_common.csv_floats,
        default=None,
        help="supply voltages (default: as above)",
    )
    p.add_argument(
        "--subset-reason",
        default="",
        help="why a subset of the full PVT matrix is acceptable (required for subsets)",
    )
    args = p.parse_args(argv)
    if args.timeout is None:
        args.timeout = (
            batch_sim.POST_LAYOUT_BATCH_TIMEOUT_S if args.backend == "batch" else 300
        )
    return args


def resolve_record_claim_and_title(
    *,
    slug: str,
    wrapped_experiment: str,
    raw: dict,
    fallback_title: str,
    claim_tail: str | None,
    claim_split: str | None,
    error,
) -> tuple[str, str, bool]:
    """Decide the `claim` and `title` an `extracted`-provenance record carries,
    for either of the two manifest shapes `run_post_layout_experiment` supports.

    Extracted from that function so the rule is testable without a PDK, ngspice
    or `klt` on PATH -- every branch below is a mislabeling guard, which is
    exactly the kind of thing that should not first be exercised at the moment
    a record is being written. `error` is the exception class to raise (the
    caller passes `cr.HarnessError`; a test can pass anything).

    Returns `(claim_text, title, owns_its_manifest)`.

    - **Wrapping shape** (`claim_tail` is a string): the manifest belongs to
      the SCHEMATIC-level bench and its claim's trailing sentence describes
      that DUT ("Measures design/bandgap_core.sch ..."), which is accurate for
      that manifest's own records and misleading for this one. Keep the
      spec-line identification up to `claim_split` (default `"Measures "`),
      replace the provenance tail with `claim_tail`, and mark the title
      `-- POST-LAYOUT (extracted netlist)`. Passing `claim_split` explicitly
      makes its presence mandatory, so a manifest that does not contain the
      marker fails loudly instead of silently keeping its schematic-level
      sentence.
    - **Own-manifest shape** (`claim_tail is None`, issue #299): the manifest
      is the post-layout bench's own, already written for the extracted DUT.
      Claim and title are used verbatim. Legal only when the manifest IS this
      bench's own -- otherwise the result would be another bench's
      schematic-level claim copied verbatim into an extracted-provenance
      record, the same mislabeling the `claim_split` guard prevents.
    """
    if claim_tail is not None:
        marker = claim_split if claim_split is not None else "Measures "
        if claim_split is not None and claim_split not in raw["claim"]:
            raise error(
                f"{slug}: claim_split {claim_split!r} does not occur in "
                f"{wrapped_experiment}'s own claim -- the post-layout record would keep "
                "that manifest's schematic-level provenance sentence verbatim"
            )
        claim_head = raw["claim"].split(marker)[0].rstrip()
        title = raw.get("title", fallback_title) + " -- POST-LAYOUT (extracted netlist)"
        return claim_head + " " + claim_tail, title, False

    if wrapped_experiment != slug:
        raise error(
            f"{slug}: claim_tail=None means 'this manifest is already written for "
            f"the post-layout DUT', but this bench wraps {wrapped_experiment}'s "
            "manifest -- using another bench's claim verbatim in an "
            "extracted-provenance record is exactly the mislabeling the "
            "claim_split guard exists to prevent; supply a claim_tail instead"
        )
    if claim_split is not None:
        raise error(
            f"{slug}: claim_split is meaningless with claim_tail=None (nothing is "
            "being replaced) -- pass one or the other, not both"
        )
    if raw.get("provenance") != "extracted":
        raise error(
            f"{slug}: claim_tail=None uses this manifest's claim verbatim in an "
            "extracted-provenance record, so the manifest must declare "
            f"\"provenance\": \"extracted\" itself -- it declares "
            f"{raw.get('provenance')!r}"
        )
    return raw["claim"], raw.get("title", fallback_title), True


def check_claim_matches_lvs_verdict(
    slug: str,
    claim_text: str,
    layout_provenance: dict,
    error,
) -> None:
    """Refuse a claim that asserts an "LVS-clean" layout while the selected
    record's own combined LVS report disagrees (issue #621).

    Extracted from `run_post_layout_experiment` so the rule is testable
    without a PDK, ngspice or `klt` on PATH -- the same reason
    `resolve_record_claim_and_title` exists. `error` is the exception class
    to raise (callers pass `cr.HarnessError`; a test can pass anything).

    The historical claims this guard retired said "the ROUTED, LVS-clean
    bandgap-core layout" at a time when the graded record's LVS verdict was
    `mismatch_count: 0`. The thick-oxide record's verdict is 5 disclosed
    mismatches, and a claim is a sentence about the DUT -- it must not
    assert a verdict the record's own evidence contradicts. Records carry
    the actual verdict in `layout_provenance["layout_lvs"]` and cite it
    under 'Netlist provenance' instead. A record with no `lvs.combined.json`
    (predating it) has no verdict to contradict, so the guard passes.
    """
    lvs = layout_provenance.get("layout_lvs") or {}
    if "lvs-clean" in claim_text.lower() and lvs.get("mismatch_count"):
        raise error(
            f"{slug}: the claim text asserts an 'LVS-clean' layout, but layout record "
            f"{layout_provenance.get('layout_record_id')}'s combined LVS report carries "
            f"mismatch_count={lvs.get('mismatch_count')} (status {lvs.get('status')!r}). "
            "Cite the record's actual LVS verdict under 'Netlist provenance' instead of "
            "asserting cleanliness (issue #621)"
        )


def run_post_layout_experiment(
    cr,
    here: Path,
    slug: str,
    wrapped_experiment: str,
    wrapped_schematic: str,
    claim_tail: str | None,
    argv: list[str],
    temp_override: list[float] | None = None,
    supply_override: list[float] | None = None,
    process_override: list[str] | None = None,
    subset_reason: str = "",
    claim_split: str | None = None,
    legacy_layout_record_id: str | None = None,
) -> int:
    """Run one bench's whole post-layout re-verification and write its record.

    `here` is the `sim/<slug>/` directory of the POST-LAYOUT experiment (the
    caller's own `Path(__file__).parent`); `wrapped_experiment` is the slug
    under `sim/` whose `experiment.json` supplies the corner matrix, deck
    options and measurement limits, and `wrapped_schematic` is the testbench
    netlisted to carry them.

    Two shapes, both supported here:

    - **Wrapping** (the usual one, and what "wrapped" in these parameter names
      means): `wrapped_experiment` is the SCHEMATIC-level bench whose manifest
      and testbench are reused UNCHANGED -- never edited, so the only variable
      between its records and this one is the DUT body. Pass a `claim_tail`
      (and, where the manifest's claim needs it, a `claim_split`).
    - **Own-manifest** (issue #299): `wrapped_experiment == slug` and the
      post-layout bench carries its own `experiment.json` + `testbench/`
      because the schematic-level bench's measurements cannot be reused at
      all. Pass `claim_tail=None`; see below.

    `temp_override`/`supply_override`/`process_override` restrict the runner's
    outer temperature/supply/process axis. Two distinct reasons a bench does
    this, both ending in the same `is_subset` bookkeeping:

    - the deck sweeps that axis INTERNALLY, so outer points would be identical
      reruns (`output-voltage-tc`'s box TC collapses temperature;
      `line-regulation`'s in-deck `dc v1 2.97 3.63 ...` sweep collapses supply,
      since ngspice's `.dc <source>` sweep overrides the outer `vsup` value for
      that source regardless of the corner loop);
    - issue #16's Acceptance Criteria ask for a bench "at worst corners"
      rather than over the full matrix -- which is what `process_override`
      (added by the startup increment) exists for, alongside the temperature
      and supply extremes.

    Any of the three makes the run a subset, so `subset_reason` is then
    REQUIRED -- there is no `--subset-reason` flag on this path, and
    `sim/README.md` makes the justification a prose obligation for bespoke
    scripts.

    `claim_split` names the phrase in the wrapped manifest's own `claim` at
    which its schematic-level provenance description begins; everything from
    there is dropped and `claim_tail` is appended instead. It defaults to
    `"Measures "` (what the first three post-layout benches' manifests all
    use). Passing it EXPLICITLY also makes its presence mandatory: a manifest
    whose claim does not contain the marker would otherwise silently keep its
    "... design/bandgap_core.sch ..." sentence in an `extracted`-provenance
    record, which is exactly the mislabeling issue #16 is guarding against.

    `legacy_layout_record_id` allows the startup-time bench to reuse its
    committed klt-0.5.0 snapshot for that layout. Other layouts use the
    PDK-bound snapshot key `<layout-record-id>-pdk`.

    `claim_tail=None` selects the OTHER manifest shape this runner supports
    (issue #299): a bench that owns its own post-layout manifest instead of
    wrapping a schematic-level one. There is then no schematic-level
    provenance sentence to split off -- the manifest's `claim` is already
    written for the extracted DUT -- so it is used verbatim and the title is
    taken verbatim too (no `-- POST-LAYOUT (extracted netlist)` suffix, since
    the manifest says it itself). This is only legal when the manifest IS this
    bench's own (`wrapped_experiment == slug`); passing `claim_tail=None`
    while wrapping somebody else's manifest would copy that bench's
    schematic-level claim into an `extracted`-provenance record verbatim,
    which is the same mislabeling the `claim_split` guard above exists to
    prevent, so it raises instead.

    Two benches need that shape rather than the wrapping one:
    `sim/startup-stability-post-layout/` and `sim/startup-ramp-post-layout/`.
    Their schematic-level manifests measure control-dependent quantities
    (`imin_off_bare`, `i_off_bare`, `ncross_bare`, `dvref`, `i_standing`,
    `i_su_standing`, `vref_n`, `gn_n`) against a bare-core control instance
    the drawn cell cannot express since issue #285 drew the injector into it,
    so reusing those manifests unchanged is not possible at all -- see either
    manifest's own "WHY THIS MANIFEST EXISTS" note.

    Exit status matches `corner-run.py`: 0 all checks passed, 2 a record was
    written but something failed (raises otherwise, so the caller maps
    HarnessError/PostLayoutError to 1).
    """
    args = parse_post_layout_args(argv)
    batch = args.backend == "batch"
    if batch and args.jobs > 1:
        raise cr.HarnessError("--jobs is a local-concurrency flag; --backend batch ignores it, drop it")
    if batch:
        try:
            batch_sim.require_batch_enabled(
                slug, batch_sim.POST_LAYOUT_BATCH_ENABLED_SLUGS, dry_run=args.dry_run
            )
            # Refuse an unenforceable per-corner budget here, before any work:
            # a `--timeout` whose single-unit job bound already exceeds the
            # fleet ceiling cannot be fixed by any `remote.hosts` split, so
            # klt would warn and submit a job that is killed at the ceiling
            # with every unit reported `batch_job_timeout` (issue #510).
            # `build_groups()` re-checks each request's real unit count.
            batch_sim.require_job_bound_fits(1, args.timeout, what=f"{slug} --timeout")
        except batch_sim.BatchError as err:
            raise cr.HarnessError(str(err)) from err

    # CLI axis overrides (issue #284) may only fill in an axis this bench's own
    # runner script leaves open. An axis the script pins deliberately -- because
    # the deck sweeps it INTERNALLY, or because the bench's acceptance criteria
    # scope it to worst corners -- is not negotiable from the command line: a
    # caller who "restored" line-regulation's supply axis here would silently be
    # re-running ngspice's own .dc sweep 3 times, and the record would not say so.
    for axis, caller_value, cli_value in (
        ("process", process_override, args.process),
        ("temp", temp_override, args.temp),
        ("supply", supply_override, args.supply),
    ):
        if cli_value is not None and caller_value is not None:
            raise cr.HarnessError(
                f"{slug}: --{axis} given on the command line, but this bench's own "
                f"runner script already pins its {axis} axis to {caller_value!r} for a "
                "reason stated in that script; edit the script (and its stated reason) "
                "rather than overriding it per-invocation"
            )
    process_override = args.process if process_override is None else process_override
    temp_override = args.temp if temp_override is None else temp_override
    supply_override = args.supply if supply_override is None else supply_override
    if args.subset_reason:
        subset_reason = (
            f"{subset_reason.rstrip()} {args.subset_reason}".strip()
            if subset_reason
            else args.subset_reason
        )

    pin = cr.load_pin()
    pdk = cr.resolve_pdk(pin)
    # Batch requests name `models.pdk` from the pin dict: hand them the RESOLVED
    # variant so a `PDK=` override reaches the fleet, same as extraction.
    batch_pin = {**pin, "variant": pdk.variant}
    if not pdk.matches_pin and not args.allow_pdk_mismatch:
        raise cr.HarnessError(
            f"installed PDK {pdk.variant} is open_pdks {pdk.installed_commit}, but "
            f"sim/pdk.json pins {pin['open_pdks_commit']} (use --allow-pdk-mismatch to override)"
        )
    if not batch and not shutil.which("ngspice"):
        raise cr.HarnessError("ngspice not found on PATH")
    if not shutil.which("klt"):
        raise cr.HarnessError("klt (klayout-tools) not found on PATH")

    exp = cr.load_experiment(SIM_DIR / wrapped_experiment)
    claim_text, title, owns_its_manifest = resolve_record_claim_and_title(
        slug=slug,
        wrapped_experiment=wrapped_experiment,
        raw=exp.raw,
        fallback_title=exp.slug,
        claim_tail=claim_tail,
        claim_split=claim_split,
        error=cr.HarnessError,
    )

    class _Args:
        quick = False
        process = process_override
        temp = temp_override
        supply = supply_override

    matrix, is_subset = cr.build_matrix(exp, _Args(), pin)
    if is_subset and not subset_reason:
        raise cr.HarnessError(
            f"{slug}: the resolved matrix is a subset of {wrapped_experiment}'s own "
            "corners but no subset_reason was supplied -- sim/README.md requires the "
            "justification in the record body"
        )
    reason = subset_reason if is_subset else ""

    git_info = cr.git_state()
    now = datetime.now(timezone.utc)
    record_id = f"{now:%Y%m%d}-{now:%H%M%S}-{git_info['sha']}"

    records_dir = here / "records"
    snapshots_dir = here / "netlist-snapshots"
    corners_dir = here / "corners" / record_id
    record_md = records_dir / f"{record_id}.md"
    record_json = records_dir / f"{record_id}.json"
    snapshot = snapshots_dir / f"{record_id}.spice"
    for path in (record_md, record_json, snapshot, corners_dir):
        if path.exists():
            raise cr.HarnessError(f"{path} already exists — sim/ is append-only, refusing to overwrite")

    run_dir = SIM_DIR / "build" / slug / record_id
    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SIM_DIR / "spiceinit", run_dir / ".spiceinit")

    body, layout_provenance = build_extracted_body(
        cr, pdk, run_dir, here / "parasitics-snapshot", wrapped_schematic,
        legacy_layout_record_id=legacy_layout_record_id,
    )

    # Claim-vs-verdict guard (issue #621): see
    # `check_claim_matches_lvs_verdict` -- the record's actual verdict is
    # carried in layout_provenance (layout_lvs) and cited under 'Netlist
    # provenance'; the claim text has to say that instead.
    check_claim_matches_lvs_verdict(slug, claim_text, layout_provenance, cr.HarnessError)

    print(f"experiment      : {slug}")
    print(f"record id       : {record_id}")
    print(f"layout record   : {layout_provenance['layout_record_id']}")
    print(f"layout gds      : {layout_provenance['layout_gds_source']['kind']}")
    print(f"parasitics      : {layout_provenance['parasitics_snapshot']['source']}")
    print(f"corner points   : {len(matrix)}" + (" (SUBSET)" if is_subset else " (full matrix)"))

    spiceinit_text = (SIM_DIR / "spiceinit").read_text()

    if args.dry_run and batch:
        try:
            groups = batch_sim.build_groups(
                exp, batch_pin, matrix, body, spiceinit_text, run_dir / "batch", args.timeout,
                capacity_wait_s=args.batch_capacity_wait_s,
                runner_version_check=args.batch_runner_version_check,
                poll_interval_s=30.0, gate_slug=slug, allow_step_requests=True,
                enforce_job_ceiling=True,
            )
        except batch_sim.BatchError as err:
            raise cr.HarnessError(str(err)) from err
        print("\n-- batch requests (one klt sim job per supply voltage) --")
        for g in groups:
            print(f"  {g.request_path}  ({len(g.corners)} corners at {g.supply_v:.2f} V)")
        print(f"\n-- request for {groups[0].supply_v:.2f} V --")
        print(groups[0].request_path.read_text())
        print("(dry run: nothing submitted, nothing written under sim/<experiment>/)")
        return 0

    if args.dry_run:
        print("\n-- corner list --")
        for corner in matrix:
            print(f"  {corner.id}")
        print(f"\n-- deck for {matrix[0].id} --")
        print(cr.build_deck(exp, pdk, matrix[0], body))
        print("\n(dry run: nothing written under sim/)")
        return 0

    gds_source = layout_provenance["layout_gds_source"]
    if gds_source["kind"] == "artifact-store":
        gds_citation = (
            f"{gds_source['manifest']}#{gds_source['entry']} "
            f"(sha256 {str(gds_source.get('sha256'))[:16]}..., fetched via `klt artifact get` "
            f"to {layout_provenance['layout_gds']})"
        )
    else:
        gds_citation = layout_provenance["layout_gds"]
    experiment_fields = {
        "slug": slug,
        "title": title,
        "claim": claim_text,
        "provenance": "extracted",
        "provenance_source": (
            f"{gds_citation} via `klt extract --parasitics` "
            f"(layout record {layout_provenance['layout_record_id']}), translated by "
            "sim/bin/post_layout_common.py, "
            + ("over this bench's own " if owns_its_manifest else "wrapped over the unmodified ")
            + f"{wrapped_schematic}"
        ),
        "statistical_convention": exp.raw.get("statistical_convention", "N/A"),
    }
    execute_matrix = None
    if batch:
        local_tools = cr.tool_versions()
        local_tools["klt"] = cr.first_line(["klt", "--version"])

        def execute_matrix(matrix_, corners_dir_):
            try:
                return batch_sim.execute(
                    exp, batch_pin, pdk, matrix_, body, spiceinit_text,
                    run_dir / "batch", corners_dir_, REPO_ROOT, args.timeout,
                    cr.evaluate_measurements, local_tools,
                    capacity_wait_s=args.batch_capacity_wait_s,
                    runner_version_check=args.batch_runner_version_check,
                    gate_slug=slug,
                    enforce_job_ceiling=True,
                )
            except batch_sim.BatchError as err:
                raise cr.HarnessError(str(err)) from err

    _record, overall = sim_common.run_matrix_and_write_record(
        cr,
        exp=exp,
        matrix=matrix,
        is_subset=is_subset,
        subset_reason=reason,
        pdk=pdk,
        pin=pin,
        body=body,
        run_dir=run_dir,
        corners_dir=corners_dir,
        records_dir=records_dir,
        record_md=record_md,
        record_json=record_json,
        snapshot=snapshot,
        record_id=record_id,
        git_info=git_info,
        now=now,
        args=args,
        experiment_fields=experiment_fields,
        links={
            "testbench": wrapped_schematic,
            "manifest": str((SIM_DIR / wrapped_experiment / "experiment.json").relative_to(REPO_ROOT)),
        },
        record_extra={"layout_provenance": layout_provenance},
        execute_matrix=execute_matrix,
    )
    return 0 if overall else 2


def main_wrapper(cr, run) -> None:
    """`if __name__ == "__main__":` body shared by the per-bench scripts --
    maps the two harness exception types to exit status 1 (no record written),
    the same convention `corner-run.py` uses."""
    try:
        sys.exit(run(sys.argv[1:]))
    except (cr.HarnessError, PostLayoutError) as err:
        print(f"{Path(sys.argv[0]).name}: error: {err}", file=sys.stderr)
        sys.exit(1)
