"""Portable privacy/wiring controls; actual ObjC/Swift execution is a separate mandatory runner."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class GuestLaunchDiagnosticControls(unittest.TestCase):
 def test_storage_is_bounded_memory_only_and_canonical(self):
  source=(ROOT/'LiveContainerSwiftUI/Utilities/LCUtils.m').read_text()
  storage=source.split('// LC_GUEST_DIAGNOSTIC_STORAGE_BEGIN')[1].split('// LC_GUEST_DIAGNOSTIC_STORAGE_END')[0]
  methods=source.split('// LC_GUEST_DIAGNOSTIC_METHODS_BEGIN')[1].split('// LC_GUEST_DIAGNOSTIC_METHODS_END')[0]
  for bad in ('NSUserDefaults','NSFileManager','writeTo','bundleId','dataUUID','localizedDescription'):
   self.assertNotIn(bad,storage+methods)
  self.assertIn('[allowed member:phase]',methods)
  self.assertIn('phase = canonical;',methods)
  self.assertIn('generation != LCGuestDiagnosticGeneration',methods)
  self.assertIn('LCGuestDiagnosticPhases.count > 16',methods)
 def test_new_launch_and_legacy_wrapper_use_bounded_generation(self):
  source=(ROOT/'LiveContainerSwiftUI/Utilities/LCUtils.m').read_text()
  self.assertIn('diagnosticGeneration:[self beginGuestLaunchDiagnostics]',source)
  self.assertIn('pidCallback:finish',source)
  self.assertIn('launcherView.pidAvailableHandler = finish;',source)
  self.assertIn('if (completionHandler) completionHandler(pid, error);',source)
 def test_copy_retains_existing_policy_without_new_service_dependency(self):
  source=(ROOT/'LiveContainerSwiftUI/Views/V3UnifiedShell.swift').read_text().split('struct V3LogsView: View {',1)[1].split('struct V3ExperimentalView:',1)[0]
  self.assertLess(source.index('LCUtils.guestLaunchDiagnosticSnapshot()'),source.index('guard V3OperationLogLoadPolicy.shouldRequestServiceLogs'))
  self.assertIn('V3OperationLogLoadPolicy.copyText(startup: startup, operations: tail)',source)
 def test_completion_scope_is_not_guest_visibility_claim(self):
  source=(ROOT/'LiveContainerSwiftUI/Utilities/LCUtils.m').read_text()
  self.assertIn('guest_launch_scope=host_boundary_not_guest_readiness',source)
  self.assertIn('pid.intValue > 0 ? @"completed" : @"callback_no_pid"',source)
if __name__=='__main__':unittest.main(verbosity=2)
