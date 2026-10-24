# Group B: actual customization execute and native preferences

This test-only fixture extracts the complete pinned `UserCustomizationOperation`
class, the actual `UserCustomizationHandler` protocol and complete default
extension, and five exact native `UserDefaults` preference properties. It does not
replace the production operation with a behavioral rewrite. Git blob pins in
`generate.py` match the reviewed `SideStore.base-leaves.json` inventory.

## Deliberate boundaries

- The only operation-body substitution is `UserDefaults.standard -> testDefaults`
  (nine occurrences). `testDefaults` is a unique native Foundation suite, not a
  dictionary approximation. Cleanup removes only that test suite's persistent
  domain and its registration defaults.
- Preference properties are extracted verbatim except removal of `@objc`; the five
  actual `false` registration entries are extracted from the same pinned source.
- CoreData, SideSign, Auth, profile assignment, models, and base-operation plumbing
  have inert boundary doubles. No real signing, profile assignment, database,
  network, device, file parsing, or UI action is performed.
- The default host double implements only the supported App ID and app-group
  requirements. All six unsupported methods execute the extracted protocol
  extension, through actual protocol dispatch.
- The context's computed `targetBundleIdentifier` mirrors the source expression;
  unrelated context behavior is not under test.

## Generate and run in the authorized macOS test-only CI

From the copied `.ci/install-chain-fixture/customization` directory, with `$ROOT`
containing the pinned sibling `SideStore` and `LiveContainer` source checkouts:

```sh
python3 generate.py --root "$ROOT" --output "$OUT/Fixture.swift"
swiftc -parse-as-library "$OUT/Fixture.swift" -o "$OUT/fixture"
"$OUT/fixture" > "$OUT/result.json"
```

The generator also accepts a direct SideStore root. A sparse source snapshot may
pass `--preferences-source` with the exact pinned preferences file. It refuses any
blob mismatch. Generation does not compile or execute Swift.

The runtime emits one `install-chain-runtime-v1` JSON object with group
`customization`, ordered `{name, passed}` case results, aggregate `passed`, and
`native_signing_device_executed: false`. Failed assertions are recorded, remaining
cases continue, diagnostic reasons go to stderr, and any failed case causes exit
status 1. `CASE_NAMES` is the ordered 17-case contract in `generate.py`.

## Coverage

- Absent, registered-false, and persisted-false settings: no handler request and
  nil result through the actual operation.
- Each of the four unsupported feature flags: persisted true remains true after
  native `register(defaults:)` with false, and actual execute reaches the exact
  unsupported default error at its expected progress milestone.
- Supported App ID default choice and cancellation through a test handler.
- Nil target guard and store-update skip, including true flags and a nil target.
- Six direct protocol-default controls: both Info.plist overloads, both entitlement
  overloads, icon, and provisioning profile.

## Negative controls

Generate and compile each negative separately; they are expected to exit nonzero:

```sh
python3 generate.py --root "$ROOT" --output "$OUT/NegativeDropPersistedTrue.swift" --mutation drop-persisted-true
python3 generate.py --root "$ROOT" --output "$OUT/NegativeBypassInfoPlist.swift" --mutation bypass-info-plist
```

The first removes the persisted true value after registration. Six persistence
cases should fail. The second bypasses the real Info.plist `if` branch. Only its
persisted-true actual-operation case should fail; direct defaults remain intact.
Each adjacent `.sources.json` records the exact intended failing case names.
Merely observing a nonzero process is insufficient: CI must parse the JSON,
verify all ordered case names, require exactly the intended failures, and reject
missing output, crashes, compile failures, and unexpected additional failures.

## Source-only preparation checks and limits

`test_generator.py --root "$ROOT"` runs seven Python source-extraction checks,
including exact operation/protocol/property preservation, schema/case ordering,
single-change negative controls, and source-hash rejection. It does not compile
or execute Swift. Native compilation and the seventeen Swift cases remain for
authorized test-only macOS CI; source-check success is not runtime success.

These tests do not establish the cause of the user's reported install failure.
The report is an ordinary imported IPA, active VPN, no deliberate customization,
and no option shown. Absence of an observed prompt neither proves flags were
false nor proves customization caused the failure. The actual cause remains
unknown pending runtime and on-device evidence.
