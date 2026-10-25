"""Offline controls for exact variant source selection; does not compile or run Swift."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('portal_generator_controls', HERE / 'generate_regression.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


def run(candidate, baseline, output):
    receipt = g.generate(candidate, baseline, output)
    wire_spec = importlib.util.spec_from_file_location('portal_dependency_wire_controls',
        candidate / g.SUPPORT_PATHS['wire_generator'])
    wire = importlib.util.module_from_spec(wire_spec)
    wire_spec.loader.exec_module(wire)
    checks = []
    for variant, root in [('baseline', baseline), ('candidate', candidate)]:
        value = receipt[variant]
        assert value['expected_case_count'] == len(set(value['expected_case_names'])) == 19
        assert value['inputs_sha256'] == {p: g.digest((root / p).read_bytes()) for p in g.INPUT_PATHS.values()}
        assert value['support_inputs_sha256'] == {p: g.digest((candidate / p).read_bytes()) for p in g.SUPPORT_PATHS.values()}
        generated = (output / variant / 'service.swift').read_text()
        policy = wire.block((root / g.INPUT_PATHS['service']).read_text(), 'enum V3AuthFailureDiagnosticsPolicy {')
        g.validate_service_dependencies(generated, policy, wire.block)
        # These are dependency-closure assertions within the existing exact-source
        # controls, not additional runtime cases or replacements for native Swift.
        context = wire.block(generated, 'struct FixtureRemoteAuthenticationContext {')
        route = wire.block(generated, 'enum ILoaderRemoteAuthentication {')
        owned = wire.block(generated, 'enum OwnedODAAuthentication {')
        for scope, omitted in [(policy, policy), (context, context),
                               (context, 'let session = FakeDispatcher()'),
                               (context, 'func checkActive() throws {}'), (route, route),
                               (route, 'static var current: FixtureRemoteAuthenticationContext? { nil }'),
                               (owned, owned), (owned, 'legacySession: FakeDispatcher'),
                               (owned, 'remoteSelected: Bool = false'),
                               (owned, 'validateAfterResponse: Bool = true'),
                               (owned, 'try await legacySession.data(for: request)')]:
            assert generated.count(scope) == 1 and scope.count(omitted) == 1
            mutated = generated.replace(scope, scope.replace(omitted, '', 1), 1)
            try:
                g.validate_service_dependencies(mutated, policy, wire.block)
            except AssertionError:
                pass
            else:
                raise AssertionError('Missing service dependency was not rejected: ' + omitted)
        assert 'URLSession' not in context
        assert wire.block((root / g.INPUT_PATHS['portal']).read_text(),
                          '    func sendServicesRequest<T: Decodable>') in generated
        checks.append(variant + '-exact-production-and-candidate-support-pinned')
    with tempfile.TemporaryDirectory() as folder:
        temporary = Path(folder)
        for variant, root in [('baseline', baseline), ('candidate', candidate)]:
            for relative in set(g.INPUT_PATHS.values()) | set(g.SUPPORT_PATHS.values()):
                source = candidate / relative if relative in g.SUPPORT_PATHS.values() else root / relative
                target = temporary / variant / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
        for variant in ['baseline', 'candidate']:
            root = temporary / variant
            for key, anchor in [('service', 'enum V3ResponseEncoder {'), ('host', 'enum V3CatalogRequestContext {')]:
                path = root / g.INPUT_PATHS[key]
                text = path.read_text()
                marker = 'VARIANT_SOURCE_SELECTION_' + variant.upper() + '_' + key.upper()
                assert text.count(anchor) == 1
                path.write_text(text.replace(anchor, anchor + '\n// ' + marker, 1))
        g.generate(temporary / 'candidate', temporary / 'baseline', temporary / 'generated')
        for variant, opposite in [('baseline', 'candidate'), ('candidate', 'baseline')]:
            for key in ['service', 'host']:
                generated = (temporary / 'generated' / variant / (key + '.swift')).read_text()
                assert 'VARIANT_SOURCE_SELECTION_' + variant.upper() + '_' + key.upper() in generated
                assert 'VARIANT_SOURCE_SELECTION_' + opposite.upper() not in generated
            checks.append(variant + '-variant-source-selection-mutation-isolated')
        path = temporary / 'candidate' / g.INPUT_PATHS['service']
        previous = path.read_text()
        path.write_text(previous + '\n// Unrelated integration is intentionally permitted.\n')
        g.generate(temporary / 'candidate', temporary / 'baseline', temporary / 'unrelated')
        checks.append('unrelated-AppDelegate-edits-accepted')
        path.write_text(previous.replace('lcPortalSigningRequest(sourceStep: "fetchCertificate", facts: [:])',
                                         'lcPortalSigningRequest(sourceStep: "fetchCertificate", facts: ["unsafe": "detail"])', 1))
        try:
            g.generate(temporary / 'candidate', temporary / 'baseline', temporary / 'wrong-method')
        except AssertionError as error:
            assert 'Portal read method diff changed' in str(error)
        else:
            raise AssertionError('Method-scope drift was not rejected')
        checks.append('portal-method-scope-drift-rejected')
    report = {'schema': 'portal-portability-controls-v1', 'status': 'pass', 'checks': checks,
              'check_count': len(checks), 'swift_executed': False, 'network_executed': False}
    (output / 'static-controls.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PORTAL_PORTABILITY_CONTROLS_PASS checks=' + str(len(checks)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-root', type=Path, required=True)
    parser.add_argument('--baseline-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.candidate_root, args.baseline_root, args.output)
