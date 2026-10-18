"""Run the exact runner request reader against deterministic native file races."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
START = '// P1_REQUEST_READER_BEGIN\n'
END = '// P1_REQUEST_READER_END\n'
CASES = ['missing', 'regular'] + [kind + '-' + phase for phase in ['before', 'after']
          for kind in ['rename', 'unlink', 'hardlink']] + [
    'empty', 'oversized', 'maximum-size', 'directory', 'fifo', 'symlink',
    'unlinked-empty-fatal', 'fstat-error-typed', 'close-error-preserves-primary',
    'short-read-fatal', 'read-error-fatal', 'changed-size-fatal', 'repeated-replace-no-fd-leak']


def digest(data): return hashlib.sha256(data).hexdigest()


def extracted(source):
    if source.count(START) != 1 or source.count(END) != 1:
        raise ValueError('request reader extraction markers differ')
    before, tail = source.split(START)
    body, after = tail.split(END)
    if not body or END in before or START in after:
        raise ValueError('request reader extraction order differs')
    return START + body + END


def verify(report):
    if not isinstance(report, dict) or report.get('schema') != 'p1-request-reader-regression-v1':
        raise ValueError('invalid native reader report')
    for key in ['admissionEligible', 'uiExecuted', 'simulatorExecuted']:
        if report.get(key) is not False: raise ValueError('native regression scope differs')
    rows = report.get('cases')
    if (report.get('passed') is not True or not isinstance(rows, list)
        or len(rows) != len(CASES) or [r.get('id') for r in rows if isinstance(r, dict)] != CASES
        or any(set(r) != {'id', 'passed'} or r.get('passed') is not True for r in rows)):
        raise ValueError('exact ordered native reader regressions did not pass')
    if set(report) != {'schema', 'passed', 'admissionEligible', 'uiExecuted', 'simulatorExecuted', 'cases'}:
        raise ValueError('unexpected native regression fields')
    return report


def run(command, work, output):
    work, output = Path(work), Path(output)
    if work.exists() or output.exists(): raise ValueError('fresh reader regression paths required')
    work.mkdir(); output.mkdir()
    runner = (HERE / 'runner_ui_tests.swift').read_bytes()
    block = extracted(runner.decode()).encode()
    test = (HERE / 'request_reader_regression.swift').read_bytes()
    combined = b'import Foundation\nimport Darwin\n' + block + b'\n' + test
    source = output / 'request-reader-regression.swift'; source.write_bytes(combined)
    (output / 'runner-reader.swift').write_bytes(block)
    (output / 'regression.swift').write_bytes(test)
    result = {'schema': 'p1-request-reader-gate-v1', 'passed': False,
              'admissionEligible': False, 'runner_sha256': digest(runner),
              'reader_sha256': digest(block), 'regression_sha256': digest(test),
              'compiled_source_sha256': digest(combined), 'case_ids': CASES}
    try:
        result['swift_version'] = command('xcrun', 'swiftc', '--version', timeout=10)
        binary = work / 'request-reader-regression'
        command('xcrun', 'swiftc', '-swift-version', '5', '-D', 'P1_REQUEST_READER_REGRESSION',
                source, '-o', binary, timeout=60)
        raw = command(binary, timeout=10)
        (output / 'native-report.json').write_text(raw)
        result['native_report_sha256'] = digest(raw.encode())
        result['native'] = verify(json.loads(raw))
        result['passed'] = True
    finally:
        (output / 'result.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    return result
