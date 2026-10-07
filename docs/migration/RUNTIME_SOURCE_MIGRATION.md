# LiveContainer runtime source migration

## Checkpoint

- Owner: NRG-Wardog/LiveContainer
- Upstream: LiveContainer/LiveContainer
- Upstream base: `12377cf3b91d51739a33f14a302e5f522b238593`
- Frozen integration baseline: `141776ba6ba38fc04a5e77f68b0cfc4e6c8842ee`
- Local branch: `migration/runtime-source-141776ba`
- Product-source parity commit: `7d9786afb7ff11f1698dcd900e7372e58f93dc88`
- Local checkpoint only: no remote push, default-branch change, release, tag, active integration workflow change, or dependency-pin change.

## Parity result

54 runtime source files, one runtime configuration plist, and one Xcode build-membership file match the final OLD prepared source **byte-for-byte**, including file modes. The reference is the successful, idempotent 19-stage combined replay from the frozen integration baseline. All 218 other tracked upstream entries, including the original root license and every submodule pointer, remain unchanged.

Three build-only patch-preparation records are archived under `preparation-sidecars/` instead of becoming maintained root product files:

- `.combined-service-startup.json` → `preparation-sidecars/combined-service-startup.json`; SHA-256 `e3e6e34175e37dc976991d67dde97c81b9b81ae2c4804c1802168a8a93ea62b1`
- `.lc-app-layout.json` → `preparation-sidecars/lc-app-layout.json`; SHA-256 `927a01d2ad270264c2623be10b34693757338362ae377cb2a9b23bc9d1c760a4`
- `.v3-command-patch.json` → `preparation-sidecars/v3-command-patch.json`; SHA-256 `0de99fdf9b8635e3c2aa8f8b23d2a2b517aeb6384db3396649a92fbaf37945c9`

These sidecars describe the OLD generator run. They are not runtime inputs or replacement sources. The runtime source, plist and project file have no parity exceptions. The only added material outside that product surface is attribution, migration documentation, archived evidence and fork-native tests.

Per-file OLD/NEW SHA-256 values, modes, producing stages and subsystem commits are in [source-parity.json](source-parity.json). [source-components.json](source-components.json) indexes 22 exact historical template payloads by maintained source file, byte offset, byte length, line range and SHA-256. It is a read-only provenance index, never a build-time generator. [PATCH_TO_SOURCE.md](PATCH_TO_SOURCE.md) provides the human-readable patch map.

## Ordered subsystem commits

1. embedded service lifecycle: `311577423c3bef56b16c75889036cf61ee56ef0e`
2. App Group runtime identity: `1c73e8df77bd1731a89a6ab8f584e70d2f92ab67`
3. XPC and refresh result bridge: `c894d8e88f229945a40aef9f60dd7ea81a39e3cc`
4. refresh scheduling and settings: `3cc5652cd324a47d8090bbd3a75f8a1388aa0c09`
5. guest and process lifecycle: `93b29c03ebca6d1bacb6eafd612338b66e068f20`
6. certificate readiness observation: `e9d09118d075785a333fe1262140d183e46b956f`
7. unified host shell and UI: `523b623542fcb545c5a433d45427f3542c7cd782`
8. diagnostic presenters and bounded bootstrap: `7d9786afb7ff11f1698dcd900e7372e58f93dc88`

The two large pre-existing generated composition units, `SideStoreSupport/SideStore.swift` and `LiveContainerSwiftUI/Views/V3UnifiedShell.swift`, deliberately retain their frozen file topology. Breaking them into separate runtime files would be a refactor outside byte-parity scope. The component index supplies smaller review boundaries without changing production bytes.

Overlapping `LCBootstrap.m` edits were split by responsibility: storage/hooks in service lifecycle, Return controls in guest lifecycle, legacy navigation in unified UI, and the bounded CFBundle adapter in the final bootstrap commit. Native presenter substitutions in the App List, root wrapper and Settings were likewise deferred to the diagnostic commit. Framework-wide Swift service/connection/shared-contract definitions remain together in the XPC/result-bridge commit because the accepted baseline composes them into one target-owned file. Certificate import ownership and readiness presentation remain in the unified Settings/shell source unit; the certificate-observation commit owns the native parser adapters.

## Review and preserved behavior

The migration reviewed upstream deltas and resolved implementation boundaries rather than copying an entire prepared checkout. The explicit import allowlist covers all 59 changed host-owned paths, with the three metadata exclusions above. Unchanged upstream content was independently checked after migration.

- Embedded startup hooks are deferred until SideStore classes exist, installed once, and retain checked shared-container preparation.
- Runtime App Group selection retains bounded identifiers, runtime authority, fail-closed selection, entitlement/openability checks, inherited group forwarding and existing quarantined-store behavior.
- XPC retains launched-peer admission, primitive data envelopes, schema/type/size bounds, run correlation, result allowlisting, readiness deadlines, transaction ownership and cancellation handling.
- Scheduling retains the current retry/deadline/VPN handoff, history and host-verification policies; alarm and background-task configuration are unchanged from OLD.
- Guest Return, launch completion, cleanup ordering, process ownership, foreground reset and dock session behavior are preserved without a lifecycle fix.
- Certificate observation retains the original ZSign parser and public fingerprint/team facts. Import confirmation, request ownership and current-state checks remain untouched.
- The unified shell, authentication/2FA presentation, known-source policies, staging/keychain handoff and cleanup paths are the frozen baseline. Unpublished P1 UI work is not included.
- Temporary diagnostic vocabulary and its 64-event/2,048-byte bounds are preserved, including the baseline enabled state. No logging-policy redesign or new diagnostic data was introduced.

## Fork-native validation

Run from this fork:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
```

Result on the available Linux environment: **39 tests discovered; 37 passed; 2 skipped** after whole-checkout gate hardening.

Executed production-code probes:

- App Group C identity/selection rules from the maintained header, including runtime-vs-packaged selection, malformed identifiers, host/service parity and re-sign shapes.
- Bounded CFBundle scanner with real maintained instruction decoders and guard-page scenarios: missing pattern, first/last instruction boundaries, out-of-window branch, valid patterns and invalid/denied reads.
- Maintained CFBundle platform adapter/caller with OS and Objective-C surface doubles: read refusal, short read, absent pattern, cache mismatch, write refusal and success propagation.
- Maintained atomic Dead10cc transition gate under 8 concurrent threads, 1,000 claims each, across 20 reset rounds.
- Maintained guest Return geometry/visibility helper copies, including non-finite and out-of-range inputs.

Additional checks cover exact hashes/modes, ancestry, unchanged paths, licenses, submodule pointers, shared-source copies, archived metadata, plist/project membership, App Group launch keys, wire/result bounds, non-destructive storage, cleanup order, certificate parser/import contracts and preserved sign-in diagnostic/cleanup source.

The tests consume maintained source directly. They do not import an integration patcher, reconstruct production files, or require the builder templates. The imported C fixture origins are attributed by the separate MIT notice. Structural source assertions are not runtime behavior proof for Swift/UIKit/XPC.

Explicitly skipped:

- Swift refresh-policy compilation/execution: `swiftc` is unavailable.
- Objective-C bootstrap compilation against the actual iPhoneOS SDK: macOS/Xcode/`xcrun` are unavailable.

Not run: full Xcode build/link, SwiftUI render tests, code signing, installed artifact verification, real-device authentication/provisioning/refresh, UIKit/XPC lifecycle behavior and cleanup concurrency acceptance. No build/device readiness is claimed from source parity.

`git diff --check` against upstream reports exactly two trailing-whitespace lines in the frozen `SideStoreSupport/SideStore.swift` (lines 3294 and 3462). These bytes are preserved intentionally for exact OLD/NEW parity. New tests and documentation have no whitespace errors.

## Sign-in evidence and unresolved concerns

This is not a sign-in fix. The reported frozen-baseline sequence still has successful staging/rename followed by `anisetteFetch → nativeOTP → -45061`. The known Swift cleanup race remains unresolved. This migration does not reset or delete `adi.pb`, replace identifiers, change provider selection, reprovision automatically, change normal VM initialization/cleanup lifetime, enable automatic recovery or suppress native failures.

The embedded support and shell contain independently compiled shared policies. Exact component fingerprints make their current parity reviewable; coordinated cross-repository compatibility/version gates still belong to the all-owner integration transition. No new wire version or silently divergent runtime constant was introduced here.

Historical integration patchers remain in place, and the active combined build still uses the frozen old pins. They must not be run over this maintained fork in the eventual transition. The all-owner checkpoint, reviewed exact fork pins, child dependency/lockfile changes, read-only contract checks and Apple-platform validation must precede activation.

## Licensing

The upstream `LICENSE` remains byte-identical AGPL-3.0. Imported builder-authored additions retain the exact MIT copyright/license notice from the frozen integration repository at `LICENSES/sidestore-auto-refresh-MIT.txt`. This separate notice does not replace or relicense upstream work.

## Exact whole-checkout gate

The original 56-file delta check was insufficient to reject added source. The
fork-native gate now anchors product expectations to immutable upstream and
frozen manifest objects and validates all 274 product tree entries, plus an
explicit list of 17 reviewed attribution/test/documentation additions. The
complete allowlist is recorded in `repository-inventory.json`; no directory
prefix or ignore rule grants permission for extra files.

Validation compares the committed tree, stage-0 index and real filesystem. It
rejects missing/extra paths (including ignored files and empty directories),
case/Unicode collisions, mode/type substitutions, symlink and hardlink
replacements, dirty source or metadata, and index hiding flags. Root `.git` is
administrative state; submodule gitlinks remain unchanged, empty directories.
Git is bound to the supplied worktree and its local `.git`, without inherited
`GIT_*` overrides, replacement refs, graft views or global/system configuration.
Shallow repositories are rejected, and implicit lazy object fetching is disabled.
Full object-availability/fsck evidence is a separate checkpoint check.
The parity manifest is read from pinned historical commit
`6f5452fa51a4aea2103fc86d3b855bd110ec6f25`, verified by SHA-256, rather than trusted
from the working tree.

Disposable-copy regressions exercise additions (untracked and committed),
ignored extras, case collisions, file modes, type-only commits, symlink/hardlink
substitution, dirty index/worktree, metadata substitution, environment and
local-worktree redirection, replacement refs and grafts. No production runtime
bytes or dependency identities changed while hardening this gate.

This remains a local source-integrity/accidental-drift gate. Its checked-in test
code and reviewed-additions policy are themselves reviewable source, not an
external attestation or authorization to adopt a fork commit. The coordinated
cutover still requires separate exact fork/pin admission and whole-owner
checkpoint review; selected-file cross-repository contract checks alone do not
establish that admission.
