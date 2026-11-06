#!/usr/bin/env bash
# guard-review-332.sh — inert replay of the guard-review table (issue #332).
#
# Feeds each command to the PreToolUse hook as JSON on stdin. The command text
# is only ever a JSON string value: it is never eval'd or executed. Side effect:
# the hook may append lines to .loom/logs/guard-decisions.log (untracked).
#
# Exit 0 = every row matched (SKIP rows do not count as mismatches);
# exit 1 = at least one row differs from its expected decision.
set -u

COMMON="$(git rev-parse --path-format=absolute --git-common-dir)" || exit 2
MAIN="${COMMON%/.git}"                      # main checkout (cwd the hook sees)
TOP="$(git rev-parse --show-toplevel)"
HOOK="${GUARD_HOOK:-$TOP/.loom/hooks/guard-destructive.sh}"
[ -f "$HOOK" ] || { echo "hook not found: $HOOK" >&2; exit 2; }
command -v jq >/dev/null || { echo "jq required" >&2; exit 2; }

# Row D needs a managed worktree; otherwise the guard fails open.
HAVE_WT=0
for s in "$MAIN"/.loom/worktrees/*/.loom-managed; do [ -e "$s" ] && HAVE_WT=1; done

# label | expected (allow|deny) | reason substring (deny only) | command
ROWS=(
  'A|allow||S=/tmp/inert332; echo x > "$S/a.txt"'
  'C|allow||cd /tmp/inert332 && for n in a b; do echo x > "$n.gds"; done'
  'H|allow||D=/tmp/inert332; rm -rf "$D/x"'
  'F|allow||S=$(mktemp -d); echo x > "$S/a.txt"'
  'E|allow||S=/tmp/inert332/../../home; echo x > "$S/a.txt"'
  'B|deny|unexpanded shell variable|echo x > "$S/a.txt"'
  "D|deny|main repository checkout|S=$MAIN/sim; echo x > \"\$S/a.txt\""
  'G|deny|unexpanded shell variable|rm -rf "$D/x"'
)

fail=0
printf '%-3s %-6s %-6s %s\n' ROW EXPECT ACTUAL RESULT
for row in "${ROWS[@]}"; do
  IFS='|' read -r label expect reason cmd <<<"$row"
  if [ "$label" = D ] && [ "$HAVE_WT" = 0 ]; then
    printf '%-3s %-6s %-6s %s\n' "$label" "$expect" - "SKIP (no managed worktree; guard fails open)"
    continue
  fi
  out="$(jq -nc --arg c "$cmd" --arg d "$MAIN" \
      '{tool_name:"Bash",tool_input:{command:$c},cwd:$d}' \
    | (cd "$MAIN" && bash "$HOOK") 2>/dev/null)"
  actual="$(printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecision // "allow"' 2>/dev/null)"
  [ -n "$actual" ] || actual=allow
  res=ok
  if [ "$actual" != "$expect" ]; then
    res=MISMATCH
  elif [ "$expect" = deny ] && ! printf '%s' "$out" | grep -qF "$reason"; then
    res="MISMATCH (deny reason lacks '$reason')"
  fi
  [ "$res" = ok ] || fail=1
  printf '%-3s %-6s %-6s %s\n' "$label" "$expect" "$actual" "$res"
done
exit "$fail"
