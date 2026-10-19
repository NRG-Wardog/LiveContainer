# Post-settlement direct timeout analysis

`offline_analysis.run(runtime, case.context)` is a concrete local adapter. Call
it only after successful `Case.run()`, before closing the existing Scope and
capture descriptors. It has no CLI and performs no work on import. The adapter
has not been run against Apple tools; its tests use mocked Commands, synthetic
bytes, and the real pure-Python registration/geometry validators.

## Actual runtime inputs

The adapter uses the existing Runtime's `scope`, `ps.Commands`, `remaining`,
`retain`, `video`, `output`, `local`, `session`, `device`, `native_receipt`,
`helper`, `channels`, `transport`, `final_journal`, and `capture_binding`.
The context supplies the exact `argv`, completed `protocol`, and retained
`prepare`/`verify_cleanup` stage Evidence objects.

`capture_binding` is the concrete `CaptureHandoff`: acknowledged and not failed,
with its original baseline and promoted binding objects, immutable receipt map,
actual frame Directory/identity, plan, timebase, request bytes, first-complete
manifest/packed bytes, bridge source map, and original window identity. Its
source/artifact and census methods are reused read-only after settlement.

Required retained inputs include:

- Successful `case-sequence.json`, exact `protocol.json`, native command receipt,
  clean helper receipt, and all-writers-settled/exact-device-deleted evidence
- Every raw app event/strip file and all 29 retained request/response receipts
- Every live handoff input/proof, actual accepted ROI plan, baseline BGRA,
  first-complete bytes, final helper inventory, and all packed frame files
- Actual final full-context BGRA/metadata and both final owner/window censuses
- The owned native command's xcresult bundle

No new deadline is granted. Each export/Swift command uses existing retained
Scope Commands with `receipt=True`, at most the maintained 600-second decode
allowance and the original remaining Scope time. All actual command receipts,
stdout/stderr, and failures remain retained. Offline analysis never extends
the live 240-second method/360-second command capture budget.

## Validation order

1. Recheck successful cleanup and exact native/helper completion receipts.
2. Re-read the original journal, including maintained strip write-order checks,
   and join raw transport bytes to the owned app-directory identity. Derive
   the clock identity from this runtime's device/PID/source/container receipt.
3. Re-freeze the actual retained baseline raster with its original journal
   prefix; require exact baseline proof equality. Re-promote the retained first
   complete frame and require exact final binding equality.
4. Run `packed_frames.inspect` over every native row and actual packed file.
   Require the retained frame-file census to equal all complete records.
   Run a fresh `GeometryValidator` and real packet/component/strip decoding
   for every complete row, starting at the exact bound first sample.
5. Recheck final full-context BGRA bytes/hash/layout and final window censuses.
6. Use maintained `video.export_case`/`exports.verify`, retaining exact raw
   xcresulttool stdout as well as the maintained parsed exports.
7. Execute source-pinned `control_ocr.swift` and source-generated
   `independent_ocr.swift` through the same retained Commands. Retain exact
   source/input/output hashes and execution receipt hashes; recheck source,
   input, and every actual pixel file after execution.
8. Use the maintained independent screenshot mapping: last marker geometry
   rectangle and measured screen scale, original Copy AX rectangle, original
   at-most-one-point marker/AX agreement, and the actual full PNG dimensions.
   The two exact PNGs must match `round(screenPoints * scale)`. This preserves
   the existing guest-screenshot path; it does not infer an SCK guest viewport
   or equate guest screenshot presentation with WindowServer presentation.
9. Enrich independent decoder rows only with verified PNG filenames, hashes,
   and actual full-image dimensions. No host value supplies labels or markers.
10. Rehash retained frame/journal bytes and invoke `timeout_case.inspect` for
    the original protocol/input/feedback predicates and 120 ms gate.

The output remains conditional and always has `admissionEligible=false`.
Exact rational values serialize as numerator/denominator objects, without
float rounding. Failures write `offline-analysis/result.json` with their
stage and error; prior command/geometry/decoder evidence is preserved.

## Bounds and unproved feasibility

All outputs count toward the existing inclusive one-case archive/peak-disk
limits. No extra storage allowance is introduced. The current packed inspector
materializes the bounded raw crop inventory once, potentially approaching
3 GiB at the maximum record/ROI envelope. Crop payloads are released after
geometry replay; OCR manifest generation and final rechecks do not allocate
a second complete crop inventory. Actual native/offline memory, execution time,
retention size, OCR behavior, source-locality/rendering premises, and 120 ms
coverage remain unproved until a permitted measured run. Any budget exhaustion,
unknown pixel result, incomplete census, or missing proof fails closed.
