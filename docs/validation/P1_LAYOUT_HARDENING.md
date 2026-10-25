# P1 layout hardening forwardport

Base: NRG-Wardog/LiveContainer main at
`5980d02b91077562fb5994027ff12e7773f4113e`.

Preserved source changes: `0dcc2a20d9490a797ead972507a28fe02eef56fc`
(guest safe-area guards) and `bd5d9d87af76bfce0553d358bb3c6d45cbbc806a`
(bounded recovery banner). This is a narrow forwardport, not a historical-tree
replacement. Current localization, diagnostics, recovery actions, tab selection,
and presentation callbacks are unchanged.

## User-visible purpose

- Keep a detached, invalid, rotated, or sheared host-view snapshot from replacing
  the guest's existing safe area with zero, negative, or nonfinite insets.
- Keep recovery notices in their own scrollable region above navigation, capped
  at the smaller of 320 points or 40% of available height. Recovery actions and
  normal app navigation remain available together.

## Geometry contract

The original scene update runs first. Only an attached hosting view with a
positive, finite, axis-aligned scale and finite nonnegative source/output insets
can override those resulting settings. Unsupported transforms are not converted
using a guessed formula. Validation precedes the existing landscape adjustment;
valid conversions use the exact prior top/bottom over d and left/right over a
arithmetic. Remote-sheet bypass and OS-specific orientation setters are unchanged.
There is no guessed fallback, forced keyboard dismissal, added private API,
guest lifecycle operation, telemetry, or retry. A later valid scene update must
apply the new insets after reattachment. This does not establish that issue 47's
device symptoms are fixed.

## Focused checks

Run `python -B tests/test_guest_safe_area_geometry.py` and
`python -B tests/test_recovery_banner_layout.py`.

The C fixture uses the production header and covers 384 valid combinations plus
invalid source/transform, overflow, null-output, and output-preservation cases.
Python checks hook ordering, remote-sheet bypass, layout wiring, retained
localization, and recovery actions. If Swift is available, the actual two sizing
expressions are extracted and compiled for nine scalar cases. None of these
checks executes UIKit or SwiftUI layout. Missing compilers are reported as skips,
not passes. Do not run the historical simulator or native provisioning harness.

Before shipping, build the exact candidate with the supported Xcode/iPhoneOS SDK.
On device, compare recovery shown/hidden/replaced, repeated show/hide, compact
landscape, large accessibility text, Hebrew RTL and English LTR, banner scrolling,
tab changes, preserved navigation, and existing confirmation/presentation flows.
Compare guest attach/detach/reattach, identity and unequal positive scaling,
rotation, supported window modes, remote-sheet bypass and orientation-specific
safe areas. Inject invalid scalars only into test doubles, not live UIKit views.
Do not infer keyboard-focus correctness from either geometry or banner checks.
