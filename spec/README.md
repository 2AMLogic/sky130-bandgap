# spec/

This directory holds the ratified specification and its decision history.

A decision record is required whenever a spec value or approach in the
target-spec table (see the top-level `README.md`) is set, changed, or
scoped — not for routine design/sim work that merely targets the existing
spec. To write one: copy `decision-records/TEMPLATE.md` to
`decision-records/DR-NNN-<slug>.md` (next unused `NNN`, one decision per
record), fill it in, and commit it alongside the spec change it justifies.
Never edit a ratified record after the fact — if a decision changes,
supersede it with a new `DR-NNN` that says so.
