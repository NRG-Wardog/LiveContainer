# Issue 47 validation

The candidate preserves measured host safe-area insets instead of clearing the top inset in landscape based solely on an OS selector. Existing geometry validation still rejects unattached, invalid, rotated, or sheared snapshots. Safe-area changes request normal layout propagation.

Input handoff now asks the outgoing guest's content hierarchy and host responder chain to end editing before return, minimize, PiP, close, termination, native-scene deactivation, or another virtual guest activation. It does not enumerate application/system windows, alter keyboard windows, dispatch delayed cleanup, or invoke new private UIKit APIs. Incoming guest focus is not cleared. Existing private scene hosting infrastructure is unchanged.

## Evidence limits

Linux tests execute the production C geometry helper, including 384 valid cases and invalid-input preservation cases. Python source-contract tests verify cleanup wiring and scope, not UIKit behavior. In particular, host-side `endEditing:` and responder resignation do not prove that a remote process has relinquished keyboard ownership. This issue must remain open until the actual remote keyboard transitions and layout are checked on supported devices. No device result is claimed.

## Device matrix required

- iPhone with notch/Dynamic Island and iPad; portrait and both landscape orientations, fullscreen and resized guest windows, supported scale settings.
- Open keyboard in guest A, return/minimize/close A, then open B. B must not inherit A's keyboard. Focus B and verify normal input.
- Switch from A to B using the dock and by touching B. Repeat quickly, interrupt minimize with reopen, and return to A. Do not lose new focus to old completions.
- Native-window mode: activate another scene and return; close a guest while keyboard is open.
- PiP enter/exit, host background/foreground, hardware keyboard connected/disconnected, and guest crash/termination during a transition.
- Verify no status bar/content overlap, no duplicated landscape top padding, and proper safe-area update on rotation, activation, and keyboard transitions.
- Verify embedded SideStore and system sheets retain their existing behavior.
