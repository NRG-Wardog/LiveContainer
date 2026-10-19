# Local fixture registration and retained draw receipts

This directory is an opt-in source generator and validation primitive. No
published candidate is changed. Swift has not been compiled or run here. The
Python tests exercise source reconstruction and retained-row validation, not
UIKit ordering, native scheduling, filesystem durability, or capture acceptance.

## Exact fixture delta

`render_fixture.py` still requires the original maintained fixture SHA256
`3fa3f4329dd0dac18a94d8c43922e545be87ebed5136b7a49d18b02ca57118ff`
and packet-source SHA256
`8b6493a7015ff5c4dbf33a81ba37f27972ba1069653bfca31d9ecf6c0b4da0ee`.
It copies the reviewed packet enum verbatim and appends `registration.swift`.
There are exactly three insertions into the original fixture:

1. One stored receipt buffer and its forwarding method in `P1VideoProbe`.
2. One buffer attachment immediately after the existing `start` event append
   and before the existing `journal.start()` call.
3. The existing fixture-only non-hit-testing four-packet/four-feature overlay.

Removing those additions reconstructs the original fixture byte-for-byte. No
production action, timer, declaration, original statement, or protocol command
is replaced. The source guards and native source identity checks remain required.

## Queue and ordering

The screen starts the probe in `onAppear`; UIKit anchor drawing is not assumed
to occur later. The new MainActor buffer retains pre-start rows and forwards
them, in order, once the journal exists. The original `start` event is enqueued
first. Therefore journal file order need not be global draw-time order: an early
draw can have an uptime less than the previously written `start` event.

The buffer accepts at most 520 draw rows (eight views with at most 64 successful
draws and one terminal error each). It reserves one further pending error row.
A duplicate attachment, sequence restart/gap, wrong ordinal/session, invalid
draw, or overflow latches failure; later draw receipts are explicitly suppressed
and the run is ineligible. The first-draw inventory is never queued before
attachment, so at most 521 fixed-shape rows can wait in memory. This bound is not
a measured observer-cost or archive-budget claim.

Both successful and failed draw rows carry canonical `uptime = beforeUptime`,
`clock = app-ProcessInfo.systemUptime`, `timingMeaning = fixture-draw-only`, and
false `displayTimeEstablished` / `admissionEligible`. The journal separately
adds enqueue/start clocks and its prior-write inventory. Draw brackets measure
only the drawing body. They exclude subsequent receipt forwarding/queue flush
work and do not establish presentation, freshness, capture time, or acceptable
observer overhead.

## Mandatory future host prerequisite

`direct-anchor-initial-draws` is emitted once, only after all eight session-bound
`direct-anchor-draw` rows with source tags `packet` and `feature`, each ordinals 1–4 and `draw = 1` have been forwarded to
the journal. Its `initialDrawsEnqueued = true` means queued writes, not durable
receipts or visible pixels. It has no authority by itself.

Before baseline release, the future host must retrieve a verified contiguous
journal prefix containing the inventory and all eight earlier source-tagged draw=1 rows, resolve
their immutable retained bytes/hashes, and run
`draw_receipts.validate_initial_draw_receipts(events, session)`. Bind these exact
retained events into the separately verified four-anchor proof. Missing rows,
errors, unknown fields, reused/gapped IDs, clock contradictions, or a missing
inventory prohibit release. Final replay must validate the complete journal;
later errors remain fatal even after an earlier valid prerequisite. The current
handoff/native producer has not been integrated with this prerequisite here.

`firstDrawSources` is exactly the ordered packet-1 through packet-4 and feature-1 through feature-4 inventory. Each draw sequence is separately bounded and tracked by `(source, anchor)`; views cannot substitute for one another.

The validator returns event indices and draw-cost diagnostics, always with
`admissionEligible = false`. Collection completeness, hash resolution, journal
write-cost checking, measured clock mapping, actual session-bearing pixels,
frozen geometry, all frame gaps, production labels/actions, and cleanup remain
separate mandatory evidence. Static 3-point cells require an actually measured
decoder scale of at least four pixels per cell; their viability, non-overlap,
containment, and ROI byte budget cannot be inferred from the draft placement.

## Local tests

Run `python3 -B -m unittest discover -s p1-stall-isolation/direct-feedback-local/fixture -v`
from the workspace root. The same tests pass under `python3 -B -O`.

## Isolated tiny features and explicit premise

The overlay also draws four clipped, non-hit-testing, opaque magenta 2×2-point UIViews with AX identifiers `p1-direct-feature-1` through `-4`. Each sits diagonally outward from its corresponding packet board with a fixed 2-point source gap. The whole actual AX frame is measured by the handoff; nominal layout coordinates are never substituted for the measurement. Packet draws carry `source=packet`; feature draws carry `source=feature`. All eight draw bodies and their first-draw inventory must be retained. No production layout constraints or action/delay statements change.

The interval adapter is conditional on exclusive source locality: observed qualifying magenta comes from that corresponding source-owned clipped UIView, under a single upright positive affine transform whose native filtering behavior is separately validated. An exact-color component and adjacency do not authenticate a same-colored foreign replacement. No exact vector edge, center, fixed pixel rendering error, or native presentation is asserted. Source binding, real pixel rejection of overlap/clipping, and independent holdout remain mandatory.
