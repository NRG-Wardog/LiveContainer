# External video capability experiment

Diagnostic only. A successful collection never grants P1 native/UI admission.
The existing full acceptance lane remains unchanged and disabled. Production
feedback/timers/actions are extracted verbatim. Recovery layout helpers and the
complete wrapper are extracted verbatim from the separately reviewed source.

## Why external video

Run 39016929889 established readable actual Copy Details / Copied / Copy Details
pixels but recurring app-thread rasterization and PNG work took up to 2.15 s per
frame and delayed normal XCTest inputs beyond the captured window. This probe
removes all application rasterization and PNG encoding. `simctl io recordVideo`
records externally; decoding and OCR happen after interaction. It introduces no
private XCTest API, synthetic copied-state flag, direct production action call,
or change to the production two-second timer.

## Reviewed protocol window and live strip

Run 39041266465 recovered readable feedback pixels and real overlap on three of
four lifecycle cases, but held visual markers produced 0.643–4.152 second stage
uncertainty and the variable-frame video contained long static intervals. That
run remains failed; none of its timing criteria have been retrospectively waived.

The fixture now draws a tiny 192×16 point binary UIKit strip at a requested 30 Hz.
Each actual draw receives a new ID, independent of every production label,
clipboard payload and feedback state. No SwiftUI state/body is refreshed per
frame. Immutable draw/tick brackets and background enqueue/write receipts are
batched in groups of 30; completion binds the exact contiguous ID inventory.
Measured draw/tick brackets must each stay ≤ 5 ms and their summed cost ≤ 10% of
the draw span. These CPU brackets exclude final receipt enqueue, compositor and
indirect scheduling costs. A draw bracket is never a presentation timestamp.

XCTest first verifies the actual Copy control and takes its independent baseline
screenshot, then physically taps the separate fixture Baseline ready button.
Only its actual app receipt starts pre-calibration. The strip runs before this
handshake and for 2 seconds after completed post-calibration, giving live pixels
around the fixed measurement boundaries. It never changes a production timer.

All raw video and PTS are retained and validated for finite values, ordering and
continuous frame inventory. The ≤ 120 ms frame-gap and duration limits apply to the
entire protocol-defined window from the baseline-ready receipt through the
finish receipt after post-calibration, including every possible boundary frame
under the full clock uncertainty. Every tap, replacement/reopen, reset and
settling interval is inside. No interior gap can be removed, and no label outside
this fixed window can establish a lifetime. Launch/teardown pixels cannot supply
an assertion. This is an explicit measurement-boundary change, not a claim that
an earlier run passed.

## Conditional calibration model

A file request/response exchange gives app-minus-host monotonic offset in
[appSend-hostReceive,appReceive-hostSend]. Every exchange is retained. Exactly
8 exchanges at each pre/mid/post stage must independently constrain offset to at
most 20 ms and share an intersection. Stage boundaries are bound to exact actual
protocol commands and their clocks, not inferred from friendly case names. All
29 ordered request/response records are bound to the 24 exact clock exchanges
and five app command events, including strict IDs, response shapes and clocks.
Host and app ordering are checked separately; their raw clocks are never equated.

Exactly 3 independent simctl screenshots per stage retain request/return brackets.
The decoder reads the real live-strip ID in each screenshot, then encloses ALL
matching video intervals in a hull. The screenshot ordinal is never a pixel ID.
Draw IDs/times are provenance and causal cross-checks only; they cannot shrink
the screenshot-derived uncertainty. Independent constraints may intersect, but
alternative matches are enclosed. Each stage must constrain video/host offset
to ≤ 120 ms, with a shared intersection. Long screenshot latency may still fail.

Every used video frame must contain an ordered, actually journaled strip ID.
OCR observations bind exact raw-frame index/PTS/endPTS, and only recognizable
actual production-label pixels count. Independent before/after screenshots must
show the actual control and clock IDs bracketing calibration. No frame rate is
assumed from the requested rate. Missing/ambiguous boundaries, unknown strip
pixels, reordered IDs, excessive gaps or wide/disjoint mapping fail closed.

This still assumes continuous clocks with a stable unit rate during the short
scenario. Screenshot and draw receipts do not prove an arbitrary compositor
latency bound. A positive result is conditional capability only, never admission.

## Input and observation

The first input is a normal XCTest element tap. The second is a previously
located coordinate tap, attempted after a 0.90 s sleep in the XCTest runner following the first call return;
there is no claim that XCTest will schedule it in time. Actual clipboard event
ordinals, payloads, generation and monotonic timestamps must show 0.75–<2 s
spacing. A late/missing input fails independently of pixel calibration. A normal
isHittable + element tap after the window is the third event, never a substitute
for the second overlap event. Same-ID dismissal/reopen is distinct from changed
identity replacement. Every ≥1.5 s lifetime, observation beyond old event +2.25 s,
and expiry <5 s uses worst-case clock bounds and real production-label pixels.
Unknown, cropped, ambiguous or missing labels cannot satisfy an assertion.

Clipboard callbacks enqueue immutable records only. Journal serialization and
atomic writes run on a serial background queue, preserving actual event times,
callback brackets, enqueue/write delay and prior write costs. This reduces but
does not prove zero observer perturbation. The measured costs stay in evidence. Conditional feasibility additionally requires
the retained in-method callback bracket to stay within a fixed 5 ms budget.
This bracket excludes the final journal enqueue and is not a bound on total
notification delivery or indirect scheduling perturbation. The recorded event clock is receipt of
UIPasteboard.changedNotification, not a proven production write or timer-start
timestamp. Delivery delay has not been independently bounded. Numerical expiry
and lifetime findings are relative to that receipt under the stated clock model,
not unconditional claims about the production timer's start or elapsed duration.

A recorder is finalized with SIGINT. Exit status 0 is accepted; -SIGINT is
accepted only when this collector actually sent that signal from its stop call.
The explicit stop request and signal-sent receipt are retained, together with a
readable, successfully decoded video. Any other exit status or forced kill fails collection. Raw process logs,
status, start/end host brackets and unmodified video are retained.

The independently verified source is bd5d9d87af76bfce0553d358bb3c6d45cbbc806a,
tree 4a84f4115cb0d95aa71c0be97d9ce4fdfb553fbc, shell SHA-256
cee763b4190e50f324c666b99e5b117d6468f83de7b8026514968d09aec0e70c.
It is fetched as an exact commit, with origin/tree/cleanliness checked before
and after collection. It does not implicitly include P0 constructor work or P2.

## Independent actual-host build

A separate job builds actual LiveContainer at the exact new source commit for
unsigned generic iPhoneOS Release. It reuses the previous reviewed clone,
command-environment and native_build implementations unchanged, including the
same OpenSSL/litehook repository/commit/tree pins. Full source and child checkouts
are checked before and after, and fresh unsigned product hashes are retained in
an independent artifact. Its receipt cannot assert UI execution or admission.
A video failure does not cancel this job. Neither job runs the full baseline
matrix, a signed build, an IPA, or the real backend.

## Recovery evidence

Both devices run four strict XCTest methods: the five-kind matrix at default
portrait, AX5 portrait, AX5 landscape, then state/size/orientation transitions.
Raw evidence must include 15 primary and 12 named transition observations,
21 actual scrolled-action/callback pairs, 21 after-action geometries, 12
confirmation screenshots, the two actual Apps/Home tab-roundtrip screenshots,
and all associated primary/action/transition images.
Additional scroll attempts are retained. Actual production banner identity,
fixture current kind, inherited text-size receipt, viewport orientation, real
navigation-action frame and actual four tab controls are validated. Callbacks
are synthetic fixture observations, never proof of service recovery effects.

## Bounded original-byte evidence packaging

After collection, including a failed or partial run, a separate always-run step
creates one deterministic stored ZIP64 archive of all regular evidence files and
empty directories. It never imports or executes evidence. The original file
bytes/hashes and collector receipts are preserved; packaging cannot claim UI
success. A strict manifest binds the complete member inventory, whole ZIP size
and SHA256, ordered offsets and per-part hashes. The archive is capped during
writing at 16 × 256 MiB, including ZIP overhead; overflow fails without truncation.

The manifest and EACH ≤ 256 MiB byte part are uploaded separately to this same
Actions repository, so every downloadable artifact is below 512 MiB. No credential
or new external destination is introduced. A consumer must authenticate artifact
digests, reconstruct in ordinal order, verify the exact whole ZIP identity and
all indexed members before interpreting the evidence. The original archive is
never uploaded as one oversized combined artifact. The independent host artifact
remains unchanged. The temporary evidence-only transport workflow is restored to
this diagnostic workflow only in the reviewed successor commit.
