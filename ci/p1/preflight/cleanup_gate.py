#!/usr/bin/env python3
"""Compact macOS cleanup regressions; never boot or build a simulator app."""
import argparse
import hashlib
import importlib.util
import os
from pathlib import Path
import platform
import sys
import time
import unittest
import process_scope

HERE = Path(__file__).resolve().parent
SUITES = ('test_process_lifecycle', 'test_simulator_cleanup',
          'test_capability.ProcessQuiescenceTests',
          'test_capability.CleanupAndDeadlineTests',
          'test_capability.FailureDiagnosticTests')


class Result(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs); self.rows = []
    def addSuccess(self, test):
        super().addSuccess(test); self.rows.append({'id': test.id(), 'outcome': 'passed'})
    def addFailure(self, test, err):
        super().addFailure(test, err); self.rows.append({'id': test.id(), 'outcome': 'failed'})
    def addError(self, test, err):
        super().addError(test, err); self.rows.append({'id': test.id(), 'outcome': 'error'})
    def addSkip(self, test, reason):
        super().addSkip(test, reason); self.rows.append({'id': test.id(), 'outcome': 'skipped'})


def execute(output, identity=None):
    if output.exists(): raise ValueError('fresh cleanup regression output required')
    output.mkdir(parents=True)
    before = time.monotonic()
    report = {'schema': 'p1-cleanup-regression-result-v1', 'scope': 'cleanup-regression-only',
              'admissionEligible': False, 'production_ready': False, 'ui_executed': False,
              'simulator_executed': False, 'host_built': False, 'passed': False,
              'python': sys.version, 'platform': platform.platform(),
              'suites': list(SUITES), 'identity': identity}
    try:
        if sys.platform != 'darwin': raise ValueError('native cleanup gate requires macOS')
        suite = unittest.defaultTestLoader.loadTestsFromNames(SUITES)
        with (output / 'tests.log').open('w') as log:
            result = unittest.TextTestRunner(stream=log, verbosity=2, resultclass=Result).run(suite)
        complete = (result.testsRun > 0 and len(result.rows) == result.testsRun
                    and len({r['id'] for r in result.rows}) == result.testsRun
                    and all(r['outcome'] == 'passed' for r in result.rows))
        report.update(tests=result.testsRun, skipped=len(result.skipped), cases=result.rows,
                      passed=result.wasSuccessful() and not result.skipped and complete)
        report['tests_log_sha256'] = hashlib.sha256((output / 'tests.log').read_bytes()).hexdigest()
    except Exception as error:
        report['error'] = process_scope.error_info(error)
    finally:
        report['elapsed_seconds'] = time.monotonic() - before
        process_scope.atomic(output / 'result.json', report)
        process_scope.emit_diagnostic('cleanup-regression-result', passed=report['passed'],
                                      tests=report.get('tests'), skipped=report.get('skipped'))
    return report['passed']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-root', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--approved-inputs-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('cleanup_seal', HERE / 'capture.py')
    capture = importlib.util.module_from_spec(spec); spec.loader.exec_module(capture)
    capture.validate(args.host_root, args.inputs, args.approved_inputs_sha256)
    identity = {'github': {key: os.environ.get(key) for key in
                           ['GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_REPOSITORY']},
                'approved_inputs_sha256': args.approved_inputs_sha256,
                'retained_ui_source': capture.SOURCE, 'retained_ui_source_sha256': capture.SOURCE_SHA}
    return 0 if execute(args.output, identity) else 1


if __name__ == '__main__': raise SystemExit(main())
