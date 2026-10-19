# Local pre-baseline observer handoff

Status: isolated local implementation. No published candidate, repository, workflow, or production source was edited. No app was launched. Swift/XCTest has **not** been compiled, type-checked, or run on macOS/iOS in this Linux workspace. Python tests are local schema/state/source-delta checks only.

## Scope and honest source delta

`ui_tests.swift` is a generated test-only candidate based on the sealed `window-capture-candidate/ci/p1/video/ui_tests.swift`. `observer.swift` is its reviewable standalone observer addition. `source-binding.json` records the input, reused primitive, observer, and output hashes.

The original `pixel(_:)` method is **instrumented, not byte-identical**. The complete allowed method delta is:

1. Record runner method-start uptime and require a fresh 32-lowercase-hex `P1_DIRECT_SESSION` before launch.
2. Append `--session`, that session to the original app launch arguments. This enables the separately supplied fixture-only four-packet/four-feature overlay.
3. Insert one fail-closed `guard P1DirectHandoff.beforeBaseline(...) else { return }` immediately before the original `baselineBefore` timestamp and `baselineReady.tap()` statement.

Imports and test-only helper declarations are added outside the method. No original action, assertion, screenshot, post-baseline timestamp, tap, delay, phase wait, or criterion is rewritten. The original three test entrypoints remain byte-identical. Removing exactly those declared additions reconstructs the entire original source byte-for-byte. The suffix beginning at the original baseline tap is also checked byte-for-byte. The observer introduces setup/AX/journal/wait costs and can prevent the method from proceeding; that is an intentional observer effect, not an unchanged execution claim.

The fixture overlay is not implemented in this directory. It must expose exactly one `otherElements` accessibility element for each `p1-direct-anchor-1` through `-4`, with packet ordinals 1 through 4 and the full current session in actual pixels. It must additionally expose unique `p1-direct-feature-1` through `-4` AX-visible isolated magenta views. An accessibility label or frame is not pixel identity proof.

## Narrow transport

The `P1CapabilityError`, uptime/JSON utilities, `P1RequestReader`, and `P1CapabilityFiles` source block is copied **verbatim** from the sealed preflight runner source. Its SHA256 is `c8f21f91675173c959f73c92bbc49a2466d66c133def65779c79501ebee182c2`. Reuse deliberately keeps the existing `Documents/p1-capability/<session>/` directory spelling; this is a direct-feedback session and never accepts the capability protocol's schema.

The runner creates the session directory exclusively. Existing session directories fail; they are never removed or reused. Directory-relative descriptor access, `O_NOFOLLOW`, regular/single-link bounded request checks, immutable exclusive journals, fsync, and atomic publication come from that exact block. `request.json` is the host-to-runner acknowledgement filename because the reader is reused unchanged. The host must use its already reviewed exact-owned runner-container discovery and atomic file publication; this directory does not add an alternate discovery or transport implementation.

File sequence:

1. `geometry.json`: exclusive immutable exact request bytes, followed by file/directory durability.
2. `ready.json`: atomic publication referencing the geometry filename and SHA256. The host must wait for this publication before reading geometry, rather than consuming a partially written immutable file by filename alone.
3. `request.json`: one atomically published canonical host acknowledgement after all native readiness checks pass.
4. `acknowledgement-received.json`: exact acknowledgement bytes retained before schema validation, including malformed acknowledgements when the safe reader delivered bytes.
5. `capture-ready-proof.json`: exact canonical nested proof bytes, after validation.
6. `observer-receipt.json`: durable acknowledgement-validation receipt after unchanged AX geometry is rechecked. It includes exact request/ack/proof hashes and runner-clock brackets. It does not prove that the baseline tap occurred.
7. `observer-error.json`: best-effort durable terminal failure record on any failure. Failure persistence problems are explicitly reported in the XCTest failure attachment. A prior validation receipt does not override a later error.

The valid receipt is persisted and attached before returning to the original tap. The deadline is checked again after both costs. The method guard returns without any subsequent original input if the observer fails or expires. Native per-method/outer watchdogs remain authoritative for a blocked AX, filesystem, or kernel call; a polling deadline cannot interrupt a blocked syscall.

## Geometry and deadline

The observer requires a foreground app, a unique steady Copy Details control, unique live marker and baseline fixture control, and a unique app window. It samples their actual current AX rectangles in XCTest screen points, plus the four distinct packet-anchor rectangles and four whole actual 3×3-point feature rectangles. All rectangles must be finite, positive, bounded, contained in the window; anchor and feature rectangles must not intersect each other or the full control/marker/baseline rectangles. Each feature must have the source-defined outward-corner relation to its same-ordinal packet. Host pixel verification must separately establish orientation, viewport, real anchor packets, no overlap, clipping, registration uncertainty, frozen transform, and retention budget. AX checks alone cannot do that.

After acknowledgement, the observer obtains a second full snapshot and requires exact equality, including all actual rectangles and identities. Geometry can still change after a snapshot; native capture must continue checking the frozen geometry and session across all later frames. No UI sampling is atomic or a guarantee of future stability.

The setup deadline is `min(observerEnteredUptime + 120, methodStartedUptime + 240)`. The setup wait consumes the original 240-second native method allowance; it never adds time outside it. The unchanged native method timeout and 360-second xcodebuild command bound must remain configured by the future collector. The host must additionally cap work by remaining observation/cleanup/outer budget, use only the single allowed discovery/registration pass, and stop without acknowledging if that cannot fit. The first 120 seconds are a maximum, not a promise that enough protocol time remains. This handoff does not define or clear final capture scheduling, pre/post-roll, or resource envelopes.

All handoff times are runner `ProcessInfo.systemUptime`. They are not assumed equivalent to host, mach, app, or presentation clocks. The host must not reinterpret the runner deadline as a host-clock timestamp.

## Exact wire schemas

Every object has exactly the stated keys. Unknown or missing keys are errors. Session is 32 lowercase hex; SHA256 fields are 64 lowercase hex. Simulator UUID is canonical uppercase `8-4-4-4-12` hex and must equal the runner's actual `SIMULATOR_UDID` environment value. The host must separately prove that same UUID is the live exact-owned device. The runner environment value is a binding, not ownership proof.

`geometry.json`, `p1-direct-baseline-geometry-v1`:

- `schema`, `session`, `scenario` (timeout/replacement/dismissal)
- `runnerBundleIdentifier`, `runnerPID`, `simulatorUDID`
- `geometry`
- `sampleBeforeUptime`, `sampleAfterUptime`, `observerEnteredUptime`, `methodStartedUptime`, `deadlineUptime`
- `waitLimitSeconds` = 120, `methodLimitSeconds` = 240
- `clock` = `runner-ProcessInfo.systemUptime`
- `clockEquivalenceAssumed` = false, `admissionEligible` = false

`geometry` has `coordinateSpace` = `XCTest-screen-points`, `orientation` = `portrait-up`, `copyIdentifier`, `copyLabel`, `copyFrame`, `markerIdentifier`, `markerFrame`, `baselineIdentifier`, `baselineFrame`, `windowFrame`, `anchors`, `features`, `registrationModel`, and `sourceLocalityEstablished`. Every rectangle is `[x,y,width,height]`. `anchors` is exactly four ordered objects, each with `identifier`, integer `ordinal`, and `frame`. `features` has the same four-object shape with the feature identifiers. `registrationModel` is `whole-source-view-to-observed-support-v1`; `sourceLocalityEstablished` is exactly false. Exclusive source-owned UIView locality, upright affine transform, and native filtering behavior are external prerequisites, never inferred from AX or nominal centers. These are measurements; the orientation value is the requested runner orientation and must be independently verified by host pixels before release.

`ready.json`, `p1-direct-baseline-ready-v1`: exactly `schema`, `session`, `geometryFile` = `geometry.json`, `geometryRequestSHA256`, `acknowledgementFile` = `request.json`, `admissionEligible` = false.

`request.json`, `p1-direct-baseline-ack-v1`: exactly `schema`, `session`, `geometryRequestSHA256`, `captureReadyProof`, `captureReadyProofSHA256`, `admissionEligible` = false. Hash `geometry.json` exactly as received, never a host JSON re-encoding. The proof hash is SHA256 of its canonical JSON bytes. The acknowledgement is canonical UTF-8 JSON, sorted keys, no whitespace, no slash escaping, no duplicate keys, no nonfinite numbers. Its numeric fields are exact integers; all string values in this schema are ASCII. Maximum 8192 bytes. These restrictions make its canonical representation compatible with the reused Swift serialization; native byte-parity testing is still required before use.

`captureReadyProof`, `p1-direct-owned-capture-ready-v1`:

- `schema`, `session`, `geometryRequestSHA256`
- `captureInstance`: fresh 32-lowercase-hex identity for this stream
- `simulatorUDID`: exact-owned device, equal to the geometry request's device
- `guiPID`, `helperPID`: distinct integers 2 through 2^31−1
- `windowID`: integer 1 through 2^32−1
- `helperSourceSHA256`
- `ownedDeviceReceiptSHA256`, `ownedGUIReceiptSHA256`, `windowBindingReceiptSHA256`
- `fourAnchorProofSHA256`, `streamReadyReceiptSHA256`, `firstCompleteFrameSHA256`
- `firstCompleteFrameIndex`: integer 0 through 2^53−1
- `firstCompleteFrameDisplayTime`: nonzero UInt64 decimal **string**, no leading zeros; this preserves all native ticks without JSON/Double rounding
- `captureStarted`, `firstCompleteFramePresent`, `guiLiveRegistered`, `fourAnchorsDecoded`, `geometryFrozen`: each exact true
- `captureErrors`, `ownershipErrors`: each an empty JSON array
- `admissionEligible`: exact false

## Required host producer meaning

The runner's validation binds the host's attestation to this session, device, immutable geometry request, and exact retained proof bytes. It does **not** prove that the host told the truth. There is no direct-feedback native producer implemented here, and no producer-ownership claim follows from hash-shaped fields, boolean fields, the Python tests, or acceptance of this message.

Before emitting the acknowledgement, the native producer must validate all of these against retained native evidence:

1. The exact-owned fresh simulator UUID and its creation/lifetime receipts.
2. The pinned registered GUI process, its still-live unreaped lifetime, executable identity, and uniquely bound current window ID. The helper must also be registered/owned. Never infer this from PID alone or process/window names.
3. The immutable geometry request's byte hash and the full current session in all four correctly ordered distinct real pixel anchor packets. Decode four bounded exact opaque-magenta components, pair only by declared source-relative adjacency, and use whole measured feature rectangles with whole actual pixel support intervals. Reconstruct the independent transform from ordinals 1–3, retaining ordinal 4 as holdout without crop tuning/refit; reject clipping, overlap, unknown/ambiguous anchors, and incompatible geometry. Retrieve and bind all eight source-tagged retained initial draw receipts and their inventory; a queued-ready flag alone is insufficient. A public registration screenshot is geometry-only and supplies no timing claim.
4. Stream start has completed and an actual **complete stream frame** has been retained with valid full-session four-anchor evidence, frozen geometry, and its true documented displayTime. Registration screenshots do not satisfy `firstCompleteFramePresent`. Do not treat startCapture completion, callback time, a pending stream, or requested cadence as a frame.
5. Every proof hash resolves to immutable native evidence and matches the session/device/owners/window/stream/frame/request identities. `firstCompleteFrameSHA256` must be the retained complete-frame bundle identity, with replayable required pixels and metadata, rather than an unresolvable full-image hash alone.
6. There are no latched ownership/capture errors, and capture remains live and owned through baseline release and later protocol completion. Subsequent errors remain fatal even after this acknowledgement.

Independent replay must resolve and revalidate those evidence hashes. The initial handoff never establishes feedback lifetime, gap coverage, clock correspondence, payload correctness, observer-cost eligibility, cleanup, or admission. In particular an early buffered complete frame is not proof that sampling brackets the baseline event; final coverage must establish that independently without filtering early frames.

## Local verification

From the workspace root:

```sh
python3 p1-stall-isolation/direct-feedback-local/handoff/build_candidate.py
python3 -m unittest discover -s p1-stall-isolation/direct-feedback-local/handoff -v
python3 -O -m unittest discover -s p1-stall-isolation/direct-feedback-local/handoff -v
```

The pure oracle tests malformed/missing/unknown schemas, stale session/request/device/proof bindings, exact native ticks, booleans versus numeric impostors, all readiness/error flags, anchor ambiguity/overlap/clipping, geometry drift, duplicate messages/JSON keys, bounded wait, method-budget truncation, missing ack, failed persistence, post-persistence timeout, and irreversible failure states. Source tests bind the reused primitives and reconstruct the original source by removing only the declared instrumentation. The Python state oracle does not execute Swift, AX, native filesystem transport, actual durability, or host proof production.
