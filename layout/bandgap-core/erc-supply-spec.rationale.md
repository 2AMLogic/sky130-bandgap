# `erc-supply-spec.json` — rationale

This text used to live in the spec's `_comment` key. klt 0.7.0 rejects unknown
top-level spec keys (`unknown field '_comment'`; allowed: devices, nets, stackup,
ties, ties_disclosure, vias), so the per-field rationale is kept beside the spec
instead. The spec itself must stay free of non-schema keys.

```text
klt erc supply spec for bandgap-core's routed GDS -- the T1 item 11
(power delivery, structural) artifact. Run it with:

    layout/bin/run-erc-supply-flow.sh

which drives, for each committed routed GDS:

    klt erc <bandgap_core_routed.gds> layout/bandgap-core/erc-supply-spec.json \
      --deck sky130 --pdk sky130 --format json

Reports land under layout/bandgap-core/erc/<record-id>/; read that
directory's record.md first, and layout/bandgap-core/erc/README.md for
what this evidence does and does not establish.

=== Layer provenance (every number below resolved twice) ===

Source A -- the PDK's own KLayout layer properties file:
  ~/.ciel/ciel/sky130/versions/f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7/
  sky130A/libs.tech/klayout/tech/sky130A.lyp  (the same sky130A install
  sim/pdk.json pins). Each <properties><source> entry names the pair
  directly, e.g. 'poly.drawing - 66/20'.
Source B -- klayout-tools' curated sky130 deck layer table,
  klayout_tools/decks/sky130.py (its module docstring's 'Layer numbers
  (verified against sky130.lyt's layer-map ...)' block for the
  diff/tap/poly/licon1/li1/mcon/met1/via/met2 rows, and the
  'klt extract connectivity + device-extraction deck' comment block for
  nwell.drawing 64/20 and the datatype-5 label-layer convention).
Both sources agree on every pair used below. No number here was copied
from another PDK's spec.

=== stackup, entry by entry ===

(Drawn-area figures below are measured on the newest committed routed
GDS, layout/bandgap-core/reports/20260817-020222-13476b7/, and are there
to show each declared role is actually used -- they are not part of the
spec and do not change what klt erc reads.)

- poly 66/20, role 'gate'. klt erc's own contract requires stackup[0] to
  carry role 'gate', so the accumulation starts at gate poly, not at a
  metal. active_layer is diff 65/20, which makes the antenna denominator
  gates[].gate_area_um2 the true poly n diff gate-oxide area rather than
  raw poly area (klayout-tools docs/cli/erc.md, 'Gate area: poly n diff
  vs. raw poly area'). That matters here specifically: this block draws
  587 um^2 of res_high_po poly-resistor body (poly.res 66/13 marker over
  66/20), real poly with no gate oxide, which would otherwise be read as
  gates and reported with non-physical antenna ratios. Running with
  --deck sky130 additionally carves that resistor body out of the poly
  conductor role entirely (provenance.devices records the carve-out and
  its 587 um^2), so a poly resistor is not read as a wire shorting the
  nets at its two ends -- which is exactly the failure mode that would
  otherwise fabricate an erc.supply_short across a supply-referenced
  bias string (docs/cli/erc.md, 'Device bodies are not wires', #2183).
- li1 67/20. sky130's local-interconnect level; this block routes device
  terminals and both supply straps on it (4080 um^2 drawn).
- met1 68/20. The block's main routing level (1688 um^2 drawn) and the
  only level carrying pin text -- see label_layer below.
- met2 69/20. The escape plane over the core (276 um^2 drawn); it is the
  topmost conductor this block draws. met3/met4/met5 (70/20, 71/20,
  72/20) are deliberately absent from this spec because they are absent
  from the stream -- `klt layers` on both committed routed GDSs reports
  exactly 16 layers and none of them is a met3+ level, so declaring them
  would add nothing (klt erc allows it, but a spec that lists layers the
  design does not use is a spec that has not been read against the
  design).

=== label_layer ===

- met1 carries label_layer 68/5 (met1.label). This is the ONLY label
  layer declared, because 68/5 is the only text-bearing layer in the
  stream: it holds all 11 of this block's pin labels (VDD, VSS, VOUT,
  VA, VB, VBQ, PN, D1, D2, TAIL, GDRV) -- exactly the 11 pins
  lvs.combined.json matches against reference.spice. li1.label 67/5,
  poly.label 66/5 and met2.label 69/5 carry no text here, so declaring
  them would name nothing. Net names in nets[] below are matched against
  this text, so 68/5 is what makes 'VDD'/'VSS' resolvable at all rather
  than a cosmetic nicety.

=== vias ===

  licon1 66/44 (poly->li1), mcon 67/44 (li1->met1), via 68/44
  (met1->met2) -- the three via levels this block actually draws,
  bridging consecutive stackup roles in fabrication order. via2 69/44
  and above are absent from the stream for the same reason met3+ is.

=== nets ===

  VDD and VSS, both kind 'supply'. 'supply' is what makes a short
  between the two report as the severe erc.supply_short rather than the
  general erc.multiply_driven_net, and it is what T1 item 11 grades on.
  Each must resolve to exactly ONE electrical island:
  erc.unconnected_net fires both on zero label matches (nothing in the
  layout carries that name) and on more than one island (the rail is
  split into pieces that never touch), so zero findings of that rule is
  the 'one island per supply' verdict itself, not merely an absence.

=== ties: the two n-well classes ===

  The routed GDS draws eight merged shapes on nwell 64/20 holding two
  differently-biased well classes: five wells at VDD (the PMOS bodies)
  and three at VSS (the vertical-PNP base tubs). ties[].well_layer alone
  would check every shape against one net, so each tie narrows its well
  side with ties[].well_requires_boxes (klayout-tools#2339 / #2540, klt
  0.7.0): a merged shape is graded when it interacts with the union of
  those [left, bottom, right, top] micrometre boxes. Each box below is the
  bounding box of one merged nwell shape read from the newest routed GDS,
  layout/bandgap-core/reports/20260923-070209-dbd57a9/
  bandgap_core_routed.gds (klayout, merged 64/20 region), and the class
  assignment comes from the two former known-gap reproductions: the VDD
  run's erc.missing_tie bounds are exactly the three VSS-class wells and
  the VSS run's are exactly the five VDD-class wells, so between them they
  partitioned all eight shapes (the earlier 4+2 / six-well count in this
  file's history under-counted the shapes; the report bounds are the
  source of truth).

  The class selection rests on the caller's word about which shapes are
  which, so klt lists both ties in erc_coverage.checked_by_well_assertion
  rather than as drawn-marker selection. The falsifiability evidence is the
  negative control committed beside each record (the same boxes declared to
  the opposite net, expecting erc.missing_tie): see
  layout/bandgap-core/erc/README.md. A ninth nwell shape added to the
  layout would match neither box list and would NOT be checked -- extend
  the boxes when the well set changes.

  The tap is sky130's dedicated tap layer 65/44 (tap_is_dedicated), tied
  through li1 to the supply, exactly as in the known-gap reproductions.
```
