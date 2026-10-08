# Actual remote production graph validation

## Staging-order diagnostic v2

`PRODUCTION_SOURCE_BASIS=diagnostic-v2` selects `inputs-adi-v2-<phase>.json`
and the separately reviewed `diagnostic-v2/` source metadata. The explicit
version table preserves the parity and original diagnostic v1 paths. Unknown
versions, missing source tuples and missing approved basis digests are rejected.
The same validation branch is reused, with phase one published before phase two.

The v2 immutable registry is
`2333ff8e03dea9fa4b8620e64e15ec76cb6a870a2d61c42dd057ddce0c13354f`,
and its delta is
`65a3689c1609cfbcfaa317e33401d500c5bde88a80cf054b240124f93b025165`.
The source basis is `maintained-adi-consumption-v2`, descended from accepted
integration `f9f23d980df363eb0f6eb5093b48e3639b03e137`. Real resolution permits
only the exact Anisette revision transition from `e530b84687ebea2e7d1115119e1a6d18372de14b`
to `f494494ede88890555df345054f7fbb87b53aea5`, preserving every other pin object.
Actual resolver locks and originHash are captured, never synthesized.

The focused native receipt from run 37773853730 is preserved verbatim, SHA-256
`42357eab1cf9b97d597d533e51fa4a88f93e7b30a79e4d5c279553131230a4da`.
It binds seven producer tests plus six coupled consumer tests with zero skips
to the exact three v2 source checkpoints. These tests are not repeated here.
The current 42 SideStore tests and four named historical assertions retain the
same division. The historical fixture stays at original parity `dd4f0ca3`,
explicitly independent of the latest accepted diagnostic SideStore `1ebc6939`.

The v2 app compiler proof adds exact SideStore target requirements for
`AltStore/Core/Components/Keychain.swift` and
`SideStore/Core/Anisette/OnDeviceAnisetteManager.swift` to the existing four Swift
files. All six require their actual Release iPhoneOS arm64 SwiftFileList,
committed blob/hash, and real target compilation command. Historical log replay
validates parser compatibility only; fresh phase-two compilation remains required.

Phase-two final SideSign and SideStore tuples, basis digests and the real
SideSign resolver receipt remain null until observed, published and reviewed.
The phase-one published SideSign input is
`6be9afd7e07762f77b74eda9c7710d029799f2e6`, tree
`47ff728db2ca6a7e35e105eb8949dc2729539d0a`; its previous genuine lock remains
unchanged pending the new native resolution. The independently approved input
digest is `2ffaa1aded824b33e56bf1f8e90d0e73019f8fa0874ec9927ee1dee7a49b3692`.

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

## Explicit diagnostic graph

`PRODUCTION_SOURCE_BASIS=diagnostic` selects `inputs-adi-<phase>.json`.
The phase-two inputs select real resolved SideSign
`3bd4afa0addbf95a8666ac91d8bfcf99f5182eea` and pending-lock SideStore
`3f0f1e40ac37e1b02f8c375743a46b3ce9ff3a8d`, with exact trees and independently
reviewed dependency metadata. The separately approved workflow input digest is
`39577aacdbea7705053a835cc018d86f21ba8ce4ff96c5ff7160334211872fa4`;
no workflow can infer its own approval. Both
`dependency_bases`, the SideSign entry in `resolver_receipts`, and
`sidesign_lock_metadata_reviewed` are required. Each descriptor binds
the exact `diagnostic/dependencies/<Owner>-basis.json` or `-resolver.json` bytes.
SideStore's resolver receipt is null for its first genuine Xcode resolution;
a committed changed app lock instead requires its separate genuine receipt.
The workflow phase and input digest require their own review before publishing.
The original diagnostic phase-one inputs and source basis remain archived at
host commit `e63ba26ef6984c558bf29fc9e233e4b8d529cb5a`; this host candidate selects
the completed SideSign dependency basis for phase two.

The diagnostic registry, seven owner manifests and source evidence are copied
unchanged from the source-only contract review. They remain separate from the
historical parity contracts. Every nondependency owner is bound to its exact
diagnostic tuple; SideStore's dependency basis must bind the exact final SideSign
commit, tree and source-basis digest. Both owner dependency verifiers run before
native compilation, and all source, resolver, toolchain, network, binary,
generated-source and actual compiler-input gates remain active.
Diagnostic compiler proof additionally requires the exact four changed Swift
files in their actual Release iPhoneOS arm64 target lists: SideStore AppDelegate,
AnisetteDataProvider, LiveContainer V3UnifiedShell and SideStoreSupport's decoder.
Each source retains its proven committed blob/hash, and its exact list must be
consumed by an actual logged iPhoneOS Swift compilation for the matching target.

The already-verified focused native run 37734029130 is retained verbatim in
`diagnostic/focused-native-verification.json`, SHA-256
`2a1793ebea48380229591240bad2122c72dad2ef8711d8000a1b92ec7a2f37b8`.
It covers the exact AnisetteKit observer, SideStore observer checkpoint and
LiveContainer decoder: seven producer tests and five coupled consumer tests,
zero failures or skips. Dependency source gates prove those runtime/test bytes
remain unchanged in later dependency-only descendants. The host records this
receipt in provenance and does not rerun the identical focused tests. This
receipt alone does not establish app compilation, resolver or device success.

The original SideStore suite contains four parity-specific assertions. The
diagnostic lane runs exactly those four unchanged assertions on a detached
worktree at accepted SideStore `dd4f0ca36e8ef1d858548f583c65842a8fc0ced3`, with
strict before/after Git/source proof and `historical_baseline_only` scope. The
remaining 42 tests run unchanged against the actual diagnostic candidate,
including all three Swift runtime tests. The two selections are disjoint and
cover all original 46 tests once; any inventory drift, failure or skip fails.
The historical four never count as diagnostic candidate coverage.

The replaced candidate assertions and their required current-source evidence are:

- Whole owner hashes/modes/inventory: exact diagnostic owner dependency basis and
  before/after source proof.
- Ancestry/gitlinks/clean inventory: diagnostic owner proof and actual committed
  source/child identities.
- Old AppDelegate segment hashes: immutable diagnostic registry/source delta,
  current contract proof and the already-verified focused native receipt.
- Old Anisette lock pin: diagnostic lock proof and real Xcode resolution retaining
  all nine unrelated pins. The original valid-Info.plist assertion still runs
  against the current candidate.

`sidestore-native-tests.json` records only the current 42-test result and actual
tested commit/tree. `sidestore-historical-native-tests.json` records the four
historical assertions and their separate tested tuple. Native readiness remains
an external review of genuine two-app artifacts, never a claim by either suite.


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
