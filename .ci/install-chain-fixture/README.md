# Test-only default imported-IPA contract projections

No production edits. Sources are extracted only from the delivered SS7ff41a checkout and hash-verified before generation. LiveContainer a8be8bab and SideSign483c are task baseline dependencies, not mocked runtime proof. Official upstream d97ec133 audit finds the step definition byte-identical and customization operation behavior equal except log text.

Generate: python3 generate.py --root SOURCE_ROOT --output OUTPUT
SOURCE_ROOT contains SideStore and LiveContainer repositories. Support is read beside this script. No absolute paths/timestamps appear in receipts. Copy only the finite support list in generate.py SUPPORT, not local generated/source-view/pycache directories.

Compile each sources.json variants[].file independently using swiftc -swift-version 5 -parse-as-library FILE -o BINARY. Foundation/CoreFoundation are SDK modules; cache also imports CryptoKit. Use modern macOS Swift compiler (Swift 5.7+). Do not combine sources: each has its own @main and support types.

Runtime emits one JSON object: schema=install-chain-runtime-v1, group, ordered cases[{name,passed}], passed, native_signing_device_executed=false. Baselines require exit0 and all true. Each negative requires exit1 and ONLY its receipt's expected_failed_names false. Compilation failures, crashes, missing/malformed JSON and unexpected extra failures are not passing negative controls. Preserve each independent compile/runtime outcome.

Three groups only:
1. chain: actual resolveInstallTarget/canonicalToken/AnyApp/AppOperation, exact context classes, exact PipelineStepDefinition, entire performPipeline and executePipeline, and exact 20 install switch arms. All concrete operation bodies are inert recording boundaries, including archive parsing/download, verification, Apple/certificate/profile/signing, transfer/native install and post-install persistence. Eleven noninstall executor arms and its logging/diagnostic observer/catch are excluded; listed in chain receipt. Inert failures verify loop termination and post-install failure propagation, not actual device behavior.
2. customization: actual full UserCustomizationOperation and six protocol defaults, actual preference getters and registration values, isolated native Foundation defaults; Auth/DB/models inert. Current default flags versus persisted-true controls do not establish what the user's device stored.
3. cache: actual cachePayload and full actual fingerprint with Foundation/CryptoKit synthetic .app files, new/repeated/changed content, symlink guards and conflict/obstruction preservation. Does not parse an IPA or invoke native signing/device.

The user's install cause remains unknown. Passing the projections means the tested wiring, default decisions, and synthetic cache contracts held. It does not establish the user's IPA validity, native library/portal/device acceptance, or that installation is fixed. This lane must not package or deliver an IPA.
