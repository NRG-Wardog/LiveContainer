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
- The inset attaches to an outer selection-bound `TabView`, with four tab
  children, each owning a stack-style `NavigationView`, matching the production
  container topology. The selected Home tab supplies synthetic Recovery/Open/
  Details content; the other three tabs are synthetic placeholders. Labels and
  ordering are Home, Apps, Sources, Settings. The inset does not attach directly
  to the navigation child. No fixed height/width, ignored safe area, or Dynamic
  Type cap compensates for layout failures.
- `P1RecoveryStatus`, `P1RecoveryOperation`, tab contents, navigation root/
  destination and fixture IDs are synthetic. Callback bodies are no-ops. This
  is not the full production `V3UnifiedTabs`, status store, recovery lifecycle,
  list contents, lifecycle modifiers, or backend. The fixture's inline Recovery
  title is not a claim to reproduce every production navigation-bar setting.
- The tested states are dispatched install, prepared certificate creation with
  manual-check-required postcondition, lost refresh, and clear-eligible
  malformed recovery record. All four are tested at default and largest
  Dynamic Type. Other policy/status combinations are not covered.
- A `--recovery-kind none` control uses that identical tab/navigation hierarchy
  and the same unmodified recovery inset, with every recovery condition false.
  It proves the synthetic navigation is usable without a banner at each size.
  It cannot excuse a failed recovery branch or establish production behavior.
- The app routes `--recovery` to `P1RecoveryScreen()`, passes the environment
  size category from `--largest`, and uses full available device width. This
  does not establish the separate 320-point sign-in viewport's recovery layout.

## Test integration

Add generated recovery Swift to the P1 app sources and append/include
`recovery_ui_tests.swift` in the P1 UI test target. It extends `P0SignInUITests`
and uses the shared `p1Launch`, `p1Wait` and `p1Record` helpers. Methods are
`testP1RecoveryNavigationDefault` and `testP1RecoveryNavigationLargest`.

Each method first launches its no-banner control, then relaunches all four
recovery states. It records native accessibility
frames for the banner's title/control envelope, navigation bar/button and
synthetic content, checks visible non-overlap and navigation hittability,
then actually taps Open and the system Back button. It attaches one screenshot
per state/control and a final shared-helper JSON report with bounded per-state
metrics. The control checks absent recovery labels, valid finite frames,
bar/content non-overlap, navigation/bar/content inside the viewport, and the
same Open/Back round trip. A successful control is necessary and never sufficient
for a successful recovery test.

Before acceptance guards, each state/control also retains a screenshot and a
`p1-recovery-observation-v1` JSON attachment containing observed existence,
hittability and frames. These pre-assertion observations are failure diagnostics,
not passing reports. An absent heading or occluded navigation therefore retains
evidence while the existing strict XCTest assertions still fail closed.

Case IDs: `recovery-navigation-default`, `recovery-navigation-largest`.

Check IDs:
- `recovery-no-banner-control`
- `recovery-all-four-branches-visible`
- `recovery-content-above-navigation`
- `recovery-navigation-hittable`
- `recovery-navigation-tap-opens-destination`
- `recovery-navigation-back-restores-root`

Both recovery reports retain four `branches` and add `noBannerControl` plus
`containerTopology: "TabView>NavigationView"`. The control has `kind: "none"`,
the matching `largestDynamicType`, `recoveryBannerAbsent`, navigation/content/
viewport frames, `navigationHittable`, `navigationOpenedDestination`, and
`navigationBackRestoredRoot`. The four Boolean results must all be true.

New required screenshots per device:
- `p1-recovery-navigation-default-no-banner`
- `p1-recovery-navigation-largest-no-banner`

The eight existing branch screenshots and two final recovery-case screenshots
remain mandatory. With the three existing lifecycle-case screenshots, the
targeted five-case suite requires 15 screenshots per device, 30 across phone
and tablet. This changes no targeted XCTest method/case ID and adds no skipped
or substituted branch. Each device also retains ten pre-assertion recovery
observation JSON attachments on a complete run.

The native gate must reject XCTest failures/skips and require all branches,
control metrics and screenshots. JSON attachment existence alone is not UI proof.
Run portable extraction checks with `python -B ci/p1/recovery_source_tests.py
/path/to/V3UnifiedShell.swift`. Portable checks do not compile SwiftUI or execute
XCTest. Fresh macOS simulator execution remains required.
