# Original evidence required before finalization

This is a deterministic acquisition/replay checklist, not evidence that any new
capture succeeded. Historical failed Phase A attempts, including diagnostic run 39300623354, supply
no successful capture binding or passing consumer/product evidence. Genuine successful bindings
remain pending. The final
builder successor is `defensive-diagnostic-phase-b-v1`; existing full-login approval
remains historical and unchanged.

## Phase A: exact frozen emitter paths

See PHASE_A_REPLAY.md for the executable original-replay schema and corrected
emitter immutable source closure. Obtain the original authenticated exact
run-attempt API body, complete run-artifact listing body, selected complete
artifact object with explicit listing provenance, host commit API body, artifact
ZIP, original upload identity and independent actual-command/source replay review.
Keep initial run-level observations separately. Do not rewrite old originals.

Offline original replay requires `run-api.json`, `artifact-list-api.json`,
`artifact-api.json` (selected/derived from that listing), `commit-api.json`,
`artifact.zip`, and `upload-identity.json`. The independent receipt hash map has
exactly `run_api`, `artifact_api`, `artifact_list_api`, `commit_api`, `archive`,
and `upload_identity`.

For Phase B, seal original observations in `ci/p0defensiveb/reviewed/` as
`original-run-api.json`, `original-artifact-api.json`,
`original-artifact-list-api.json`, `original-commit-api.json`, plus unchanged
`upload-identity.json` and `independent-review.json`. All six are copied unchanged
under `prior-phase-a/`. Fresh runtime `run-api.json`, `artifact-api.json`,
`commit-api.json`, `artifact.zip`, `retrieval-helper.json`, and
`retrieval-receipts.json` separately retain the actual current-run authenticated
retrieval, owned outer command and settlement. Original and fresh APIs must bind
identical capture/source/artifact identities; only JSON serialization and valid
run/artifact `updated_at` metadata may differ. Listing selection and both sets
of raw hashes remain independently replayable. The exact empty ordinary
`prior-phase-a/gh-config/` directory is required; links or content are rejected.

Inside the original Phase A artifact, the current A+B emitter writes:

- `evidence-index.json`
- `provenance/reviewed-inputs.json`
- `provenance/result.json`
- `provenance/owned-command-groups.json`
- `provenance/retention-summary.json`
- `provenance/host-overlay.json`
- `provenance/source-delta-AnisetteKit.json`
- `provenance/source-delta-SideSign.json`
- `provenance/source-before.json`
- `provenance/source-after-resolve.json`
- `provenance/source-after-anisette-build.json`
- `provenance/source-after-sidesign-build.json`
- `provenance/source-terminal.json`
- `provenance/SideSign-lock-before.json`
- `provenance/SideSign.Package.resolved.before`
- `provenance/SideSign.Package.resolved.after`
- `provenance/SideSign.Package.resolved.terminal-observed`
- `provenance/resolved-lock.json`
- `provenance/AnisetteKit-lock-before.json` (must record absent lock)
- `provenance/tool-identities.json`
- `provenance/macos-sdk-raw.json`
- `provenance/host-unicorn-headers.json`
- `provenance/anisette-trace-regression-discovery.json`
- `provenance/anisette-trace-regression-tests.json`
- `provenance/sidesign-core-regression-discovery.json`
- `provenance/sidesign-core-regression-tests.json`

For each owner `AnisetteKit`, `SideSign`, require:

- `provenance/after-resolve/{owner}/workspace-state.json`
- `provenance/after-resolve/{owner}/resolved-graph.json`
- `provenance/after-build/{owner}/workspace-state.json`
- `provenance/after-build/{owner}/resolved-graph.json`
- `provenance/terminal/{owner}/workspace-state.json`
- `provenance/terminal/{owner}/resolved-graph.json`
- `provenance/before-tests/{owner}/generated-inputs-and-products.json`
- `provenance/terminal/{owner}/generated-inputs-and-products.json`

The workspace-state paths are retention-record JSON, not replacement raw
workspace-state bytes. Follow every record's `blob_path` into its original
`blobs/sha256/XX/SHA256` file. Recompute SHA-256, length, Git blob identity where
present, modes, and path sets. Follow raw_tree entries in every source, tool,
SDK, package/artifact and compiler-product report, preserving links literally.
Require every referenced byte in the complete evidence index. Do not accept a
hash-only receipt if its referenced raw bytes are absent.

The pinned original dependency archive retention records are:

- `provenance/archives/4f61907db6aafc56fb3e336b524d742342312f498bb40739f1da55fb4a24614a.json`
- `provenance/archives/37846a8bd302cb2443eff47f1045ab844d0cd40bf82cc6159cfad9aa5c3eff9e.json`

For every actual top-level command ID reconstructed from the approved Phase A
adapter, require all five original files under `logs/`:
`{id}.command.json`, `{id}.log`, `{id}.stderr.log`, `{id}.exit-code.txt`,
`{id}.settlement.json`. Match complete ordered argv, cwd, finite environment,
return code, timeout/signal state and retained process-group settlement. Do not
borrow the old login capture's 67-command/208-nested-command counts.

For every actual host lane under `host-tests/{lane}/`, retain original
`retention-summary.json`, `final-output.json`, every numbered
`NNNN.command.json`, `NNNN.stdout`, `NNNN.stderr`, `NNNN.result.json`,
`NNNN.before.json`, `NNNN.after.json`, and every referenced local blob. The
approved Phase A `host_tests.py` defines exact lane names and fixture counts.
The aggregate result must bind AK6 plus SideSign5, 4,041 host assertions and nine
maintained aggregate tests, all zero-skipped, against final approved source and
adapter bytes. Counts alone are insufficient.

The Phase A artifact's successful result must say
`source-parent-plus-genuine-observed-lock; future-lock-child-not-directly-compiled`.
The SideSign `after` and `terminal-observed` bytes must match. The before lock
must equal manifest-only b28fb0b7's committed original lock. Only the AK pin and
genuine resolver originHash may change; all other package pins remain exact.

## SideSign child and SideStore Phase B input

Supply original Git commit/tree/blob bytes plus authenticated publication
readbacks and independent source-only reviews for:

1. A direct sole-parent SideSign child of
   `b28fb0b72937849d4428e9ae313209b606f859b4`, changing only ordinary mode100644
   `Package.resolved`. Its bytes must be identical to the reviewed Phase A
   observed and terminal lock. The child itself was not directly compiled in
   Phase A; this is explicit source-plus-lock equivalence.
2. A direct sole-parent SideSign integrity-source child of that genuine lock-only
   intermediate. Exactly the independently reviewed ten-path patch is allowed;
   Package.swift and the genuine resolver lock remain byte-identical. The b28-based
   candidate is patch identity only, never a substitute for this true successor.
3. A direct sole-parent SideStore child of
   `d507f9e417f12c262b4d7e717c84d4a244c8e625`, changing only mode160000
   `Dependencies/SideSign` from `c733332b0d64022cd603ab9ac5de054413729aab` to
   that actual final SideSign integrity-source child. Its app lock remains the genuine d507 source
   input. This is the SideStore commit that Phase B will capture.

LiveContainer remains `545438e1f0a89fdef375f73273c5c9fc2735cbce`, tree
`e8014dd771c25c4a05dc76ab0aa304a233642a83`; no reserve UI or producer override.

## Phase B executable raw output contract

These paths are written by the complete capture adapter once genuine bindings
and independent input/overlay review admit execution. No A+B product evidence
has been produced by this local preparation.

Retain `provenance/reviewed-inputs.json`, `provenance/result.json`,
`provenance/host-overlay.json`, `provenance/owned-command-groups.json`,
`provenance/source-before.json`, `provenance/source-after.json`,
`provenance/source-terminal.json`, `provenance/retention-summary.json`, and the
complete `evidence-index.json` plus all raw source/compiler/product blobs.

The reused retry5 product helpers emit:

- `provenance/SideStore.Package.resolved.before`
- `provenance/SideStore.Package.resolved.after`
- `provenance/app-resolved-before-build.json`
- `provenance/app-resolved-after-build.json`
- `provenance/SideStore.workspace-state.before.json` and `.after.json` (raw)
- `provenance/SideStore.OpenSSL.source.zip` (original exact ZIP)
- `provenance/SideStore.OpenSSL.source-before.json` and `source-after.json`
- `provenance/Cargo.metadata.before.json` and `.after.json` (actual output)
- `provenance/cargo-resolved-before.json` and `cargo-resolved-after.json`
- `provenance/cargo-generated-transition.json`
- `provenance/plist_ffi.generated.plist.h` (actual generated raw bytes)
- `provenance/native-tools-before.json` and `native-tools-after.json`
- `provenance/rust-toolchain.json`, `provenance/bindgen-install.json`,
  `provenance/openssl.json`, `provenance/iphoneos-sdk.json`
- `provenance/transport.json`
- `provenance/product-inventory-SideStore.json` and `product-inventory-LiveContainer.json`
- `provenance/product-inspection-snapshot-SideStore.json` and `product-inspection-snapshot-LiveContainer.json`
- `provenance/macho-product-SideStore.json` and `macho-product-LiveContainer.json`
- `provenance/macho-products.json`, `provenance/unsigned-products.json`
- `provenance/product-inventory-SideBackup.json`, `provenance/internal-sidebackup-resource.json`

The integrated gate also writes the exact terminal lock at
`provenance/SideStore.Package.resolved.terminal-observed`, exact38 result at
`provenance/consumer-tests.json`, compiled resource report at
`provenance/compiled-resources.json`, and consumer observer receipts below
`consumer-nested/`. Bind the same five raw command-log suffixes described above,
including resolver, frozen repeat, native transport and both unsigned builds.
Retain all generated compiler-input/product trees before cleanup and terminal,
under one aggregate retention budget shared with nested observers.

Additional exact gate paths:

- `provenance/SideStore.Package.resolved.frozen-observed`
- `provenance/SideSign.Package.resolved.terminal-observed`
- `provenance/terminal/SideSign-lock.json` and `SideStore-lock.json`
- `provenance/source-after-consumers.json` and `source-after-transport.json`
- `provenance/prior-phase-a.json`, `source-object-equivalence.json`, `prior-authenticated-raw.json`
- `provenance/consumer-budget.json`; `consumer-nested/retention-summary.json`
- `consumer-nested/NNNN.command.json`, `.before.json`, `.after.json`, `.stdout`, `.stderr`, `.result.json`
- `provenance/tool-identities-before.json`, `tool-identities-native-before.json`, `tool-identities-terminal.json`
- `provenance/{before,terminal}/{macosx,iphoneos}-sdk-raw.json`
- `provenance/{native-before,terminal}/native-compiler-runtime-inputs.json`
- `provenance/{cargo-before,cargo-after}/cargo-registry-raw.json`
- `provenance/app-resolved-{1,2,3}/app-workspace-state.json` and `app-dependencies-raw.json`
- `provenance/{before,after}-{idevice,sidestore,livecontainer}-build/generated-inputs-and-products.json`
- `provenance/terminal/generated-inputs-and-products.json` and `product-inventories.json`

Every returned raw record resolves under its containing evidence root using
`blobs/sha256/XX/SHA256`. Nested consumer blobs are relative to consumer-nested.
Original Phase A ZIP bytes stay at prior-phase-a/artifact.zip; that bounded file
is indexed directly and counts against the aggregate budget. The successful
app-resolved checkpoints are 1 before both app builds, 2 after, and 3 terminal.

## Final SideStore app-lock-only child, after Phase B

The final release input is a different commit from the captured gitlink-only
SideStore input. Require a direct sole-parent child of the exact captured
SideStore commit, changing only
`AltStore.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved`.
Its raw blob must equal Phase B's genuine observed lock, frozen-repeat lock and
terminal-observed lock. Require unchanged non-AK pins and source graph. Preserve
`compiled_final_commit=false`, `tested_commit`, `final_commit`, exact final tree,
observed-lock digest, source delta, authenticated publication readback and an
independent equivalence review. No fabricated app lock or retroactive claim that
the child was compiled is admissible.


## Integrity-source successor extension

See INTEGRITY_CAPTURE.md for the exact two-edge graph, distinct original publication
receipts and source-only clearances. Every source checkpoint additionally retains
the true resolver-lock-only intermediate tree plus original commit/listing objects
for b28, that intermediate, and the final integrity source child. The separate
provenance/library-integrity.json and its full raw closure are required for the
eight genuine-source synthetic Apple cases; a summary-only status is insufficient.
