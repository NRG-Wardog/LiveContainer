# Actual remote production graph validation

This is a local review candidate for the dedicated
`NRG-Wardog/LiveContainer` branch
`validation/production-dependencies-141776ba`. Its parent is published validation
commit `5c41d2eb82051b23b387d42e1563dfc920dba4d4`. The current native validation
workflow, seven-owner map and assembler remain unchanged.

## Two separately reviewed phases

1. **SideSign:** publish and independently verify the provisional source commit,
   populate `inputs-sidesign.json`, and pin the independently approved file digest
   in the workflow. Fetch exact full-history owner commits. Run the committed
   strict proof while pristine, resolve the untouched remote package graph, and
   capture genuine lock metadata. Require identical complete pin objects, freeze
   resolution, build tests, and run the existing five selected offline Swift
   tests. Capture source bytes, dependency origins, revisions, trees, compiled
   source lists and binary archive proof. This phase reports iOS compilation as
   `NOT_RUN_PHASE_1`; its macOS tests do not establish an iOS/combined build pass.
2. **SideStore:** after importing and reviewing genuine SideSign resolver metadata
   as a new owner commit, publish the final SideSign commit. Finalize both actual
   SideStore child gitlinks and publish its new source commit. Populate and
   independently approve `inputs-sidestore.json`, then separately review the
   workflow phase and timeout change. Build pinned idevice/jktcp and stage the
   existing declared local framework before Xcode resolution. Run the SideStore
   suite, unchanged compatibility contract gate, real remote graph resolution,
   and unsigned SideStore/LiveContainer builds. Compare exact lock objects,
   source inputs, framework bytes, symbols, compiler lists and submodules again.

Phase 1 selects published SideSign commit
`0d451a6eca73358be8dfed6a89c4e227752d0083`, tree
`702559ec7158d567de4b0cb383dc9d9f4bc20bf7`, and the unchanged Anisette revision.
Phase 2 selects receipt-bound SideSign
`5ce52d12f1846e1a08fad30ed27c4cbadd176529` and SideStore
`f6e9e0ed6c3f4d02e99a0dcff0660faa0e5372b8`, whose actual child gitlinks select that
SideSign commit and the frozen minimuxer commit. Its independently reviewed input
digest is required in the workflow before acquisition or native work. SideSign's
successful Phase 1 receipt preserves the genuine absent originHash; SideStore's
lock is still provisional. Phase 2 native acceptance remains pending. No branch-name fallback,
manual dispatch fallback, package mirror configuration, source rewrite or local
Anisette dependency overlay exists.

## Invocation and evidence

The workflow invokes:

```sh
bash ci/production/run-production.sh sidesign NEW_WORK_DIRECTORY EVIDENCE_DIRECTORY
```

`APPROVED_PRODUCTION_INPUTS_SHA256` must be an independently reviewed literal;
calculating it from the candidate at runtime cannot approve the candidate.

Resolver-produced locks are retained before, after and at exit. Only the root
lock may change; all other tracked bytes/modes remain anchored to fetched Git
objects. Exact unrelated pins are preserved. An absent originHash is explicitly
unresolved; the runner never creates one. Unexpected `.swiftpm` or ignored files
are recorded and rejected until observed metadata is narrowly reviewed.

Git proof commands bind the canonical work tree and Git directory explicitly,
disable replacement/graft/lazy-fetch behavior, and cannot be redirected by local
core.worktree. Effective SwiftPM checkouts may use the reviewed one-hop local
bare repository mechanism: `checkouts/<package>` to `repositories/<mirror>` to
its exact HTTPS upstream. Mirror history, checkout commit/tree, and any shared
object alternate are checked. Nested local mirrors are rejected. This policy
and its real Git regressions match reviewed integration commit
`b783a64bbb340d24eb221078f2db1baebf62d565`.

The unchanged contracts directory is copied from the frozen integration review.
Its validator SHA-256 is
`0d5a5aa61dd37f566359312611826ae5dbbae00176c50b1e4c5e2143530bf520` and registry
SHA-256 is `8e7eba95b8bc69037ffed8931478cefd46984b458f767c2a067547e3cd60b467`.

Dependency acquisition and build preparation can use the network. Test execution
uses the existing deny-network wrapper. The same temporary-localhost canary must
prove an unsandboxed connection works and the sandboxed child receives explicit
permission denial before tests run. Filtered, already-built Swift tests disable
only SwiftPM's inner sandbox. LLVM archive reading uses the producer's verified
Rust component. Native toolchain and build flags match the current validation.
No account, Apple provisioning, device/VPN, signing credentials, release, tag or
deployment action is added. Uploaded artifacts contain logs, commands, status,
locks and provenance, not app binaries.

## Cost and limits

Estimated cost, not measured: Phase 1 uses 15–35 macOS minutes (60-minute job
cap); Phase 2 uses 60–120 minutes (proposed 150-minute cap in its later review).
Cold downloads/builds can vary. This candidate has only local Python/Git fixture,
YAML and shell checks. Real SwiftPM/Xcode schemas, native compile success, current
sandbox execution and Phase 2 native behavior remain unobserved here.
The Phase 1 published SideSign source/transition proofs passed in an exact remote
checkout; its lock still has no originHash and native resolution remains not run.
Every run reports `production_ready: false`; reviewed metadata import and exact
remote graph rechecking are still required.


## Observed SDK-generated Swift sources

The phase 2 compiler gate accepts only nine reproduced generated Swift files:
SideStore and AltWidgetExtension asset symbols, their exact observed ViewApp and
legacy intent outputs, and LiveContainerSwiftUI's two ViewApp intent outputs.
The explicit generator table is grounded in the saved Xcode 26.4.1/17E202 build
commands and committed intent/catalog inputs. The historical command fixture
records source-log hashes and line numbers, including the unselected SideBackup
command as a boundary case.

Each actual actool or intentbuilderc command must match its target, configuration,
input set and output paths. Input blobs and modes are checked. The same official
SDK tool is invoked into a new proof directory with every output redirected;
regenerated Swift bytes must equal the original compiler input. The exact arm64
SwiftFileList, generator commands, input hashes, generated bytes and tool hashes
are retained as provenance. This is a future Mac CI check; local regression tests
use a synthetic generator executor. No other DerivedSources, asset-generator
Swift for LiveContainer, or resource_bundle_accessor is permitted.
