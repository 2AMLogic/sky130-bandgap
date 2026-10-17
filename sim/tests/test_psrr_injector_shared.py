"""Shared helpers deduplicated out of the two psrr-injector scripts (issue #379)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import sim_common  # noqa: E402


def test_corner_id_and_matrix():
    assert sim_common.corner_id("tt", 27, 1.8) == "tt_27c_1.80v"
    assert sim_common.matrix(["tt", "ss"], [-40, 27], [1.7]) == [
        ("tt", -40, 1.7), ("tt", 27, 1.7), ("ss", -40, 1.7), ("ss", 27, 1.7),
    ]


def test_band_min_by_corner(tmp_path):
    rec = tmp_path / "r.json"
    rec.write_text(json.dumps({"corners": [
        {"corner_id": "a", "measurements": [{"name": "psrr_band_min", "value": -41.5}]},
        {"corner_id": "b", "measurements": [{"name": "psrr_band_min", "value": None}]},
    ]}))
    assert sim_common.band_min_by_corner(rec, "rec") == {"a": -41.5}
    with pytest.raises(sim_common._cr().HarnessError):
        sim_common.band_min_by_corner(tmp_path / "missing.json", "rec")


def test_run_all_variants(capsys):
    def fake(v, p, t, s):
        cid = sim_common.corner_id(p, t, s)
        return {"variant": v, "corner_id": cid, "ngspice_exit": 0, "timed_out": False,
                "measurements": {"psrr_band_min": -40.0} if v == "x" else {}}

    res = sim_common.run_all_variants(fake, ["x", "y"], [("tt", 27, 1.8)], 2, 5)
    assert set(res) == {("x", "tt_27c_1.80v"), ("y", "tt_27c_1.80v")}
    out = capsys.readouterr().out
    assert "[  1/2] x     tt_27c_1.80v" in out
    assert "NO MEASUREMENT (rc=0, timeout=False)" in out
