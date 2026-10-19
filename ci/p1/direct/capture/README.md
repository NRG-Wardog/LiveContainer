# Local native capture adapter draft

Not compiled or executed. No published source or workflow is changed.

`roi_capture.swift` validates six fixed, disjoint, outward-rounded regions and
copies their rows losslessly from one locked BGRA buffer into one packed payload.
The order is control, live marker, and four independent registration anchors.
It enforces the same width/height/stride contract as `pixels/roi_bytes.py` and
caps total retained ROI bytes at 512 KiB per complete frame. There is no PNG
conversion, OCR, color normalization or resampling in this path.

`direct_sink.swift` is generated from the exact previously reviewed owned-window
Sink by `build_sink.py`, bound by `source-sha256.txt`. The status chronology,
positive monotonic actual displayTime, owner identity, immutable frame metadata,
queue settlement and error latch remain. The changed callback writes one packed
raw file and its per-region/hash metadata. Total delivered record count is capped
at 6,000 and packed bytes at 3 GiB. The record/per-frame product is 3,145,728,000
bytes (2.9296875 GiB), preserving the former draft's raw maximum. These raw caps
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
