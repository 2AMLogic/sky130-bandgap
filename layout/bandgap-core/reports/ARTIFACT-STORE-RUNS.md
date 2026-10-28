# Report-run GDS moved to the artifact store (issue #440)

Operator ruling (2026-10-28): the `.gds` blobs of superseded bandgap-core
report runs may leave git for the fleet artifact store. Nothing was deleted:
all 133 files (8,404,582 bytes) were stored and checked with
`klt artifact verify` (all 212 candidates passed, 0 failed) before `git rm`. Each run's
`record.md`, verdict JSONs, renders and other non-GDS files stay in place.

Kept in git: `20260804-012421-1a97bf5` (read by
`layout/tests/test_routed_flow_gates.py`) and every run from `20260806-055811-3a4293a`
onward.

79 further `.gds` files in these runs are byte-identical to files still tracked
in later runs (same git blob), so moving them would free nothing; they stay.

## Moved (133 files, 15 run directories)

- 20260803-192947-e7a30b4 (13 files)
- 20260803-232955-05e1b99 (12 files)
- 20260803-235842-b4bcce9 (12 files)
- 20260804-001742-bc9c31f (12 files)
- 20260804-045058-649329e (12 files)
- 20260804-065252-496ab43 (12 files)
- 20260804-105025-25d02e6 (12 files)
- 20260804-113412-4fb2a3a (12 files)
- 20260804-174203-ddf7f17 (6 files)
- 20260804-181651-f3b2b2e (6 files)
- 20260804-190815-092c8cb (6 files)
- 20260804-211109-0336eb4 (6 files)
- 20260804-231410-539e30b (4 files)
- 20260805-102026-19c521f (4 files)
- 20260805-105719-f126dca (4 files)

## Recovery

Manifest (name, size, sha256 per file):
`manifests/artifacts/layout-bandgap-core-superseded-reports-440.manifest.json`.
Each `name` is the file's original repo path. Fetching needs
`$KLT_ARTIFACT_BROKER`:

```bash
klt artifact get 'manifests/artifacts/layout-bandgap-core-superseded-reports-440.manifest.json#<repo path of the .gds>' -o <dest>
klt artifact verify manifests/artifacts/layout-bandgap-core-superseded-reports-440.manifest.json
```

Pre-move commit (on `main`, contains every blob): `a2ce34b7ba9910c4291de3fb241e3387a61676fb`.

```bash
git checkout a2ce34b7ba9910c4291de3fb241e3387a61676fb -- layout/bandgap-core/reports/<run-id>
```
