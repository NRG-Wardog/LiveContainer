"""Negative tests for raw P1 UI export admission, not native/UI evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib
from test_feedback_trace import observations

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('p1_behavior', HERE / 'behavior_capture.py')
behavior = importlib.util.module_from_spec(spec); spec.loader.exec_module(behavior)
# Use the same frozen PNG decoder through the archived baseline source on CI.
# Unit fixture decoder checks its exact generated PNG; native gate uses the full
# independently pinned baseline PNG validator for all real exported screenshots.
def png():
    def chunk(kind, value):
        return struct.pack('>I', len(value)) + kind + value + struct.pack('>I', zlib.crc32(kind + value) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 100, 100, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress((b'\x00' + b'\x00\x00\x00\xff' * 100) * 100)) + chunk(b'IEND', b'')


class Decoder:
    @staticmethod
    def valid_png(data): return data == png()


class BehaviorExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.summary = {'result': 'Passed', 'passedTests': 5, 'failedTests': 0, 'skippedTests': 0, 'totalTestCount': 5}
        self.cases = []
        names = []
        for name, checks in behavior.CHECKS.items():
            case = {'schema': 'p1-behavior-case-v1', 'case': name, 'checks': checks, 'passed': True,
                    'testFailureCount': 0, 'screenshot': 'p1-' + name, 'observations': {}}
            names.append(case['screenshot'])
            if name.startswith('recovery-'):
                largest = name.endswith('-largest')
                branches = []
                for kind in ('operation', 'direct', 'refresh', 'unreadable'):
                    screenshot = 'p1-' + name + '-' + kind; names.append(screenshot)
                    branches.append({'kind': kind, 'largestDynamicType': largest,
                        'navigationHittable': True, 'navigationOpenedDestination': True, 'navigationBackRestoredRoot': True,
                        'bannerContentFrame': [0, 0, 100, 50], 'navigationFrame': [0, 60, 50, 20],
                        'navigationBarFrame': [0, 60, 100, 20], 'contentFrame': [0, 90, 100, 30],
                        'viewportFrame': [0, 0, 100, 200], 'screenshot': screenshot})
                control = {'kind': 'none', 'largestDynamicType': largest, 'recoveryBannerAbsent': True,
                    'navigationHittable': True, 'navigationOpenedDestination': True, 'navigationBackRestoredRoot': True,
                    'navigationFrame': [0, 60, 50, 20], 'navigationBarFrame': [0, 60, 100, 20],
                    'contentFrame': [0, 90, 100, 30], 'viewportFrame': [0, 0, 100, 200],
                    'screenshot': 'p1-' + name + '-no-banner'}
                names.append(control['screenshot'])
                case['observations'] = {'largestDynamicType': largest, 'branches': branches,
                    'containerTopology': 'TabView>NavigationView', 'noBannerControl': control}
            else:
                case['observations'] = observations(name)
            self.cases.append(case)
        self.manifest = [{'attachmentName': name, 'exportedFileName': str(i) + '.png'} for i, name in enumerate(names)]
        for row in self.manifest: (self.root / row['exportedFileName']).write_bytes(png())

    def verify(self, directory=None):
        for i, case in enumerate(self.cases):
            (self.root / (str(i) + '-case.json')).write_text(json.dumps(case))
            observations = case['observations']
            if 'passiveTrace' in observations:
                (self.root / (str(i) + '-trace.json')).write_text(json.dumps(observations['passiveTrace']))
            if 'normalTapObservation' in observations:
                (self.root / (str(i) + '-normal-trace.json')).write_text(json.dumps(observations['normalTapObservation']['passiveTrace']))
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest))
        return behavior.verify_export(self.root if directory is None else directory, self.summary, Decoder)

    def test_exact_five_cases_and_fifteen_screenshots(self):
        result = self.verify()
        self.assertEqual(result['test_count'], 5); self.assertEqual(len(result['screenshots']), 15)

    def test_accepts_canonicalized_parent_alias(self):
        with tempfile.TemporaryDirectory() as temporary:
            alias = Path(temporary) / 'parent'
            alias.symlink_to(self.root.parent, target_is_directory=True)
            result = self.verify(alias / self.root.name)
        self.assertEqual(result['test_count'], 5)
        self.assertEqual(len(result['screenshots']), 15)
        self.assertTrue(all(not Path(item['path']).is_absolute() and
            (self.root / item['path']).is_file() for item in result['screenshots'].values()))

    def test_rejects_linked_export_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            alias = Path(temporary) / 'root'
            alias.symlink_to(self.root, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'linked/missing UI export root'):
                self.verify(alias)

    def test_rejects_linked_export_artifact(self):
        (self.root / 'linked.png').symlink_to(self.root / '0.png')
        with self.assertRaisesRegex(ValueError, 'linked UI artifact'):
            self.verify()

    def test_rejects_skipped_or_failed_native_test(self):
        for key in ('failedTests', 'skippedTests'):
            with self.subTest(key=key):
                old = dict(self.summary); self.summary[key] = 1
                with self.assertRaises(ValueError): self.verify()
                self.summary = old

    def test_rejects_boolean_native_count(self):
        self.summary['failedTests'] = False
        with self.assertRaises(ValueError): self.verify()

    def test_rejects_missing_case(self):
        self.cases.pop()
        with self.assertRaises(ValueError): self.verify()

    def test_rejects_duplicate_case(self):
        self.cases[-1] = copy.deepcopy(self.cases[0])
        with self.assertRaises(ValueError): self.verify()

    def test_rejects_missing_required_check(self):
        self.cases[0]['checks'] = self.cases[0]['checks'][:-1]
        with self.assertRaises(ValueError): self.verify()

    def test_rejects_premature_timeout(self):
        self.cases[0]['observations']['minimumLifetimeSeconds'] = 0.1
        with self.assertRaises(ValueError): self.verify()

    def test_rejects_missed_feedback_window(self):
        self.cases[0]['observations']['feedbackObservedSeconds'] = 3.5
        with self.assertRaises(ValueError): self.verify()

    def test_rejects_no_old_task_overlap(self):
        self.cases[1]['observations']['copyEventSpacingSeconds'] = 2.5
        with self.assertRaises(ValueError): self.verify()

    def test_rejects_overlap_too_early_to_expose_stale_reset(self):
        self.cases[1]['observations']['copyEventSpacingSeconds'] = 0.25
        with self.assertRaises(ValueError): self.verify()

    def test_rejects_transition_after_feedback_expiry(self):
        self.cases[2]['observations']['transitionDelaySeconds'] = 2.1
        with self.assertRaises(ValueError): self.verify()

    def test_rejects_missing_recovery_branch(self):
        self.cases[3]['observations']['branches'].pop()
        with self.assertRaises(ValueError): self.verify()

    def test_rejects_overlapping_navigation(self):
        self.cases[3]['observations']['branches'][0]['bannerContentFrame'][3] = 100
        with self.assertRaises(ValueError): self.verify()

    def test_rejects_unhittable_navigation(self):
        self.cases[3]['observations']['branches'][0]['navigationHittable'] = False
        with self.assertRaises(ValueError): self.verify()

    def test_rejects_wrong_recovery_topology(self):
        self.cases[3]['observations']['containerTopology'] = 'NavigationView'
        with self.assertRaises(ValueError): self.verify()

    def test_rejects_missing_no_banner_control(self):
        self.cases[3]['observations'].pop('noBannerControl')
        with self.assertRaises(ValueError): self.verify()

    def test_rejects_no_banner_navigation_failure(self):
        self.cases[3]['observations']['noBannerControl']['navigationOpenedDestination'] = False
        with self.assertRaises(ValueError): self.verify()

    def test_rejects_wrong_dynamic_type(self):
        self.cases[4]['observations']['largestDynamicType'] = False
        with self.assertRaises(ValueError): self.verify()

    def test_rejects_missing_screenshot(self):
        self.manifest.pop()
        with self.assertRaises(ValueError): self.verify()

    def test_rejects_duplicate_manifest_binding(self):
        self.manifest.append(copy.deepcopy(self.manifest[0]))
        with self.assertRaises(ValueError): self.verify()

    def test_rejects_reused_image_path(self):
        self.manifest[1]['exportedFileName'] = self.manifest[0]['exportedFileName']
        with self.assertRaises(ValueError): self.verify()

    def test_rejects_invalid_png(self):
        (self.root / '0.png').write_bytes(b'not a png')
        with self.assertRaises(ValueError): self.verify()

    def test_rejects_screenshot_escape(self):
        self.manifest[0]['exportedFileName'] = '../outside.png'
        with self.assertRaises(ValueError): self.verify()

    def test_rejects_nonfinite_geometry(self):
        self.cases[4]['observations']['branches'][0]['bannerContentFrame'][0] = float('nan')
        with self.assertRaises(ValueError): self.verify()

    def test_rejects_case_assertion_failure(self):
        self.cases[0]['testFailureCount'] = 1
        with self.assertRaises(ValueError): self.verify()


if __name__ == '__main__': unittest.main()
