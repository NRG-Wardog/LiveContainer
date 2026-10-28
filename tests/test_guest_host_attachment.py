"""Portable wiring contracts; actual UIKit attachment/resolver run in focused CI."""
import pathlib, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class GuestHostAttachmentTests(unittest.TestCase):
 def setUp(self):
  self.dock=(ROOT/'MultitaskSupport/MultitaskDockView.swift').read_text()
  self.view=(ROOT/'MultitaskSupport/VirtualWindowsHostView.m').read_text()
  self.launch=(ROOT/'LiveContainerSwiftUI/Utilities/LCUtils.m').read_text()
 def test_root_overlay_not_swiftui_implementation_child(self):
  self.assertNotIn('rootViewController!.view.subviews.first!',self.dock)
  self.assertNotIn('connectedScenes',self.view)
  for fragment in ('[super initWithFrame:CGRectZero]','[hostView addSubview:self]','self.frame = bounds','[hostView bringSubviewToFront:self]','!hostView.window','CGRectIsEmpty(bounds)','isfinite(bounds.size.height)'):
   self.assertIn(fragment,self.view)
 def test_typed_host_marker_unique_attached_and_guest_scoped(self):
  start=self.dock.index('// LC_GUEST_HOST_WINDOW_SELECTION_BEGIN')
  end=self.dock.index('// LC_GUEST_HOST_WINDOW_SELECTION_END')
  scope=self.dock[start:end]
  for fragment in ('controller is AppSceneViewController || controller is DecoratedAppSceneViewController','controller is V3HostLanguageUIKitBridge.Controller','controller.viewIfLoaded?.window === window','root.viewIfLoaded?.window === window','!window.isHidden','window.windowLevel == .normal','candidates.count == 1'):
   self.assertIn(fragment,scope)
  self.assertNotIn('String(describing:',scope)
 def test_recorded_scene_precedes_bounded_marker_fallback(self):
  start=self.dock.index('public var keyWindow: UIWindow?')
  scope=self.dock[start:self.dock.index('@objc public func prepareVirtualWindowHost',start)]
  for fragment in ('MultitaskWindowManager.mainSceneSession','session.persistentIdentifier','.foregroundActive','.foregroundInactive','LCGuestHostWindowSelection.select'):
   self.assertIn(fragment,scope)
  self.assertNotIn('connectedScenes.first',self.dock)
  self.assertNotIn('keyWindow!',self.dock)
 def test_admission_precedes_guest_construction_and_same_root_is_used(self):
  start=self.launch.index('MultitaskDockManager *dock = [MultitaskDockManager shared];',self.launch.index('return;\n            }'))
  scope=self.launch[start:self.launch.index('#pragma mark Code signing',start)]
  self.assertLess(scope.index('[dock prepareVirtualWindowHost]'),scope.index('initWindowName:'))
  self.assertIn('if (!rootVC)',scope)
  self.assertIn('finish(nil, error)',scope)
  self.assertIn('if (completionHandler) completionHandler(pid, error);',self.launch)
  self.assertIn('dataUUID:dataUUID rootVC:rootVC',scope)
  self.assertIn('CGRectGetMidX(dock.windowHostingView.bounds)',scope)
 def test_retained_guest_owner_never_migrates(self):
  start=self.dock.index('@objc public func prepareVirtualWindowHost')
  scope=self.dock[start:self.dock.index('public var safeAreaInsets',start)]
  self.assertLess(scope.index('controller.parent !== root'),scope.index('windowHostingView.attach'))
  self.assertNotIn('removeFromParent',scope)
  self.assertNotIn('root.addChild',scope)
  resume=self.dock[self.dock.index('func bringMultitaskViewToFront'):self.dock.index('private func passURLSchemeToView')]
  self.assertIn('prepareVirtualWindowHost() != nil',resume)
 def test_dock_uses_same_window_for_mount_and_gestures(self):
  self.assertIn('hostingController.view.superview !== keyWindow',self.dock)
  start=self.dock.index('private func setupEdgeGestureRecognizers()')
  self.assertIn('guard let keyWindow = self.keyWindow',self.dock[start:start+160])
if __name__=='__main__':unittest.main()
