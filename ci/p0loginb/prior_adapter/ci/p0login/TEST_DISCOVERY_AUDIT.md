# Finite safe test discovery audit

This is source inspection and command-contract review only. No Swift/native compilation, test discovery, test execution, real provisioning, guest execution or remote run was performed while preparing this adapter.

## Exact inspected source bytes

- AnisetteKit `Tests/AnisetteKitTests/AnisetteKitTests.swift`: SHA256 `3a3b13ad711b4e4bb8e5b552f4ccc4b06bafd5b29455cd05e4d5e6b09feb0561`.
- AnisetteKit `Tests/AnisetteKitTests/LoginDiagnosticTraceTests.swift`: SHA256 `0a04f3657123356af34ad0c51a50291b1d494dd50376478684aa066996790bbf`.
- SideSign `Tests/SideSignTests/SideSignTests.swift`: SHA256 `511c3fe77e5b4e5e8903ada85e8b2ee4b17f08016cf6ac8db90446158bcd0ad6`.

The adapter requires the complete Swift test-file inventory to equal these inspected files before discovery. Additional Swift test sources fail closed. No inspected test type declares a custom setup/teardown, stored-property initialization or suite initializer invoking ADI. AnisetteKit's real `unicornAnisetteProvisioningAndHeaders` test contains online/native provisioning inside its test function; that function must never run in this lane.

The selected SideSign singleton case constructs `DeveloperPortal.shared`, whose initialization creates configuration and URLSession without issuing a request. `AnisetteDataManager.shared` starts with no provider and only local configuration/directory state. Remaining selected SideSign cases use ephemeral device model values, local CSR generation and in-memory archive round trips. Inspected production native globals are constants, null pointers, empty maps and locks; VM setup is inside explicit setup calls. This source audit is not a complete audit of third-party binary static initializers. Ordinary package builds link the declared real Unicorn artifact; no binary stand-in is introduced. The selected source paths do not invoke its guest APIs. Network sandboxing is supplementary and does not establish absence of guest execution by itself.

## Discovery and execution contract

Build with `swift build --build-tests` first. Then run `swift test list --skip-build --disable-sandbox` inside the network-denying sandbox, with the same package/scratch/frozen dependency options. Do not add verbose or filter flags to discovery. Capture stdout and stderr separately. Every nonblank stdout line must exactly equal an expected ID; extra, missing, duplicate or reformatted IDs fail closed.

AnisetteKit uses `--enable-xctest --disable-swift-testing` for both discovery and execution. Expected six IDs all begin `AnisetteKitTests.LoginDiagnosticTraceTests/`, with these method suffixes:

- `testBoundsRetainFinalFailureAndMarkLoss`
- `testErrorMetadataNeverIncludesProviderStrings`
- `testIndependentTaskLocalScopesDoNotBleed`
- `testNativeTimingIsStrictAndAtomic`
- `testTerminalEventIsExactlyOnceAndDurationIsMonotonicBounded`
- `testWrappersPreserveSuccessAndError`

The execution filter is the anchored exact class plus an alternation of these six methods and a final `$`. The gate checks every XCTest start/pass identity and exact six-test zero-failure summary; any Swift Testing run is rejected. Finite trace events containing `outcome=failed` are valid diagnostic test output. Successful runtime stdout and stderr must contain none of `account@example.invalid`, `TOKEN-CANARY`, `PASSWORD-CANARY`, `BLOB-CANARY`, `SECRET`, `ORIGINAL`; compiler failure source excerpts are outside that successful-runtime assertion.

SideSign uses `--disable-xctest --enable-swift-testing` for both steps. Expected five IDs all begin `SideSignTests.SideSignTests/` and end in `()`:

- `archiveDeflateRoundtrip()`
- `archiveStoreRoundtrip()`
- `certificateRequestCSRGeneration()`
- `developerPortalSingleton()`
- `deviceInitializationAndFiltering()`

Its anchored filter ends `\(\)(/|$)` because runtime Swift Testing IDs may append the source location, which human-readable discovery elides. The gate checks the `SideSign Core Tests` suite, exactly five starts/passes, no XCTest events, zero skips/failures and the exact final count. A zero-test filter is a failure, never permission to widen the selection.

## Primary implementation references

- [SwiftPM SwiftTestCommand, swift-6.3 release](https://raw.githubusercontent.com/swiftlang/swift-package-manager/swift-6.3-RELEASE/Sources/Commands/SwiftTestCommand.swift): `test list`, complementary framework flags and build/test behavior.
- [Swift Testing ABI EntryPoint, swift-6.3 release](https://raw.githubusercontent.com/swiftlang/swift-testing/swift-6.3-RELEASE/Sources/Testing/ABI/EntryPoints/EntryPoint.swift): discovery and runner entry points.
- [Swift Testing TestFilter, swift-6.3 release](https://raw.githubusercontent.com/swiftlang/swift-testing/swift-6.3-RELEASE/Sources/Testing/Running/Configuration.TestFilter.swift): regular-expression test identifier filtering.
- [Swift Testing Test.ID, swift-6.2 release](https://raw.githubusercontent.com/swiftlang/swift-testing/swift-6.2-RELEASE/Sources/Testing/Test.ID.swift): source-location-bearing runtime identifiers.

Actual selected Xcode/Swift version, complete discovery output and runtime identities remain mandatory fresh capture evidence. These references do not substitute for that evidence.
