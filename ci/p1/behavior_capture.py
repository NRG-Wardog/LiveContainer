#!/usr/bin/env python3
"""Additional real P1 UI checks; no changes to the frozen baseline matrix."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import plistlib
import shutil
import sys

HERE = Path(__file__).resolve().parent
SOURCE_SHA256 = '3c40aab6667431d0ecb502d49a38416b9e76250ddf6e66dc1037e60d4594e0be'
METHODS = ['testP1FeedbackTimeout', 'testP1PromptReplacement', 'testP1DismissReopen',
           'testP1RecoveryNavigationDefault', 'testP1RecoveryNavigationLargest']
RECOVERY_CHECKS = ['recovery-all-four-branches-visible', 'recovery-content-above-navigation',
    'recovery-navigation-hittable', 'recovery-navigation-tap-opens-destination', 'recovery-navigation-back-restores-root',
    'recovery-no-banner-control']
CHECKS = {
    'feedback-timeout': ['copied-label', 'safe-clipboard', 'minimum-feedback-lifetime', 'feedback-timeout'],
    'prompt-replacement': ['copied-label', 'replacement-clears-feedback', 'replacement-clears-fields',
        'replacement-safe-clipboard', 'replacement-feedback-timeout', 'replacement-during-feedback',
        'replacement-minimum-lifetime', 'replacement-old-timer-overlap', 'normal-replacement-copy-hittable-and-tapped'],
    'dismiss-reopen': ['copied-label', 'dismiss-removes-prompt', 'reopen-clears-feedback', 'reopen-clears-fields',
        'reopen-safe-clipboard', 'reopen-feedback-timeout', 'dismiss-during-feedback',
        'reopen-minimum-lifetime', 'reopen-old-timer-overlap', 'normal-replacement-copy-hittable-and-tapped'],
    'recovery-navigation-default': RECOVERY_CHECKS,
    'recovery-navigation-largest': RECOVERY_CHECKS,
}


def require(value, message):
    if not value: raise ValueError(message)


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate evidence JSON key')
        result[key] = value
    return result


def write(path, value): path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def prepare(output, source, builder, command):
    renderer = load('p1_baseline_extract', builder / 'scripts/run_p0_signin_rendering.py')
    recovery = load('p1_recovery_extract', HERE / 'recovery_source.py')
    require(digest(source) == SOURCE_SHA256, 'actual P1 shell differs')
    build = output / 'build'
    sources = build / 'Sources'
    sources.mkdir(parents=True)
    extracted, hashes = renderer.extract_sources(source, builder / 'scripts/templates')
    original_app = (builder / 'tests/fixtures/p0_signin_app.swift').read_text()
    main = '@main @MainActor struct P0SignInApp: App'
    require(original_app.count(main) == 1, 'baseline fixture app marker changed')
    # Retain baseline service stubs only; run a separate P1 fixture entry point.
    original_app = original_app.replace(main, '@MainActor struct P0SignInApp: App')
    extracted['p0_signin_app.swift'] = original_app + '\n' + (HERE / 'behavior_observer.swift').read_text() + '\n' + (HERE / 'behavior_app.swift').read_text() + '\n' + recovery.generate_recovery_source(source.read_text())
    extracted['p0_signin_ui_tests.swift'] = (HERE / 'behavior_ui_tests.swift').read_text() + '\n' + (HERE / 'recovery_ui_tests.swift').read_text()
    for name, content in extracted.items():
        (sources / name).write_text(content)
        hashes[name] = digest(sources / name)
    project = build / 'P0SignIn.xcodeproj'
    shutil.copytree(builder / 'tests/fixtures/p0_signin_project', project)
    commit = command('git', '-C', str(builder), 'rev-parse', 'HEAD')
    info = plistlib.loads((project / 'Info.plist').read_bytes())
    info['LCBuilderCommit'] = commit
    (project / 'Info.plist').write_bytes(plistlib.dumps(info))
    # Separate app identity prevents confusing baseline and targeted fixture data.
    pbx = project / 'project.pbxproj'
    pbx.write_text(pbx.read_text().replace('org.sidestore.fixture.p0signin', 'org.sidestore.fixture.p1behavior'))
    for path in project.rglob('*'):
        if path.is_file(): hashes['project/' + str(path.relative_to(project))] = digest(path)
    shutil.copytree(sources, output / 'sources')
    shutil.copytree(project, output / 'project')
    fragments = recovery.recovery_fragments(source.read_text())
    identity = {'source_sha256': SOURCE_SHA256, 'sourceSHA256': hashes, 'baseline_builder_commit': commit,
        'fixture_files': {p.name: digest(p) for p in sorted(HERE.iterdir()) if p.suffix in ('.py', '.swift')},
        'recovery_fragments_sha256': {k: hashlib.sha256(v.encode()).hexdigest() for k, v in fragments.items()},
        'production_instrumentation': 'none; prompt declaration and recovery modifier copied verbatim',
        'scope': 'Exact production prompt and recovery modifier on synthetic lifecycle/status/navigation state; no full-app recovery backend claim'}
    write(output / 'source-identity.json', identity)
    command('xcodebuild', 'build-for-testing', '-project', str(project), '-scheme', 'P0SignIn',
        '-sdk', 'iphonesimulator', '-destination', 'generic/platform=iOS Simulator', '-derivedDataPath', str(build / 'DerivedData'),
        '-jobs', '2', 'CODE_SIGNING_ALLOWED=NO', 'CODE_SIGNING_REQUIRED=NO', timeout=600)
    candidates = list((build / 'DerivedData/Build/Products').glob('*.xctestrun'))
    require(len(candidates) == 1, 'ambiguous P1 test run')
    return candidates[0], renderer, identity


def rows(value):
    if isinstance(value, dict):
        if 'exportedFileName' in value: yield value
        for child in value.values(): yield from rows(child)
    elif isinstance(value, list):
        for child in value: yield from rows(child)


def frame(value):
    require(isinstance(value, list) and len(value) == 4 and all(type(v) in (float, int) and math.isfinite(v) for v in value)
            and value[2] > 0 and value[3] > 0, 'invalid recovery frame')
    return value


def verify_export(directory, summary, renderer):
    require(directory.is_dir() and not directory.is_symlink(), 'linked/missing UI export root')
    # macOS temporary paths can use /var while resolved files use /private/var.
    # Reject a linked export root before canonicalizing its parent aliases.
    directory = directory.resolve()
    require(summary.get('result') == 'Passed' and all(type(summary.get(k)) is int for k in
        ['passedTests', 'failedTests', 'skippedTests', 'totalTestCount']) and
        [summary['passedTests'], summary['failedTests'], summary['skippedTests'], summary['totalTestCount']] == [5, 0, 0, 5], 'P1 requires exactly five passed XCTest methods, zero skips')
    cases, manifests, artifacts, traces = [], [], {}, []
    for path in sorted(directory.rglob('*')):
        require(not path.is_symlink(), 'linked UI artifact')
        if not path.is_file(): continue
        data = path.read_bytes()
        artifacts[str(path.relative_to(directory))] = hashlib.sha256(data).hexdigest()
        try: item = json.loads(data, object_pairs_hook=unique_pairs)
        except (UnicodeDecodeError, ValueError): continue
        if path.name == 'manifest.json': manifests.append(item)
        if isinstance(item, dict) and item.get('schema') == 'p1-behavior-case-v1': cases.append(item)
        if isinstance(item, dict) and item.get('schema') == 'p1-passive-ax-trace-v1': traces.append(item)
    require(len(cases) == 5 and {c.get('case') for c in cases} == set(CHECKS), 'missing/duplicate P1 cases')
    trace_keys = {(name, phase) for name in ('feedback-timeout', 'prompt-replacement', 'dismiss-reopen')
        for phase in (['overlap'] if name == 'feedback-timeout' else ['overlap', 'normal-xctest-tap'])}
    require(len(traces) == 5 and {(t.get('scenario'), t.get('phase')) for t in traces} == trace_keys,
            'raw passive AX trace exports missing or duplicated')
    required = []
    for case in cases:
        name = case['case']
        require(case.get('passed') is True and type(case.get('testFailureCount')) is int and case['testFailureCount'] == 0 and
                len(case.get('checks', [])) == len(CHECKS[name]) and set(case['checks']) == set(CHECKS[name]), 'P1 case checks failed: ' + name)
        require(case.get('screenshot') == 'p1-' + name, 'wrong case screenshot')
        required.append(case['screenshot'])
        observations = case.get('observations', {})
        if name in ('feedback-timeout', 'prompt-replacement', 'dismiss-reopen'):
            load('p1_passive_trace', HERE / 'feedback_trace.py').verify_observations(observations, name)
            expected_traces = [observations['passiveTrace']]
            if name != 'feedback-timeout': expected_traces.append(observations['normalTapObservation']['passiveTrace'])
            require(all(t in traces for t in expected_traces), 'case differs from raw passive trace export')
        if name in ('feedback-timeout', 'prompt-replacement', 'dismiss-reopen'):
            minimum = observations.get('minimumLifetimeSeconds')
            sampled = observations.get('feedbackObservedSeconds')
            expiry = observations.get('observedExpirySeconds')
            require(all(type(t) in (float, int) and math.isfinite(t) for t in (minimum, sampled, expiry)) and
                    1.5 <= minimum <= sampled < 3 and sampled <= expiry < 5, 'own feedback lifetime not observed')
        if name in ('prompt-replacement', 'dismiss-reopen'):
            spacing = observations.get('copyEventSpacingSeconds')
            require(type(spacing) in (float, int) and 0.75 <= spacing < 2 and
                    spacing + observations['minimumLifetimeSeconds'] >= 2.25, 'new lifetime was not observed beyond the old timer deadline')
            delay = observations.get('transitionDelaySeconds')
            require(type(delay) in (float, int) and 0 < delay < 2, 'transition did not occur during production feedback lifetime')
        elif name == 'feedback-timeout':
            delay = observations.get('observedExpirySeconds')
            require(type(delay) in (float, int) and 0 <= delay < 5, 'feedback timeout unobserved')
        else:
            largest = name.endswith('-largest')
            require(observations.get('containerTopology') == 'TabView>NavigationView', 'wrong recovery container topology')
            control = observations.get('noBannerControl', {})
            require(control.get('kind') == 'none' and control.get('largestDynamicType') is largest and
                all(control.get(k) is True for k in ['recoveryBannerAbsent', 'navigationHittable',
                    'navigationOpenedDestination', 'navigationBackRestoredRoot']), 'missing no-banner navigation control')
            nav, bar, content, viewport = [frame(control.get(k)) for k in
                ['navigationFrame', 'navigationBarFrame', 'contentFrame', 'viewportFrame']]
            require(bar[1] + bar[3] <= content[1] + 1, 'no-banner content overlaps navigation')
            for value in (nav, bar, content):
                require(value[0] >= viewport[0] - 1 and value[1] >= viewport[1] - 1 and
                    value[0] + value[2] <= viewport[0] + viewport[2] + 1 and
                    value[1] + value[3] <= viewport[1] + viewport[3] + 1, 'no-banner control outside viewport')
            expected_control = 'p1-' + name + '-no-banner'
            require(control.get('screenshot') == expected_control, 'missing no-banner screenshot')
            required.append(expected_control)
            branches = observations.get('branches', [])
            require(observations.get('largestDynamicType') is largest and len(branches) == 4 and
                    {b.get('kind') for b in branches} == {'operation', 'direct', 'refresh', 'unreadable'}, 'incomplete recovery branch/size matrix')
            for branch in branches:
                require(branch.get('largestDynamicType') is largest and all(branch.get(k) is True for k in
                    ['navigationHittable', 'navigationOpenedDestination', 'navigationBackRestoredRoot']), 'recovery routing/hittability failed')
                banner, nav, bar, content, viewport = [frame(branch.get(k)) for k in
                    ['bannerContentFrame', 'navigationFrame', 'navigationBarFrame', 'contentFrame', 'viewportFrame']]
                require(banner[1] + banner[3] <= bar[1] + 1 and bar[1] + bar[3] <= content[1] + 1, 'recovery overlaps navigation/content')
                for value in (banner, nav):
                    require(value[0] >= viewport[0] - 1 and value[1] >= viewport[1] - 1 and
                            value[0] + value[2] <= viewport[0] + viewport[2] + 1 and
                            value[1] + value[3] <= viewport[1] + viewport[3] + 1, 'recovery outside viewport')
                expected = 'p1-' + name + '-' + branch['kind']
                require(branch.get('screenshot') == expected, 'missing recovery branch screenshot')
                required.append(expected)
    exported = list(rows(manifests)); seen = set(); screenshots = {}
    require(len(required) == len(set(required)) == 15, 'P1 screenshot matrix differs')
    for name in required:
        matches = [row for row in exported if row.get('attachmentName') == name or
            isinstance(row.get('suggestedHumanReadableName'), str) and
            (row['suggestedHumanReadableName'] in (name, name + '.png') or row['suggestedHumanReadableName'].startswith(name + '_'))]
        require(len(matches) == 1 and isinstance(matches[0].get('exportedFileName'), str), 'missing/duplicate screenshot: ' + name)
        path = (directory / matches[0]['exportedFileName']).resolve()
        require(path.is_relative_to(directory) and path.is_file() and path not in seen and
                renderer.valid_png(path.read_bytes()), 'invalid/reused screenshot: ' + name)
        seen.add(path); screenshots[name] = {'path': str(path.relative_to(directory)), 'sha256': digest(path)}
    return {'passed': True, 'cases': cases, 'artifact_sha256': artifacts, 'screenshots': screenshots,
            'test_ids': ['P0SignInUITests/' + m for m in METHODS], 'test_count': 5, 'skips': 0}


def run(builder, source, output):
    require(not output.exists(), 'fresh P1 UI evidence path required')
    output.mkdir(parents=True)
    rendering = load('p1_baseline_commands', builder / 'scripts/run_issue25_rendering.py')
    rendering.COMMAND_LOG = output / 'command-diagnostics.jsonl'
    result = {'passed': False, 'source_sha256': SOURCE_SHA256, 'device_classes': ['phone', 'tablet'],
        'case_ids': list(CHECKS), 'cases_per_device': 5, 'test_count': 0, 'reports': [],
        'physical_device_execution': False, 'backend_execution': False,
        'observation_mode': 'passive-production-accessibility-v1',
        'input_drivers': ['XCTest-tap', 'public-accessibilityActivate', 'XCTest-tap'],
        'recovery_topology': 'TabView>NavigationView', 'no_banner_control_required': True}
    try:
        xctestrun, renderer, identity = prepare(output, source, builder, rendering.command)
        devices = rendering.available_devices()
        require(len(devices) == 2 and {k for k, _, _ in devices} == {'phone', 'tablet'} and
                len({d for _, d, _ in devices}) == 2, 'exact phone/tablet matrix required')
        for kind, device, runtime in devices:
            state = json.loads(rendering.command('xcrun', 'simctl', 'list', 'devices', '--json'))
            booted = any(d['udid'] == device and d['state'] == 'Booted' for group in state['devices'].values() for d in group)
            try:
                if not booted: rendering.command('xcrun', 'simctl', 'boot', device)
                rendering.wait_for_simulator_boot(device)
                bundle = output / (kind + '.xcresult')
                exports = output / (kind + '-attachments')
                error = None
                try:
                    rendering.command('xcodebuild', 'test-without-building', '-xctestrun', str(xctestrun),
                        '-destination', 'id=' + device, '-resultBundlePath', str(bundle), '-parallel-testing-enabled', 'NO',
                        '-maximum-concurrent-test-simulator-destinations', '1', '-test-timeouts-enabled', 'YES',
                        '-default-test-execution-time-allowance', '240', '-maximum-test-execution-time-allowance', '240',
                        *['-only-testing:P0SignInUITests/P0SignInUITests/' + m for m in METHODS], timeout=1500)
                except Exception as exception: error = exception
                require(bundle.exists(), 'P1 XCTest produced no result bundle')
                rendering.command('xcrun', 'xcresulttool', 'export', 'attachments', '--path', str(bundle), '--output-path', str(exports), timeout=120)
                summary = json.loads(rendering.command('xcrun', 'xcresulttool', 'get', 'test-results', 'summary', '--path', str(bundle)))
                write(output / (kind + '-xctest-summary.json'), summary)
                report = verify_export(exports, summary, renderer)
                require(error is None, 'P1 XCTest command failed despite retained exports')
                report.update(device_class=kind, simulator_udid=device, runtime=runtime, source_sha256=SOURCE_SHA256, summary=summary)
                write(output / (kind + '-verification.json'), report)
                result['reports'].append(report)
            finally:
                if not booted: rendering.command('xcrun', 'simctl', 'shutdown', device)
        result.update(passed=True, test_count=10, screenshot_count=30,
            source_identity_sha256=digest(output / 'source-identity.json'))
    finally:
        write(output / 'behavior-verification.json', result)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--builder', required=True, type=Path); p.add_argument('--source', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    run(a.builder.resolve(), a.source.resolve(), a.output.resolve())
