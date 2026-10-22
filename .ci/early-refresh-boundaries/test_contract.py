#!/usr/bin/env python3
"""Portable extraction/provenance contract. Does not compile or execute Swift."""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('early_refresh_generator', HERE / 'generate_regression.py')
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)

def validate(candidate_root, baseline_root, output, variants=('baseline', 'candidate')):
    candidate_root, baseline_root, output = map(lambda path: Path(path).resolve(), (candidate_root, baseline_root, output))
    receipts = generator.generate(candidate_root, baseline_root, output, variants)
    checks = []
    def check(value, name):
        assert value, name
        checks.append(name)
    dependency = generator.load_dependency(candidate_root)
    block = dependency.block
    exact = [
        (generator.INPUT_PATHS['manager'], '    func refresh(_ installedApps:'),
        (generator.EXTRA_INPUTS['runner'], '    func perform(_ operations:'),
        (generator.EXTRA_INPUTS['preflight'], 'final class PreflightChecksOperation:'),
        (generator.EXTRA_INPUTS['auth'], '    public func getAuthenticatedTeam()'),
        (generator.EXTRA_INPUTS['auth'], '    private func resolveActiveTeam()'),
        (generator.EXTRA_INPUTS['group'], 'final class RefreshGroup:'),
        (generator.EXTRA_INPUTS['minimuxer'], 'public func isMinimuxerReady()'),
        (generator.EXTRA_INPUTS['minimuxer'], '    var asOperationError:'),
        (generator.INPUT_PATHS['producer'], '            group.completionHandler = { (results) in'),
        (generator.INPUT_PATHS['host'], 'fileprivate func completedRefresh('),
        (generator.INPUT_PATHS['ui'], 'enum V3RefreshAllFailureDiagnostics {'),
        (generator.INPUT_PATHS['service'], 'enum V3HeadlessPairingFailure {'),
        (generator.INPUT_PATHS['pipeline'], 'func lcRefreshFailureFacts('),
        (generator.INPUT_PATHS['pipeline'], 'func lcStructuredSigningFailure('),
    ]
    required = set(generator.INPUT_PATHS.values()) | set(generator.EXTRA_INPUTS.values())
    for variant, receipt in receipts.items():
        root = baseline_root if variant == 'baseline' else candidate_root
        swift = (output / variant / 'early-refresh.swift').read_text()
        check(receipt['status'] == 'GENERATED_NOT_COMPILED_NOT_RUN' and receipt['swift_executed'] is False,
              variant + ': runtime remains NOT RUN')
        check(receipt['input_root'] == str(root) and receipt['support_root'] == str(candidate_root),
              variant + ': production and candidate-only support roots distinguished')
        check(set(receipt['inputs_sha256']) == required, variant + ': exact repo-relative production input set')
        for relative, expected in receipt['inputs_sha256'].items():
            check(hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected,
                  variant + ': actual production input ' + relative)
        for relative, expected in receipt['support_inputs_sha256'].items():
            check(hashlib.sha256((candidate_root / relative).read_bytes()).hexdigest() == expected,
                  variant + ': candidate-only support ' + relative)
        check(hashlib.sha256(swift.encode()).hexdigest() == receipt['generated_sha256'],
              variant + ': generated hash matches')
        check(receipt['expected_case_names'] == generator.CASE_NAMES and receipt['expected_case_count'] == 24,
              variant + ': exact 24 runtime case names retained')
        check(dependency.pure_model((root / generator.INPUT_PATHS['host']).read_text()) in swift,
              variant + ': whole shared model comes from actual variant root')
        for relative, anchor in exact:
            check(block((root / relative).read_text(), anchor) in swift,
                  variant + ': exact function ' + anchor.strip())
        check('struct RefreshFailureCases' not in swift and 'static func producer(' not in swift and swift.count('@main') == 1,
              variant + ': no legacy 36-case entrypoint or producer-injection route')
        check('baseline redacted underlying' in swift and 'SS-VERIFY-C11' in swift,
              variant + ': generic observed-signature negative controls retained')
        check('current_request_gate' in swift and 'current_run_gate' in swift and 'unknown_preflight_error_privacy' in swift,
              variant + ': correlation and privacy controls retained')
        helper = 'enum V3RefreshEarlyFailureBoundary {'
        check((helper in swift) == (variant == 'candidate'), variant + ': correct early-boundary generation')
        if variant == 'candidate':
            check(block((root / generator.EXTRA_INPUTS['runner']).read_text(),
                        '    private func performUsingAdmittedRoute(') in swift,
                  'candidate: exact admitted-route readiness/preflight body extracted')
            check(block((root / generator.EXTRA_INPUTS['runner']).read_text(), helper) in swift,
                  'candidate: actual integrated annotation helper extracted')
    report = {'schema': 'early-refresh-portable-contract-v1', 'status': 'STATIC_PASS_RUNTIME_NOT_RUN',
              'checks': checks, 'check_count': len(checks), 'variants': list(receipts),
              'swift_compiled': False, 'swift_executed': False, 'expected_cases_per_variant': 24,
              'expected_generic_baseline_cases': 12, 'device_cause': 'NOT_ESTABLISHED'}
    (output / 'contract.json').write_text(json.dumps(report, indent=2) + '\n')
    return report

def main():
    args = generator.parser().parse_args()
    report = validate(args.candidate_root, args.baseline_root, args.output, args.variants)
    print('EARLY_REFRESH_PORTABLE_STATIC_PASS_RUNTIME_NOT_RUN checks=' + str(report['check_count']))

if __name__ == '__main__': main()
