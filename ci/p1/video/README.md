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

## Conditional calibration model

A bounded file request/response exchange gives app-minus-host monotonic offset
in [appSend-hostReceive, appReceive-hostSend]. Every exchange is retained. Three
pre/mid/post calibration sets must independently constrain offset to at most
20 ms and share an intersection. The middle set occurs after the overlap window,
before the separate ordinary third tap. There are no marker changes during taps.

Each independent simctl screenshot retains host request/return times and an
actual fixture-only binary marker. Match every plausible occurrence of that ID
in the video, enclosing the entire presentation interval. Alternatives are
unioned/enclosed; only independent screenshot constraints are intersected.
Video-minus-host calibration uncertainty must be at most 120 ms in each set,
with a shared pre/mid/post intersection. No nominal frame rate is used. Duplicate
or reordered PTS, presentation gaps above 120 ms, absent calibration, ambiguous
geometry, or wide/disjoint bounds fail conditional feasibility.

These constraints assume continuous clocks with a stable unit rate during the
short scenario and a continuous video timeline. Calibration does not prove
arbitrary nonlinear clock behavior or a compositor latency bound. Screenshots
and raw video are retained for independent visual assessment. Therefore even a
positive numerical result is conditional feasibility, never admission.

## Input and observation

The first input is a normal XCTest element tap. The second is a previously
located coordinate tap, attempted after a 1.10 s sleep in the XCTest runner following the first call return;
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
confirmation screenshots, and all associated primary/action/transition images.
Additional scroll attempts are retained. Actual production banner identity,
fixture current kind, inherited text-size receipt, viewport orientation, real
navigation-action frame and actual four tab controls are validated. Callbacks
are synthetic fixture observations, never proof of service recovery effects.
