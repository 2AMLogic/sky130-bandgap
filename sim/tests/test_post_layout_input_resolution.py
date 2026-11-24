#!/usr/bin/env python3
"""The store-backed layout-input resolver and the flavour/LVS gates
(issue #621).

`sim/bin/post_layout_common.py` historically read
`bandgap_core_routed.gds` and `reference.spice` directly out of the
selected `layout/bandgap-core/reports/<record-id>/` directory. Issue #440's
operator ruling moved report-run GDS blobs to the fleet artifact store
(git keeps the manifest), and #620's verified thick-oxide record is the
first LATEST candidate in that form -- so advancing `reports/LATEST`
without a resolver change would leave a fresh checkout unable to run any
post-layout bench. These tests pin the three halves of the fix:

- `resolve_record_gds` / `resolve_latest_layout`: in-tree records keep
  resolving exactly as before; store-backed records resolve through
  `klt artifact get <manifest>#<entry>` into a digest-keyed cache, with
  every failure mode (no manifest, no GDS entry, broker failure, digest
  mismatch) naming the failing record and stopping before simulation;
- `resolve_record_reference`: a record without an in-tree
  `reference.spice` resolves the tracked copy named by its companion
  artifact-store summary, digest-verified BEFORE the injector check reads
  it;
- `check_parasitics_mos_flavour` / `layout_record_lvs_status` /
  `check_claim_matches_lvs_verdict`: the raw PDK-bound wrapper binding is
  gated against the record's geometry-derived counts before any local MOS
  translation (a single wrong-flavour card fails even when the total MOS
  count agrees), the record's own LVS verdict is read for provenance, and
  a claim asserting "LVS-clean" is refused when that verdict disagrees.

`klt` is exercised through a stub script (the same technique
`test_artifact_store.py` uses), so no broker, PDK or ngspice is needed
here.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SIM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIM_DIR / "bin"))

import post_layout_common as plc  # noqa: E402

RECORD_ID = "20260101-000000-abcdefg"
GDS_NAME = f"layout/bandgap-core/staging/{RECORD_ID}/bandgap_core_routed.gds"

GDS_BYTES = b"fake routed GDS bytes for the thick-oxide record\n"
GDS_SHA = hashlib.sha256(GDS_BYTES).hexdigest()

#: A minimal in-tree-style reference netlist carrying the injector cards
#: (`layout/bandgap-core/reference.spice`'s own card order).
REFERENCE_TEXT = """\
.subckt bandgap_core_routed VOUT GDRV VDD VSS
MMPC1 NC1  NC1  GDRV VDD pfet L=20U  W=1U  m=1
MMPC2 NG   NG   NC1  VDD pfet L=20U  W=1U  m=1
MMNS  NG   VOUT NE   VSS nfet L=0.5U W=48U m=1
MMNI  GDRV NG   VSS  VSS nfet L=0.5U W=10U m=1
MMNC  VDD  VOUT GDRV VSS nfet L=1U   W=4U  m=1
QQS VSS VSS NE  pnp AE=3.6992P PE=21.76U NE=8
.ends bandgap_core_routed
"""

#: A `klt` stand-in that implements just enough of `artifact get` for the
#: resolver: it writes the bytes named by the manifest selector and prints
#: the same "verified ..." line the real tool does. A test toggles failure
#: with `FAIL=1` in the stub's environment and counts invocations through
#: `CALLS`.
STUB = """\
#!/usr/bin/env python3
import hashlib, json, os, sys
from pathlib import Path

calls = Path(os.environ["CALLS_FILE"])
with calls.open("a") as fh:
    fh.write(" ".join(sys.argv[1:]) + "\\n")

if os.environ.get("FAIL"):
    sys.stderr.write("broker_unreachable\\n")
    sys.exit(1)

argv = sys.argv[1:]
assert argv[:2] == ["artifact", "get"], argv
ref = argv[2]
manifest_sel, _, name_sel = ref.partition("#")
manifest = json.loads(Path(manifest_sel).read_text())
entry = next(e for e in manifest["entries"] if e["name"] == name_sel)
out = Path(argv[argv.index("-o") + 1])
data = Path(os.environ["STORE_BYTES"]).read_bytes()
digest = hashlib.sha256(data).hexdigest()
if digest != entry["sha256"]:
    sys.stderr.write(f"sha mismatch: {digest} != {entry['sha256']}\\n")
    sys.exit(1)
out.write_bytes(data)
print(f"verified {digest} {len(data)} bytes -> {out}")
"""


def _pex_netlist(nfet_hvi: int, pfet_hvi: int, nfet_thin: int = 0) -> str:
    """A minimal PDK-bound parasitics snapshot body: `nfet_hvi` + `pfet_hvi`
    thick-oxide wrapper X cards plus `nfet_thin` thin-oxide ones (the
    single-wrong-card negative), and one of each non-MOS bound card to
    prove the census ignores them."""
    lines = [f".subckt bandgap_core_routed D1 D2 GDRV VDD VOUT VSS"]
    for i in range(nfet_hvi):
        lines.append(f"X${i} D1 D2 GDRV VSS sky130_fd_pr__nfet_g5v0d10v5 L=2 W=8 AS=3.36p")
    for i in range(pfet_hvi):
        lines.append(f"X$1{i} D1 D2 GDRV VDD sky130_fd_pr__pfet_g5v0d10v5 L=2 W=8 AS=3.36p")
    for i in range(nfet_thin):
        lines.append(f"X$2{i} D1 D2 GDRV VSS sky130_fd_pr__nfet_01v8 L=2 W=8 AS=3.36p")
    lines.append("X$98 VA VB VSS sky130_fd_pr__res_high_po l=5 w=1")
    lines.append("X$74 VC VB VE sky130_fd_pr__pnp_05v5_W0p68L0p68")
    lines.append(".ends bandgap_core_routed")
    return "\n".join(lines) + "\n"


class _SyntheticRepo(unittest.TestCase):
    """A tmp repo root with `layout/bandgap-core/reports/<id>/` plus the
    `manifests/artifacts/` pair a store-backed record ships, and a stubbed
    `klt` on PATH."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.layout_dir = self.tmp / "layout" / "bandgap-core"
        self.record_dir = self.layout_dir / "reports" / RECORD_ID
        self.record_dir.mkdir(parents=True)
        self.cache_root = self.tmp / "cache"
        self.store = self.tmp / "store-bytes"
        self.store.write_bytes(GDS_BYTES)
        self.calls = self.tmp / "klt-calls"
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        stub = self.bin / "klt"
        stub.write_text(STUB)
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
        self.klt_calls = 0

    def klt_env(self, fail: bool = False):
        env = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "STORE_BYTES": str(self.store),
            "CALLS_FILE": str(self.calls),
        }
        if fail:
            env["FAIL"] = "1"
        return mock.patch.dict(os.environ, env, clear=True)

    def count_klt_calls(self) -> int:
        if not self.calls.is_file():
            return 0
        return len(self.calls.read_text().splitlines())

    def write_store_manifest(self, sha256: str | None = None, include_gds: bool = True):
        manifest_rel = self.tmp / plc.layout_artifact_manifest_relpath(RECORD_ID)
        manifest_rel.parent.mkdir(parents=True, exist_ok=True)
        entries = []
        if include_gds:
            entries.append(
                {
                    "sha256": sha256 or GDS_SHA,
                    "size": len(GDS_BYTES),
                    "kind": "evidence",
                    "uri": f"artifact:evidence/o__n/{GDS_SHA[:2]}/{GDS_SHA}",
                    "name": GDS_NAME,
                }
            )
        manifest_rel.write_text(json.dumps({"schema_version": 1, "entries": entries}))
        return manifest_rel

    def write_companion_summary(self, tracked_sha: str | None = None, tracked: str | None = None):
        tracked = tracked or "layout/bandgap-core/reference.spice"
        summary = self.tmp / f"manifests/artifacts/layout-bandgap-core-{RECORD_ID}.md"
        summary.parent.mkdir(parents=True, exist_ok=True)
        sha = tracked_sha or hashlib.sha256(REFERENCE_TEXT.encode()).hexdigest()
        summary.write_text(
            "# Evidence manifest: layout-bandgap-core / %s\n\n"
            "Not stored (identical bytes are already tracked in git):\n\n"
            "| name | sha256 | already committed at |\n|---|---|---|\n"
            f"| reference.spice | {sha} | `{tracked}` |\n" % RECORD_ID
        )
        return summary

    def write_tracked_reference(self, text: str = REFERENCE_TEXT) -> Path:
        path = self.tmp / "layout" / "bandgap-core" / "reference.spice"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path


class TestResolveRecordGds(_SyntheticRepo):
    def test_in_tree_record_resolves_unchanged(self) -> None:
        gds = self.record_dir / "bandgap_core_routed.gds"
        gds.write_bytes(GDS_BYTES)
        with self.klt_env():
            path, source = plc.resolve_record_gds(
                self.layout_dir, RECORD_ID, self.record_dir, cache_root=self.cache_root
            )
        self.assertEqual(path, gds)
        self.assertEqual(source["kind"], "in-tree")
        self.assertEqual(source["sha256"], GDS_SHA)
        self.assertEqual(self.count_klt_calls(), 0)

    def test_store_backed_record_fetches_through_the_manifest(self) -> None:
        self.write_store_manifest()
        with self.klt_env():
            path, source = plc.resolve_record_gds(
                self.layout_dir, RECORD_ID, self.record_dir, cache_root=self.cache_root
            )
        self.assertTrue(path.is_file())
        self.assertEqual(path.read_bytes(), GDS_BYTES)
        self.assertEqual(source["kind"], "artifact-store")
        self.assertEqual(source["manifest"], plc.layout_artifact_manifest_relpath(RECORD_ID))
        self.assertEqual(source["entry"], GDS_NAME)
        self.assertEqual(source["sha256"], GDS_SHA)
        self.assertEqual(source["size"], len(GDS_BYTES))
        self.assertEqual(source["cache"], str(path.relative_to(self.tmp)))
        self.assertEqual(self.count_klt_calls(), 1)

    def test_a_cached_digest_matched_download_is_reused_without_klt(self) -> None:
        self.write_store_manifest()
        with self.klt_env():
            plc.resolve_record_gds(
                self.layout_dir, RECORD_ID, self.record_dir, cache_root=self.cache_root
            )
            path2, _ = plc.resolve_record_gds(
                self.layout_dir, RECORD_ID, self.record_dir, cache_root=self.cache_root
            )
        self.assertTrue(path2.is_file())
        self.assertEqual(self.count_klt_calls(), 1)

    def test_a_corrupt_cache_is_refetched_not_trusted(self) -> None:
        self.write_store_manifest()
        cache = self.cache_root / RECORD_ID / "bandgap_core_routed.gds"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(b"stale partial download")
        with self.klt_env():
            path, _source = plc.resolve_record_gds(
                self.layout_dir, RECORD_ID, self.record_dir, cache_root=self.cache_root
            )
        self.assertEqual(path.read_bytes(), GDS_BYTES)

    def test_missing_manifest_names_the_record(self) -> None:
        with self.klt_env():
            with self.assertRaises(plc.PostLayoutError) as caught:
                plc.resolve_record_gds(
                    self.layout_dir, RECORD_ID, self.record_dir, cache_root=self.cache_root
                )
        self.assertIn(RECORD_ID, str(caught.exception))
        self.assertIn(plc.layout_artifact_manifest_relpath(RECORD_ID), str(caught.exception))

    def test_manifest_without_a_gds_entry_names_the_record(self) -> None:
        self.write_store_manifest(include_gds=False)
        with self.klt_env():
            with self.assertRaises(plc.PostLayoutError) as caught:
                plc.resolve_record_gds(
                    self.layout_dir, RECORD_ID, self.record_dir, cache_root=self.cache_root
                )
        self.assertIn(RECORD_ID, str(caught.exception))

    def test_a_failed_fetch_names_the_record(self) -> None:
        self.write_store_manifest()
        with self.klt_env(fail=True):
            with self.assertRaises(plc.PostLayoutError) as caught:
                plc.resolve_record_gds(
                    self.layout_dir, RECORD_ID, self.record_dir, cache_root=self.cache_root
                )
        self.assertIn(RECORD_ID, str(caught.exception))
        self.assertIn("broker_unreachable", str(caught.exception))

    def test_a_digest_mismatch_after_fetch_names_the_record(self) -> None:
        # The manifest pins a digest the fetched bytes cannot match, so the
        # post-fetch re-check (not just klt's own) must refuse them.
        self.write_store_manifest(sha256="0" * 64)
        with self.klt_env():
            with self.assertRaises(plc.PostLayoutError) as caught:
                plc.resolve_record_gds(
                    self.layout_dir, RECORD_ID, self.record_dir, cache_root=self.cache_root
                )
        self.assertIn(RECORD_ID, str(caught.exception))

    def test_a_manifest_gds_entry_is_found_by_staging_name(self) -> None:
        manifest = {
            "entries": [
                {"name": "layout/bandgap-core/staging/other-record/x.gds", "sha256": "a" * 64},
                {"name": GDS_NAME, "sha256": GDS_SHA, "size": len(GDS_BYTES)},
            ]
        }
        entry = plc._manifest_gds_entry(manifest, RECORD_ID)
        self.assertEqual(entry["name"], GDS_NAME)


class TestResolveRecordReference(_SyntheticRepo):
    def test_in_tree_reference_resolves_unchanged(self) -> None:
        (self.record_dir / "reference.spice").write_text(REFERENCE_TEXT)
        path, source = plc.resolve_record_reference(self.layout_dir, RECORD_ID, self.record_dir)
        self.assertEqual(path, self.record_dir / "reference.spice")
        self.assertEqual(source["kind"], "in-tree")

    def test_store_backed_record_resolves_the_tracked_copy_digest_checked(self) -> None:
        self.write_companion_summary()
        self.write_tracked_reference()
        path, source = plc.resolve_record_reference(self.layout_dir, RECORD_ID, self.record_dir)
        self.assertEqual(path, self.tmp / "layout/bandgap-core/reference.spice")
        self.assertEqual(source["kind"], "tracked")
        self.assertEqual(
            source["sha256"], hashlib.sha256(REFERENCE_TEXT.encode()).hexdigest()
        )

    def test_a_drifted_tracked_reference_is_refused_naming_the_record(self) -> None:
        self.write_companion_summary()
        self.write_tracked_reference(text=REFERENCE_TEXT + "* drifted edit\n")
        with self.assertRaises(plc.PostLayoutError) as caught:
            plc.resolve_record_reference(self.layout_dir, RECORD_ID, self.record_dir)
        self.assertIn(RECORD_ID, str(caught.exception))

    def test_a_summary_without_a_reference_row_names_the_record(self) -> None:
        summary = self.tmp / f"manifests/artifacts/layout-bandgap-core-{RECORD_ID}.md"
        summary.parent.mkdir(parents=True)
        summary.write_text("# Evidence manifest\n\n| name | sha256 |\n|---|---|\n")
        with self.assertRaises(plc.PostLayoutError) as caught:
            plc.resolve_record_reference(self.layout_dir, RECORD_ID, self.record_dir)
        self.assertIn(RECORD_ID, str(caught.exception))

    def test_no_summary_and_no_in_tree_reference_names_the_record(self) -> None:
        with self.assertRaises(plc.PostLayoutError) as caught:
            plc.resolve_record_reference(self.layout_dir, RECORD_ID, self.record_dir)
        self.assertIn(RECORD_ID, str(caught.exception))

    def test_the_injector_guard_reads_the_resolved_reference(self) -> None:
        """The store-backed record's injector verdict must come from the
        digest-verified tracked reference: an injector-inclusive reference
        reads True, a core-only reference (pinned by its own summary) reads
        False, and a drifted one never reaches the guard at all (refused by
        the digest check, above)."""
        self.write_companion_summary()
        self.write_tracked_reference()
        self.assertTrue(
            plc.layout_record_draws_injector(self.record_dir, self.layout_dir)
        )
        core_only = REFERENCE_TEXT.replace("MMPC1", "XMPC1")
        self.write_tracked_reference(text=core_only)
        self.write_companion_summary(
            tracked_sha=hashlib.sha256(core_only.encode()).hexdigest()
        )
        self.assertFalse(
            plc.layout_record_draws_injector(self.record_dir, self.layout_dir)
        )


class TestResolveLatestLayout(_SyntheticRepo):
    def _latest(self) -> Path:
        latest = self.layout_dir / "reports" / "LATEST"
        latest.write_text(RECORD_ID + "\n")
        return latest

    def test_store_backed_latest_resolves_end_to_end(self) -> None:
        self._latest()
        self.write_store_manifest()
        with self.klt_env():
            record_id, record_dir, gds, source = plc.resolve_latest_layout(
                self.layout_dir, cache_root=self.cache_root
            )
        self.assertEqual(record_id, RECORD_ID)
        self.assertEqual(record_dir, self.record_dir)
        self.assertTrue(gds.is_file())
        self.assertEqual(source["kind"], "artifact-store")

    def test_in_tree_latest_resolves_without_a_manifest(self) -> None:
        self._latest()
        (self.record_dir / "bandgap_core_routed.gds").write_bytes(GDS_BYTES)
        with self.klt_env():
            record_id, _record_dir, gds, source = plc.resolve_latest_layout(
                self.layout_dir, cache_root=self.cache_root
            )
        self.assertEqual(record_id, RECORD_ID)
        self.assertEqual(gds, self.record_dir / "bandgap_core_routed.gds")
        self.assertEqual(source["kind"], "in-tree")
        self.assertEqual(self.count_klt_calls(), 0)


class TestMosFlavourGate(unittest.TestCase):
    EXPECTED = {"nfet": 19, "pfet": 54}

    def test_a_clean_binding_passes_and_reports_the_census(self) -> None:
        result = plc.check_parasitics_mos_flavour(
            _pex_netlist(19, 54), self.EXPECTED, RECORD_ID
        )
        self.assertTrue(result["clean"])
        self.assertEqual(result["observed"], {"nfet": 19, "pfet": 54})
        self.assertEqual(result["unexpected_mos_models"], {})

    def test_a_single_wrong_flavour_card_fails_though_the_total_agrees(self) -> None:
        """19 + 54 = 73 MOS cards either way; one nfet bound to the
        thin-oxide wrapper must still fail -- the exact hole a total-count
        check would leave open (issue #621's acceptance criterion)."""
        text = _pex_netlist(18, 54, nfet_thin=1)
        self.assertEqual(sum(plc.bound_mos_wrapper_census(text).values()), 73)
        with self.assertRaises(plc.PostLayoutError) as caught:
            plc.check_parasitics_mos_flavour(text, self.EXPECTED, RECORD_ID)
        self.assertIn(RECORD_ID, str(caught.exception))
        self.assertIn("flavour.json", str(caught.exception))

    def test_a_polarity_shortfall_fails_even_with_no_unexpected_models(self) -> None:
        with self.assertRaises(plc.PostLayoutError):
            plc.check_parasitics_mos_flavour(_pex_netlist(18, 54), self.EXPECTED, RECORD_ID)

    def test_the_census_ignores_bound_resistors_and_pnps(self) -> None:
        census = plc.bound_mos_wrapper_census(_pex_netlist(2, 3))
        self.assertEqual(
            census,
            {
                "sky130_fd_pr__nfet_g5v0d10v5": 2,
                "sky130_fd_pr__pfet_g5v0d10v5": 3,
            },
        )

    def test_an_unbound_legacy_netlist_censuses_to_nothing(self) -> None:
        legacy = "M$1 D1 D2 GDRV VSS nfet L=2 W=8\nR$98 VA VB 2003.8 res_high_po\n"
        self.assertEqual(plc.bound_mos_wrapper_census(legacy), {})


class TestLayoutRecordLvsStatus(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.record_dir = self.tmp / "reports" / RECORD_ID
        self.record_dir.mkdir(parents=True)

    def test_reads_the_combined_verdict(self) -> None:
        (self.record_dir / "lvs.combined.json").write_text(
            json.dumps({"status": "mismatch", "mismatch_count": 5})
        )
        status = plc.layout_record_lvs_status(self.record_dir, RECORD_ID)
        self.assertEqual(status["status"], "mismatch")
        self.assertEqual(status["mismatch_count"], 5)
        self.assertEqual(
            status["report"],
            f"layout/bandgap-core/reports/{RECORD_ID}/lvs.combined.json",
        )

    def test_a_record_without_the_report_reads_none(self) -> None:
        self.assertIsNone(plc.layout_record_lvs_status(self.record_dir, RECORD_ID))

    def test_a_corrupt_report_is_an_error_naming_the_record(self) -> None:
        (self.record_dir / "lvs.combined.json").write_text("{not json")
        with self.assertRaises(plc.PostLayoutError) as caught:
            plc.layout_record_lvs_status(self.record_dir, RECORD_ID)
        self.assertIn(RECORD_ID, str(caught.exception))


class TestClaimMatchesLvsVerdict(unittest.TestCase):
    def _provenance(self, mismatch_count):
        return {
            "layout_record_id": RECORD_ID,
            "layout_lvs": {"status": "mismatch", "mismatch_count": mismatch_count},
        }

    def test_an_lvs_clean_claim_against_a_mismatching_record_is_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            plc.check_claim_matches_lvs_verdict(
                "a-bench",
                "Measures the ROUTED, LVS-clean bandgap-core layout (issue #62) ...",
                self._provenance(5),
                ValueError,
            )
        self.assertIn("a-bench", str(caught.exception))
        self.assertIn(RECORD_ID, str(caught.exception))
        self.assertIn("mismatch_count=5", str(caught.exception))

    def test_a_claim_without_the_assertion_passes_on_the_same_record(self) -> None:
        plc.check_claim_matches_lvs_verdict(
            "a-bench",
            "Measures the ROUTED bandgap-core layout (LVS verdict cited under "
            "'Netlist provenance') ...",
            self._provenance(5),
            ValueError,
        )

    def test_the_assertion_passes_only_on_a_clean_verdict(self) -> None:
        plc.check_claim_matches_lvs_verdict(
            "a-bench",
            "Measures the ROUTED, LVS-clean bandgap-core layout ...",
            self._provenance(0),
            ValueError,
        )

    def test_a_record_with_no_verdict_has_nothing_to_contradict(self) -> None:
        plc.check_claim_matches_lvs_verdict(
            "a-bench",
            "Measures the ROUTED, LVS-clean bandgap-core layout ...",
            {"layout_record_id": RECORD_ID, "layout_lvs": None},
            ValueError,
        )


if __name__ == "__main__":
    unittest.main()
