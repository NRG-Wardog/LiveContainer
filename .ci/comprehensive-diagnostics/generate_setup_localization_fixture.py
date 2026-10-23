#!/usr/bin/env python3
"""Generate tests from actual setup source and localization catalog; never build by default."""
import argparse
import hashlib
import json
import plistlib
import re
import shutil
import subprocess
from pathlib import Path

LANGUAGES = ['en', 'he', 'zh-Hans', 'zh-Hant']
PAIRING_KEYS = ['Pairing file saved and selected.', 'The placed file is available but has not been selected.', 'Pairing was reset. Use the placed file or import a file to enable it again.', 'The selected pairing file is missing.', 'The pairing files or selected protocol have changed. Check the selection before continuing.', 'The saved pairing file could not be validated.', 'Saved pairing selection could not be confirmed.', 'Device connection has not been checked on this screen.', 'The device connection was verified for the saved pairing file.', 'The pairing file remains saved. The device connection could not be confirmed. Check the connection before refreshing.']
PAIRING_ANCHOR = "enum V3PairingSelectionPresentation {"
TITLE_ANCHOR = 'enum V3SetupTitle: String, CaseIterable {'
SOURCE_PATHS = {
    'ui': 'LiveContainerSwiftUI/Views/V3UnifiedShell.swift',
    'localization': 'LiveContainerSwiftUI/Utilities/V3Localization.swift',
    'catalog': 'Resources/Localizable.xcstrings',
    'display': 'LiveContainerSwiftUI/Utilities/V3LanguageSettings.swift',
    'identity_diagnostics': 'SideStoreSupport/SideStore.swift',
}
HERE = Path(__file__).resolve().parent

def digest(data):
    return hashlib.sha256(data).hexdigest()

def block(source, anchor):
    assert source.count(anchor) == 1, (anchor, source.count(anchor))
    start = source.index(anchor)
    # All extracted declarations have balanced braces, including interpolation.
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]

def read_sources(root):
    return {key: (root / path).read_text() for key, path in SOURCE_PATHS.items()}

CONNECTION_COPY_ANCHOR = 'enum V3SetupConnectionCopy: String, CaseIterable {'
CONNECTION_LABELS = ['Verified', 'Detected', 'Not checked']
LOCAL_REFRESH_ANCHORS = ['private var localRefreshMessage: String?', 'private var localRefreshRecovery: String?', 'private var localDevVPNActivationMessage: String?']
RETAINED_BASELINE_KEYS = {
    'Checked after a successful refresh',
    'Tunnel interface present (not a CoreDevice proof)',
    'Tunnel not present',
    'Verified by successful refresh',
}

def connection_keys(s):
    if CONNECTION_COPY_ANCHOR not in s['ui']:
        return set()
    keys = set(re.findall(r'case \w+ = "([^"]+)"', block(s['ui'], CONNECTION_COPY_ANCHOR)))
    assert len(keys) == 11, 'Exact finite setup connection copy inventory'
    return keys | set(CONNECTION_LABELS)

def local_refresh_keys(s):
    if LOCAL_REFRESH_ANCHORS[0] not in s['identity_diagnostics']:
        return set()
    source = '\n'.join(block(s['identity_diagnostics'], anchor) for anchor in LOCAL_REFRESH_ANCHORS)
    keys = set(re.findall(r'return "([^"]+)"', source))
    assert len(keys) == 13, 'Exact finite local refresh formatter inventory'
    return keys

def overlay_keys(s):
    keys = connection_keys(s) | local_refresh_keys(s)
    assert not keys or len(keys) == 27, 'Exact narrow status/profile overlay copy inventory'
    return keys

def coverage(s, retained_baseline=None):
    ui, localization = s['ui'], s['localization']
    view = block(ui, 'struct V3SetupAssistantView: View {')
    store = block(ui, 'final class V3SetupStore: ObservableObject {')
    sections = {
        'assistant': view[:view.index('    private func openLocalVPN()')],
        'setup_store': store[:store.index('    // A human-copyable pairing word')],
        'jitless_presentation': block(ui, 'struct V3JITLessPresentation: Equatable {'),
        'host_signing_presentation': block(ui, 'enum V3HostSigningState: String, Equatable, Sendable {'),
        'outstanding_items': block(ui, 'enum V3SetupOutstandingItem: String, Equatable, CaseIterable {'),
        'pairing_prerequisite': block(ui, 'struct V3RefreshPrerequisite: Equatable {'),
    }
    by_section = {}
    for name, source in sections.items():
        # Owned English UI literals, excluding interpolated/log/protocol values.
        # This fails on any newly introduced capitalized copy missing a catalog
        # entry, instead of relying on a manually maintained list of UI keys.
        keys = set()
        for raw in re.findall(r'"((?:[^"\\]|\\.)*)"', source):
            if not raw or not raw[0].isupper() or '\\(' in raw:
                continue
            if raw == 'LiveContainerAutoRefreshRunNow':
                assert 'Notification.Name("LiveContainerAutoRefreshRunNow")' in source
                continue
            if raw in ['V3SetupPendingRefreshRequestID', 'V3SetupPendingRefreshRequestDate']:
                assert re.search(r'private static let \w+ = "' + raw + '"', source), raw
                continue
            if raw.startswith('V3'):
                # Only host-owned event names, not product copy.
                assert 'Notification.Name("' + raw + '")' in source, raw
                continue
            keys.add(json.loads('"' + raw + '"'))
        by_section[name] = sorted(keys)
    if TITLE_ANCHOR in localization:
        titles = dict(re.findall(r'case (\w+) = "([^"]+)"', block(localization, TITLE_ANCHOR)))
        row_titles = re.findall(r'setupRow\(icon:.*?title: \.(\w+)', view)
        assert len(row_titles) == 12 and set(row_titles) == set(titles), row_titles
        assert len(titles) == 12
        by_section['row_titles'] = sorted(titles.values())
    else:
        titles = {}
        by_section['row_titles'] = sorted(re.findall(r'setupRow\(icon:.*?title: "([^"]+)"', view))
        assert len(by_section['row_titles']) == 12
    format_keys = re.findall(r'DisplayFormat\(key: "(Scheduled refresh enabled [^"]+)"', localization)
    assert len(format_keys) == 2
    for key in ['Every six hours', 'Daily', 'Weekly']:
        assert '"' + key + '"' in localization
    assert 'V3Localization.format("Last verified %@"' in view
    assert 'V3Localization.format("%@, %@"' in view
    by_section['formats_and_labels'] = sorted(format_keys + ['Every six hours', 'Daily', 'Weekly', 'Error ID:', 'Last verified %@', '%@, %@'])
    if PAIRING_ANCHOR in ui:
        selection = block(ui, PAIRING_ANCHOR)
        produced = set(re.findall(r'return "([^"]+)"', selection))
        assert produced == set(PAIRING_KEYS[:7]), produced
        placed = block(ui, 'enum V3PlacedPairingPresentation {')
        for key in PAIRING_KEYS[8:]:
            assert 'return ("' + key + '",' in placed, key
        pairing_view = block(ui, 'struct V3PairingView: View {')
        assert 'V3LocalizedText("' + PAIRING_KEYS[7] + '")' in pairing_view
        assert 'V3LocalizedText(V3PairingSelectionPresentation.detail(' in pairing_view
        by_section['pairing_saved_selection_and_live_evidence'] = sorted(PAIRING_KEYS)
    if connection_keys(s):
        by_section['connection_detection_and_readiness'] = sorted(connection_keys(s))
    if local_refresh_keys(s):
        by_section['finite_local_refresh_diagnostics'] = sorted(local_refresh_keys(s))
    retained_copy = {}
    if retained_baseline is not None:
        historical = coverage(retained_baseline)
        current_keys = set().union(*map(set, by_section.values()))
        retained_keys = set(historical['keys']) - current_keys
        assert retained_keys == RETAINED_BASELINE_KEYS, retained_keys
        by_section['retained_baseline_copy'] = sorted(retained_keys)
        retained_copy = {
            key: {'source': SOURCE_PATHS['ui'],
                  'source_sha256': digest(retained_baseline['ui'].encode()),
                  'baseline_sections': sorted(section for section, keys in historical['by_section'].items() if key in keys),
                  'emitted_by_current_ui': False}
            for key in sorted(retained_keys)}
    keys = sorted(set().union(*map(set, by_section.values())))
    catalog = json.loads(s['catalog'])['strings']
    missing = catalog_missing(keys, catalog)
    return {'keys': keys, 'by_section': by_section, 'missing': missing,
            'retained_baseline_copy': retained_copy,
            'title_cases': titles, 'key_count': len(keys),
            'localized_value_count': len(keys) * len(LANGUAGES)}

def catalog_missing(keys, catalog):
    missing = []
    for key in keys:
        for language in LANGUAGES:
            unit = catalog.get(key, {}).get('localizations', {}).get(language, {}).get('stringUnit', {})
            if not unit.get('value') or unit.get('state') != 'translated':
                missing.append({'key': key, 'language': language})
    return missing

def write_bundle(out, name, rows):
    bundle = out / (name + '.bundle')
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / 'Info.plist').write_bytes(plistlib.dumps({
        'CFBundleIdentifier': 'test.synthetic.setup-localization.' + name,
        'CFBundleDevelopmentRegion': 'en', 'CFBundlePackageType': 'BNDL'}))
    for language, entries in rows.items():
        directory = bundle / (language + '.lproj')
        directory.mkdir(exist_ok=True)
        (directory / 'Localizable.strings').write_bytes(plistlib.dumps(entries))
    return [bundle / 'Info.plist'] + [bundle / (language + '.lproj') / 'Localizable.strings' for language in rows]

def expected_case_names(inventory):
    names = []
    missing_keys = sorted({row['key'] for row in inventory.get('baseline_missing', [])})
    for language in LANGUAGES:
        names.extend('actual-source-copy-' + language + '-' + key for key in inventory['keys'])
        for title in inventory['title_cases'].values():
            names.append('actual-typed-title-' + language + '-' + title)
            for variant in ['missing_locale', 'missing_title_entries', 'empty_title_entries']:
                names.append('owned-title-english-fallback-' + variant + '-' + language + '-' + title)
            for variant in ['empty_all_titles', 'empty_bundle']:
                names.append('owned-title-source-fallback-' + variant + '-' + language + '-' + title)
        for state in ['selected', 'available', 'reset', 'missing', 'changed', 'invalid', 'unknown']:
            names.append('actual-pairing-selection-producer-' + language + '-' + state)
        for state in ['disconnected', 'unobserved']:
            names.append('actual-pairing-unconfirmed-producer-' + language + '-' + state)
        for state in ['adoptedReady', 'adoptedConnectionNotReady']:
            names.append('actual-pairing-live-result-producer-' + language + '-' + state)
        for name in ['unknown-pairing-selection-stays-finite', 'unknown-provider-fails-closed',
                     'original-error-copy-unmodified', 'unknown-provider-cannot-be-title',
                     'prefix-cannot-grant-owned-title', 'diagnostic-id-preserved-without-provider-secret',
                     'diagnostic-original-unmodified', 'dynamic-detail-keeps-strict-locale-policy']:
            names.append(name + '-' + language)
        for variant in ['missing_locale', 'missing_title_entries', 'empty_title_entries', 'empty_all_titles', 'empty_bundle']:
            names.append('unknown-provider-fails-closed-' + variant + '-' + language)
        for frequency in ['interval', 'daily', 'weekly']:
            names.append('actual-schedule-format-' + language + '-' + frequency)
        names.extend('baseline-reproduces-missing-owned-copy-' + language + '-' + key for key in missing_keys)
    assert len(names) == len(set(names))
    return sorted(names)

def generate(root, out, baseline=None):
    s = read_sources(root)
    original = read_sources(baseline) if baseline else None
    inventory = coverage(s, original)
    assert not inventory['missing'], inventory['missing']
    assert inventory['title_cases'], 'Typed setup titles are required'
    out.mkdir(parents=True, exist_ok=True)
    catalog = json.loads(s['catalog'])['strings']
    rows = {language: {key: row['localizations'][language]['stringUnit']['value']
            for key, row in catalog.items()
            if 'stringUnit' in row.get('localizations', {}).get(language, {})}
            for language in LANGUAGES}
    title_keys = set(inventory['title_cases'].values())
    variants = {
        'complete': rows,
        'missing_locale': {'en': rows['en']},
        'missing_title_entries': {language: {key: value for key, value in entries.items()
            if language == 'en' or key not in title_keys} for language, entries in rows.items()},
        'empty_title_entries': {language: {key: '' if language != 'en' and key in title_keys else value
            for key, value in entries.items()} for language, entries in rows.items()},
        'empty_all_titles': {language: {key: '' if key in title_keys else value
            for key, value in entries.items()} for language, entries in rows.items()},
        'empty_bundle': {},
    }
    bundle_outputs = []
    for name, entries in variants.items():
        bundle_outputs.extend(write_bundle(out, name, entries))
    if baseline:
        original_inventory = coverage(original)
        assert {r['key'] for r in original_inventory['missing']} <= {'JIT-Less', 'Wi-Fi', 'CoreDevice'}
        baseline_catalog = json.loads(original['catalog'])['strings']
        bundle_outputs.extend(write_bundle(out, 'baseline', {language: {key: row['localizations'][language]['stringUnit']['value']
            for key, row in baseline_catalog.items()
            if 'stringUnit' in row.get('localizations', {}).get(language, {})} for language in LANGUAGES}))
        inventory['baseline_missing'] = catalog_missing(inventory['keys'], baseline_catalog)
        (out / 'baseline_missing_keys.json').write_text(json.dumps(sorted({row['key'] for row in inventory['baseline_missing']})) + '\n')
    (out / 'coverage.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + '\n')
    expected = {language: {key: rows[language][key] for key in inventory['keys']} for language in LANGUAGES}
    (out / 'expected.json').write_text(json.dumps(expected, ensure_ascii=False, indent=2) + '\n')
    # The entire real localization implementation is compiled by an authorized
    # native CI run. No independently reimplemented renderer stands in for it.
    harness = (HERE / 'setup_localization_harness.swift').read_text()
    pairing_producers = '\n'.join(block(s['ui'], anchor) for anchor in [PAIRING_ANCHOR, 'enum V3PlacedPairingPresentation {']) if PAIRING_ANCHOR in s['ui'] else ''
    assert pairing_producers, 'Combined candidate must contain the finite pairing producers'
    fixture = s['localization'] + '\n' + pairing_producers + '\n' + harness
    (out / 'fixture.swift').write_text(fixture)
    owned_outputs = [out / name for name in ['fixture.swift', 'coverage.json', 'expected.json']] + bundle_outputs
    if baseline:
        owned_outputs.append(out / 'baseline_missing_keys.json')
    manifest = {
        'schema': 'setup-localization-sources-v1', 'status': 'generated_not_compiled',
        'source_sha256': {key: digest(s[key].encode()) for key in SOURCE_PATHS},
        'baseline_sha256': {key: digest(original[key].encode()) for key in SOURCE_PATHS} if original else None,
        'fixture_inputs': {name: digest((HERE / name).read_bytes()) for name in [
            'generate_setup_localization_fixture.py', 'setup_localization_harness.swift', 'test_setup_localization_contract.py']},
        'key_count': inventory['key_count'], 'localized_value_count': inventory['localized_value_count'],
        'retained_baseline_copy': inventory['retained_baseline_copy'],
        'expected_native_case_count': len(expected_case_names(inventory)),
        'expected_case_names': expected_case_names(inventory),
        'output_sha256': {str(path.relative_to(out)): digest(path.read_bytes())
            for path in sorted(owned_outputs)},
        'execution_limits': 'No app/device/UI execution. Native renderer fixture execution requires explicit --run.'}
    (out / 'sources.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-root', '--livecontainer-root', dest='candidate_root', type=Path, required=True)
    parser.add_argument('--baseline-root', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    manifest = generate(args.candidate_root, args.output, args.baseline_root)
    if args.run:
        compiler = shutil.which('swiftc')
        if not compiler:
            raise SystemExit('Swift unavailable; compile and execution NOT RUN')
        subprocess.run([compiler, '-swift-version', '5', '-parse-as-library', str(args.output / 'fixture.swift'), '-o', str(args.output / 'fixture')], check=True)
        subprocess.run([str(args.output / 'fixture'), str(args.output)], check=True)
        manifest['status'] = 'synthetic_renderer_executed_pass'
        (args.output / 'sources.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('SETUP_LOCALIZATION_EXECUTED' if args.run else 'SETUP_LOCALIZATION_GENERATED_NOT_COMPILED')

if __name__ == '__main__':
    main()
