# Issue 47: guest scene geometry and remote input ownership

Status: narrow geometry hardening candidate; the reported device symptoms are
not verified fixed. Keyboard handoff remains an investigation and device gate.

Issue: <https://github.com/NRG-Wardog/sidestore-auto-refresh/issues/47>

Source base: `NRG-Wardog/LiveContainer` at
`bd5d9d87af76bfce0553d358bb3c6d45cbbc806a`. The issue was read through authenticated
GitHub access on 2026-10-17. It describes an iOS 27.2 device reproduction and a
screenshot available to the reporter; no screenshot or comments are attached.
The launch mode, device model, guest builds, scaling preference and window-bar
placement have not yet been established. Do not infer them from the title.

## Source findings

- `MultitaskSupport/UIKitHooks.m`,
  `hook_FBScene_performUpdateWithoutActivation`: after invoking the original
  update block, the hook replaces guest safe-area settings with the hosting
  superview's insets divided by the hosting view's transform diagonals. Before
  this change there was no attachment, transform, input or output validation.
  A missing superview can replace usable incoming settings with zero insets;
  zero diagonals can produce NaN/Infinity. A rotated or sheared transform cannot
  be handled by this division. These are source-level defects, independently of
  the Instagram report. Their occurrence in that report is unproven.
- The same hook clears the top inset in its existing remote-sheet-capable
  landscape branch. `DecoratedAppSceneViewController.m` also has separate
  maximized/windowed inset policy. Neither policy is changed by this patch.
  Their relationship to the reported overlap needs real geometry evidence.
- `AppSceneViewController.m`, `setUpAppPresenter`, creates a remote scene for a
  distinct LiveProcess PID. Modern hosting uses a scene-view controller and an
  existing event-deferring component. Its keyboard fields are in the guest
  process, not ordinary descendants of the host's view hierarchy.
- `DecoratedAppSceneViewController.m`, `minimizeWindow` and `minimizeWindowPiP`,
  animate and hide the presentation. `AppSceneViewController.lcReturnToHost`
  selects minimize or native host-scene activation. Dock switching in
  `MultitaskDockView.swift` raises retained views. None of those operations sends
  an explicit guest-owned end-editing request.
- `AppSceneViewController.terminate` kills the extension; cleanup destroys or
  invalidates the presentation. That is a different path from retaining and
  minimizing a running guest. Direct-process Return in `LiveContainer/LCBootstrap.m`
  restarts LiveContainer and is different again. This patch changes none of them.
- `LiveProcess/main.m` establishes its current NSXPC endpoint only for
  `builtinSideStore`. The ordinary guest launch dictionary in
  `AppSceneViewController.initWithBundleId` does not carry that endpoint.
  `SideStoreSupport/XPCServer.h` defines refresh/service commands, not a general
  per-guest input channel. It is not a safe shortcut for keyboard handoff.

Apple documents `UIView.endEditing` as searching the receiver's subview
hierarchy. Calling it on a host-wide window would affect unrelated host controls,
and calling it only on a remote hosting view does not prove guest-side first
responder release. No such speculative cleanup is added.

- [Apple: endEditing](https://developer.apple.com/documentation/uikit/uiview/endediting(_:))
- [Apple: UIView frame and non-identity transforms](https://developer.apple.com/documentation/uikit/uiview/frame)

## Patch contract

1. Call the original scene update block exactly as before.
2. Preserve its resulting settings when the particular hosting view has no
   superview or window.
3. Preserve those settings for nonfinite or negative source insets, nonfinite
   transforms, zero/negative scale, rotation, shear, or nonfinite scaled output.
4. For attached, valid positive axis-aligned scale, use exactly the existing
   top/bottom divided by `d`, left/right divided by `a` arithmetic. Keep the
   existing landscape adjustment, orientation mapping and OS-specific setters.
5. Leave the system remote-sheet bypass intact. Add no private UIKit API,
   hard-coded replacement inset, guest lifecycle operation, window destruction,
   process-wide editing action, keyboard delay, or new diagnostic logging.

`LCGuestSafeAreaGeometry.h` is a framework-free production helper included by
the existing `UIKitHooks.m` compilation unit. It needs no new build source entry.
Rejection leaves its output untouched; the adapter returns without changing
the caller's safe-area settings. Unsupported transforms are deliberately not
converted by a guessed formula.

This does not add a deferred retry when an unattached view later attaches.
Observe the next real scene/layout update in native validation. If a usable
update never arrives, that is a separate propagation defect to investigate.

## Portable checks

```sh
python -B tests/test_guest_safe_area_geometry.py
git diff --check
```

The C fixture compiles the production header with fatal warnings and executes
384 valid scale/inset combinations, invalid source edges, zero/reflected/rotated/
sheared/nonfinite transforms, overflow and null-output cases. The Python source
contracts check original-block ordering, attachment gating, validation before
the landscape adjustment, setter ordering and the untouched remote-sheet bypass.
Source contracts are not execution of UIKit or its remote scene implementation.

The repository-wide frozen migration suite must also be attempted and reported
separately. It is a historical whole-tree/parity gate, not an automatically
updated acceptance suite for later product changes. Do not rewrite its pinned
hashes or allowlist to make this patch pass.

## Native geometry regression

Build this exact source with the project's supported Xcode/iPhoneOS SDK and
signing setup. A successful C harness is not an Objective-C/UIKit build pass.

In a native test harness, exercise the actual hook's block boundary with a
recording scene/settings double and actual UIKit hosting-container views:

1. Seed both safe-area fields to distinct, nonzero sentinel insets in the caller
   block. Verify the caller executes once for each update.
2. Test nil hosting view, no superview, and a superview not attached to a window.
   Verify both fields retain exactly the caller's values.
3. Attach the hosting container to a UIWindow. Verify identity, 0.5, 1 and 2
   scales and unequal positive axis scales against the previous arithmetic in
   portrait and both landscape orientations. Include zero insets and notch/home
   indicator-shaped inputs. Exercise both remote-sheet capability states.
4. Inject unsupported transforms and invalid input/output values into the
   settings/view doubles, rather than assigning NaN/Infinity to live UIKit views.
   Verify preservation. Include the landscape path with an invalid top inset,
   so clearing the top cannot hide invalid input.
5. Detach and reattach the same view; check that a subsequent valid update applies
   the current insets, not the detached snapshot. Verify the system remote-sheet
   bypass still receives the original block.

Then compare baseline and candidate on physical devices. Record the exact build
SHA, device model, OS build, guest version and launch mode. Cover notch/Dynamic
Island and a non-notched phone where supported, plus iPad native/virtual windows:

- Direct guest, virtual windowed, virtual maximized and iPad native window modes
- Portrait, landscape-left/right, repeated rotation and supported upside-down
- Scale 0.5/1/2, resize, top/bottom window bar and collapsed/expanded dock
- Minimize/restore, PiP entry/exit where available, and background/foreground
- Keyboard hidden/visible/hidden, including after a guest switch

For each step compare host window bounds/safe area, hosting view bounds and
transform, containing view safe area, outgoing scene-settings insets and the
guest window safe area/status-bar frame. Compare in the appropriate coordinate
space. Confirm top controls stay outside the status bar/notch, bottom controls
remain reachable, no unexpected scale changes occur, and touch targets follow
the rendered controls. This is separate from host recovery-banner validation.

## Bounded remote-focus investigation

Use two synthetic guest apps, A and B, each with one text field and an on-screen
non-sensitive marker. First establish the same symptoms before the patch. Then
attach the debugger to the host and the exact outgoing LiveProcess PID.

Opt in only for the test run using debugger breakpoints and fixture-owned
instrumentation. Observe, without changing focus behavior:

- Host Return/minimize, dock-front selection, terminate and presentation cleanup
- Guest scene will-deactivate/did-enter-background/did-activate callbacks
- Guest keyboard will-hide/did-hide and first-responder changes
- Host proxy first-responder state, separately from the guest field's state

Use an ephemeral test-run token plus A/B labels and transition sequence number
to correlate observations. Capture only stage, process/scene ownership, bounded
frame/inset/transform numbers and first-responder presence/class. Keep at most
one snapshot per stage per transition, with a fixed small per-run cap. Never
record input text, clipboard, URLs, account data, full object descriptions or
view-hierarchy dumps. Instrumentation is off outside the opted-in test session.

Specifically determine whether minimizing a retained remote view sends any
deactivation event to the guest. The host's existing foreground policy means
this cannot be assumed. Also determine whether public responder cleanup of the
host proxy causes the guest field to resign; neither result is established here.

If existing lifecycle delivery proves sufficient, implement the eventual public
`endEditing:YES` in the outgoing guest process, on windows belonging to its exact
scene, before the handoff. If it is insufficient, a separately reviewed per-guest
request/acknowledgment channel is needed. Bind it to the extension request and
scene ownership, run cleanup on the guest main queue, reject stale sequence
numbers, and handle guest exit and missing acknowledgment. Do not reuse a
SideStore-only endpoint, enumerate unrelated host windows, destroy system
keyboard windows, or add a private keyboard selector to force success.
An editing request or successful boolean alone is not proof the keyboard finished
hiding; collect actual guest responder/keyboard completion evidence first.

## Two-guest acceptance recipe

1. Launch A; focus its field and show the software keyboard.
2. Leave A using Return, then activate B without tapping B's field. B must have
   no inherited keyboard, focus or input delivery. Confirm A is preserved when
   Return/minimize is intended to preserve it.
3. Focus B deliberately. Confirm typing reaches only B. Return to A and check
   that any keyboard shown belongs to a deliberate new focus in A.
4. Repeat A-to-B-to-A at least 20 times, including rapid switch/reopen while
   minimize/keyboard animations are still in progress. Check that stale cleanup
   never dismisses the newly active guest's keyboard.
5. Repeat through minimize, dock selection without minimizing, Close, actual
   guest termination, PiP where supported, and native-scene switching. Test
   direct-process Return separately; it intentionally restarts the process.
6. Repeat with keyboard already dismissed and with a hardware keyboard. Keep a
   host search field available and verify guest cleanup never clears host focus
   or another guest's input. Include orientation/scale changes during the run.

Pass requires observed outgoing guest first-responder release, correct incoming
ownership and keyboard dismissal timing, plus the geometry matrix above. A
source review, scalar test pass or successful build does not close issue 47.
