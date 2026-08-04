## DRC Report: /home/ubuntu/GitHub/sky130-bandgap/.loom/worktrees/issue-62/layout/trivial-cell/reports/20260804-190552-092c8cb/trivial_mos_array.gds
**Status:** ✅ clean
- Deck: sky130
- File: /home/ubuntu/GitHub/sky130-bandgap/.loom/worktrees/issue-62/layout/trivial-cell/reports/20260804-190552-092c8cb/trivial_mos_array.gds

No violations found.

## LVS Report: trivial_mos_array.gds vs reference.spice
**Status:** ✅ match
- Top: trivial_mos_array
- Engine: klayout

| Category | Severity | Side | Description |
| --- | --- | --- | --- |
| device.body_unverified | warning | layout | 4 NMOS device body terminal(s) were compared against the 'vsubs' deck-synthesized substrate net, not a real schematic net -- no drawn substrate-tap geometry resolved these device(s)' body terminal to a real net (see docs/cli/extract.md, "Coverage") |
| topology | warning | both | nets were paired ambiguously; the comparer resolved it structurally (consider a hints.same_nets entry to pin this down) |
| topology | warning | both | nets were paired ambiguously; the comparer resolved it structurally (consider a hints.same_nets entry to pin this down) |
| topology | warning | both | nets were paired ambiguously; the comparer resolved it structurally (consider a hints.same_nets entry to pin this down) |
| topology | warning | both | nets were paired ambiguously; the comparer resolved it structurally (consider a hints.same_nets entry to pin this down) |
| topology | warning | both | nets were paired ambiguously; the comparer resolved it structurally (consider a hints.same_nets entry to pin this down) |
| topology | warning | layout | device class has no counterpart on the other side, but no devices of this class were extracted either -- not a real topology mismatch |
| topology | warning | layout | device class has no counterpart on the other side, but no devices of this class were extracted either -- not a real topology mismatch |
