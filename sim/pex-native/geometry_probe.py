#!/usr/bin/env python3
"""How far would vref_27 move if VB's resistor-to-resistor segment carried the geometry R? (issue #573)

Copies the r2 record's extracted.spice in memory (the record is never written),
replaces `RVB_seg8` (the ladder segment between VB's two resistor terminals
VB__t8/VB__t9, the only DC-carrying one -- the other VB terminals are pfet
gates) by each given value, and runs attribute_delta's tt/27C/3.30V probe:
one sequential local `ngspice -b` per value, no grid.

  python3 -I sim/pex-native/geometry_probe.py 95 399
"""
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import attribute_delta as ad  # noqa: E402

RECORD = HERE / "records" / "20261115-distributed-rc-r2"
_FLOAT = ad._FLOAT


def probe(text: str, label: str, pdk) -> dict:
    block = ad._extracted_block(text)
    log = ad._run_ngspice(ad.probe_deck(block, str(pdk.lib_file)), Path(tempfile.mkdtemp(prefix=f"geo-{label}-")))
    by = {m.group(1): float(m.group(2)) for m in re.finditer(rf"^v\((\S+)\)\s*=\s*({_FLOAT})\s*$", log, re.M)}
    return {k: by[ad.PROBE_NODES[k]] for k in ("VREF", "VA", "VB", "VBQ")}


def main(vals: list[str]) -> int:
    pdk = ad._pdk()
    ref = (HERE / "reference" / "bandgap_core_composed.spice").read_text()
    import measure_command as mc
    schem_block = mc.side_block("schematic", ref)
    log = ad._run_ngspice(ad.probe_deck(schem_block, str(pdk.lib_file)), Path(tempfile.mkdtemp(prefix="geo-schem-")))
    sch = {m.group(1): float(m.group(2)) for m in re.finditer(rf"^v\((\S+)\)\s*=\s*({_FLOAT})\s*$", log, re.M)}
    v_s = sch[ad.PROBE_NODES["VREF"]]
    text = (RECORD / "extracted.spice").read_text()
    print(f"schematic VREF {v_s:.6f} V")
    for v in [None] + vals:
        t = text if v is None else re.sub(r"^(RVB_seg8 \S+ \S+ )\S+", rf"\g<1>{v}", text, flags=re.M)
        assert v is None or t != text
        r = probe(t, str(v), pdk)
        print(f"RVB_seg8={'998.987 (record)' if v is None else v} ohm: VREF {r['VREF']:.6f} V, "
              f"delta {1e3 * (r['VREF'] - v_s):+.3f} mV")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
