"""Tests for sim/pex-native (issue #335): reference composition, the input
checks (one negative fixture each) and the pinned-klt resistor dialect."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

PEX = Path(__file__).resolve().parents[1] / "pex-native"
sys.path.insert(0, str(PEX))
sys.path.insert(0, str(PEX.parent / "bin"))
import pexlib  # noqa: E402

REF = (PEX / "reference" / "bandgap_core_composed.spice").read_text()


def extracted(ports=pexlib.ROUTED_PORTS) -> str:
    return f".SUBCKT {pexlib.TOP} {' '.join(ports)}\n.ENDS {pexlib.TOP}\n"


def test_committed_reference_is_current():
    assert pexlib.compose_reference() == REF


def test_reference_matches_extracted_pins():
    pexlib.check_reference(REF, extracted())


def test_refuses_reordered_pins():
    ports = list(pexlib.ROUTED_PORTS)
    ports[0], ports[1] = ports[1], ports[0]
    with pytest.raises(pexlib.PexNativeError, match="pin mismatch"):
        pexlib.check_reference(REF, extracted(tuple(ports)))


def test_refuses_reference_with_four_pins():
    four = REF.replace(" ".join(pexlib.ROUTED_PORTS), " ".join(pexlib.EXPOSED), 1)
    with pytest.raises(pexlib.PexNativeError, match="pin mismatch"):
        pexlib.check_reference(four, extracted())


def test_refuses_reference_without_injector():
    bare = "\n".join(ln for ln in REF.splitlines() if not ln.startswith("XMNS "))
    with pytest.raises(pexlib.PexNativeError, match="startup injector"):
        pexlib.check_reference(bare, extracted())


def doc(ids):
    return {"corners": [{"corner_id": i, "measurements": [{"name": "vref_27", "value": 1.2, "status": "pass"}]}
                        for i in ids]}


def test_matrix_complete_ok():
    pexlib.check_matrix(doc(pexlib.corner_ids()))
    assert len(pexlib.corner_ids()) == 15


def test_refuses_incomplete_matrix():
    with pytest.raises(pexlib.PexNativeError, match="incomplete corner matrix"):
        pexlib.check_matrix(doc(pexlib.corner_ids()[:-1]))


def test_refuses_errored_corner_dropped_to_empty():
    d = doc(pexlib.corner_ids())
    d["corners"][3]["measurements"] = []
    with pytest.raises(pexlib.PexNativeError, match="no measurement entries"):
        pexlib.check_matrix(d)


def test_cli_exit_codes(tmp_path):
    bad = tmp_path / "m.json"
    bad.write_text(json.dumps(doc(pexlib.corner_ids()[:3])))
    rc = subprocess.run([sys.executable, "-I", str(PEX / "check_inputs.py"), "matrix", "--measurements", str(bad)],
                        capture_output=True, text=True)
    assert rc.returncode == 1 and "REFUSED" in rc.stderr


def test_normalize_klt_resistors_keeps_value_and_is_translatable():
    import post_layout_common as plc

    raw = "X$98 A__t0 B__t0 VSS__t24 res_high_po r=2003.841367 L=5U W=1U\n"
    text, n = pexlib.normalize_klt_resistors(raw)
    assert n == 1
    translated, counts = plc.translate_extracted_netlist(text)
    assert counts["res"] == 1 and "R$98 A__t0 B__t0 2003.841367" in translated


def test_delta_limits_declared_for_pilot_observables():
    lim = json.loads((PEX / "delta-limits.json").read_text())
    got = {o["name"]: o for o in lim["observables"]}
    assert set(got) == {"vref_27", "vref_min", "vref_max"}
    assert all(o["unit"] == "V" and o["rationale"] for o in got.values())


def test_grade_deltas_flags_exceeded_and_missing():
    import grade_deltas

    limits = json.loads((PEX / "delta-limits.json").read_text())
    rows = [{"corner_id": c, "spec_row": o["name"], "schematic_value": 1.2, "extracted_value": 1.2005}
            for c in pexlib.corner_ids() for o in limits["observables"]]
    g = grade_deltas.grade({"delta": rows}, limits)
    assert g["n_exceeded"] == 0 and not g["missing"]
    rows[0]["extracted_value"] = 1.19
    assert grade_deltas.grade({"delta": rows}, limits)["n_exceeded"] == 1
    assert grade_deltas.grade({"delta": rows[1:]}, limits)["missing"]
