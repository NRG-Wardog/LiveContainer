#!/usr/bin/env python3
"""Source-owned setup key coverage, boundary invariants and baseline regression. No builds."""
import argparse
import hashlib
import importlib.util
import json
import re
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('setup_generator', HERE / 'generate_setup_localization_fixture.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

def check(root, baseline, output):
    s, old = g.read_sources(root), g.read_sources(baseline)
    current, previous = g.coverage(s, old), g.coverage(old)
    assert not current['missing'], current['missing']
    assert {row['key'] for row in previous['missing'] if row['language'] in g.BASELINE_LANGUAGES} <= {'JIT-Less', 'Wi-Fi', 'CoreDevice'}
    overlay_keys = g.overlay_keys(s)
    assert len(overlay_keys) == 27
    assert set(current['retained_baseline_copy']) == g.RETAINED_BASELINE_KEYS
    assert set(previous['keys']) <= set(current['keys'])
    assert not set(current['retained_baseline_copy']) & set(g.coverage(s)['keys'])
    assert set(current['keys']) - set(previous['keys']) <= set(g.PAIRING_KEYS) | overlay_keys
    assert overlay_keys <= set(current['keys'])
    assert set(g.PAIRING_KEYS) <= set(current['keys'])
    assert set(current['title_cases'].values()) == set(previous['by_section']['row_titles'])
    view = g.block(s['ui'], 'struct V3SetupAssistantView: View {')
    old_view = g.block(old['ui'], 'struct V3SetupAssistantView: View {')
    # The typed-title patch and the bounded connection-evidence overlay own
    # only the exact snippets below. Every remaining Setup Assistant byte must
    # still match baseline; no broad method deletion or wildcard normalization.
    def normalize_owned_titles(source):
        # Live language switching binds the outer formatter even when the date
        # branch is absent. Normalize only this exact presentation-only addition.
        source = source.replace(
            'V3Localization.format("Last verified %@", V3Localization.date(date, date: .abbreviated, time: .shortened, language: V3AppLanguage.resolve(dateLocale.identifier)), language: .resolve(dateLocale.identifier))',
            'V3Localization.format("Last verified %@", V3Localization.date(date, date: .abbreviated, time: .shortened, language: V3AppLanguage.resolve(dateLocale.identifier)))')
        for case, title in current['title_cases'].items():
            source = source.replace('title: .' + case + ',', 'title: "' + title + '",')
        source = source.replace('title: V3SetupTitle,', 'title: String,')
        source = source.replace('Text(verbatim: title.localized(language: .resolve(dateLocale.identifier))).font(.headline)', 'V3LocalizedText(title).font(.headline)')
        source = source.replace('V3Localization.format("%@, %@", title.localized(language: .resolve(dateLocale.identifier)), V3Localization.prose(stateLabel(state.state), language: .resolve(dateLocale.identifier)), language: .resolve(dateLocale.identifier))', 'V3Localization.format("%@, %@", V3Localization.prose(title), V3Localization.prose(stateLabel(state.state)))')
        return source
    def normalize_connection_evidence(source):
        def replace_once(current, old):
            nonlocal source
            assert source.count(current) == 1, current
            source = source.replace(current, old, 1)
        replace_once('        .onReceive(NotificationCenter.default.publisher(for: Notification.Name(LiveContainerAutoRefreshScheduler.runStateChangedNotification))) { _ in\n            setup.refreshConnectionEvidence()\n        }\n', '')
        replace_once('if ["actionRequired", "detected", "failed"].contains(setup.tunnel.state) {',
                     'if setup.tunnel.state == "actionRequired" {')
        expected_core = 'private func coredeviceState() -> V3SetupStepState { setup.coreDevice }'
        assert g.block(source, 'private func coredeviceState()') == expected_core
        replace_once(expected_core, g.block(old_view, 'private func coredeviceState()'))
        replace_once('                    else if let owned = V3SetupConnectionCopy(rawValue: state.detail) {\n                        Text(verbatim: V3Localization.string(owned.rawValue, language: .resolve(dateLocale.identifier)))\n                    } else { V3LocalizedText(state.detail.isEmpty ? stateLabel(state.state) : state.detail) }', '                    else { V3LocalizedText(state.detail.isEmpty ? stateLabel(state.state) : state.detail) }')
        replace_once('V3Localization.string(stateLabel(state.state), language: .resolve(dateLocale.identifier))',
                     'V3Localization.prose(stateLabel(state.state), language: .resolve(dateLocale.identifier))')
        replace_once('case "complete", "verified": return "checkmark.circle.fill"',
                     'case "complete": return "checkmark.circle.fill"')
        replace_once('case "complete", "verified": return .green', 'case "complete": return .green')
        replace_once('        case "verified": return "Verified"\n        case "detected": return "Detected"\n        case "notChecked": return "Not checked"\n', '')
        return source
    normalized = normalize_owned_titles(normalize_connection_evidence(view))
    assert normalized == normalize_owned_titles(old_view)
    # Prove unrelated mutations are not erased by the narrow normalizer.
    assert normalize_owned_titles(normalize_connection_evidence(view.replace(
        'if setup.testRunning { setup.cancelTest() }', 'if setup.testRunning { }', 1))) != normalize_owned_titles(old_view)

    assert s['display'] == old['display']
    # Russian adds exactly these two finite fail-closed messages. No other
    # production renderer bytes may change relative to the historical baseline.
    def normalize_russian_renderer(source):
        additions = [
            '        case .russian: return "Некоторые сведения недоступны на выбранном языке."\n',
            '"ru": "ID ошибки:", ',
        ]
        for addition in additions:
            assert source.count(addition) == 1, addition
            source = source.replace(addition, '', 1)
        return source
    renderer = normalize_russian_renderer(s['localization'][s['localization'].index('enum V3Localization {'):])
    baseline_renderer = old['localization'][old['localization'].index('enum V3Localization {'):]
    assert renderer == baseline_renderer
    assert normalize_russian_renderer(s['localization'].replace(
        'guard depth < 8 else { return nil }', 'guard depth < 9 else { return nil }', 1)
        [s['localization'].index('enum V3Localization {'):]) != baseline_renderer
    for anchor in ['enum V3Localization {', 'extension V3Localization {', 'struct V3DisplayMessage: LocalizedError, @unchecked Sendable {']:
        # Two separate V3Localization extensions exist; compare full suffix below.
        if anchor != 'extension V3Localization {':
            assert g.block(renderer, anchor) == g.block(old['localization'], anchor)
    assert renderer == baseline_renderer
    for anchor in ['private func setupRow(', 'private func rowContent(']:
        assert 'title: V3SetupTitle' in g.block(view, anchor)
    content = g.block(view, 'private func rowContent(')
    assert 'Text(verbatim: title.localized(language: .resolve(dateLocale.identifier)))' in content
    assert '.accessibilityLabel(V3Localization.format("%@, %@", title.localized(language: .resolve(dateLocale.identifier))' in content
    assert 'if state.detailIsOpaque { Text(state.detail) }' in content
    assert 'else { V3LocalizedText(state.detail.isEmpty ? stateLabel(state.state) : state.detail) }' in content
    assert 'V3LocalizedText(setup.verificationGuidance)' in view
    title_type = g.block(s['localization'], g.TITLE_ANCHOR)
    assert 'let value = V3Localization.string(rawValue, language: language, bundle: bundle)' in title_type
    assert 'if !value.isEmpty { return value }' in title_type
    assert 'let english = V3Localization.string(rawValue, language: .english, bundle: bundle)' in title_type
    assert 'return english.isEmpty ? rawValue : english' in title_type
    catalog, baseline_catalog = json.loads(s['catalog']), json.loads(old['catalog'])
    added = set(catalog['strings']) - set(baseline_catalog['strings'])
    # Only these fixed local messages may extend this catalog; never arbitrary error text.
    identity_keys = set(['The saved remote provider identity is invalid. It was not replaced.', 'The saved remote provider identity could not be verified in protected storage.', 'The active account or remote provider identity changed during this request.', 'This saved session needs one manual sign-in to confirm its provider identity.', 'Keep the saved identity unchanged and copy Diagnostics before retrying.', 'Open Account & Signing and sign in again. The local pairing file and certificates are kept.'])
    identity_producers = g.block(s['identity_diagnostics'], 'static func remoteIdentityMessage(') + g.block(s['identity_diagnostics'], 'static func remoteIdentityRecovery(')
    assert set(re.findall(r'return "([^"]+)"', identity_producers)) == identity_keys
    owned_oda_keys = {
        'Built-in On-Device libraries are checked against pinned vendor hashes before use.',
        'Custom On-Device source: HTTPS and an archive checksum are required. A supplied checksum does not verify who published the libraries.',
        'On-Device is unavailable for this sequence: its configured source must use HTTPS without embedded credentials or a URL fragment.',
        'On-Device is unavailable for this sequence because its private storage is unavailable.',
    }
    owned_notice = g.block(s['ui'], 'private var ownedODASourceNotice: String? {')
    assert set(re.findall(r'return "([^"]+)"', owned_notice)) == owned_oda_keys
    assert 'default: return nil' in owned_notice
    # Issue56 owns exactly eight startup strings. Bind the allowlist to the
    # actual finite producers, not to whatever happens to appear in the catalog.
    startup_messages = {
        'SideStore stopped startup because its private data layout could not be verified.',
        'SideStore stopped startup because conflicting saved data locations were found.',
        'SideStore could not access its required shared storage.',
        'SideStore could not open or prepare its saved database.',
        'SideStore database startup failed before readiness.',
    }
    startup_recovery = 'Open Operation Logs and copy the startup diagnostics. Keep the existing app and its data; do not delete, reset, or move its database as a workaround.'
    startup_logs_message = 'Service operation logs are unavailable because startup is not complete. Available safe startup diagnostics are shown below.'
    startup_keys = startup_messages | {startup_recovery, startup_logs_message, 'Startup Diagnostics'}
    assert len(startup_keys) == 8
    startup_producer = g.block(s['identity_diagnostics'], 'private var databaseStartupMessage: String? {')
    assert set(re.findall(r'return "([^"]+)"', startup_producer)) == startup_messages
    recovery = g.block(s['identity_diagnostics'], 'public var recovery: String {')
    startup_recovery_producer = g.block(recovery, 'if isTerminalDatabaseStartupFailure {')
    assert set(re.findall(r'return "([^"]+)"', startup_recovery_producer)) == {startup_recovery}
    startup_logs = g.block(s['ui'], 'struct V3LogsView: View {')
    assert 'Section("Startup Diagnostics") {' in startup_logs
    assert 'message = "' + startup_logs_message + '"' in startup_logs
    assert not g.catalog_missing(startup_keys, catalog['strings'])
    allowed = {'JIT-Less', 'Wi-Fi', 'CoreDevice'} | set(g.PAIRING_KEYS) | identity_keys | overlay_keys | owned_oda_keys | startup_keys
    assert added == allowed - set(baseline_catalog['strings']), added
    negative = g.catalog_missing(current['keys'], baseline_catalog['strings'])
    historical_negative = [row for row in negative if row['language'] in g.BASELINE_LANGUAGES]
    assert {row['key'] for row in historical_negative} == added & set(current['keys'])
    assert len(historical_negative) == len(added & set(current['keys'])) * len(g.BASELINE_LANGUAGES)
    # Independent Russian audit, 2026-10-25: reviewed corrections to inherited
    # Russian copy (including negation, certificate actions, plurals and data-loss
    # warnings). Pin the exact reviewed map; this is not a blanket locale waiver.
    reviewed_path = root / 'tests/fixtures/russian_reviewed_existing.json'
    reviewed_bytes = reviewed_path.read_bytes()
    assert hashlib.sha256(reviewed_bytes).hexdigest() == 'fd2259f2e1279d713d81dd24908fe1ff158e35ba0427d13a895ac9e5bc67711d'
    reviewed_russian = json.loads(reviewed_bytes)
    assert len(reviewed_russian) == 108
    for key, reviewed_value in reviewed_russian.items():
        assert catalog['strings'][key]['localizations']['ru'] == reviewed_value, key
    for key, baseline_row in baseline_catalog['strings'].items():
        candidate_row = json.loads(json.dumps(catalog['strings'][key]))
        # Permit additive Russian entries or the exact independently reviewed
        # corrections above. Every other locale and metadata field remains equal.
        if 'ru' not in baseline_row.get('localizations', {}):
            candidate_row.get('localizations', {}).pop('ru', None)
        elif key in reviewed_russian:
            assert candidate_row['localizations']['ru'] == reviewed_russian[key], key
            candidate_row['localizations']['ru'] = baseline_row['localizations']['ru']
        assert candidate_row == baseline_row, key
    assert not set(baseline_catalog['strings']) - set(catalog['strings'])
    for key in added:
        for language in g.LANGUAGES:
            unit = catalog['strings'][key]['localizations'][language]['stringUnit']
            assert unit['state'] == 'translated' and unit['value']
            if (key in {'JIT-Less', 'Wi-Fi', 'CoreDevice'} and language in g.BASELINE_LANGUAGES) or language == 'en':
                assert unit['value'] == key
            elif key not in {'JIT-Less', 'Wi-Fi', 'CoreDevice'}:
                assert unit['value'] != key
    # The existing finite Russian overlay remains fully translated, and Russian
    # is now also covered by all candidate renderer cases and mutation checks.
    for key in overlay_keys:
        unit = catalog['strings'][key]['localizations']['ru']['stringUnit']
        assert unit['state'] == 'translated' and unit['value'] and unit['value'] != key
    # Fail closed if a real source title/body loses ANY supported translation.
    mutation_checks = []
    for key in current['keys']:
        for language in g.LANGUAGES:
            localizations = catalog['strings'][key]['localizations']
            saved = localizations.pop(language)
            failure = g.catalog_missing(current['keys'], catalog['strings'])
            assert {'key': key, 'language': language} in failure
            localizations[language] = saved
            mutation_checks.append(key + '|' + language)
    # Keep the historical setup case counts unchanged. The separate startup
    # scope rejects each missing translation independently (8 keys x 5 locales).
    startup_mutation_checks = []
    for key in sorted(startup_keys):
        for language in g.LANGUAGES:
            localizations = catalog['strings'][key]['localizations']
            saved = localizations.pop(language)
            failure = g.catalog_missing(startup_keys, catalog['strings'])
            assert {'key': key, 'language': language} in failure
            localizations[language] = saved
            startup_mutation_checks.append(key + '|' + language)
    assert len(startup_mutation_checks) == 40
    manifest = g.generate(root, output, baseline)
    assert len(manifest['expected_case_names']) == len(set(manifest['expected_case_names'])) == manifest['expected_native_case_count']
    assert set(manifest['expected_case_names']) == set(g.expected_case_names(current | {'baseline_missing': negative}))
    inherited_copy_cases = {'actual-source-copy-' + language + '-' + key
        for language in g.LANGUAGES for key in previous['keys']}
    assert inherited_copy_cases <= set(manifest['expected_case_names'])
    fixture = (output / 'fixture.swift').read_text()
    assert fixture.startswith(s['localization'] + '\n')
    for token in ['URLSession.shared', 'import UIKit', 'import SwiftUI', 'dlopen(', 'SRPClient(']:
        assert token not in fixture, token
    for token in ['unknown-provider-fails-closed-', 'original-error-copy-unmodified-', 'baseline-reproduces-missing-owned-copy-', 'owned-title-english-fallback-', 'owned-title-source-fallback-', 'actual-schedule-format-']:
        assert token in fixture, token
    assert not (output / 'cases.json').exists()
    for name, digest in manifest['output_sha256'].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    report = {
        'schema': 'setup-localization-static-contract-v1', 'status': 'pass',
        'baseline_key_coverage': 'fail_as_expected', 'baseline_missing': negative,
        'baseline_existing_source_missing': previous['missing'],
        'setup_view_except_typed_titles_and_exact_connection_overlay': 'byte_for_byte_unchanged',
        'exact_connection_scope_negative_control': 'unrelated_cancel_mutation_rejected',
        'overlay_keys': sorted(overlay_keys), 'overlay_russian_values': 27,
        'startup_diagnostic_keys': sorted(startup_keys),
        'startup_missing_translation_mutation_cases': len(startup_mutation_checks),
        'reviewed_russian_corrections_sha256': hashlib.sha256(reviewed_bytes).hexdigest(),
        'reviewed_russian_correction_count': len(reviewed_russian),
        'retained_baseline_copy': current['retained_baseline_copy'],
        'inherited_source_copy_cases_retained': len(inherited_copy_cases),
        'pairing_keys': g.PAIRING_KEYS, 'identity_diagnostic_keys': sorted(identity_keys),
        'candidate_key_coverage': 'pass', 'key_count': current['key_count'],
        'localized_value_count': current['localized_value_count'],
        'missing_translation_mutation_cases': len(mutation_checks),
        'native_renderer_cases': 'generated_not_executed', 'swift_build': 'not_run',
        'expected_native_case_count': manifest['expected_native_case_count'],
        'strict_prose_and_original_copy': 'unchanged_except_exact_russian_fallback_additions',
        'source_sha256': manifest['source_sha256'], 'baseline_sha256': manifest['baseline_sha256']}
    (output / 'static-contract.json').write_text(json.dumps(report, indent=2) + '\n')
    print('SETUP_LOCALIZATION_STATIC_PASS baseline=fail_as_expected candidate=pass keys=' + str(current['key_count']) + ' localized_values=' + str(current['localized_value_count']) + ' swift_executed=false')

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate-root', '--livecontainer-root', dest='candidate_root', type=Path, required=True)
    p.add_argument('--baseline-root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    check(a.candidate_root, a.baseline_root, a.output)
