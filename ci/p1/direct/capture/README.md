# Local native capture adapter draft

Not compiled or executed. No published source or workflow is changed.

`roi_capture.swift` validates six fixed, disjoint, outward-rounded regions and
copies their rows losslessly from one locked BGRA buffer into one packed payload.
The order is control, live marker, and four independent registration anchors.
It enforces the same width/height/stride contract as `pixels/roi_bytes.py` and
caps total retained ROI bytes at 1 MiB per complete frame. There is no PNG
conversion, OCR, color normalization or resampling in this path.

`direct_sink.swift` is generated from the exact previously reviewed owned-window
Sink by `build_sink.py`, bound by `source-sha256.txt`. The status chronology,
positive monotonic actual displayTime, owner identity, immutable frame metadata,
queue settlement and error latch remain. The changed callback writes one packed
raw file and its per-region/hash metadata. Total delivered record count is capped
at 6,000 and packed bytes at 3 GiB. The independent 3 GiB cumulative cap stops retention before the
6,000-record/per-frame product can exceed that raw allowance. These raw caps
are subordinate to a future inclusive single-case, ZIP_STORED archive ceiling
of 4 GiB and separately checked source/archive/parts/temporary peak-disk budget.
They are local prototype limits, not production acceptance criteria. They do
not reserve space for metadata/archive/parts themselves.

At requested 30 Hz the 6,000-record cap is only about 200 seconds, reduced by
noncomplete status records. It cannot promise a full 360-second command-length
capture. Original method/command deadlines and all timing/feedback gates remain
unchanged; cap exhaustion fails without dropping samples or trimming coverage.

`directRegistrationFrame` uses Apple's public single-window screenshot sample
API for a full-context registration image. It explicitly establishes no capture
timestamp. The integrating lifecycle must retain one immutable window filter and
configuration through registration and streaming, independently enforce the
existing-permission/registered-owner/window checks and stage deadlines, and
retain final full context. The baseline frame and the first stream sample must
be bound through actual metadata/pixel evidence before baseline release.

Remaining mandatory integration: retained-byte geometry intervals and source
locality, native startup/ROI-plan wire parser, bounded stream start/stop/drain,
full first-frame proof before host ack, source/session/process bindings,
final-context verification, inclusive artifact budgeting, unchanged callback
cost/cadence/120ms limits, and exact-owned cleanup. A matching geometry hash
alone is not proof of any of these properties.

Official API references checked2026-10-19:
- https://developer.apple.com/documentation/ScreenCaptureKit/SCScreenshotManager/captureSampleBuffer%28contentFilter%3Aconfiguration%3AcompletionHandler%3A%29
- https://developer.apple.com/documentation/corevideo/cvpixelbuffergetbaseaddress%28_%3A%29
- https://developer.apple.com/documentation/screencapturekit/sccontentfilter/contentrect
- https://developer.apple.com/documentation/screencapturekit/sccontentfilter/pointpixelscale

The current local tests check source generation/bounds, not native API behavior
or performance. Native compilation and a bounded reviewed run are still needed.

The local lifecycle now consumes absolute Mach observation/cleanup cutoffs
anchored before the existing 360-second XCTest command. With the full command
budget available, observation ends at280s and helper cleanup at350s, reserving
70s for up to60s of bounded stop/revalidation/final-context/detach/drain stages
and10s for parent reaping. Parent Scope may shorten this further. Every stage
records its effective remaining allowance; delayed startup cannot reset it.
A terminal watchdog is independent of stage cancellation. The original
240-second native test allowance remains separate and unchanged. Timeout or
forced settlement still fails collection. These are uncompiled draft semantics.


## Owned-window source sizing

The actual compiled helper checks existing accessibility trust before fixture preparation and again before sizing. It never requests permission. The previous run proved trust but rejected the size-attribute route before mutation. The prospective correction uses one documented Simulator Window > Pixel Accurate action, only through the exact owned application's bounded accessibility hierarchy. The sole AX window, main/focused target, PID, frame, advertised press action and enabled unique menu item must agree immediately before the action. No global keystroke, raise, retry or unrelated window selection is used. A missing menu or unchanged/unsettled window fails within the existing15-second stage allowance; action errors are retained and never retried.

The same original window ID and AX target must settle before constructing the immutable capture filter. Source window geometry is independently capped at4096 points; native filter dimensions are capped at16384 pixels. Actual output is downscaled only, by min(1,1000/nativeWidth,1600/nativeHeight), with preserved aspect ratio and explicit full-owned-window capture even when it extends beyond the display. This does not capture any other window. Output/decoder dimensions remain below2048, combined six-ROI bytes remain1MiB, cumulative raw3GiB and archive4GiB.

The preset and configured dimensions do not establish source resolution or timing. Actual four-board decoding, feature locality, whole-ROI geometry, identity and every timing predicate must still pass. No output upscaling, decoder relaxation or altered guest controls is permitted. Current Apple documentation describes newer Device Hub controls; this pinned Simulator's menu availability remains a native prerequisite, not an assumption.

References:
- https://developer.apple.com/videos/play/wwdc2020/10647/
- https://developer.apple.com/documentation/screencapturekit/scstreamconfiguration/ignoreglobalclipsinglewindow

The menu-state successor records typed enabled status before opening. It registers exact-submenu open/close notifications, opens only the unique enabled Window menu once, then reacquires and reads Pixel Accurate again. A false or unknown enabled value still stops without invoking the preset. Success requires a matching owned-menu closed notification after the one preset attempt, followed by same-window settlement. The observer is removed on every exit; failure paths perform no capture and rely on existing verified exact-GUI cleanup. No menu enabling setter, global shortcut or permission change is used. The total sizing stage remains15 seconds. Menu notification support and live enabled state remain native prerequisites.

Before menu inspection, the helper normally foregrounds only the already-owned Simulator application if inactive, using its verified NSRunningApplication instance. The request is attempted once, retained, and must yield actual isActive=true with unchanged exact window/PID/frame before proceeding. This ordinary reversible isolated-CI UI operation is inside the same15-second stage and uses existing trust. It neither launches another app nor expands permissions.

## Bounded persistence and timing policy v2

The callback copies the six exact BGRA regions into independently owned Data and
retains the original ScreenCaptureKit displayTime. One serial persistence queue
then computes region/file hashes and atomically writes those same bytes. There
are at most two reserved records, including the callback currently copying and
the writer currently persisting. Each can retain at most the existing 1 MiB ROI
plan. The holder releases its Data before releasing its reservation. Region
hashing can additionally use one temporary subdata slice of at most 1 MiB, so the
explicit copied-pixel working bound is 3 MiB including that scratch, apart from
the unchanged SCK buffer pool and bounded 6,000-record metadata inventory. No
CMSampleBuffer or CVPixelBuffer is queued. Reservation overflow, write failure,
owner failure or any missing record permanently fails collection.

First-complete is published only after the immutable pixels have been written
and their hashes recorded. After stop and output detachment, the existing drain
watchdog covers the callback queue followed by the persistence queue. Final
success requires the drained result and all retained bytes; queueing alone is
never evidence of successful persistence.

The callback bracket now measures synchronous metadata validation and ROI copy,
ending immediately before dispatch submission. It is not a presentation clock.
The historical 5 ms observer-work limit is retained as a diagnostic exceedance
under `display-time-with-diagnostic-observer-cost-v2`, rather than a product
acceptance limit. No fixed overhead is subtracted. Pixel observation intervals
still use the original displayTime converted with the actual Mach timebase and
the measured clock mapping. The unchanged coverage validator requires the full
protocol window, strictly increasing display observations, and at most 120 ms
between observation bounds. Delayed writes do not move a frame's displayTime,
backdate an acknowledgement, fill missing coverage, or establish visual state
between unknown frames. App-side draw-cost and combined observer-work checks are
unchanged. This policy does not make any historical failed run successful.

## Startup persistence diagnostics (diagnostic-only successor)

The first eight delivered screen callbacks have preallocated fixed numeric
milestone storage. Existing admission locking also protects two in-flight
indices and admitted/released counters. The first overflow freezes a value
snapshot while the original pendingRecords guard still holds its lock; the
original unlock/failure-latch order is unchanged. Its observedMach is not the
sink failureObservedMach. Later updates cannot alter this frozen snapshot.
Swift value-array copy-on-write after snapshots can allocate bounded storage
under the lock; this is not an allocation-free implementation. Before the first
snapshot the eight row/timestamp arrays are allocated during sink initialization,
not callback entry. No per-row-of-pixels or per-byte telemetry is performed.

A record contains 24 explicitly named Mach milestones. The normal callback
bracket and original displayTime/PTS remain unchanged in meaning. The callback
trace separates owner lookup, metadata validation, ROI preflight, buffer-lock,
row-copy and unlock stages. Writer marks separate preflight, owner lookup,
region hashes, atomic write, packed hash and finalization/release. enqueueBefore
and enqueueAfter bracket DispatchQueue.async submission; neither is claimed as
exact insertion. writerBegin can precede enqueueAfter, even on a successful
capture. Enum/list order is therefore NOT a total temporal ordering. Zero means
not observed, never zero-duration. Adjacent observed timestamps can be equal.

First-overflow and current snapshot records contain startup stages only, for
indices 0–7. In-flight IDs/counters remain available afterwards, but stage data
for later IDs is intentionally unavailable. Trace retention does not expand
with run length. This is startup diagnosis, not a general continuous profiler.

On an ordinary caught capture failure the authoritative primary-failure.json
is attempted first, unchanged. Then a non-draining snapshot is exclusively
published as startup-persistence.json, using a maximum 32 KiB temporary file and
exclusive atomic rename. No fsync is added. Retention errors are separate and
cannot replace the primary error. A final settled snapshot is embedded only in
the OUTER window-capture result; strict samples/frame/primary schemas are not
changed. Watchdogs stay armed. A watchdog exit before these paths, failure of
primary I/O, or a blocked diagnostic write can still prevent retained telemetry;
there is no guarantee of power-loss durability. No hot-path file I/O is added.

The fixed worst-magnitude current+frozen JSON shape is under 16 KiB in the
portable shape test; the sidecar hard limit is 32 KiB. At most 64 KiB is reserved
within the unchanged 512 MiB ancillary allowance for sidecar plus embedded final
snapshot, with at most 32 KiB additional temporary diagnostic storage. Existing
inclusive inventory/archive limits still enforce the total without relaxation.

traceMarkCount and traceMarkCostMach report bounded update count and elapsed
mark-start through mutation/lock-wait measurements, excluding final unlock and
some call/branch/admission/snapshot costs. They do NOT measure total telemetry
overhead and are never subtracted from any acceptance timestamp. Additional
clock reads/locks can perturb this startup-sensitive run; no native performance
equivalence is claimed. Long stages localize where progress was observed, but
cannot alone distinguish CPU work, filesystem service, framework blocking and
descheduling inside that stage. Native compilation/performance validation and
exact retained evidence remain necessary before any causal fix is claimed.

A missing completion marker proves only that completion was not recorded in the
snapshot. Descheduling or marker-lock wait can separate work completion from
its marker. Error-path pixel-buffer unlock emits no bufferUnlockEnd marker, so
missing unlock completion can also mean exceptional cleanup. Interpret markers
with retained frame errors, not as proof of the executing CPU instruction.
