# P1 recovery navigation fixture

`recovery_source.generate_recovery_source(source_text)` returns one complete
Swift source file for the P1 behavior app target. It requires exact P1 shell
SHA256 `3c40aab6667431d0ecb502d49a38416b9e76250ddf6e66dc1037e60d4594e0be`
(commit `fbaafb939bfd3b7c08fdc8ff4b8d2aae43526ece`). The caller should retain
`recovery_fragments(source_text)` hashes with its generated-source identity.

## Boundaries

- The top recovery safe-area-inset modifier is extracted verbatim in full from
  `V3UnifiedTabs`. No accessibility IDs, geometry probes, or altered sizing are
  added inside it.
- `V3HostDirectRecoveryRecord`, `V3DirectRecoveryPostcondition`,
  `V3DirectRecoveryHostPolicy`, and `V3DirectRecoveryPresentationPolicy` are exact
  production declaration extracts. The target already supplies its extracted
  `V3DiagnosticBuild` declaration; do not add another one.
- `P1RecoveryStatus`, `P1RecoveryOperation`, navigation root/destination and
  fixture IDs are synthetic. Callback bodies are no-ops. This is not the full
  production `TabView`, status store, recovery lifecycle or backend.
- The tested states are dispatched install, prepared certificate creation with
  manual-check-required postcondition, lost refresh, and clear-eligible
  malformed recovery record. All four are tested at default and largest
  Dynamic Type. Other policy/status combinations are not covered.
- The app routes `--recovery` to `P1RecoveryScreen()`, passes the environment
  size category from `--largest`, and uses full available device width. This
  does not establish the separate 320-point sign-in viewport's recovery layout.

## Test integration

Add generated recovery Swift to the P1 app sources and append/include
`recovery_ui_tests.swift` in the P1 UI test target. It extends `P0SignInUITests`
and uses the shared `p1Launch`, `p1Wait` and `p1Record` helpers. Methods are
`testP1RecoveryNavigationDefault` and `testP1RecoveryNavigationLargest`.

Each method relaunches all four recovery states, records native accessibility
frames for the banner's title/control envelope, navigation bar/button and
synthetic content, checks visible non-overlap and navigation hittability,
then actually taps Open and the system Back button. It attaches one screenshot
per state and a final shared-helper JSON report with bounded per-state metrics.

Case IDs: `recovery-navigation-default`, `recovery-navigation-largest`.

Check IDs:
- `recovery-all-four-branches-visible`
- `recovery-content-above-navigation`
- `recovery-navigation-hittable`
- `recovery-navigation-tap-opens-destination`
- `recovery-navigation-back-restores-root`

The native gate must reject XCTest failures/skips and require all branches,
metrics and screenshots. JSON attachment existence alone is not UI proof.
Run portable extraction checks with `python -B ci/p1/recovery_source_tests.py
/path/to/V3UnifiedShell.swift`. Portable checks do not compile SwiftUI or execute
XCTest. Fresh macOS simulator execution remains required.
