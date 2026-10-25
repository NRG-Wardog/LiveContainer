"""Host-side input ownership contracts; remote keyboard dismissal needs device QA."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def method(source, signature):
    tail = source.split(signature, 1)[1]
    start = tail.index('{')
    depth = 1
    for index in range(start + 1, len(tail)):
        depth += (tail[index] == '{') - (tail[index] == '}')
        if depth == 0:
            return tail[start + 1:index]
    raise AssertionError('unterminated method')


class GuestInputLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scene = (ROOT / 'MultitaskSupport/AppSceneViewController.m').read_text()
        cls.decorated = (ROOT / 'MultitaskSupport/DecoratedAppSceneViewController.m').read_text()

    def test_cleanup_is_synchronous_and_scoped_to_outgoing_guest(self):
        body = method(self.scene, '- (void)lcEndGuestEditing')
        for expected in ('NSThread.isMainThread', '[self.contentView endEditing:YES]',
                         '[self.viewIfLoaded endEditing:YES]',
                         '[self.hostingController.sceneViewController resignFirstResponder]',
                         '[self resignFirstResponder]'):
            self.assertIn(expected, body)
        for forbidden in ('dispatch_', 'UIApplication', 'connectedScenes', '.windows',
                          'sendAction:', 'setValue:', 'invalidate', 'removeFromSuperview'):
            self.assertNotIn(forbidden, body)
        # No delayed cleanup can run after a newer guest has acquired focus.

    def test_cleanup_precedes_host_activation_process_kill_and_teardown(self):
        for signature, next_action in (
            ('- (void)lcReturnToHost', 'self.lcActivateHost()'),
            ('- (void)terminate', '[self.extension _kill:SIGTERM]'),
            ('- (void)appTerminationCleanUp', '_isAppTerminationCleanUpCalled = true'),
            ('- (void)viewWillDisappear:', '[super viewWillDisappear:animated]'),
        ):
            body = method(self.scene, signature)
            self.assertLess(body.index('[self lcEndGuestEditing]'), body.index(next_action))
        cleanup = method(self.scene, '- (void)appTerminationCleanUp')
        self.assertLess(cleanup.index('if (_isAppTerminationCleanUpCalled) return'),
                        cleanup.index('[self lcEndGuestEditing]'))

    def test_minimize_and_pip_release_before_animation(self):
        for signature in ('- (void)minimizeWindow {', '- (void)minimizeWindowPiP {'):
            body = method(self.decorated, signature[:-1])
            self.assertLess(body.index('[self.appSceneVC lcEndGuestEditing]'),
                            body.index('[UIView animateWithDuration:'))

    def test_activation_preserves_incoming_guest_and_other_scenes(self):
        body = method(self.decorated, '- (void)lcPrepareForGuestActivation')
        self.assertIn('self.parentViewController.childViewControllers', body)
        self.assertIn('sibling == self', body)
        self.assertIn('isKindOfClass:DecoratedAppSceneViewController.class', body)
        self.assertIn('sibling.viewIfLoaded.window != self.viewIfLoaded.window', body)
        self.assertIn('[outgoing.appSceneVC lcEndGuestEditing]', body)
        self.assertNotIn('dispatch_', body)
        for signature in ('- (void)appSceneVCWillActivateScene:', '- (void)touchesBegan:'):
            self.assertIn('[self lcPrepareForGuestActivation]', method(self.decorated, signature))
        dock = (ROOT / 'MultitaskSupport/MultitaskDockView.swift').read_text()
        body = method(dock, 'private func bringViewToFront(')
        self.assertLess(body.index('lcPrepareForGuestActivation()'), body.index('bringSubviewToFront'))

    def test_native_scene_observation_is_replaced_and_scoped(self):
        appeared = method(self.scene, '- (void)viewDidAppear:')
        self.assertLess(appeared.index('removeObserver:self'), appeared.index('addObserver:self'))
        self.assertIn('object:scene', appeared)
        deactivating = method(self.scene, '- (void)lcHostSceneWillDeactivate:')
        self.assertIn('notification.object == self.viewIfLoaded.window.windowScene', deactivating)
        self.assertIn('[self lcEndGuestEditing]', deactivating)
        self.assertIn('removeObserver:self', method(self.scene, '- (void)dealloc'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
