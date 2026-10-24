"""Bounded macOS investigation only. Never produces native-app admission or an IPA."""
import argparse
import ast
import hashlib
import json
import os
import plistlib
from pathlib import Path
import re
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
XCODE_DEVELOPER = Path('/Applications/Xcode_26.4.1.app/Contents/Developer')
PASS = 'TEST_ONLY_FIXTURE_PASS_NOT_APP_OR_DEVICE_VALIDATION'

def require(value, message):
    if not value:
        raise ValueError(message)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')

def regular(root, relative):
    require(isinstance(relative, str) and relative and not relative.startswith('/') and
            '..' not in Path(relative).parts and Path(relative).as_posix() == relative,
            'Unsafe fixture input path')
    path = root / relative
    require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root.resolve()),
            'Missing or escaping fixture file: ' + relative)
    return path

def inventory(root, hashes):
    actual = {p: sha(regular(root, p).read_bytes()) for p in hashes}
    require(actual == hashes, 'Exact fixture input bytes differ')
    return actual

class Commands:
    def __init__(self, output):
        self.output, self.rows = output, []
        (output / 'commands').mkdir()
    def run(self, name, argv, timeout=300):
        require(re.fullmatch(r'[a-z0-9-]+', name) and name not in [r['name'] for r in self.rows],
                'Invalid or repeated command identity')
        row = {'name': name, 'argv': list(map(str, argv)), 'exit_code': None,
               'timed_out': False, 'launch_error': None, 'log': 'commands/' + name + '.log'}
        start = time.monotonic()
        try:
            result = subprocess.run(row['argv'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=timeout, check=False)
            raw, row['exit_code'] = result.stdout, result.returncode
        except subprocess.TimeoutExpired as error:
            raw = error.output or b''; row['timed_out'] = True
        except OSError as error:
            raw = str(error).encode(); row['launch_error'] = str(error)
        if isinstance(raw, str): raw = raw.encode()
        row.update(stdout_sha256=sha(raw), duration_seconds=round(time.monotonic() - start, 3))
        (self.output / row['log']).write_bytes(raw)
        self.rows.append(row)
        return row, raw

def command_pass(row):
    return type(row['exit_code']) is int and row['exit_code'] == 0 and not row['timed_out'] and not row['launch_error']

def validate_runtime(raw, row, spec):
    require(not row['timed_out'] and not row['launch_error'], 'Fixture timed out or could not launch')
    value = json.loads(raw)
    require(isinstance(value, dict) and value.get('schema') == 'install-chain-runtime-v1' and value.get('group') == spec['group'],
            'Runtime identity differs')
    require(value.get('native_signing_device_executed') is False, 'Native signing/device execution claim')
    cases = value.get('cases')
    require(isinstance(cases, list) and all(isinstance(v, dict) for v in cases) and
            [v.get('name') for v in cases] == spec['cases'] and
            all(type(v.get('passed')) is bool for v in cases), 'Ordered runtime case closure differs')
    failed = [v['name'] for v in cases if not v['passed']]
    expected = spec['expected_failures']
    require(failed == expected and value.get('passed') is (not expected), 'Unexpected runtime case outcome')
    require(type(row['exit_code']) is int and row['exit_code'] == (1 if expected else 0),
            'Runtime exit does not match exact expected outcome')
    return value

def run(sources, recorder, output, contract_path):
    require(not output.exists() and not output.is_symlink(), 'Fresh evidence output required')
    output.mkdir(parents=True); output = output.resolve(strict=True)
    commands = Commands(output)
    contract = json.loads(contract_path.read_text())
    report = {'schema': 'test-only-install-chain-investigation-v1', 'status': 'FAILED_TEST_ONLY_NO_NATIVE_ADMISSION',
              'workflow_commit': os.environ.get('GITHUB_SHA'), 'run_id': os.environ.get('GITHUB_RUN_ID'),
              'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
              'contract_sha256': sha(contract_path.read_bytes()), 'runner_sha256': sha(Path(__file__).read_bytes()),
              'commands': commands.rows, 'failures': [], 'runtime': {},
              'app_compiled': False, 'app_executed': False, 'package_created': False, 'ipa_created': False,
              'native_admission': False, 'native_signing_device_execution_allowed': False,
              'source_network_scope': 'Unchanged recorder acquires exact immutable source graph only.'}
    before = None
    try:
        require(contract.get('schema') == 'install-chain-ci-contract-v1', 'Fixture CI contract schema differs')
        require(sha(recorder.read_bytes()) == contract['recorder_sha256'], 'Delivered recorder bytes differ')
        require(sources.resolve() == (Path.cwd() / 'sources').resolve() and not sources.is_symlink(),
                'Recorder source root differs')
        owners = next(ast.literal_eval(n.value) for n in ast.parse(recorder.read_text()).body
                      if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'OWNERS' for t in n.targets))
        require({k: list(v) for k, v in owners.items()} == contract['source_pins'], 'Delivered source pins differ')
        inventory(HERE, contract['fixture_inputs_sha256'])
        require(os.environ.get('DEVELOPER_DIR') == str(XCODE_DEVELOPER),
                'Unexpected Xcode selection')
        for name, argv in [('acquire', [sys.executable, '-B', recorder, 'acquire']),
                           ('snapshot-before', [sys.executable, '-B', recorder, 'snapshot', 'install-chain-before']),
                           ('xcode-version', ['xcodebuild', '-version'])]:
            row, raw = commands.run(name, argv, timeout=1200 if name == 'acquire' else 300)
            require(command_pass(row), 'Required command failed: ' + name)
            if name == 'xcode-version': require(raw.decode().splitlines()[0] == 'Xcode 26.4.1', 'Xcode version differs')
        before_raw = (Path.cwd() / 'evidence/install-chain-before.json').read_bytes()
        before = json.loads(before_raw)
        report['source_snapshot_before_sha256'] = sha(before_raw)
        report['source_inputs_before'] = inventory(sources, contract['source_inputs_sha256'])
        row, raw = commands.run('swiftc-path', ['xcrun', '--find', 'swiftc'])
        require(command_pass(row), 'Swift compiler discovery failed')
        swiftc = Path(raw.decode().strip())
        require(swiftc.is_absolute() and swiftc.is_file(), 'Invalid Swift compiler path')
        row, raw = commands.run('swift-version', [swiftc, '--version'])
        require(command_pass(row), 'Swift compiler version failed')
        row, raw = commands.run('macos-sdk-path', ['xcrun', '--sdk', 'macosx', '--show-sdk-path'])
        require(command_pass(row), 'macOS SDK discovery failed')
        sdk = Path(raw.decode().strip())
        sdk_parent = XCODE_DEVELOPER / 'Platforms/MacOSX.platform/Developer/SDKs'
        require(sdk.is_absolute() and sdk.is_dir() and sdk.resolve().parent == sdk_parent.resolve(),
                'SDK is not inside the selected Xcode macOS platform')
        sdk = sdk.resolve(strict=True)
        settings_raw = (sdk / 'SDKSettings.plist').read_bytes()
        settings = plistlib.loads(settings_raw)
        require(isinstance(settings.get('CanonicalName'), str) and settings['CanonicalName'].startswith('macosx'),
                'Selected SDK is not macOS')
        report['macos_sdk'] = {'path': str(sdk), 'canonical_name': settings['CanonicalName'],
                               'settings_sha256': sha(settings_raw)}
        generated = output / 'generated'
        row, raw = commands.run('generate', [sys.executable, '-B', HERE / contract['generator'],
            '--root', sources.resolve(), '--output', generated])
        require(command_pass(row), 'Actual source fixture generation failed')
        inventory(generated, contract['generated_sha256'])
        actual = {p.relative_to(generated).as_posix() for p in generated.rglob('*') if p.is_file()}
        require(actual == set(contract['generated_sha256']), 'Generated fixture file closure differs')
        report['source_receipt'] = json.loads(regular(generated, contract['source_receipt']).read_text())
        compiled = {}
        variants = contract['variants']
        require(variants and len({v['name'] for v in variants}) == len(variants), 'Variant identity closure differs')
        for spec in variants:
            name = spec['name']; require(re.fullmatch(r'[a-z0-9-]+', name), 'Unsafe variant name')
            file = regular(generated, spec['swift'])
            require(spec.get('compile_flags', []) in ([], ['-framework', 'CryptoKit']), 'Unexpected fixture compile flags')
            row, raw = commands.run('compile-' + name,
                [swiftc, '-sdk', sdk, '-swift-version', '5', '-parse-as-library', *spec.get('compile_flags', []), file, '-o', output / name])
            compiled[name] = command_pass(row)
            if not compiled[name]: report['failures'].append({'name': name, 'phase': 'compile', 'reason': 'See exact compiler log'})
        for spec in variants:
            name = spec['name']
            if not compiled[name]: continue
            row, raw = commands.run('run-' + name, [output / name], timeout=60)
            try:
                report['runtime'][name] = validate_runtime(raw, row, spec)
            except (ValueError, TypeError, KeyError) as error:
                report['failures'].append({'name': name, 'phase': 'runtime', 'reason': str(error)})
        report['source_inputs_after'] = inventory(sources, contract['source_inputs_sha256'])
        inventory(HERE, contract['fixture_inputs_sha256'])
        require(not report['failures'], 'Independent fixture failures remain')
        report['status'] = PASS
    except Exception as error:
        report['failures'].append({'phase': 'investigation', 'reason': str(error)})
    finally:
        if before is not None:
            row, raw = commands.run('snapshot-after', [sys.executable, '-B', recorder, 'snapshot', 'install-chain-after'])
            try:
                require(command_pass(row), 'Final source snapshot failed')
                after_raw = (Path.cwd() / 'evidence/install-chain-after.json').read_bytes()
                after = json.loads(after_raw)
                report['source_snapshot_after_sha256'] = sha(after_raw)
                require(before == after, 'Delivered source graph or bytes mutated')
                report['complete_source_graph_unchanged'] = True
            except Exception as error:
                report['failures'].append({'phase': 'source-immutability', 'reason': str(error)})
        if report['failures']: report['status'] = 'FAILED_TEST_ONLY_NO_NATIVE_ADMISSION'
        report['artifact_sha256'] = {p.relative_to(output).as_posix(): sha(p.read_bytes())
            for p in sorted(output.rglob('*')) if p.is_file() and p.name != 'report.json'}
        write(output / 'report.json', report)
    return report

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--recorder', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--contract', type=Path, default=HERE / 'contract.json')
    args = parser.parse_args()
    report = run(args.sources, args.recorder, args.output, args.contract)
    print(report['status'])
    raise SystemExit(0 if report['status'] == PASS else 1)
