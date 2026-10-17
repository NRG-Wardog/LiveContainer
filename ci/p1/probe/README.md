# P1 diagnostic-only pixel and topology probe

This independently sealed lane temporarily replaces the full native workflow on
`validation/p1-native-basis`. A green job means collection completed on phone and
tablet. It never grants P1 admission, builds an IPA, validates dependencies, or
claims the full host/native baseline matrix passed. Existing P0 evidence and P1
acceptance requirements remain unchanged. The production input is exactly
`fbaafb939bfd3b7c08fdc8ff4b8d2aae43526ece`, not the validation harness checkout.

## Reconstruction provenance

The previously reviewed, unpublished tree `435f0785` was lost when the execution
workspace reset. These are newly reconstructed bytes against published harness
`a8055512`, requiring new tests and review. The old tree approval does not cover
them. Publish only after reviewing this complete new tree; retain it in Git.

## Pixel capability experiment

The production prompt declaration and recovery modifier are copied verbatim.
No production instrumentation, copied-state flag, timer override, private AX,
or direct production copy-method call is used. A separate Begin capture button
arms a bounded observer before the ordinary XCTest Copy tap. At requested 100 ms
intervals, at most 120 full PNGs / 12 seconds are captured using public
`UIView.drawHierarchy(afterScreenUpdates:false)` on the single visible key window.
Each frame records the Boolean return, bounds/scale and before/after uptime.
Tick brackets also include PNG encoding and disk write. Capture stops 4.5 seconds
after the last real clipboard notification, within the hard bounds.

The monotonic clock is the same app `ProcessInfo.systemUptime` used for clipboard
payload, changeCount, event ordinal and actual synthetic lifecycle transitions.
Every completed frame and event atomically checkpoints the trace. Incomplete
traces survive early XCTest termination and remain ineligible for completed
collection. Each checkpoint records all previous atomic write durations; the
last write follows the capture window. Synchronous clipboard-event journaling
can delay the subsequent production feedback mutation and timer scheduling.
That measured perturbation must be included in interpretation.

A new scenario rejects existing output. Exact trace-to-PNG inventory is verified
before offline Apple Vision OCR. Raw frames remain unmodified; OCR returns text,
confidence and boxes, never an inferred expected feedback state. Independent
before/after XCTest screenshots are retained. Only actual exported video
attachments, if any, may be described as video evidence.

This route was selected as a capability hypothesis over external simctl video
because capture-work brackets and events share a clock without a video-clock
alignment assumption. It is NOT framebuffer proof: snapshots can be stale or
differ from compositor pixels, and main-thread capture/journaling may delay
production timers and XCTest idling. Brackets bound capture work, not pixel freshness. Review must
compare at least one steady-state region with independent XCTest screenshots,
recognize actual Copy Details -> Copied -> Copy Details pixels, and inspect max /
total overhead and frame gaps before selecting any later acceptance rate.
Missing, obscured, stale or ambiguous labels are unknown, never a negative label
observation or a pass.

Replacement is requested 0.75 seconds after the first real event; dismissal uses
that delay and reopens at 1.05 seconds. The second coordinate tap is experimental
normal XCTest input issued immediately after the first returns. Its actual event
ordinal, payload and generation determine what it hit. It may miss the window.
No overlap success is assumed. Later admission still requires own lifetime >=1.5
seconds, observation beyond the old deadline, expiry <5 seconds, actual reset /
cleared fields, and separate real replacement/reopened prompt tap coverage. Any
video-based clock alignment would need measured uncertainty and conservative
bounds before it could satisfy those criteria.

## Recovery topology experiment

Eight cases per device compare no-banner versus operation-banner at default and
AX5 for two roots: prior synthetic VStack/inline Recovery and production-shaped
List/insetGrouped/automatic large Home. Both use outer TabView with four child
NavigationViews and include an empty bottom inset and a one-point noninteractive,
AX-hidden clear overlay. Those are explicit no-op substitutes for the inactive
production picker path, not a full app/backend reproduction.

Pre-guard screenshots and native element observations survive missing controls.
Actual Open/Back actions are attempted when hittable. No-banner controls must
work for usable comparison. Banner overlap remains an observed failure outcome;
collection success does not reinterpret it as passing geometry. Full acceptance
still requires all four recovery branches on both devices, strict non-overlap,
continuous navigation/tab access and every recovery control reachable. A bounded
scrolling source correction needs its own source pin and review after diagnosis.

## Evidence and interpretation

The artifact retains pinned source/project and fragment hashes, exact harness
inputs, actual Xcode/Swift versions and simulator identities, raw XCTest bundles,
exports, summaries, raw PNGs/traces, capture costs, OCR, command logs, before/after
source proof and a complete SHA-256 index. Failures preserve partial evidence and
do not suppress collection on the other device. Diagnostic result always has
`admission_eligible:false`, `production_ready:false`,
`full_native_lane_executed:false`, `pixel_fidelity_proven:false` and
`timing_capability_proven:false`. Independent artifact review must determine the
next experiment; never launch a full lane merely because this probe is green.
