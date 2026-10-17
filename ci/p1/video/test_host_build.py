import inspect
from pathlib import Path
import unittest
import host_build

class HostBuild(unittest.TestCase):
    def test_exact_reviewed_methods_reused(self):
        self.assertIs(host_build.Host.run,host_build.original.Capture.run)
        self.assertIs(host_build.Host.clone,host_build.original.Capture.clone)
        self.assertIs(host_build.Host.native_build,host_build.original.Capture.native_build)
    def test_source_is_published_layout(self):
        self.assertEqual(host_build.capture.SOURCE['commit'],'bd5d9d87af76bfce0553d358bb3c6d45cbbc806a')
        self.assertEqual(host_build.PARENT,'fbaafb939bfd3b7c08fdc8ff4b8d2aae43526ece')
    def test_dependency_map_matches_immutable_p0(self):
        path=Path(__file__).resolve().parents[2]/'p0/inputs-sidestore.json'
        original=host_build.p0.parse(path.read_bytes())['submodules']
        self.assertEqual(host_build.SUBMODULES,{k:v for k,v in original.items() if k.startswith('LiveContainer/')})
    def test_never_claims_ui_or_admission(self):
        state=host_build.Host(Path('/host'),Path('/work'),Path('/evidence'),'a'*64).state
        for key in ['production_ready','admission_eligible','full_native_lane_executed','ui_executed','ipa_built','fresh_dependency_validation']:self.assertIs(state[key],False)
    def test_no_legacy_ui_is_invoked(self):
        source=inspect.getsource(host_build.Host.execute)
        self.assertIn('self.native_build()',source);self.assertNotIn('.targeted_behavior(',source);self.assertNotIn('.rendering(',source)

if __name__=='__main__':unittest.main()
