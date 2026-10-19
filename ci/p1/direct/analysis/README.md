# Direct timeout evidence joins

Local offline validation only. No native execution, production admission, or
physical-device presentation claim is supplied by these Python tests.

`timeout_case.inspect` preserves the maintained 29-command protocol, input and
actual clipboard predicates, observer costs, three calibration phases,
receipt-relative lifetime, and combined uncertainty/gap limit of 120 ms.

## Required input provenance

The integrating collector must first obtain `records` from
`packed_frames.inspect` using every delivered native row, all actual packed
bytes, the frozen plan, and the finalized stream identity. It must reconstruct
registration from retained baseline/first-frame evidence and replay
`registration_bridge.validate_complete_frame` for every complete row in order.
The resulting marker proofs and final binding hash are joined here; arbitrary
objects with matching hashes or `primitiveValid=True` do not establish that
those upstream validators ran. Fresh container, source, process/window ownership,
complete journal, and decoder execution receipts remain mandatory upstream.

`ocr_input_bytes` must equal the exact canonical manifest derived from all
verified complete records and their fixed first control regions. The wire
format is parity-tested against `packed_frames.ocr_input`. The OCR result must
name this manifest hash and every actual control/packed hash and ordinal.
Retain the source-bound decoder's input, output, and owned execution receipt;
hash equality alone cannot prove that Vision executed on those pixels.

## Independent screenshots

The new mandatory `screenshot_exports` argument is an exact dictionary:

- `summaryBytes`: retained raw XCTest summary JSON
- `testsBytes`: retained raw XCTest test-tree JSON
- `manifestBytes`: retained raw exported attachment manifest JSON
- `files`: the complete exported attachment leaf-name to byte-string map

This includes the original before/after PNGs and their `before-clock` and
`after-clock` JSON attachments, as well as the original controls, input, and
completion reports. The source-pinned maintained `exports.verify` checks the
one passed timeout method, exact simulator, attachment association, complete
result, original control availability, and original input receipt. The latter
must exactly equal the analyzer's `controls` argument (its historical name;
that argument is the input receipt, not the geometry report).

Each independent decoded row must additionally contain `exportedFileName`,
`pngSHA256`, and full-image `pixelSize`, matched to actual retained PNG bytes.
The copied PNG validator is source-equivalence-tested against the maintained
renderer and validates CRCs and bounded decoded scanlines, including Adam7.
The independent decoder must separately prove its actual control/strip crop
geometry and source-bound execution on these exact PNGs. This module neither
executes OCR nor infers a viewport transform for a screenshot.

Screenshot receipt clocks are compared only with the same XCTest runner's
input clocks: before screenshot finishes before the baseline tap begins, and
after screenshot begins after the first tap finishes. Actual decoded marker IDs
must bracket all captured observations whose entire conservative app interval
falls inside a pre/mid/post calibration phase, with at least one such witness
in each phase. This replaces the old guest-video calibration screenshot
bracketing check with direct timestamped phase pixels. It does not claim a
screenshot presentation timestamp, equate runner and app clocks, or use strip
draw timestamps as presentation evidence.

The local export reader bounds JSON inputs at 8 MiB each, attachment count at
64, each attachment at 32 MiB, and aggregate attachment bytes at 128 MiB.
These are fail-closed parser bounds, not extra retention allowances; all bytes
still count toward the inclusive one-case archive/peak-disk budget.

Tests are synthetic arithmetic/byte/schema fixtures. Their PNG pixels do not
depict the supplied synthetic OCR labels. They prove joins and rejection
behavior only, never native OCR, registration, or timing feasibility.
