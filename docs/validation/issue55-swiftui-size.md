# SwiftUI Release size candidate

Only the `LiveContainerSwiftUI` framework target's Release configuration explicitly selects Swift `-Osize`. Previously this target and the project Release configuration did not specify a Swift optimization override; the effective optimization must still be checked with the selected Xcode toolchain. The candidate asks the compiler to favor code size rather than removing supported functionality or data.

Debug remains inherited and unmodified. No architectures, frameworks, resources, runtime entry points, entitlements, export lists or signing material are removed. The existing `LiveProcess` `DEAD_CODE_STRIPPING = NO`, `STRIP_STYLE = debugging`, and shared-library symbol policy remain unchanged. Release dSYM generation is retained. SideStore's optimization configuration is not modified here.

## Evidence and acceptance

The static target-configuration tests verify that the override belongs only to the intended Release target and that diagnostic/dynamic-symbol protections remain. They do not compile Swift, measure savings, or establish guest compatibility.

Before accepting this optimization:

1. Build the coherent candidate with the same Xcode, SDK, architectures and packaging configuration as its comparison build. Confirm the framework Swift compiler invocations use `-Osize`, and retain the dSYM and provenance manifest.
2. Compare the framework's uncompressed binary size, total uncompressed bundle bytes and final IPA size. A comparison against the published release also contains other source changes and is not a causal benchmark of this flag alone. If isolation is needed, compare the exact same source tuple with only this setting toggled.
3. Verify packaged runtime symbols, metadata and signatures with the existing artifact checks.
4. Exercise installation, launch, sign-in, signing/refresh, Sources, extension handling and guest apps. Include observed performance and stability before keeping the setting.

No binary reduction or minimum-size claim is made before that build and validation. If the result is not beneficial or causes a regression, remove this one target override instead of compensating with broad symbol stripping.
