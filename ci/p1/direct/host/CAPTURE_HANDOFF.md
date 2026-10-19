# Local concrete capture prerequisites

`capture_handoff.py` joins the owned native helper's files to the reviewed retained-byte bridge. It has not been compiled or exercised against macOS, ScreenCaptureKit, XCTest, or a simulator here. Local tests replace process execution, not real native evidence. Every receipt remains `admissionEligible: false`.

## Runtime API

1. Snapshot `source_hashes()` before compilation and retain that map. Retain the exact returned original `process_scope.Commands(..., timeout <= 60, receipt=True)` receipt for:

   `xcrun swiftc -swift-version 5 -parse-as-library <local>/capture/direct_capture.swift -o <work>/direct-capture`

2. Call `bind_compilation(source_path, binary_path, compile_receipt_bytes, scope=scope, expected_source_sha256=expected_host_sources['direct-feedback-local/capture/direct_capture.swift'])` before helper launch. It checks the actual settled compiler's registry, process and launch-receipt object, original owned timeout and deadline/start allowance, unchanged expected assembled source, and executable binary bytes. The original returned receipt has no `timeoutSeconds`; the check uses the actual owned LaunchReceipt.timeout (strictly <=60), exact retained deadline/start fields, and the producer's original started+timeout arithmetic. It does not subtract rounded absolute clocks or add an epsilon.

3. Call `target = prepare_capture_target(frame_path)` before helper launch. This exclusively creates the fresh root plus `roi-channel` and `stop-channel`, fsyncs them and retains open descriptor identities and an empty-inventory observation. Swift opens these directories; it does not create them. A failed partial setup remains on disk for diagnostics.

4. Start the original `native_process.RetainedCommand` in the exact same Scope as the original `window_capture.OwnedGUI`, with argv:

   `<binary> <GUI PID> <pinned Simulator executable> <frame_path> <session> <observationDeadlineMach> <cleanupDeadlineMach>`

5. Construct `CaptureHandoff` with keyword arguments `scope`, `gui`, `helper`, `compiled`, `target`, `frame_path`, `geometry_request_bytes`, `runner_directory`, `journal`, `channels`, `budget`, `bridge`, `window_capture`, `remaining`, `retain`, `expected_bridge_sources`, `expected_host_sources`.

   `channels` is the actual original `native_channels.Channels`, with the exact live retained XCTest command, one-shot clean app/runner container lookup receipts, original ready/request bytes and the same Directory objects used by `runner_directory` and `journal.directory`. The journal is created before registration and reused by the unchanged protocol driver. The helper need not have completed launch when the constructor returns.

6. Call exactly once, in order: `register_baseline(timeout)`, `publish_roi(timeout)`, `await_first(timeout)`, `promote_first(timeout)`, `publish_ack(timeout)`. Each returns immutable receipt bytes. Invalid order, expiry, changed bytes, owner loss, or any validation failure latches failure. No recovery/refit/republication path exists.

`retain(name, raw)` must durably save exact arbitrary bytes, including BGRA payloads; these inputs are not all JSON. `remaining(maximum)` must use the existing shared case/scope budget. Keep descriptors open until final collection analysis; then call `close()`. This only closes handoff-owned descriptors, not the caller's runner/app channel descriptors.

## Exposed final-analysis inputs

- `baseline`: provisional `RegistrationResult`, including frozen raster fit/ROIs, proof bytes and exact plan bytes
- `binding`: promoted `StreamBindingResult`, including immutable final identity and validated first-frame accumulator
- `plan`, `timebase`, `geometry_request_bytes`
- `frames`, `roi_channel`, `stop_channel`: actual bound Directory objects
- `expected_geometry`: `(actual contentRect list, actual contentScale, actual scaleFactor)`
- `stream_ready_bytes`, `first_complete_bytes`, `first_packed_bytes`
- `receipts`: retained exact bytes indexed by name; their hashes resolve all ack proof references

Final native inventory is `frames/window-capture.json`, with `samples` holding the complete ordered records and aggregate counters. The final analyzer must inspect every delivered record, restart a fresh GeometryValidator at the exact bound first complete row, and call `registration_bridge.validate_complete_frame` on every complete row. Readiness cannot replace that replay or cleanup proof.

## Checks and limits

The baseline comes from descriptor-read `baseline.json` and full retained `baseline.bgra`, bounded to 2048 by 2048 with strict BGRA stride. Initial census selects exactly one GUI-owned window. The source-bound helper repeats that exact window/frame census after accepting the immutable six-role plan. The host never performs a new independent window lookup or selects a different fit/window when registration fails.

The stream-ready record supplies actual start-return, owner/window/executable, timebase and request binding. The first complete native manifest and its <=1 MiB packed payload pass the shared strict parser. Promotion adds actual SCStream content metadata once without replacing the baseline fit or shrinking ROIs. No content metadata is invented from the registration screenshot or filter. `geometrySHA256` remains the exact AX request hash; separate baseline/final proof hashes bind the actual pixels and geometry.

Live process proof uses original exact types, Scope registry identities and the original LaunchReceipt parser. Once the live helper/XCTest receipt reaches EOF, its idempotent `finish()` and `require()` execute under the same OwnedProcess lock used by original wait polling. This finalizes the actual pre-exec receipt; it does not reap, rediscover, signal, or substitute a PID. Source and binary hashes are rechecked before promotion/ack. Scope ownership, source snapshots and the official compiler invocation are trusted execution prerequisites, not something a JSON-shaped success flag establishes.

The host enforces its stage allowance, a 120-second local setup ceiling and the original shared observation cutoff. It does not equate runner uptime and host monotonic clocks. The runner independently enforces the original `min(observer + 120, method + 240)` limit, so a delayed host ack never extends the native method or authorizes an action after runner expiry.

The ack is published only after validated owned-device/GUI/helper/XCTest evidence, both exact censuses, real decoded nonce boards/features, unchanged full-control ROIs, accepted plan, native stream start and retained first complete pixels. It retains exact ack/proof bytes and resolvable evidence hashes before atomic publication. A final helper report or stage-timeout file, early stop request, stale ack, foreign directory, mutation or owner error prevents publication. A later callback or future failure remains a final-collection failure; readiness does not assert that all future records or ownership observations are valid.

Native source locality/exclusivity, upright affine rendering and native filtering behavior remain explicit prerequisites not proven by synthetic raster tests. Registration and readiness are therefore conditional and never grant timing/product admission. All-record clocks, OCR, coverage, observer costs, final full context, source identity, cleanup and external review remain separate gates.

The live-window binding v2 retains the initial owned census, the exact successful
direct-preset resize receipt, and the fresh resized census. Session, PID, CG ID,
initial frame and final validated frame must join exactly. Registration freezes
that post-resize frame; stream readiness and both final censuses must match it.
The original pre-resize frame remains evidence of the transition and cannot be
mistaken for the captured window geometry. Failed actions, ambiguous windows,
stale resized evidence or a later frame change still fail closed.

## Shared preparation service deadline

Boot, boot readiness and installation now consume the existing single 360-second
preparation deadline, clamped by the earlier parent Scope deadline. They do not
receive separate resetting 30/120/120-second service-completion caps. Each exact
command receipt retains its historical allowance and measured wait exceedance;
a timeout or unsettled/unknown launch remains a failure even if settlement later
reports exit zero. This does not change the later 240-second native method,
280-second observation window, 120ms confidence/coverage or cleanup reserves.

Adjacent bounds were audited together: build already uses this shared deadline;
fresh-device inventory/create, post-install isolation and GUI registration retain
their existing independently bounded ownership checks. Every nested command is
also clamped by bounded_preparation's absolute Scope deadline. GUI registration
observes the owned process launch protocol, rather than waiting for UI completion.
Historical run39313067116 remains failed: install exceeded120 seconds and settled
with exit zero afterward; that result does not retrospectively pass.
