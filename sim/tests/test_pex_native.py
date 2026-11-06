"""Tests for sim/pex-native (issue #335): reference composition, the input
checks (one negative fixture each) and the pinned-klt resistor dialect."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PEX = Path(__file__).resolve().parents[1] / "pex-native"
sys.path.insert(0, str(PEX))
sys.path.insert(0, str(PEX.parent / "bin"))
import pexlib  # noqa: E402

REF = (PEX / "reference" / "bandgap_core_composed.spice").read_text()


def extracted(ports=pexlib.ROUTED_PORTS) -> str:
    return f".SUBCKT {pexlib.TOP} {' '.join(ports)}\n.ENDS {pexlib.TOP}\n"


def doc(ids):
    return {"corners": [{"corner_id": i, "measurements": [{"name": "vref_27", "value": 1.2, "status": "pass"}]}
                        for i in ids]}


class PexNative(unittest.TestCase):
    def test_committed_reference_is_current(self):
        self.assertEqual(pexlib.compose_reference(), REF)

    def test_reference_matches_extracted_pins(self):
        pexlib.check_reference(REF, extracted())

    def test_refuses_reordered_pins(self):
        ports = list(pexlib.ROUTED_PORTS)
        ports[0], ports[1] = ports[1], ports[0]
        with self.assertRaisesRegex(pexlib.PexNativeError, "pin mismatch"):
            pexlib.check_reference(REF, extracted(tuple(ports)))

    def test_refuses_reference_with_four_pins(self):
        four = REF.replace(" ".join(pexlib.ROUTED_PORTS), " ".join(pexlib.EXPOSED), 1)
        with self.assertRaisesRegex(pexlib.PexNativeError, "pin mismatch"):
            pexlib.check_reference(four, extracted())

    def test_refuses_reference_without_injector(self):
        bare = "\n".join(ln for ln in REF.splitlines() if not ln.startswith("XMNS "))
        with self.assertRaisesRegex(pexlib.PexNativeError, "startup injector"):
            pexlib.check_reference(bare, extracted())

    def test_matrix_complete_ok(self):
        pexlib.check_matrix(doc(pexlib.corner_ids()))
        self.assertEqual(len(pexlib.corner_ids()), 15)

    def test_refuses_incomplete_matrix(self):
        with self.assertRaisesRegex(pexlib.PexNativeError, "incomplete corner matrix"):
            pexlib.check_matrix(doc(pexlib.corner_ids()[:-1]))

    def test_refuses_errored_corner_dropped_to_empty(self):
        d = doc(pexlib.corner_ids())
        d["corners"][3]["measurements"] = []
        with self.assertRaisesRegex(pexlib.PexNativeError, "no measurement entries"):
            pexlib.check_matrix(d)

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "m.json"
            bad.write_text(json.dumps(doc(pexlib.corner_ids()[:3])))
            rc = subprocess.run([sys.executable, "-I", str(PEX / "check_inputs.py"), "matrix", "--measurements", str(bad)],
                                capture_output=True, text=True)
        self.assertTrue(rc.returncode == 1 and "REFUSED" in rc.stderr)

    def test_normalize_klt_resistors_keeps_value_and_is_translatable(self):
        import post_layout_common as plc

        raw = "X$98 A__t0 B__t0 VSS__t24 res_high_po r=2003.841367 L=5U W=1U\n"
        text, n = pexlib.normalize_klt_resistors(raw)
        self.assertEqual(n, 1)
        translated, counts = plc.translate_extracted_netlist(text)
        self.assertTrue(counts["res"] == 1 and "R$98 A__t0 B__t0 2003.841367" in translated)

    def test_delta_limits_declared_for_pilot_observables(self):
        lim = json.loads((PEX / "delta-limits.json").read_text())
        got = {o["name"]: o for o in lim["observables"]}
        self.assertTrue(set(got) == {"vref_27", "vref_min", "vref_max"})
        self.assertTrue(all(o["unit"] == "V" and o["rationale"] for o in got.values()))

    def test_grade_deltas_flags_exceeded_and_missing(self):
        import grade_deltas

        limits = json.loads((PEX / "delta-limits.json").read_text())
        rows = [{"corner_id": c, "spec_row": o["name"], "schematic_value": 1.2, "extracted_value": 1.2005}
                for c in pexlib.corner_ids() for o in limits["observables"]]
        g = grade_deltas.grade({"delta": rows}, limits)
        self.assertTrue(g["n_exceeded"] == 0 and not g["missing"])
        rows[0]["extracted_value"] = 1.19
        self.assertTrue(grade_deltas.grade({"delta": rows}, limits)["n_exceeded"] == 1)
        self.assertTrue(grade_deltas.grade({"delta": rows[1:]}, limits)["missing"])


if __name__ == "__main__":
    unittest.main()
