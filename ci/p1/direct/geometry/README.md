# Direct-feedback geometry and retention primitives

Local, pure-Python validation only. This directory does not modify the published
candidate, acquire pixels, perform OCR, execute XCTest, or establish native,
feedback, timing, input-overlap, or P1 acceptance. Every report explicitly keeps
`admissionEligible: false`.

Run the synthetic tests:

```sh
python3 -B -m unittest discover -s . -p 'test_*.py' -v
```

## Geometry API

- `Interval`, `Box`, and `PixelRect` represent measured bounds. Coordinates accept
  exact integers or `fractions.Fraction`, never binary floats or booleans.
- `Identity` contains the session, owner/window IDs, full-frame geometry,
  independently measured app-space viewport and immutable content metadata. This first
  primitive supports an upright portrait, positive axis-aligned transform only.
  It does not require or invent exact guest pixel-viewport edges. AX app-window
  bounds and SCK contentRect are not treated as equivalent coordinate systems.
  Actual BGRA width/height provide the independent pixel containment boundary;
  contentRect/contentScale/scaleFactor remain unchanged identity checks.
- `Anchor` contains a unique ID, decoded session, app/pixel coordinate intervals,
  complete measured pixel footprint and retained anchor-region name. `Region`
  retains each measured app-space rectangle. One complete control region, one
  live-marker region and distinct fiducial regions are required. Fiducials cannot
  intersect the control or live strip, or overlap one another.
- `freeze(...)` requires a hash-verified full-context baseline image, at least
  three noncollinear fit anchors, and at least one separately declared validation
  anchor. It computes exact feasible **joint** scale/translation regions by
  half-plane intersection. It checks independent validation anchors against
  those constraints, without using them to shrink the fit-derived crop bounds.
  The entire app viewport is conservatively projected from fit anchors alone;
  its complete uncertainty envelope must lie inside the actual BGRA frame.
  This projection is explicitly **derived containment**, not an independent
  measurement of guest-screen edges. Every crop is rounded outward with a fixed pixel
  margin. Clipped crops fail rather than being clamped.
- `GeometryValidator.validate(...)` verifies the immutable cropped BGRA bytes,
  hashes, exact frozen ROI rectangles, all retained anchor footprints, app
  registration coordinates and owner/window/session/viewport identity. It keeps
  one feasible transform across successive frames, without moving the crops.
  Any failure latches the validator closed. Complete-frame indices may have gaps
  because non-complete delivered statuses belong to a separate complete timeline
  validator; these gaps are not proof of timeline completeness here.

Geometry reports use `p1-direct-geometry-primitive-v2` and include
`viewportProof: fit-derived-containment-in-BGRA-frame` with exact rational
`derivedViewportBounds`. A validation anchor cannot rescue an unsafe projected
viewport by narrowing or refitting it. Independent anchor and source-coordinate
orientation identification remains required upstream.

`Crop` holds tightly packed BGRA bytes. This module does not extract source rows;
a separate checked extractor must copy all ROIs from the same immutable sample,
honoring the original source row stride. Its native source-frame/timestamp
association must be retained outside this primitive. The `bundleSHA256` is a
Python-local consistency digest of the validated record, not an authenticity
signature or a portable cross-language wire-format commitment.

## Labels and expected dismissal

`observation_role(...)` only classifies a separately verified pixel observation.
`expected-absent` requires the dismissal scenario and an explicit upstream
verification result. It supplies neither a reset nor Copied witness and is
forbidden inside a claimed maintained-Copied chain. Blank, unknown or ambiguous
pixels do not become expected absence automatically. Actual transition receipts,
same-identity ordering, reopening reset and timing must be validated elsewhere.

## Inclusive one-case retention

- `RetentionPlan.bounds()` includes all planned raw ROI bytes, metadata for every
  delivered record, full-context images, journals, ancillary files and archive
  overhead. The case and archive ceiling cannot exceed the existing 16 ×256 MiB
  transport limit. Multiple cases in one package are deliberately rejected.
- Peak disk reserves retained evidence **plus** the archive **plus** its byte
  parts **plus** explicitly bounded temporary output. No compression is assumed.
  Derived PNGs/OCR output, source snapshots, logs, manifests and any other output
  must be included in the declared categories; unaccounted output is not allowed.
- `check_geometry_plan(...)` checks the actual measured crop byte sum against the
  planned per-record allowance before a collector starts.
- `RetentionLedger` charges actual immutable byte payloads and latches any record,
  per-record or fixed-category overflow. `verify_archive_size(...)` checks stored
  archive size/overhead against charged evidence; it is not an independent ZIP
  member inventory, package digest, disk-usage or quiescence verifier.

The archive API deliberately targets the existing ZIP_STORED producer:
`../../window-capture-candidate/ci/p1/video/package_evidence.py`, lines 137–144
set `ZipInfo.compress_type = zipfile.ZIP_STORED`, and lines 168–174 construct
`ZipFile(..., compression=zipfile.ZIP_STORED, ...)`. Its uncompressed evidence
lower bound is therefore intentional. This API must not be reused for a
compressed archive without an explicit reviewed contract change. No producer or
packaging behavior has been changed by this primitive.

The bounded successor caps all delivered records at6,000 and the six combined
raw ROI payloads per complete record at1MiB. The independent3GiB cumulative
raw ceiling is checked before admitting each record; maximum raw storage is
min(6000×1MiB,3GiB), never the unenforced6,291,456,000-byte product. At exactly
1MiB per complete frame the raw ceiling permits3072complete frames; an additional
nonempty frame fails without sample dropping. Metadata still budgets all6000rows.
Full contexts, journals, ancillary output and ZIP_STORED overhead must fit the
unchanged inclusive4GiB single-case archive; peak disk includes evidence, archive,
parts and temporary storage. This supersedes512KiB per record without changing
measurement, ownership, timing or acceptance criteria.

At requested 30 Hz, 6,000 records would cover only about 200 seconds before
counting noncomplete status records. This is not a native rate/duration promise,
a guarantee of the entire 360-second outer command allowance, or an approved
run. Reaching a cap fails without discarding samples or shortening the original
protocol. Scheduling, pre/post-roll,
actual cadence, uncertainty ≤120 ms, all statuses/gaps, cleanup and package
reconstruction remain separate mandatory checks.

## Explicit trust boundary and remaining prerequisites

The supplied anchor coordinates, session decoding, production-control rectangle,
app viewport, labels and expected-absence verification must come from reviewed
independent measurements on retained bytes. This primitive cannot establish
their truth from caller declarations. Tests use synthetic zero-filled buffers
and synthetic geometry only; they are not pixel-registration evidence.

The same-frame crop extractor, fiducial decoder, app-space/orientation
proof, current full-control extent/clipping checks, full-context final-image
binding, native owner provenance, timestamp/clock model, transition/action
receipts, source seals and overall admission decision are not implemented here.
Submeasurement-uncertainty motion cannot be ruled out. No native integration or
execution is cleared by these unit tests.

## Provisional raster identity and one-shot stream binding

`RasterIdentity` contains only session, owned PID/window binding, actual raster dimensions, AX app viewport and orientation. It deliberately has no SCStream `contentRect`, `contentScale` or `scaleFactor`: screenshot registration cannot invent those fields or substitute content-filter metadata. `freeze_raster` shares the exact fit/holdout/crop math with `freeze` but returns distinct `FrozenRasterGeometry`. `GeometryValidator` rejects the provisional type.

`GeometryPromotion` accepts exactly one actual stream `Identity` plus same-frame independently re-decoded anchors and retained crops. It requires unchanged raster identity, copies fit/holdout/viewport/ROIs without recalculation, validates the first complete frame, and returns final immutable `FrozenGeometry`. The validated accumulator remains available through `.validator` for continuation. Success or failure consumes promotion; normal assignment cannot mutate the frozen result or reset its read-only state. Final replay must start again at the same bound first complete frame, or continuation must use the retained accumulator. The byte-decoding/join implementation and actual synthetic raster tests live in `../pixels/registration_bridge.py`; no native execution is implied.
