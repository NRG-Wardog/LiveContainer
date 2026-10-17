#!/usr/bin/env python3
"""Bounded diagnostic pixel/topology collection. Never grants P1 admission."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
SOURCE = {'repository': 'https://github.com/NRG-Wardog/LiveContainer.git',
          'commit': 'fbaafb939bfd3b7c08fdc8ff4b8d2aae43526ece',
          'tree': '3d3efc14415db6d28ede216965f83fa5924e9e9c'}
BUILDER = {'repository': 'https://github.com/NRG-Wardog/sidestore-auto-refresh.git',
           'commit': '7e5062114f3ba8c1fe1990389ae9a008ce4d8c1f',
           'tree': '70c4bc332a925dd608d37f39e8803a13451add33'}
SHELL = 'LiveContainerSwiftUI/Views/V3UnifiedShell.swift'
SOURCE_SHA = '3c40aab6667431d0ecb502d49a38416b9e76250ddf6e66dc1037e60d4594e0be'
APP_ID = 'org.sidestore.fixture.p1diagnostic'
SCENARIOS = {'timeout', 'replacement', 'dismissal'}
METHODS = ['testProbeTimeoutPixels', 'testProbeReplacementPixels', 'testProbeDismissalPixels', 'testProbeRecoveryTopology']
ADAPTERS = {'ci/p1/probe/' + f for f in ['README.md', 'app.swift', 'capture.py', 'recovery.swift', 'test_probe.py', 'ui_tests.swift', 'vision.swift']} | {'ci/p1/recovery_source.py'}


def require(value, message):
    if not value: raise ValueError(message)


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path, value): Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')
def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key'); result[key] = value
    return result


def parse(path): return json.loads(Path(path).read_text(), object_pairs_hook=unique)
def number(value): return type(value) in (int, float) and math.isfinite(value)
def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result); return result


def ordinary(root, relative):
    require(isinstance(relative, str) and relative and not Path(relative).is_absolute() and
            '..' not in Path(relative).parts, 'unsafe input path')
    path = root / relative
    require(path.is_file(), 'missing input ' + relative)
    current = path
    while current != root:
        require(not current.is_symlink(), 'linked input'); current = current.parent
    return path


def validate(host, inputs, approved):
    require(host.is_dir() and not host.is_symlink(), 'linked/missing host root')
    host = host.resolve()
    require(re.fullmatch('[0-9a-f]{64}', approved or '') and sha(inputs) == approved, 'unreviewed probe input bytes')
    data = parse(inputs)
    require(set(data) == {'schema', 'scope', 'livecontainer', 'builder', 'source_sha256', 'adapter_files'}, 'unexpected probe input schema')
    require(data['schema'] == 'p1-diagnostic-inputs-v1' and data['scope'] == 'diagnostic-only-no-admission', 'wrong diagnostic scope')
    require(data['livecontainer'] == SOURCE and data['builder'] == BUILDER and data['source_sha256'] == SOURCE_SHA, 'wrong exact source pins')
    require(set(data['adapter_files']) == ADAPTERS, 'wrong adapter inventory')
    for name, expected in data['adapter_files'].items():
        require(sha(ordinary(host, name)) == expected, 'altered diagnostic adapter: ' + name)
    return data


class Commands:
    def __init__(self, output): self.output, self.count = output, 0
    def __call__(self, *args, timeout=300, allow_failure=False):
        args = list(map(str, args)); self.count += 1
        name = f'command-{self.count:03d}'
        started = time.monotonic()
        print('Running:', ' '.join(args), flush=True)
        # Frozen command runner handles timeout for the entire process group.
        result = None; error = None
        try:
            result = self.renderer.capture(*args, timeout=timeout)
        except subprocess.CalledProcessError as exc:
            result = exc.output; error = exc
            (self.output / (name + '.stderr')).write_bytes(exc.stderr or b'')
        except Exception as exc: error = exc
        if result is not None: (self.output / (name + '.stdout')).write_bytes(result)
        with (self.output / 'commands.jsonl').open('a') as stream:
            stream.write(json.dumps({'argv': args, 'seconds': time.monotonic() - started,
                'stdout': name + '.stdout' if result is not None else None,
                'error': str(error) if error else None, 'allowed_failure': allow_failure}) + '\n')
        if error and not allow_failure: raise error
        return (result or b'').decode(errors='replace').strip()


def bootstrap_commands(logs):
    def command(*args, timeout=300):
        require(number(timeout) and 0 < timeout <= 300, 'unbounded bootstrap command')
        result = subprocess.run(list(map(str, args)), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=timeout)
        with (logs / 'bootstrap.log').open('ab') as stream:
            stream.write((' '.join(map(str, args)) + '\n').encode() + result.stdout)
        require(result.returncode == 0, 'source acquisition failed')
        return result.stdout.decode().strip()
    return command


def checkout_proof(root, row, command):
    require(command('git', '-C', root, 'rev-parse', 'HEAD') == row['commit'], 'checkout commit differs')
    require(command('git', '-C', root, 'rev-parse', 'HEAD^{tree}') == row['tree'], 'checkout tree differs')
    require(not command('git', '-C', root, 'status', '--porcelain', '--untracked-files=all'), 'dirty source checkout')
    require(command('git', '-C', root, 'remote', 'get-url', 'origin') == row['repository'], 'source origin differs')
    return dict(row)


def acquire(root, row, command):
    require(not root.exists(), 'fresh source directory required')
    command('git', 'init', root); command('git', '-C', root, 'remote', 'add', 'origin', row['repository'])
    command('git', '-C', root, 'fetch', '--no-tags', '--depth=1', '--no-recurse-submodules', 'origin', row['commit'], timeout=300)
    command('git', '-C', root, 'checkout', '--detach', 'FETCH_HEAD')
    return checkout_proof(root, row, command)


def prepare(source, builder, build, output):
    require(sha(source) == SOURCE_SHA, 'actual P1 shell differs')
    renderer = module('probe_signin_renderer', builder / 'scripts/run_p0_signin_rendering.py')
    recovery = module('probe_recovery_fragments', HERE.parent / 'recovery_source.py')
    sources, hashes = renderer.extract_sources(source, builder / 'scripts/templates')
    app = (builder / 'tests/fixtures/p0_signin_app.swift').read_text()
    marker = '@main @MainActor struct P0SignInApp: App'
    require(app.count(marker) == 1, 'baseline fixture entry point changed')
    app = app.replace(marker, '@MainActor struct P0SignInApp: App')
    fragments = recovery.recovery_fragments(source.read_text())
    template = (HERE / 'recovery.swift').read_text()
    for marker in ['__P1_RECOVERY_DECLARATIONS__', '__P1_RECOVERY_MODIFIER__']:
        require(template.count(marker) == 1, 'recovery marker missing/ambiguous')
    template = template.replace('__P1_RECOVERY_DECLARATIONS__', '\n'.join(fragments[s.split()[-1]] for s in recovery.DECLARATIONS))
    template = template.replace('__P1_RECOVERY_MODIFIER__', fragments['recovery-modifier'].rstrip('\n'))
    sources['p0_signin_app.swift'] = app + '\n' + (HERE / 'app.swift').read_text() + '\n' + template
    sources['p0_signin_ui_tests.swift'] = (HERE / 'ui_tests.swift').read_text()
    target = build / 'Sources'; target.mkdir(parents=True)
    for name, text in sources.items():
        (target / name).write_text(text); hashes[name] = sha(target / name)
    project = build / 'P0SignIn.xcodeproj'
    shutil.copytree(builder / 'tests/fixtures/p0_signin_project', project)
    info = plistlib.loads((project / 'Info.plist').read_bytes()); info['LCBuilderCommit'] = BUILDER['commit']
    (project / 'Info.plist').write_bytes(plistlib.dumps(info))
    pbx = project / 'project.pbxproj'
    pbx.write_text(pbx.read_text().replace('org.sidestore.fixture.p0signin', APP_ID))
    shutil.copytree(target, output / 'sources'); shutil.copytree(project, output / 'project')
    identity = {'source_sha256': SOURCE_SHA, 'source_commit': SOURCE['commit'], 'source_tree': SOURCE['tree'],
        'baseline_builder': BUILDER, 'sourceSHA256': hashes,
        'recovery_fragments_sha256': {k: hashlib.sha256(v.encode()).hexdigest() for k, v in fragments.items()},
        'project_sha256': {str(p.relative_to(project)): sha(p) for p in project.rglob('*') if p.is_file()},
        'production_instrumentation': 'none; prompt declaration and full recovery modifier copied verbatim',
        'scope': 'diagnostic-only synthetic lifecycle and recovery status; not full application/backend'}
    write(output / 'source-identity.json', identity)
    return project, renderer


def inventory(root):
    require(root.is_dir() and not root.is_symlink(), 'linked/missing raw root')
    result = {}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'symlink in raw capture')
        if path.is_file(): result[str(path.relative_to(root))] = sha(path)
    return result


def inspect_pixels(root, valid_png):
    # Resolve parent aliases only after rejecting a symlinked root.
    inventory(root); root = root.resolve()
    require({p.name for p in root.iterdir()} == SCENARIOS and all(p.is_dir() for p in root.iterdir()), 'exact three scenario folders required')
    manifest = []; reports = {}; complete = True
    for scenario in sorted(SCENARIOS):
        folder = root / scenario; trace = parse(folder / 'trace.json')
        require(trace.get('schema') == 'p1-pixel-probe-v1' and trace.get('scenario') == scenario and
                trace.get('clock') == 'ProcessInfo.systemUptime' and trace.get('admissionEligible') is False,
                'wrong raw trace identity')
        require(type(trace.get('captureFinished')) is bool and number(trace.get('captureStartUptime')) and
                number(trace.get('checkpointUptime')) and trace['captureStartUptime'] <= trace['checkpointUptime'], 'invalid capture clocks')
        require(trace.get('requestedIntervalSeconds') == 0.1 and trace.get('maximumFrames') == 120 and trace.get('maximumSeconds') == 12, 'changed capture bounds')
        frames = trace.get('frames'); require(isinstance(frames, list) and 0 <= len(frames) <= 120, 'unbounded frames')
        files = []; durations = []; costs = []; gaps = []; last = None
        for index, frame in enumerate(frames):
            name = frame.get('file'); require(name == f'frame-{index:03d}.png', 'invalid/duplicate/nonsequential frame path')
            start, before, after, end = [frame.get(k) for k in ['tickStartUptime', 'beforeUptime', 'afterUptime', 'tickEndUptime']]
            require(all(number(v) for v in [start, before, after, end]) and
                trace['captureStartUptime'] <= start <= before <= after <= end <= trace['checkpointUptime'], 'invalid capture brackets')
            require(last is None or start >= last, 'non-monotonic captures')
            if last is not None: gaps.append(start - last)
            last = end; durations.append(after - before); costs.append(end - start)
            require(type(frame.get('drawHierarchyReturned')) is bool and
                all(number(frame.get(k)) and frame[k] > 0 for k in ['widthPoints', 'heightPoints', 'scale']), 'invalid render metadata')
            require(valid_png((folder / name).read_bytes()), 'invalid PNG')
            files.append(name); manifest.append(str(folder / name))
        require({p.name for p in folder.iterdir()} == {'trace.json', *files} and len(files) == len(set(files)), 'stale/missing/unindexed raw frame')
        events = trace.get('events'); require(isinstance(events, list) and len(events) <= 4, 'unbounded/missing clipboard events')
        previous = trace['captureStartUptime']; changes = set()
        for ordinal, event in enumerate(events, 1):
            value = event.get('uptime')
            require(event.get('ordinal') == ordinal and number(value) and previous <= value <= trace['checkpointUptime'], 'invalid clipboard ordinal/clock')
            require(type(event.get('changeCount')) is int and event['changeCount'] not in changes, 'clipboard change counter reused')
            changes.add(event['changeCount']); previous = value
            require(type(event.get('generation')) is int and type(event.get('shown')) is bool and
                isinstance(event.get('payload'), str) and isinstance(event.get('expectedPayload'), str) and
                type(event.get('clipboardExact')) is bool and event['clipboardExact'] == (event['payload'] == event['expectedPayload']), 'invalid clipboard payload evidence')
        journal_costs = []; previous = trace['captureStartUptime']
        for journal in trace.get('priorJournalWrites', []):
            before, after = journal.get('beforeUptime'), journal.get('afterUptime')
            require(number(before) and number(after) and previous <= before <= after <= trace['checkpointUptime'], 'invalid journal brackets')
            previous = after; journal_costs.append(after - before)
        previous = trace['captureStartUptime']
        for transition in trace.get('transitions', []):
            at = transition.get('uptime')
            require(number(at) and previous <= at <= trace['checkpointUptime'] and transition.get('kind') in ['replace', 'dismiss', 'reopen'], 'invalid transition')
            previous = at
        errors = trace.get('errors'); require(isinstance(errors, list) and all(isinstance(e, str) for e in errors), 'missing capture errors')
        finished = trace['captureFinished'] and bool(frames) and bool(events) and all(e['clipboardExact'] for e in events) and not errors and all(f['drawHierarchyReturned'] for f in frames)
        complete &= finished
        reports[scenario] = {'capture_finished': trace['captureFinished'], 'collection_complete': finished,
            'frames': len(frames), 'events': len(events), 'incomplete_render_frames': sum(not f['drawHierarchyReturned'] for f in frames),
            'render_total_seconds': sum(durations), 'render_max_seconds': max(durations, default=0),
            'capture_png_total_seconds': sum(costs), 'capture_png_max_seconds': max(costs, default=0),
            'intercapture_gap_max_seconds': max(gaps, default=0), 'prior_journal_total_seconds': sum(journal_costs),
            'prior_journal_max_seconds': max(journal_costs, default=0), 'timing_capability_proven': False,
            'journal_cost_limit': 'final atomic write is outside capture window; event journaling may delay feedback scheduling'}
    return manifest, reports, complete


def attachment_rows(value):
    if isinstance(value, dict):
        if 'exportedFileName' in value: yield value
        for child in value.values(): yield from attachment_rows(child)
    elif isinstance(value, list):
        for child in value: yield from attachment_rows(child)


def inspect_exports(root, summary, valid_png):
    files = inventory(root); root = root.resolve()
    expected = {f'probe-{s}-{phase}' for s in SCENARIOS for phase in ['before', 'after']} | {
        f'probe-recovery-{shape}-{size}-{kind}' for shape in ['production-list', 'synthetic-vstack']
        for size in ['default', 'largest'] for kind in ['none', 'operation']}
    manifests, completed, topology = [], [], []
    for name in files:
        try: value = parse(root / name)
        except (UnicodeDecodeError, ValueError): continue
        if Path(name).name == 'manifest.json': manifests.append(value)
        if isinstance(value, dict) and value.get('schema') == 'p1-probe-completion-v1': completed.append(value)
        if isinstance(value, dict) and value.get('schema') == 'p1-probe-topology-v1': topology.append(value)
    rows = list(attachment_rows(manifests)); screenshots = {}; used = set()
    for name in sorted(expected):
        matches = [row for row in rows if row.get('attachmentName') == name or
            isinstance(row.get('suggestedHumanReadableName'), str) and
            (row['suggestedHumanReadableName'] in [name, name + '.png'] or row['suggestedHumanReadableName'].startswith(name + '_'))]
        require(len(matches) == 1, 'missing/duplicate independent screenshot: ' + name)
        file = matches[0].get('exportedFileName')
        require(isinstance(file, str) and file in files and file not in used and not Path(file).is_absolute() and
                '..' not in Path(file).parts and valid_png((root / file).read_bytes()), 'invalid/reused independent screenshot')
        used.add(file); screenshots[name] = {'path': file, 'sha256': files[file]}
    require(len(completed) == 3 and {v.get('scenario') for v in completed} == SCENARIOS, 'missing/duplicate pixel completion reports')
    require(all(v.get('admissionEligible') is False for v in completed + topology), 'admission-shaped diagnostic report')
    keys = {(v.get('shape'), v.get('largestDynamicType'), v.get('kind')) for v in topology}
    require(len(topology) == 8 and keys == {(shape, largest, kind) for shape in ['production-list', 'synthetic-vstack']
        for largest in [False, True] for kind in ['none', 'operation']}, 'incomplete topology matrix')
    counts = ['passedTests', 'failedTests', 'skippedTests', 'totalTestCount']
    success = summary.get('result') == 'Passed' and all(type(summary.get(k)) is int for k in counts) and \
        [summary[k] for k in counts] == [4, 0, 0, 4] and all(v.get('waitCompleted') is True and
        v.get('status', {}).get('label') == 'finished' for v in completed)
    return {'collection_complete': success, 'screenshots': screenshots,
            'topology': topology, 'completed': completed, 'artifact_sha256': files,
            'exported_video_files': [f for f in files if Path(f).suffix.lower() in ['.mp4', '.mov']]}


def execute(host, work, output, inputs, approved):
    require(not output.exists() and not work.exists(), 'fresh work/evidence paths required')
    output.mkdir(parents=True); work.mkdir(parents=True)
    result = {'schema': 'p1-diagnostic-collection-v1', 'scope': 'diagnostic-only-no-admission',
        'admission_eligible': False, 'production_ready': False, 'full_native_lane_executed': False,
        'pixel_fidelity_proven': False, 'timing_capability_proven': False, 'diagnostic_collection_complete': False,
        'source_sha256': SOURCE_SHA, 'approved_inputs_sha256': approved, 'reports': [], 'errors': [],
        'github': {k: os.environ.get(k) for k in ['GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_REPOSITORY']}}
    command = None
    try:
        # Bootstrap git acquisition has bounded subprocess calls and retained output;
        # subsequent build/simulator execution uses the exact frozen renderer runner.
        logs = output / 'commands'; logs.mkdir()
        bootstrap = bootstrap_commands(logs)
        builder, live = work / 'builder', work / 'LiveContainer'
        acquire(builder, BUILDER, bootstrap); acquire(live, SOURCE, bootstrap)
        runner = module('probe_commands', builder / 'scripts/run_issue25_rendering.py')
        runner.COMMAND_LOG = logs / 'bounded-commands.jsonl'
        command = Commands(logs); command.renderer = runner
        proof = {'LiveContainer': checkout_proof(live, SOURCE, command), 'builder': checkout_proof(builder, BUILDER, command)}
        write(output / 'source-before.json', proof)
        shutil.copy2(inputs, output / 'approved-inputs.json')
        write(output / 'validation-host.json', {'commit': command('git', '-C', host, 'rev-parse', 'HEAD'),
            'tree': command('git', '-C', host, 'rev-parse', 'HEAD^{tree}'), 'workflow_sha256': sha(host / '.github/workflows/p1-native-candidate.yml')})
        shutil.copytree(HERE, output / 'harness', ignore=shutil.ignore_patterns('__pycache__'))
        write(output / 'toolchain.json', {'xcodebuild': command('xcodebuild', '-version'),
            'swift': command('swift', '--version'), 'developer_dir': os.environ.get('DEVELOPER_DIR'),
            'simulators': json.loads(command('xcrun', 'simctl', 'list', '--json'))})
        project, renderer = prepare(live / SHELL, builder, work / 'build', output)
        command('xcodebuild', 'build-for-testing', '-project', project, '-scheme', 'P0SignIn', '-sdk', 'iphonesimulator',
            '-destination', 'generic/platform=iOS Simulator', '-derivedDataPath', work / 'build/DerivedData',
            '-jobs', '2', 'CODE_SIGNING_ALLOWED=NO', 'CODE_SIGNING_REQUIRED=NO', timeout=600)
        candidates = list((work / 'build/DerivedData/Build/Products').glob('*.xctestrun'))
        require(len(candidates) == 1, 'ambiguous diagnostic xctestrun')
        devices = runner.available_devices()
        require(len(devices) == 2 and {d[0] for d in devices} == {'phone', 'tablet'} and len({d[1] for d in devices}) == 2, 'exact device matrix required')
        write(output / 'selected-devices.json', devices)
        for kind, device, runtime in devices:
            report = {'device_class': kind, 'simulator_udid': device, 'runtime': runtime, 'collection_complete': False, 'errors': []}
            result['reports'].append(report)
            folder = output / kind; folder.mkdir()
            booted_here = False
            try:
                state = json.loads(command('xcrun', 'simctl', 'list', 'devices', '--json'))
                booted = any(d['udid'] == device and d['state'] == 'Booted' for group in state['devices'].values() for d in group)
                if not booted:
                    command('xcrun', 'simctl', 'boot', device)
                    booted_here = True
                command('xcrun', 'simctl', 'bootstatus', device, '-b', timeout=600)
                # Only the dedicated disposable fixture app; no account/device settings.
                command('xcrun', 'simctl', 'uninstall', device, APP_ID, allow_failure=True)
                bundle = folder / 'tests.xcresult'; exports = folder / 'attachments'
                try:
                    command('xcodebuild', 'test-without-building', '-xctestrun', candidates[0],
                        '-destination', 'id=' + device, '-resultBundlePath', bundle,
                        '-parallel-testing-enabled', 'NO', '-maximum-concurrent-test-simulator-destinations', '1',
                        '-test-timeouts-enabled', 'YES', '-default-test-execution-time-allowance', '300',
                        '-maximum-test-execution-time-allowance', '300',
                        *['-only-testing:P0SignInUITests/P0SignInUITests/' + m for m in METHODS], timeout=1500)
                except Exception as error: report['errors'].append('XCTest: ' + str(error))
                if bundle.exists():
                    try:
                        command('xcrun', 'xcresulttool', 'export', 'attachments', '--path', bundle, '--output-path', exports, timeout=120)
                        summary = json.loads(command('xcrun', 'xcresulttool', 'get', 'test-results', 'summary', '--path', bundle))
                        write(folder / 'xctest-summary.json', summary)
                        report['summary'] = summary
                        report['exports'] = inspect_exports(exports, summary, renderer.valid_png)
                        write(folder / 'export-verification.json', report['exports'])
                    except Exception as error: report['errors'].append('XCTest export: ' + str(error))
                container = Path(command('xcrun', 'simctl', 'get_app_container', device, APP_ID, 'data'))
                raw = container / 'Documents/p1-pixel-probe'; inventory(raw)
                shutil.copytree(raw, folder / 'pixels')
                manifest, costs, complete = inspect_pixels(folder / 'pixels', renderer.valid_png)
                write(folder / 'capture-costs.json', costs); write(folder / 'ocr-inputs.json', manifest)
                command('swift', HERE / 'vision.swift', folder / 'ocr-inputs.json', folder / 'ocr.json', timeout=300)
                report['raw_inventory'] = inventory(folder / 'pixels')
                report['capture_costs'] = costs
                report['collection_complete'] = complete and not report['errors'] and report.get('exports', {}).get('collection_complete') is True
            except Exception as error: report['errors'].append(str(error))
            finally:
                write(folder / 'collection-report.json', report)
                if booted_here: command('xcrun', 'simctl', 'shutdown', device, allow_failure=True)
        write(output / 'source-after.json', {'LiveContainer': checkout_proof(live, SOURCE, command),
            'builder': checkout_proof(builder, BUILDER, command)})
        require(sha(live / SHELL) == SOURCE_SHA, 'source changed during probe')
        result['diagnostic_collection_complete'] = len(result['reports']) == 2 and all(r['collection_complete'] for r in result['reports'])
    except Exception as error: result['errors'].append(str(error))
    finally:
        write(output / 'diagnostic-result.json', result)
        write(output / 'evidence-index.json', {'schema': 'p1-diagnostic-evidence-index-v1',
            'files': {str(p.relative_to(output)): sha(p) for p in sorted(output.rglob('*')) if p.is_file() and p.name != 'evidence-index.json'}})
    return result['diagnostic_collection_complete']


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host-root', type=Path, required=True); p.add_argument('--inputs', type=Path, required=True)
    p.add_argument('--approved-inputs-sha256', required=True); p.add_argument('--work', type=Path)
    p.add_argument('--evidence', type=Path); p.add_argument('--execute', action='store_true')
    a = p.parse_args(); validate(a.host_root, a.inputs, a.approved_inputs_sha256)
    if a.execute:
        require(a.work is not None and a.evidence is not None, 'execution paths required')
        sys.exit(0 if execute(a.host_root.resolve(), a.work, a.evidence, a.inputs, a.approved_inputs_sha256) else 1)
