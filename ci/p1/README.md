# P1 native host/UI capture

This branch is a separate capture lane, based on the successful P0 validation
harness commit `5a255a7b52bfa0351d1a5a2a934be90df985d138`. It does not modify
`ci/p0`, P0 receipt bytes, the default branch, tags, releases, or audit admission.
The ordinary build is excluded only for this validation branch.

## Frozen inputs

- P1 LiveContainer: `fbaafb939bfd3b7c08fdc8ff4b8d2aae43526ece`
- Its direct P0 parent: `00546cec351adad1fa1cad5590da4f06e612db8f`
- P1 full tree: `3d3efc14415db6d28ede216965f83fa5924e9e9c`
- Only changed source: `LiveContainerSwiftUI/Views/V3UnifiedShell.swift`
- Exact shell SHA256: `3c40aab6667431d0ecb502d49a38416b9e76250ddf6e66dc1037e60d4594e0be`
- Unchanged renderer/fixtures: audit builder `7e5062114f3ba8c1fe1990389ae9a008ce4d8c1f`
- Inherited P0 reviewed approval SHA256: `34d12b14364d4db4ed24ee80bf206332d383c27e958b497d6f5cd1c9d28cc6dc`

`inputs.json` seals the source delta, child commit/tree/URL pins, adapter hashes,
and exact eight canonical cleanup test IDs. The workflow pins its SHA256.
`test_v3_signin_screen_cleanup.py` is the canonical P1 integration test, with
`V3_P1_REQUIRED=1`. No P2 source, fixture, or localization change is included.

## Fresh evidence

The workflow uses Xcode 26.4.1 on macOS 26 to acquire clean sources, run cleanup8,
compile the actual unsigned iPhoneOS LiveContainer host, and run the unchanged
full rendering harness against that exact P1 source. This requires 14 legacy
render reports plus eight real sign-in XCTest cases across phone/tablet and
24 named, decoded, non-reused PNG screenshot attachments. It independently
rechecks the raw exported XCTest attachments and source identity after capture.

The frozen sign-in fixture extracts the production P1 controls. Its existing
scope remains unsigned-in credentials at a 320-point viewport, default/largest
Dynamic Type, copy-safe diagnostics, submission, and cancellation.

A separate targeted fixture then runs five cases per phone/tablet (ten tests,
26 additional screenshots): feedback timeout, prompt replacement, dismiss/reopen,
and four recovery branches at default/largest Dynamic Type. Copy lifetimes are
measured from passive pasteboard-event timestamps. A pass requires the actual
Copied label at least 1.5 seconds into its own lifetime, expiry within five
seconds, replacement/dismissal during the old two-second task lifetime, and a
new copy 0.75–2 seconds after the old copy. Its minimum-lifetime observation
must occur at least 2.25 seconds after the old event, beyond the old nominal
deadline. Missed observation windows fail closed.
Synthetic credential entry is verified through the production answer callback;
replacement/reopen must submit empty fields. Production declarations are never
instrumented. Lifecycle controls and recovery status/navigation are synthetic.
The complete production recovery inset and four policy declarations are copied
verbatim; all four representative recovery branches must leave navigation
visible, hittable and usable (Open/Back) on each device at default and AX5.
Recovery uses full device width, not the separate 320-point credentials viewport.
This is isolated modifier evidence, not a full V3UnifiedTabs/backend claim.
No real account/ADI operation, physical-device test, signing, refresh, IPA, or
release-readiness claim is made. Dependency validation is explicitly inherited
from unchanged, hash-verified P0 receipts and is not represented as a fresh run.

## Output and review

`provenance/result.json` binds the actual GitHub run/attempt, validation harness
commit/tree, approved input digest, exact tested P1 owner, source/native/UI
results, and inherited P0 approval. The full `evidence-index.json` seals capture
logs, compiler product hashes, before/after source proofs, unchanged inherited
P0 files, raw UI reports, extracted sources, and screenshots. Build products and
xcresult bundles are excluded from the portable evidence; exported raw XCTest
summaries and attachments are preserved. Artifact ID and ZIP digest are added
only by the independent post-run reviewer.

`CAPTURED_FOR_REVIEW` means evidence is available, never admission. Failed or
partial runs retain `FAILED_OR_INCOMPLETE`. The separate integration admission
may be updated only after independent review of actual new artifacts.
