# Guard review for issue #332: `worktree-write-confinement-unresolved-var`

Inert, current reproduction of the historical guard observation. Operator
ruling (2026-10-15) authorizes only this report plus containment negative
controls; nothing here relaxes confinement.

- **Hook**: `.loom/hooks/guard-destructive.sh` (dispatcher to
  `guard-destructive-generic.sh`)
- **Run against**: `origin/main` @ `932033b8`, cwd = main checkout with
  managed worktrees present
- **Method**: each command is passed as a JSON string on stdin
  (`{"tool_name":"Bash","tool_input":{"command":…},"cwd":…}`); it is never
  evaluated or executed. Replay: `bash docs/guard-review-332.sh`.

| # | Command text fed to hook | Expected | Actual | Role |
|---|---|---|---|---|
| A | `S=/tmp/inert332; echo x > "$S/a.txt"` | allow | allow | historical shape: same-command literal declaration |
| C | `cd /tmp/inert332 && for n in a b; do echo x > "$n.gds"; done` | allow | allow | historical shape: literal `/tmp` cwd + literal loop var |
| H | `D=/tmp/inert332; rm -rf "$D/x"` | allow | allow | same-command literal declaration, rm |
| F | `S=$(mktemp -d); echo x > "$S/a.txt"` | allow | allow | mktemp scratch |
| E | `S=/tmp/inert332/../../home; echo x > "$S/a.txt"` | allow | allow | resolves outside repo; observation only |
| B | `echo x > "$S/a.txt"` | deny | deny | negative control: undeclared var |
| D | `S=<main-checkout>/sim; echo x > "$S/a.txt"` | deny | deny | negative control: declaration resolving into main checkout |
| G | `rm -rf "$D/x"` | deny | deny | negative control: undeclared var, rm |

Row D needs a managed worktree to exist; without one the guard fails open and
the script reports SKIP for D instead of a pass or fail.

## Conclusion

Current behavior is correct for every historical shape sampled, and the safety
floor (B, D, G) holds. **No parser change is warranted.** Other guard decisions
listed in the 2026-10-08 issue comment (stash-scope, rm-scope-outside-repo,
gh-api-rawfield, force-op:detached, untracked-cleanup) are deliberate
protections and remain observations only. No file under `.loom/hooks/` was
modified.
