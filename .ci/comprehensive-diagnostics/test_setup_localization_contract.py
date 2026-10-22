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
    current, previous = g.coverage(s), g.coverage(old)
    assert not current['missing'], current['missing']
    assert {row['key'] for row in previous['missing']} <= {'JIT-Less', 'Wi-Fi', 'CoreDevice'}
    assert set(current['keys']) - set(previous['keys']) <= set(g.PAIRING_KEYS)
    assert set(g.PAIRING_KEYS) <= set(current['keys'])
    assert set(current['title_cases'].values()) == set(previous['by_section']['row_titles'])
    view = g.block(s['ui'], 'struct V3SetupAssistantView: View {')
    old_view = g.block(old['ui'], 'struct V3SetupAssistantView: View {')
    # Pairing/portal work can legitimately change other UI and setup-store
    # producers. The localization patch must not change any Setup Assistant
    # state, rendering, routing, copy, or control body beyond typed row titles.
    def normalize_owned_titles(source):
        for case, title in current['title_cases'].items():
            source = source.replace('title: .' + case + ',', 'title: "' + title + '",')
        source = source.replace('title: V3SetupTitle,', 'title: String,')
        source = source.replace('Text(verbatim: title.localized(language: .resolve(dateLocale.identifier))).font(.headline)', 'V3LocalizedText(title).font(.headline)')
        source = source.replace('V3Localization.format("%@, %@", title.localized(language: .resolve(dateLocale.identifier)), V3Localization.prose(stateLabel(state.state), language: .resolve(dateLocale.identifier)), language: .resolve(dateLocale.identifier))', 'V3Localization.format("%@, %@", V3Localization.prose(title), V3Localization.prose(stateLabel(state.state)))')
        return source
    assert normalize_owned_titles(view) == normalize_owned_titles(old_view)
    assert s['display'] == old['display']
    for anchor in ['enum V3Localization {', 'extension V3Localization {', 'struct V3DisplayMessage: LocalizedError, @unchecked Sendable {']:
        # Two separate V3Localization extensions exist; compare full suffix below.
        if anchor != 'extension V3Localization {':
            assert g.block(s['localization'], anchor) == g.block(old['localization'], anchor)
    assert s['localization'][s['localization'].index('enum V3Localization {'):] == old['localization'][old['localization'].index('enum V3Localization {'):]
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
    allowed = {'JIT-Less', 'Wi-Fi', 'CoreDevice'} | set(g.PAIRING_KEYS) | identity_keys
    assert added == allowed - set(baseline_catalog['strings']), added
    negative = g.catalog_missing(current['keys'], baseline_catalog['strings'])
    assert {row['key'] for row in negative} == added & set(current['keys'])
    assert len(negative) == len(added & set(current['keys'])) * len(g.LANGUAGES)
    for key in baseline_catalog['strings']:
        assert catalog['strings'][key] == baseline_catalog['strings'][key], key
    assert not set(baseline_catalog['strings']) - set(catalog['strings'])
    for key in added:
        for language in g.LANGUAGES:
            unit = catalog['strings'][key]['localizations'][language]['stringUnit']
            assert unit['state'] == 'translated' and unit['value']
            if key in {'JIT-Less', 'Wi-Fi', 'CoreDevice'} or language == 'en':
                assert unit['value'] == key
            else:
                assert unit['value'] != key
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
    manifest = g.generate(root, output, baseline)
    assert len(manifest['expected_case_names']) == len(set(manifest['expected_case_names'])) == manifest['expected_native_case_count']
    assert set(manifest['expected_case_names']) == set(g.expected_case_names(g.coverage(s) | {'baseline_missing': negative}))
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
        'setup_view_except_typed_titles': 'byte_for_byte_unchanged',
        'pairing_keys': g.PAIRING_KEYS, 'identity_diagnostic_keys': sorted(identity_keys),
        'candidate_key_coverage': 'pass', 'key_count': current['key_count'],
        'localized_value_count': current['localized_value_count'],
        'missing_translation_mutation_cases': len(mutation_checks),
        'native_renderer_cases': 'generated_not_executed', 'swift_build': 'not_run',
        'expected_native_case_count': manifest['expected_native_case_count'],
        'strict_prose_and_original_copy': 'byte_for_byte_unchanged',
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
