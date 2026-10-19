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

The overlay also draws four clipped, non-hit-testing, opaque magenta 3×3-point UIViews with AX identifiers `p1-direct-feature-1` through `-4`. Each sits diagonally outward from its corresponding packet board with a fixed 2-point source gap. The whole actual AX frame is measured by the handoff; nominal layout coordinates are never substituted for the measurement. Packet draws carry `source=packet`; feature draws carry `source=feature`. All eight draw bodies and their first-draw inventory must be retained. No production layout constraints or action/delay statements change.

The interval adapter is conditional on exclusive source locality: observed qualifying magenta comes from that corresponding source-owned clipped UIView, under a single upright positive affine transform whose native filtering behavior is separately validated. An exact-color component and adjacency do not authenticate a same-colored foreign replacement. No exact vector edge, center, fixed pixel rendering error, or native presentation is asserted. Source binding, real pixel rejection of overlap/clipping, and independent holdout remain mandatory.

## Native overlap correction after run39262135354

The retained AX log measured anchor3 at `[8,766,114,66]` and the live marker at `[105,771.33333333333337,192,16]`:17×16points overlap. The safe-area-sized overlay shares the original bottom inset with the live marker. Its geometry origin/size inferred from queried anchors is `[0,62]` / `[402,778]`, not the full `[0,0,402,874]` app viewport used by the early synthetic layout.

The historical2-point-feature correction gave only the bottom packet+feature pairs a fixed96-point upward offset. On those retained bounds, board3 became `[8,670,114,66]`, its historical modeled feature became `[4,738,2,2]`, and their historical full retained envelope ended at740, leaving31.333points before the unchanged live marker. The fourth board/features were not queried before failure; their coordinates in regression tests are explicitly source-model predictions, not native AX measurements. Both members move together because a board-only or64-point move can leave the full retained packet+feature ROI overlapping the marker. The minimum overlay height guard increases by the same fixed96points. No production view layout, test action/delay, baseline control, or whole-region overlap check changes.

The native before screenshot is an XCTest3× attachment of1206×2622pixels. It does not establish ScreenCaptureKit dimensions, scale, timing, or admission. `native-layout-39262135354.json` binds the retained log/attachment hashes and measured viewport/control bounds. `test_native_layout.py` reconstructs the exact previous overlay source by removing the placement and explicitly declared feature-size deltas, reproduces the original overlap, and checks the corrected full source envelopes.

The actual370×74-point Copy AX rectangle, unlike the earlier210×44-point synthetic control, exceeded the superseded512KiB six-ROI budget at representative1.4× scale. The coordinated successor allows1MiB combined per complete frame while independently enforcing6000total records,3GiB cumulative raw pixels and4GiB inclusive archive. The exact actual-AX synthetic model now passes1.4×; larger-scale positives and an over1MiB negative retain every source region. These are area-renderer tests, not predictions of native window scale, filtering, or admission.

## Historical centered three-point source feature successor

Run39299912951 retained a783×1600 baseline in which each upper2-point feature
formed two exact-magenta components separated by a BGRA(255,1,255,255) sample.
The strict detector rejected all six components; that failure remains unchanged.
That successor grew only the four source-owned features symmetrically to3×3points,
with unchanged centers and packet/control positions. Whole measured3×3 AX bounds
are mandatory. In the historical placement model feature3 was
[3.5,737.5,3,3], its full envelope ends at740.5, and the exact modeled marker gap
is30.83333333333337points. All whole-region non-overlap checks remain.

The exact-color detector, four-component requirement, three-anchor fit, fourth
holdout, whole-cell marker interiors, timing limits and storage bounds are
unchanged. A4-point proposal failed the existing synthetic whole-cell interval
check and was not adopted. Three-point synthetic success is not proof of native
filtering/connectivity or capture acceptance.

## Integral-origin three-point placement

Run39302741403 rejected feature1 against the unchanged exact3×3 AX check;
the returned rectangle was not retained, so snapping versus binary64 subtraction
is unresolved. The new fixture moves each feature center0.5point outward
(5→4.5 from its corner), giving integral source bounds while retaining3×3size.
Packet boards and all product controls remain fixed. The historical layout model
now gives feature3[3,738,3,3], with the full envelope ending741 and marker gap
30.33333333333337points. Actual AX bounds are still measured in full, never
replaced by these modeled coordinates. Failure text now retains the sampled
feature identity/rectangle and window rectangle. No tolerance or decoder change
is introduced; native geometry and pixel connectivity remain unproven.

Run39305732663 confirmed all four current AX features exactly3×3points. Native
filtered capture still split every feature into two exact-magenta strips.
The separate tagged complete-support association successor is documented in
pixels/REGISTRATION_BRIDGE.md; it changes no fixture source or product action.
