# Pruned trivial-cell report runs (issue #381)

Operator ruling (2026-10-19): old trivial-cell reports that are no longer
needed may be dropped. Eight of the twelve non-LATEST run directories were
removed; no result was edited, and `LATEST` and its target are unchanged.

**Assessment.** Each pruned run has the same cell (byte-identical
`trivial_mos_array.gds`, `reference*.spice`), the same stage outcomes (DRC
clean; extract 4 devices / 13 nets; LVS good reference `match`,
`mismatch_count=8`; negative controls 34 / 32) and the same `klt 0.2.0` as
the retained `20260806-055840-3a4293a`. They differ only in record id and
repo state, plus report-schema fields (`68/44` layer listing,
`voltage_domain_warnings`, `unbiased_pmos_body_nets`) that the current record
carries as a superset. None is cited outside its own directory.

**Kept** (each records a distinct outcome): `LATEST` target
`20260806-055840-3a4293a`, and the four `klt 0.1.0` runs
`20260803-133256-69a6ac2` (README-cited original proof), `20260803-190225-e7a30b4`,
`20260803-232933-05e1b99`, `20260804-045401-649329e` (8-device geometry;
LVS 12 / negative controls 62 / 60, different GDS and JSON from the current
record).

## Deleted (8 directories, 128 files, 425,926 bytes)

- 20260804-162626-ddf7f17
- 20260804-183144-f3b2b2e
- 20260804-184426-f3b2b2e
- 20260804-190552-092c8cb
- 20260804-195059-f6df783
- 20260804-201036-914af16
- 20260804-211107-0336eb4
- 20260805-104828-f126dca

## Recovery

Pre-removal commit (on `main`, contains all eight): `65e3c7f63e85c4547e87c7befe453387973ba72b`.

```bash
git checkout 65e3c7f63e85c4547e87c7befe453387973ba72b -- layout/trivial-cell/reports/<run-id>
```

Verified: extracting all eight directories with `git archive` from that
commit reproduces the original blob ids of all 128 files exactly.
