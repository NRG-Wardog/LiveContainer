#!/usr/bin/env python3
"""Fresh P1 host/UI capture. P0 bytes remain immutable; no admission is granted."""
from __future__ import annotations
import argparse
import configparser
import importlib.util
import os
from pathlib import Path
import platform
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'p0'))
import native_gate as p0
from prepare_candidate_inventory import entries, full_sha, git, snapshot, require

BASIS = 'p1-ui-feedback-v1'
PARENT = '00546cec351adad1fa1cad5590da4f06e612db8f'
COMMIT = 'fbaafb939bfd3b7c08fdc8ff4b8d2aae43526ece'
TREE = '3d3efc14415db6d28ede216965f83fa5924e9e9c'
SHELL = 'LiveContainerSwiftUI/Views/V3UnifiedShell.swift'
SHELL_HASH = '3c40aab6667431d0ecb502d49a38416b9e76250ddf6e66dc1037e60d4594e0be'
BUILDER = '7e5062114f3ba8c1fe1990389ae9a008ce4d8c1f'
RENDER_BASELINE = {'commit': '7d8ae12905f8baa6e0ecc4dbdd3f25e2aa0e43fa',
    'tree': '6996e0f5b0ea0d98760f5749528b27992c150240',
    'path': 'scripts/templates/livecontainer_grid_app_cell.swift',
    'blob': 'd3d2fb912aad314c70cbd87cd717594dcd794d27',
    'sha256': 'b18f8483db39f908cb7de779c0bafb084d8507a45e4797404c65a93df6c89973'}
P0_REVIEW = '34d12b14364d4db4ed24ee80bf206332d383c27e958b497d6f5cd1c9d28cc6dc'
ADAPTERS = {'ci/p1/native_gate.py', 'ci/p1/tests/test_v3_signin_screen_cleanup.py',
            'ci/p1/tests/test_capture_gate.py', 'ci/p1/tests/test_behavior_capture.py',
            'ci/p1/behavior_capture.py', 'ci/p1/behavior_app.swift', 'ci/p1/behavior_ui_tests.swift',
            'ci/p1/recovery_source.py', 'ci/p1/recovery_app.swift', 'ci/p1/recovery_ui_tests.swift',
            'ci/p1/recovery_source_tests.py',
            'ci/p0/native_gate.py', 'ci/p0/source_primitives.py',
            'ci/p0/run_unittest_suite.py', 'prepare_candidate_inventory.py'}


def validate(raw, approved, host):
    require(p0.sha(raw) == p0.digest(approved), 'unreviewed input bytes')
    data = p0.parse(raw)
    require(set(data) == {'schema_version', 'source_basis', 'livecontainer', 'builder', 'render_baseline', 'submodules',
                         'adapter_files', 'expected_test_ids', 'inherited_p0_review_sha256'}, 'unexpected input schema')
    require(data['schema_version'] == 1 and data['source_basis'] == BASIS, 'wrong P1 basis')
    source = data['livecontainer']
    require(set(source) == {'repository', 'commit', 'tree', 'parent', 'changes'}, 'wrong source schema')
    require(source['repository'] == 'https://github.com/NRG-Wardog/LiveContainer.git' and
            (source['parent'], source['commit'], source['tree']) == (PARENT, COMMIT, TREE), 'wrong exact P1 source')
    require(set(source['changes']) == {SHELL} and source['changes'][SHELL]['after'] == {
        'mode': '100644', 'type': 'blob', 'git_object': '093a59955fff9252e18cc42a76c7f58055ef39d4',
        'sha256': SHELL_HASH}, 'P1 delta differs')
    require(data['builder'] == {'repository': 'https://github.com/NRG-Wardog/sidestore-auto-refresh.git',
                               'commit': BUILDER, 'tree': '70c4bc332a925dd608d37f39e8803a13451add33'}, 'unreviewed renderer')
    require(data['render_baseline'] == RENDER_BASELINE, 'unreviewed historical rendering baseline')
    require(data['inherited_p0_review_sha256'] == P0_REVIEW, 'unreviewed P0 inheritance')
    original = p0.parse(p0.ordinary(host, 'ci/p0/inputs-sidestore.json').read_bytes())
    require(data['submodules'] == {k: v for k, v in original['submodules'].items() if k.startswith('LiveContainer/')}, 'child pins differ from P0')
    require(set(data['adapter_files']) == ADAPTERS, 'exact adapter inventory required')
    for path, expected in data['adapter_files'].items():
        require(p0.sha(p0.ordinary(host, path).read_bytes()) == p0.digest(expected), 'altered adapter: ' + path)
    ids = data['expected_test_ids']
    require(isinstance(ids, list) and len(ids) == len(set(ids)) == 8 and all(
        x.startswith('test_v3_signin_screen_cleanup.SignInScreenCleanupTests.test_') for x in ids), 'exact cleanup8 IDs required')
    return data


def load_renderer(builder):
    spec = importlib.util.spec_from_file_location('reviewed_p0_signin_renderer', builder / 'scripts/run_p0_signin_rendering.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_render_baseline(builder, row):
    require(git(builder, 'rev-parse', row['commit'] + '^{commit}').decode().strip() == row['commit'] and
            git(builder, 'rev-parse', row['commit'] + '^{tree}').decode().strip() == row['tree'],
            'historical rendering baseline commit/tree differs')
    require(p0.primitives.entries(builder, row['commit']).get(row['path']) ==
            ('100644', 'blob', row['blob']), 'historical rendering grid blob differs')
    require(p0.sha(git(builder, 'cat-file', 'blob', row['blob'])) == row['sha256'],
            'historical rendering grid bytes differ')
    return dict(row)


class Capture:
    run = p0.Gate.run
    clone = p0.Gate.clone

    def __init__(self, data, raw, approved, host, work, evidence):
        self.data, self.raw, self.approved = data, raw, approved
        self.host, self.work, self.evidence = host, work, evidence
        self.sources, self.results = work / 'sources', work / 'results'
        self.live, self.builder = self.sources / 'LiveContainer', self.sources / 'builder'
        self.stage = 'initialization'
        self.state = {'source_basis': BASIS, 'status': 'FAILED_OR_INCOMPLETE', 'production_ready': False,
                      'ipa_built': False, 'ADI_executed': False, 'physical_device_execution': False,
                      'backend_execution': False, 'fresh_dependency_validation': False}

    def source_proof(self):
        proof = {}
        for name, root, row in [('LiveContainer', self.live, self.data['livecontainer']),
                                ('builder', self.builder, self.data['builder'])]:
            proof[name] = p0.primitives.verify_checkout(root, row['commit'], owner=name, require_full_history=True)
            require(proof[name]['tree'] == row['tree'], 'source tree drift')
            proof[name]['origin'] = p0.primitives.verify_origin(root, row['repository'], row['commit'])
        for path, row in self.data['submodules'].items():
            root = self.sources / path
            require(git(root, 'rev-parse', 'HEAD^{tree}').decode().strip() == row['tree'], 'child tree differs')
            proof[path] = p0.primitives.verify_origin(root, row['repository'], row['commit'])
        proof['render_baseline'] = verify_render_baseline(self.builder, self.data['render_baseline'])
        actual = snapshot(self.live, PARENT, COMMIT)
        require(actual['changes'] == self.data['livecontainer']['changes'] and actual['tree'] == TREE, 'source delta differs')
        require(git(self.live, 'rev-parse', 'HEAD^').decode().strip() == PARENT, 'P1 direct parent differs')
        require(p0.sha((self.live / SHELL).read_bytes()) == SHELL_HASH, 'actual compiler source differs')
        return proof

    def acquire(self):
        self.stage = 'fetch'
        self.clone('p1-livecontainer', self.data['livecontainer'], self.live)
        self.clone('reviewed-builder', self.data['builder'], self.builder)
        # The frozen audit workflow also fetches this non-branch historical input.
        # Keep the builder checkout/renderer unchanged and prove the consumed blob.
        self.run('fetch-render-baseline', ['git', '-C', self.builder, 'fetch', '--no-tags',
            '--no-recurse-submodules', 'origin', self.data['render_baseline']['commit']])
        links = {path: row['git_object'] for path, row in entries(self.live, COMMIT).items() if row['type'] == 'commit'}
        require(set(links) == {Path(k).name for k in self.data['submodules']}, 'unreviewed child dependency')
        modules = configparser.ConfigParser(interpolation=None)
        modules.read(self.live / '.gitmodules')
        for path, row in self.data['submodules'].items():
            relative = path.split('/', 1)[1]
            declared = [dict(modules[s]) for s in modules.sections() if modules[s].get('path') == relative]
            require(declared == [{'path': relative, 'url': row['declared_repository']}] and
                    links[relative] == row['commit'], 'declared child source differs')
            self.clone('child-' + relative.lower(), row, self.live / relative)
        p0.dump(self.evidence / 'provenance/source-before.json', self.source_proof())
        root = self.builder / 'migration/p0-native-basis-v1'
        review = p0.ordinary(root, 'reviewed-approval.json').read_bytes()
        require(p0.sha(review) == P0_REVIEW, 'inherited approval differs')
        for path, expected in p0.parse(review)['files'].items():
            require(p0.sha(p0.ordinary(root, path).read_bytes()) == expected, 'inherited P0 receipt bytes differ: ' + path)
        shutil.copytree(root, self.evidence / 'inherited-p0')
        self.state['inherited_p0_review_sha256'] = P0_REVIEW

    def cleanup_tests(self):
        self.stage = 'p1-source-tests'
        expected = self.results / 'expected-test-ids.json'
        p0.dump(expected, self.data['expected_test_ids'])
        output = self.run('p1-cleanup8', ['/usr/bin/sandbox-exec', '-p', '(version 1) (allow default) (deny network*)',
            sys.executable, '-B', self.host / 'ci/p0/run_unittest_suite.py', self.host / 'ci/p1/tests', expected,
            'test_v3_signin_screen_cleanup'], env=dict(os.environ, V3_P1_REQUIRED='1',
                MAINTAINED_LIVE_CONTAINER_TEST_SOURCE=str(self.live), PYTHONDONTWRITEBYTECODE='1'))
        report = p0.parse(output.strip().splitlines()[-1])
        require(report['tests'] == 8 and set(report['test_ids']) == set(self.data['expected_test_ids']) and
                all(report[k] == 0 for k in ['failures', 'errors', 'skips', 'expected_failures', 'unexpected_successes']), 'cleanup suite incomplete')
        self.state['native_suites'] = [report]
        p0.dump(self.evidence / 'provenance/p1-cleanup8.json', report)

    def native_build(self):
        self.stage = 'unsigned-iphoneos-build'
        derived = self.results / 'livecontainer-derived'
        self.run('livecontainer-build', ['xcodebuild', '-project', self.live / 'LiveContainer.xcodeproj',
            '-scheme', 'LiveContainer', '-derivedDataPath', derived, '-sdk', 'iphoneos', '-configuration', 'Release',
            '-destination', 'generic/platform=iOS', 'CODE_SIGNING_ALLOWED=NO', 'CODE_SIGNING_REQUIRED=NO',
            'CODE_SIGN_IDENTITY=', 'DEVELOPMENT_TEAM=', 'build'])
        app = derived / 'Build/Products/Release-iphoneos/LiveContainer.app'
        require(app.is_dir() and (app / 'LiveContainer').is_file(), 'fresh unsigned host product missing')
        products = {str(p.relative_to(app)): p0.sha(p.read_bytes()) for p in sorted(app.rglob('*')) if p.is_file() and not p.is_symlink()}
        p0.dump(self.evidence / 'provenance/unsigned-products.json', {'LiveContainer': products})
        self.state['native_builds'] = {'LiveContainer': 'PASS_UNSIGNED_IPHONEOS'}

    def rendering(self):
        self.stage = 'actual-p1-ui-matrix'
        output = self.results / 'layout-evidence'
        self.run('p1-layout-rendering', [sys.executable, '-B', self.builder / 'scripts/run_issue25_rendering.py',
            '--livecontainer', self.live, '--v3-source', self.live / SHELL, '--require-p0-signin', '--output', output])
        meta = p0.parse((output / 'rendering-verification.json').read_bytes())
        require(meta['passed'] is True and meta['reportCount'] == 14 and meta['productLine'] == 'v3' and
                meta['builderCommit'] == BUILDER and meta['ciRun'] == os.environ['GITHUB_RUN_ID'], 'legacy render matrix or identity incomplete')
        sign = meta['p0SignIn']
        require(sign['required'] is True and sign['passed'] is True and sign['reportCount'] == 2 and
                sign['caseCount'] == 8 and sign['preparationFailure'] is None and
                sign['sourceSHA256']['generated-shell'] == SHELL_HASH, 'sign-in source/matrix differs')
        renderer = load_renderer(self.builder)
        reports = []
        for kind in ('phone', 'tablet'):
            root = output / 'p0-signin'
            summary = p0.parse((root / (kind + '-xctest-summary.json')).read_bytes())
            verified = renderer.verify_export(root / (kind + '-attachments'), summary)
            require(verified['passed'] is True and verified['failures'] == [] and verified['reportCount'] == 4, 'raw XCTest evidence invalid: ' + kind)
            report = p0.parse((root / (kind + '-verification.json')).read_bytes())
            require(report['sourceSHA256']['generated-shell'] == SHELL_HASH and report['deviceClass'] == kind and
                    all(report[key] == verified[key] for key in verified), 'retained UI report differs: ' + kind)
            require(sum(len(case['screenshots']) for case in verified['cases']) == 12, 'screenshot matrix incomplete')
            reports.append(report)
        self.state['ui_validation'] = {'passed': True, 'legacy_report_count': 14, 'device_classes': ['phone', 'tablet'],
            'case_count': 8, 'screenshot_count': 24, 'source_sha256': SHELL_HASH,
            'simulator_runtimes': meta['simulatorRuntimes'], 'reports': reports,
            'scope': 'Frozen baseline exact-source credentials regression matrix; targeted P1 behavior is recorded separately.'}
        p0.dump(self.evidence / 'provenance/ui-validation.json', self.state['ui_validation'])

    def targeted_behavior(self):
        self.stage = 'targeted-p1-behavior'
        self.run('p1-recovery-extraction-tests', [sys.executable, '-B', self.host / 'ci/p1/recovery_source_tests.py', self.live / SHELL])
        output = self.results / 'p1-behavior'
        self.run('p1-targeted-behavior', [sys.executable, '-B', self.host / 'ci/p1/behavior_capture.py',
            '--builder', self.builder, '--source', self.live / SHELL, '--output', output])
        spec = importlib.util.spec_from_file_location('p1_behavior_verifier', self.host / 'ci/p1/behavior_capture.py')
        behavior = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(behavior)
        result = p0.parse((output / 'behavior-verification.json').read_bytes())
        require(result['passed'] is True and result['source_sha256'] == SHELL_HASH and
            result['device_classes'] == ['phone', 'tablet'] and result['test_count'] == 10 and
            result['cases_per_device'] == 5 and result['case_ids'] == list(behavior.CHECKS) and
            result['screenshot_count'] == 26 and len(result['reports']) == 2, 'targeted P1 matrix incomplete')
        renderer = load_renderer(self.builder)
        require({r['device_class'] for r in result['reports']} == {'phone', 'tablet'}, 'targeted P1 device identity differs')
        for report in result['reports']:
            kind = report['device_class']
            summary = p0.parse((output / (kind + '-xctest-summary.json')).read_bytes())
            verified = behavior.verify_export(output / (kind + '-attachments'), summary, renderer)
            require(report['source_sha256'] == SHELL_HASH and report['summary'] == summary and
                all(report[k] == verified[k] for k in verified), 'targeted P1 raw export differs')
        identity_path = output / 'source-identity.json'
        identity = p0.parse(identity_path.read_bytes())
        require(result['source_identity_sha256'] == p0.sha(identity_path.read_bytes()) and
            identity['source_sha256'] == SHELL_HASH and identity['sourceSHA256']['generated-shell'] == SHELL_HASH,
            'targeted P1 production source differs')
        self.state['behavior_validation'] = result
        p0.dump(self.evidence / 'provenance/behavior-validation.json', result)

    def preserve_rendering(self):
        total = 0
        for name in ('layout-evidence', 'p1-behavior'):
            source = self.results / name
            if not source.exists(): continue
            destination = self.evidence / name
            for root, directories, files in os.walk(source, followlinks=False):
                require(all(not (Path(root) / d).is_symlink() for d in directories), 'linked render evidence directory')
                directories[:] = [d for d in directories if d not in ('p0-build', 'build') and not d.endswith(('.app', '.xcresult'))]
                for filename in files:
                    path = Path(root) / filename
                    require(not path.is_symlink(), 'linked render evidence')
                    if path.suffix not in {'.json', '.jsonl', '.png', '.txt', '.swift', '.plist', '.pbxproj', '.xcscheme'}: continue
                    size = path.stat().st_size
                    total += size
                    require(size <= 64 * 1024**2 and total <= 512 * 1024**2, 'render evidence exceeds capture bound')
                    target = destination / path.relative_to(source)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)

    def execute(self):
        require(platform.system() == 'Darwin', 'fresh native/UI capture requires macOS; local static tests are not native evidence')
        require(not self.work.exists() and not self.evidence.exists(), 'fresh work/evidence paths required')
        self.sources.mkdir(parents=True); self.results.mkdir()
        (self.evidence / 'logs').mkdir(parents=True); (self.evidence / 'provenance').mkdir()
        repo, commit = os.environ.get('GITHUB_REPOSITORY'), os.environ.get('GITHUB_SHA')
        run, attempt = os.environ.get('GITHUB_RUN_ID', ''), os.environ.get('GITHUB_RUN_ATTEMPT', '')
        require(repo == 'NRG-Wardog/LiveContainer' and os.environ.get('GITHUB_REF') == 'refs/heads/validation/p1-native-basis' and
                run.isdigit() and attempt.isdigit() and int(attempt) > 0, 'actual dedicated GitHub run required')
        full_sha(commit)
        require(git(self.host, 'rev-parse', 'HEAD').decode().strip() == commit, 'validation host differs from run')
        self.state.update(approved_inputs_sha256=self.approved, tested_owners={'LiveContainer': {'commit': COMMIT, 'tree': TREE}},
            run={'url': 'https://github.com/' + repo + '/actions/runs/' + run, 'attempt': int(attempt),
                 'host_commit': commit, 'host_tree': git(self.host, 'rev-parse', 'HEAD^{tree}').decode().strip()})
        try:
            self.stage = 'toolchain'
            require('Xcode 26.4.1' in self.run('xcode-version', ['xcodebuild', '-version']), 'unreviewed Xcode')
            self.run('swift-version', ['swift', '--version'])
            self.acquire(); self.cleanup_tests(); self.native_build(); self.rendering(); self.targeted_behavior()
            p0.dump(self.evidence / 'provenance/source-after.json', self.source_proof())
            self.stage = 'captured'; self.state['status'] = 'CAPTURED_FOR_REVIEW'
        finally:
            try:
                self.preserve_rendering()
            except Exception:
                self.state['status'] = 'FAILED_OR_INCOMPLETE'
                self.stage = 'evidence-preservation-failed'
                raise
            finally:
                self.state['last_stage'] = self.stage
                p0.dump(self.evidence / 'provenance/result.json', self.state)
                (self.evidence / 'provenance/approved-inputs.json').write_bytes(self.raw)
                p0.dump(self.evidence / 'evidence-index.json', {str(p.relative_to(self.evidence)): p0.sha(p.read_bytes())
                    for p in sorted(self.evidence.rglob('*')) if p.is_file() and p.name != 'evidence-index.json'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--approved-inputs-sha256', required=True)
    parser.add_argument('--host-root', type=Path, default=HERE.parents[1])
    parser.add_argument('--work', type=Path); parser.add_argument('--evidence', type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    raw = args.inputs.read_bytes()
    data = validate(raw, args.approved_inputs_sha256, args.host_root)
    if not args.execute:
        print('{"status":"SEALED_INPUTS_VALID","native_execution":false,"production_ready":false}')
        return
    require(args.work is not None and args.evidence is not None, 'execution paths required')
    Capture(data, raw, args.approved_inputs_sha256, args.host_root.resolve(), args.work.resolve(), args.evidence.resolve()).execute()


if __name__ == '__main__':
    main()
