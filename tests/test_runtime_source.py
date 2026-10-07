"""Fork-native checks that read maintained source, never integration patchers.

Native C probes compile unchanged production declarations into platform harnesses.
Swift/source assertions and frozen hash parity are distinguished from iOS testing.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from runtime_tree_gate import BoundGit, FROZEN_MANIFEST_BLOB, FROZEN_MANIFEST_SHA256, verify_repository

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_BYTES = BoundGit(ROOT).run('cat-file', 'blob', FROZEN_MANIFEST_BLOB)
assert hashlib.sha256(MANIFEST_BYTES).hexdigest() == FROZEN_MANIFEST_SHA256
MANIFEST = json.loads(MANIFEST_BYTES)
COMPONENTS_BLOB = 'cf97e350e1bbf76e1c09d03ab722b2753c5e48df'
COMPONENTS_SHA256 = '128dcce38f1a542d1f5989b56f889ae22f732f2824d94fffdf7d0ad8957cf12d'
COMPONENTS_BYTES = BoundGit(ROOT).run('cat-file', 'blob', COMPONENTS_BLOB)
assert hashlib.sha256(COMPONENTS_BYTES).hexdigest() == COMPONENTS_SHA256
COMPONENTS = json.loads(COMPONENTS_BYTES)['components']
BASE = MANIFEST['upstream_commit']
CC = shutil.which('cc') or shutil.which('clang') or shutil.which('gcc')
SWIFTC = shutil.which('swiftc')


def setUpModule():
    # Reject substituted/dirty source before any content is compiled by probes.
    verify_repository(ROOT)


def source(path: str) -> str:
    return (ROOT / path).read_text()


def block(text: str, anchor: str) -> str:
    """Extract a maintained declaration, not a transcription of its behavior."""
    start = text.index(anchor)
    opening = text.index('{', start)
    depth = 0
    for end in range(opening, len(text)):
        if text[end] == '{':
            depth += 1
        elif text[end] == '}':
            depth -= 1
            if depth == 0:
                return text[start:end + 1]
    raise AssertionError('Unbalanced declaration: ' + anchor)


def git(*args: str) -> bytes:
    return BoundGit(ROOT).run(*args)


def scan_helper() -> str:
    text = source('LiveContainer/LCBootstrap.m')
    return text[text.index('#include <stdbool.h>'):text.index('_Static_assert')]


class MaintainedSourceParityTests(unittest.TestCase):
    def test_all_product_files_match_frozen_generated_bytes_and_modes(self):
        self.assertEqual(len(MANIFEST['files']), 56)
        for item in MANIFEST['files']:
            with self.subTest(path=item['path']):
                path = ROOT / item['path']
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item['old_generated_sha256'])
                self.assertEqual(item['sha256'], item['old_generated_sha256'])
                self.assertEqual(oct(path.stat().st_mode & 0o777), item['mode'])

    def test_source_components_are_current_source_slices(self):
        self.assertGreater(len(COMPONENTS), 15)
        for component in COMPONENTS:
            with self.subTest(component=component):
                data = (ROOT / component['source']).read_bytes()
                start, count = component['byte_offset'], component['byte_length']
                self.assertEqual(hashlib.sha256(data[start:start + count]).hexdigest(), component['sha256'])

    def test_upstream_ancestry_license_and_dependency_pins_are_preserved(self):
        report = verify_repository(ROOT)
        self.assertEqual(report['product_entries'], 274)
        self.assertEqual(report['reviewed_additions'], 17)
        self.assertEqual(report['gitlinks'], 2)

    def test_preparation_sidecars_are_archived_not_product_inputs(self):
        self.assertEqual(len(MANIFEST['excluded_preparation_sidecars']), 3)
        for item in MANIFEST['excluded_preparation_sidecars']:
            self.assertFalse((ROOT / item['path']).exists())
            archived = ROOT / 'docs/migration/preparation-sidecars' / item['path'].lstrip('.')
            self.assertEqual(hashlib.sha256(archived.read_bytes()).hexdigest(), item['old_generated_sha256'])

    def test_shared_app_group_implementations_and_primitive_copies_do_not_drift(self):
        self.assertIn(source('LiveContainerSwiftUI/Utilities/V3SharedAppGroup.swift'), source('SideStoreSupport/SideStore.swift'))
        by_template = {}
        for component in COMPONENTS:
            key = component['historical_template']
            data = (ROOT / component['source']).read_bytes()
            value = data[component['byte_offset']:component['byte_offset'] + component['byte_length']]
            if key in by_template:
                self.assertEqual(value, by_template[key], key)
            by_template[key] = value

    def test_builder_notice_is_separate_and_unmodified(self):
        notice = source('LICENSES/sidestore-auto-refresh-MIT.txt')
        self.assertIn('Copyright (c) 2026 SideStore CoreDevice Self-Refresh contributors', notice)
        self.assertIn('GNU AFFERO GENERAL PUBLIC LICENSE', source('LICENSE'))
        self.assertIn('does not replace upstream licensing', source('RUNTIME_SOURCE_NOTICE.md'))


@unittest.skipUnless(CC, 'C compiler unavailable')
class NativeCExecutionTests(unittest.TestCase):
    def compile_and_run(self, text: str, cases=((),), flags=()) -> list[str]:
        with tempfile.TemporaryDirectory() as temporary:
            path, binary = Path(temporary) / 'probe.c', Path(temporary) / 'probe'
            path.write_text(text)
            compiled = subprocess.run([CC, '-std=c11', '-D_DEFAULT_SOURCE', '-Wall', '-Wextra',
                '-Wno-unused-parameter', '-I', str(ROOT / 'tests/fixtures'), str(path),
                '-o', str(binary), *flags], capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            self.assertEqual(compiled.stderr, '', compiled.stderr)
            results = []
            for args in cases:
                run = subprocess.run([str(binary), *args], capture_output=True, text=True, timeout=10)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                results.append(run.stdout)
            return results

    def test_app_group_identity_policy_executes_maintained_header(self):
        outputs = self.compile_and_run(source('tests/fixtures/app_group_identity.c'))
        self.assertIn('V3_APP_GROUP_IDENTITY_PASS', outputs[0])

    def test_bounded_cf_bundle_scan_with_guard_pages(self):
        utils = source('LiveContainer/utils.m')
        emulators = '\n'.join(block(utils, anchor) for anchor in (
            'uint64_t aarch64_get_tbnz_jump_address(', 'uint64_t aarch64_emulate_adrp(',
            'uint64_t aarch64_emulate_adrp_ldr('))
        harness = source('tests/fixtures/cf_bundle_scan.c').replace('__PRODUCTION_EMULATORS__', emulators)
        harness = harness.replace('__PRODUCTION_HELPER__', scan_helper())
        outputs = self.compile_and_run(harness, cases=[(case,) for case in ('none', 'first', 'last', 'target', 'positive')])
        self.assertIn('CF_BUNDLE_BOUNDED_SCAN_PASS', outputs[-1])

    def test_cf_bundle_platform_failure_propagation_from_maintained_adapter(self):
        text = source('LiveContainer/LCBootstrap.m')
        runtime = text[text.index('_Static_assert'):text.index('void overwriteMainNSBundle(')]
        runtime = runtime.replace('(__bridge void *)NSBundle.mainBundle._cfBundle', 'testGuestBundle')
        caller = text[text.index('    // Resolve the existing CF cache'):text.index('    // Overwrite executable info')]
        caller = caller.replace('return @"', 'return "')
        harness = source('tests/fixtures/cf_bundle_runtime.c').replace('__PRODUCTION_HELPER__', scan_helper())
        harness = harness.replace('__PRODUCTION_RUNTIME_WITH_NS_BUNDLE_DOUBLE__', runtime)
        harness = harness.replace('__PRODUCTION_CALLER_WITH_STRING_LITERALS__', caller)
        outputs = self.compile_and_run(harness)
        self.assertIn('CF_BUNDLE_FAILURE_PROPAGATION_PASS', outputs[0])

    def test_dead10cc_gate_concurrent_exactly_once_and_foreground_reset(self):
        text = source('LiveContainer/Tweaks/Dead10ccFix.m')
        gate = text.split('// DEAD10CC_TRANSITION_GATE_BEGIN\n', 1)[1].split('// DEAD10CC_TRANSITION_GATE_END', 1)[0]
        harness = '#include <assert.h>\n#include <pthread.h>\n#include <stdio.h>\n' + gate + r'''
static LCDead10ccTransitionGate gate;
static int winners;
static void *claim(void *unused) {
    for (int i = 0; i < 1000; i++) {
        if (LCDead10ccClaimBackgroundTransition(&gate)) __atomic_fetch_add(&winners, 1, __ATOMIC_SEQ_CST);
    }
    return 0;
}
int main(void) {
    for (int round = 0; round < 20; round++) {
        LCDead10ccResetBackgroundTransition(&gate);
        winners = 0;
        pthread_t threads[8];
        for (int i = 0; i < 8; i++) assert(pthread_create(&threads[i], 0, claim, 0) == 0);
        for (int i = 0; i < 8; i++) assert(pthread_join(threads[i], 0) == 0);
        assert(winners == 1);
        assert(!LCDead10ccClaimBackgroundTransition(&gate));
    }
    puts("DEAD10CC_GATE_PASS");
}
'''
        self.assertIn('DEAD10CC_GATE_PASS', self.compile_and_run(harness, flags=('-pthread',))[0])

    def test_guest_return_geometry_and_visibility_execute_both_copies(self):
        sources = ('LiveContainer/LCBootstrap.m', 'MultitaskSupport/AppSceneViewController.m')
        copies = [block(source(path), 'static double LCReturnAxisCenter(') + '\n' +
                  block(source(path), 'static int LCReturnShouldHide(') for path in sources]
        self.assertEqual(copies[0], copies[1])
        harness = '#include <math.h>\n#include <assert.h>\n#include <stdio.h>\n' + copies[0] + r'''
int main(void) {
    assert(LCReturnAxisCenter(10, 100, 0) == 40);
    assert(LCReturnAxisCenter(10, 100, 1) == 80);
    assert(LCReturnAxisCenter(10, 100, NAN) == 60);
    assert(LCReturnAxisCenter(10, 100, -10) == 40);
    assert(LCReturnAxisCenter(10, 100, 10) == 80);
    assert(LCReturnAxisCenter(10, 20, 0) == 20);
    assert(LCReturnAxisCenter(INFINITY, 100, 0) == 0);
    assert(LCReturnAxisCenter(0, -1, 0) == 0);
    for (int running = 0; running < 2; running++)
        for (int decorated = 0; decorated < 2; decorated++)
            for (int maximized = 0; maximized < 2; maximized++)
                assert(LCReturnShouldHide(running, decorated, maximized) == (!running || (decorated && !maximized)));
    puts("GUEST_RETURN_GEOMETRY_PASS");
}
'''
        self.assertIn('GUEST_RETURN_GEOMETRY_PASS', self.compile_and_run(harness, flags=('-lm',))[0])


class RuntimeBoundarySourceTests(unittest.TestCase):
    """Structural regression guards; not Swift, UIKit, XPC or device execution."""
    def test_refresh_plist_and_project_membership_are_preserved(self):
        info = plistlib.loads((ROOT / 'LiveContainer/Info.plist').read_bytes())
        self.assertEqual(info['LCRefreshContractVersion'], 2)
        self.assertEqual(len(info['BGTaskSchedulerPermittedIdentifiers']), 2)
        self.assertTrue({'fetch', 'processing'}.issubset(info['UIBackgroundModes']))
        project = source('LiveContainer.xcodeproj/project.pbxproj')
        self.assertIn('V3_LEGACY_SOURCES_UI_EXCLUDED_V1', project)
        self.assertIn('-weak_framework AlarmKit', project)
        self.assertNotIn('patch_livecontainer', project)

    def test_app_group_fail_closed_and_same_launch_key(self):
        shared = source('LiveContainerSwiftUI/Utilities/V3SharedAppGroup.swift')
        for marker in ('LC_RULE_EXPLICIT_WINS', 'LC_RULE_EXPLICIT_FAIL_CLOSED', 'LC_RULE_PACKAGED_FALLBACK_ONLY'):
            self.assertIn(marker, shared)
            self.assertIn(marker, source('LiveContainer/LCAppGroupIdentityRules.h'))
        self.assertIn('static let appGroupKey = "lcAppGroupID"', source('SideStoreSupport/SideStore.swift'))
        self.assertIn('LCValidatedAppGroupID(appInfo[@"lcAppGroupID"]', source('LiveProcess/main.m'))
        self.assertIn('forKey:@"lcAppGroupID"', source('MultitaskSupport/AppSceneViewController.m'))

    def test_result_bridge_remains_bounded_and_run_correlated(self):
        client = source('SideStoreSupport/SideStoreClient.swift')
        self.assertIn('guard data.count <= 262144', client)
        self.assertIn('CombinedVerification.sanitized(payload, runID: runID)', client)
        self.assertIn('guard let defaults = V3SharedAppGroup.sharedUserDefaults()', client)
        support = source('SideStoreSupport/SideStore.swift')
        self.assertIn('static let requestLimit = 16_384', support)
        self.assertIn('static let responseLimit = 4_194_304', support)
        self.assertIn('strictInt(request["version"]) == 1', support)
        self.assertIn('Set(request.keys).isSubset', support)
        self.assertIn('V3_XPC_PEER_ADMISSION_V1', source('SideStoreSupport/XPCServer.m'))
        self.assertNotIn('[newConnection resume];', source('SideStoreSupport/XPCServer.m'))

    def test_storage_and_guest_cleanup_order_remain_non_destructive(self):
        storage = source('LiveContainer/LCContainerStorage.h')
        self.assertNotIn('removeItem', storage)
        self.assertNotIn('moveItem', storage)
        cleanup = block(source('MultitaskSupport/AppSceneViewController.m'), '- (void)appTerminationCleanUp {')
        self.assertLess(cleanup.index('unregisterMultitaskContainerWithContainer'), cleanup.index('appSceneVCAppDidExit:'))
        self.assertIn('if (_isAppTerminationCleanUpCalled) return;', cleanup)

    def test_certificate_observation_uses_original_parser_and_public_facts(self):
        method = block(source('ZSign/zsign.mm'), '+ (NSDictionary<NSString *, NSString *> *)certificateFactsWithCert:')
        for marker in ('asset.InitSimple(', 'X509_digest(', 'EVP_sha256()', 'X509_free(', 'EVP_PKEY_free('):
            self.assertIn(marker, method)
        self.assertIn('return @{@"teamIdentifier": team, @"identitySHA256": fingerprint}', method)
        settings = source('LiveContainerSwiftUI/Views/Settings/LCSettingsView.swift')
        self.assertIn('guard V3CertificateImportOwnership.consume(requestID)', settings)
        self.assertIn('current["certificateIdentitySHA256"] as? String == fingerprint', settings)

    def test_bounded_temporary_diagnostics_and_signin_cleanup_are_preserved(self):
        support = source('SideStoreSupport/SideStore.swift')
        for marker in ('public static let maximumEvents = 64', 'public static let maximumBytes = 2048',
                       'public static let temporaryAnisetteTraceEnabled = true', 'fileRenameOk = "file.rename.ok"'):
            self.assertIn(marker, support)
        shell = source('LiveContainerSwiftUI/Views/V3UnifiedShell.swift')
        signin = shell[shell.index('struct V3SignInView: View {'):shell.index('enum V3CertificateCreatePresentation')]
        self.assertIn('.onDisappear {\n            auth.cancel()\n            auth.clearPreviousFailure()', signin)
        self.assertIn('DEBUG TEMPORARY failed step:', support)


class AppleToolchainTests(unittest.TestCase):
    @unittest.skipUnless(SWIFTC, 'Swift toolchain unavailable; no Swift compilation claim')
    def test_refresh_primitives_compile_and_execute_from_maintained_source(self):
        text = source('LiveContainerSwiftUI/App/AppDelegate.swift')
        declarations = '\n'.join(block(text, anchor) for anchor in (
            'struct LiveContainerRefreshTaskIdentifiers:', 'struct LiveContainerRefreshPolicy {',
            'final class LiveContainerRefreshCompletionGate:'))
        harness = 'import Foundation\n' + declarations + r'''
let gate = LiveContainerRefreshCompletionGate()
precondition(gate.claim())
precondition(!gate.claim())
precondition(LiveContainerRefreshPolicy.retryDelay(failureCount: 1) == 300)
precondition(LiveContainerRefreshPolicy.retryDelay(failureCount: 3) == 3600)
precondition(LiveContainerRefreshPolicy.retryDelay(failureCount: 4) == nil)
precondition(!LiveContainerRefreshPolicy.workIsDue(now: Date(), eligible: nil, retry: nil,
    pendingHandoff: true, retryExhausted: false, manual: true))
print("REFRESH_PRIMITIVES_PASS")
'''
        with tempfile.TemporaryDirectory() as temporary:
            path, binary = Path(temporary) / 'main.swift', Path(temporary) / 'probe'
            path.write_text(harness)
            compiled = subprocess.run([SWIFTC, str(path), '-o', str(binary)], capture_output=True, text=True, timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('REFRESH_PRIMITIVES_PASS', run.stdout)

    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('xcrun'), 'macOS/Xcode iPhoneOS SDK unavailable')
    def test_bootstrap_adapter_compiles_against_iphoneos_sdk(self):
        text = source('LiveContainer/LCBootstrap.m')
        adapter = text[text.index('#include <stdbool.h>'):text.index('void overwriteMainNSBundle(')]
        declarations = '''#import <Foundation/Foundation.h>
#import <CoreFoundation/CoreFoundation.h>
#include <mach/mach.h>
#include <stdint.h>
@interface NSBundle (CFBundleSDKProbe)
- (id)_cfBundle;
@end
uint64_t aarch64_get_tbnz_jump_address(uint32_t, uint64_t);
uint64_t aarch64_emulate_adrp_ldr(uint32_t, uint32_t, uint64_t);
'''
        sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'probe.m'
            path.write_text(declarations + adapter)
            compiled = subprocess.run(['xcrun', '--sdk', 'iphoneos', 'clang', '-target', 'arm64-apple-ios15.0',
                '-isysroot', sdk, '-fobjc-arc', '-fsyntax-only', '-Werror=implicit-function-declaration',
                '-Werror=shorten-64-to-32', str(path)], capture_output=True, text=True, timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)


if __name__ == '__main__':
    unittest.main()
