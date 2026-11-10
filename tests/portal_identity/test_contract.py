"""Exercise real Foundation-only wire/presentation code; Swift is mandatory in CI."""
from pathlib import Path
import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('extract', ROOT/'.ci/comprehensive-diagnostics/generate_wire_fixture.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
HOST = ROOT/'SideStoreSupport/SideStore.swift'

class PortalIdentityTests(unittest.TestCase):
    def test_source_contract(self):
        source = HOST.read_text()
        failure = g.block(source, 'public struct CombinedFailure:')
        sanitizer = g.block(failure, 'public static func validatedSigningContext(')
        self.assertLess(sanitizer.index('supplied.removeValue(forKey: "preservation_portal_identity")'), sanitizer.index('supplied.removeValue(forKey: "apple_profile_origin")'))
        self.assertIn('guard fields.count <= 20', sanitizer)
        self.assertIn('if !preservationScope ||', failure)
        rows = g.block(source, 'public enum V3RefreshTargetDiagnostics {')
        self.assertIn('evidence?.mutationDispatched == false', rows)
        self.assertIn('"preservationPortalIdentity"', rows)
        peer = Path(os.environ.get('SIDESTORE_SOURCE_ROOT', str(ROOT.parent/'SideStore')))/'AltStore/AppDelegate.swift'
        if peer.exists():
            self.assertEqual(failure, g.block(peer.read_text(), 'public struct CombinedFailure:'))

    def test_real_wire(self):
        compiler = shutil.which('swiftc')
        self.assertIsNotNone(compiler, 'Native Swift toolchain required, do not skip in CI')
        source = 'import Foundation\nimport CoreFoundation\n' + g.pure_model(HOST.read_text())
        source += '\n' + (Path(__file__).parent/'cases.swift').read_text()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'main.swift'; binary = Path(directory)/'cases'
            path.write_text(source)
            result = subprocess.run([compiler, str(path), '-o', str(binary)], capture_output=True, text=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PORTAL_WIRE_PASS', result.stdout)
            print(result.stdout)

if __name__ == '__main__': unittest.main()
