# Evidence manifests

New sim evidence is stored in the fleet artifact store. Git keeps only:

- `<bench>-<run-id>.manifest.json`: one entry per stored object
  (`sha256`, `size`, `artifact:` `uri`, `name`), written by `klt artifact put`;
- `<bench>-<run-id>.md`: a summary table (name, size, sha256 per object).

Evidence bytes are private and manifests are public, so manifests are safe to
commit. Raw per-corner outputs (`sim/*/corners/`) are git-ignored.

## Recipe

The harness does this itself: `sim_common.publish_corner_evidence()` runs from
`run_matrix_and_write_record()` and from each bespoke harness `main()`, before
the record is written.

1. A run writes raw outputs to `sim/<bench>/corners/<run-id>/` (ignored).
2. `klt artifact put --manifest manifests/artifacts/<bench>-<run-id>.manifest.json`
   stores them; the harness commits nothing else from that directory.
3. Commit the manifest, the summary and the run record.
4. Check from a fleet worker: `klt artifact verify manifests/artifacts/<manifest>`.

## Fail closed

If `$KLT_ARTIFACT_BROKER` is unset, `klt` has no `artifact put`, or the broker is
unreachable, the harness exits nonzero before running (or, if the store fails
mid-run, before writing the record or manifest). There is no fallback that
commits bytes. Needs klayout-tools `7e3561f` or later. Never write the broker URL,
a bucket name, an account ID or any object-store URI into this repo.

## CI

`scripts/ci/check_artifact_manifests.py` (in `npm run check:ci`) fails on a bad
schema, a non-`artifact:` `uri`, any storage-location string (S3 URI or AWS ARN), or an entry
whose sha256 matches a tracked file. Evidence committed before this change stays
where it is (`sim/` is append-only).
