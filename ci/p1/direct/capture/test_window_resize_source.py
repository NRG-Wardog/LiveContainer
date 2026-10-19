from pathlib import Path
import unittest
import build_main

HERE=Path(__file__).parent
class ResizeSourceTests(unittest.TestCase):
    def test_existing_trust_and_exact_owner_precede_single_action(self):
        source=(HERE/'window_resize.swift').read_text()
        mutation=source.index('AXUIElementPerformAction(preset,')
        for token in ('AXIsProcessTrusted()', 'try require(trusted,', 'windows.count == 1',
                      'AXUIElementGetPid(target, &axPID)', 'axPID == pid',
                      'directAXRect(target) == window.frame', 'try requireMainWindow()',
                      'matching.count == 1', 'menus.count == 1', 'presets.count == 1',
                      'directPresetEnabled', 'try require(owner.valid(),'):
            self.assertLess(source.index(token),mutation)
        self.assertEqual(source.count('AXUIElementPerformAction('),1)
        for forbidden in ('AXIsProcessTrustedWithOptions','AXMakeProcessTrusted','AXUIElementCreateSystemWide',
                          'CGRequestScreenCaptureAccess','AXUIElementSetAttributeValue(', 'CGEventPost'):
            self.assertNotIn(forbidden,source)
        self.assertIn('[kAXMainWindowAttribute, kAXFocusedWindowAttribute]',source)
        self.assertIn('CFEqual(value, target)',source)
        self.assertIn('"Pixel Accurate"',source)
        self.assertIn('values.count <= 128',source)
    def test_same_window_settlement_and_source_pixels_remain_required(self):
        source=(HERE/'window_resize.swift').read_text()
        for token in ('select(window.windowID, "resized")','current.frame == prior',
                      'current.frame == axFrame','current.frame.width <= 4096','current.frame.height <= 4096',
                      '"sourceResolutionEstablished": false','AXUIElementSetMessagingTimeout(target, 2)'):
            self.assertIn(token,source)
    def test_bounded_action_precedes_immutable_filter_with_downscale_only(self):
        source=build_main.build(build_main.SOURCE.read_text(),(HERE/'source-sha256.txt').read_text().strip())
        self.assertLess(source.index('deadline.arm(15, "owned-window-resize")'),source.index('directResizeOwnedWindow('))
        self.assertLess(source.index('directResizeOwnedWindow('),source.index('SCContentFilter(desktopIndependentWindow: window)'))
        self.assertIn('min(1.0, min(1000.0 / pixelWidth, 1600.0 / pixelHeight))',source)
        self.assertIn('configuration.ignoreGlobalClipSingleWindow = true',source)
        self.assertIn('configuration.preservesAspectRatio = true',source)
        self.assertIn('Double(content.width) * scale',source)
        self.assertEqual(source.count('desktopIndependentWindow:'),1)

    def test_direct_enabled_item_has_no_menu_open_or_notification_dependency(self):
        source=(HERE/'window_resize.swift').read_text()
        for token in ('"direct-enabled-preset-item-v1"','"menuOpenAttempted"] = false',
                      '"menuNotificationEvidenceClaimed"] = false','kAXMenuItemRole','directRequirePress(preset, pid: pid)'):
            self.assertIn(token,source)
        self.assertLess(source.index('try require(enabled == true'),source.index('AXUIElementPerformAction(preset,'))
        for forbidden in ('AXObserver','kAXMenuOpenedNotification','kAXMenuClosedNotification',
                          'AXUIElementPerformAction(matching[0]','menuClosureObserved','setEnabled(',
                          'AXUIElementSetAttributeValue(', 'cancelTracking', 'NSMenu('):
            self.assertNotIn(forbidden,source)

    def test_only_owned_application_may_be_foregrounded_once(self):
        source=(HERE/'window_resize.swift').read_text()
        self.assertEqual(source.count('.activate(options: [])'),1)
        self.assertIn('NSRunningApplication(processIdentifier: pid)',source)
        self.assertIn('if !ownedApplication.isActive',source)
        self.assertIn('while !ownedApplication.isActive',source)
        activation=source[source.index('while !ownedApplication.isActive'):source.index('proof["ownerActiveAfter"]')]
        self.assertIn('CFRunLoopRunInMode(CFRunLoopMode.defaultMode, 0.02, true)',activation)
        self.assertNotIn('Task.sleep',activation)
        self.assertIn('"owned-window-changed-during-activation"',source)
        self.assertLess(source.index('"ownerActiveAfter"'),source.index('let rawBar ='))
        self.assertNotIn('activateIgnoringOtherApps',source)

    def test_owner_and_focus_rechecked_after_async_selection(self):
        source=(HERE/'window_resize.swift').read_text()
        block=source[source.index('let current = try await select(window.windowID, "resized")'):]
        for token in ('try require(owner.valid()', 'try requireMainWindow()', 'ownedApplication.isActive','directAXRect(target)'):
            self.assertLess(block.index(token),block.index('if current.frame == prior'))

    def test_modern_runloop_api_and_synchronous_activation_phase(self):
        source=(HERE/'window_resize.swift').read_text()
        self.assertNotIn('kCFRunLoopDefaultMode',source)
        self.assertNotIn('CFRunLoopGetCurrent()',source)
        phase=source[source.index('@MainActor func directActivateOwnedApplication'):source.index('@MainActor func directResizeOwnedWindow')]
        self.assertIn('throws -> NSRunningApplication',phase)
        self.assertNotIn('async',phase.split('{',1)[0])
        self.assertNotIn('await ',phase)
        self.assertIn('Thread.isMainThread',phase)
        async_phase=source[source.index('@MainActor func directResizeOwnedWindow'):]
        self.assertNotIn('CFRunLoopRunInMode(',async_phase)

    def test_actual_binary_readonly_preflight_precedes_build_and_boot(self):
        source=build_main.build(build_main.SOURCE.read_text(),(HERE/'source-sha256.txt').read_text().strip())
        mode=source[source.index('if args.count == 2'):source.index('guard args.count == 7')]
        self.assertIn('AXIsProcessTrusted()',mode)
        self.assertNotIn('AXUIElement',mode)
        self.assertIn('"permissionRequested": false',mode)
        entry=(HERE.parent/'entry.py').read_text()
        self.assertLess(entry.index("startup_observation(command,result,'accessibility-prerequisite',helper,'--check-existing-accessibility',historical=10)"),entry.index('capture.base.acquire(builder'))
        self.assertLess(entry.index("capture.write(output/'accessibility-prerequisite.json'"),entry.index("require(set(accessibility)"))

class ImmutableResizeSourceTests(unittest.TestCase):
    def test_progress_snapshots_and_terminal_canonical_are_distinct(self):
        source=(HERE/'window_resize.swift').read_text()
        self.assertEqual(source.count('"window-resize.json"'),1)
        self.assertIn('"window-resize-attempt-" + String(sequence)',source)
        self.assertIn('sequence += 1',source)
        self.assertEqual(source.count('try evidence.publish(proof)'),1)
        terminal=source[source.index('if current.frame == prior'):]
        self.assertLess(terminal.index('proof["sameOwnedWindowSettled"] = true'),terminal.index('try evidence.publish(proof)'))
        self.assertNotIn('try write(proof, path)',source)
        self.assertIn('try evidence.snapshot(proof)',source)

if __name__=='__main__':unittest.main()
