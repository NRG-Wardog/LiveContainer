"""Replay P2 resource checks against the actual compiled LiveContainer product.

Frozen translations are historical expected data, never execution evidence.
This standalone adapter imports no prior source override or historical gate.
Compiled resource equality does not establish runtime language/plural selection.
"""
import hashlib
import json
from pathlib import Path
import plistlib
import re

from consumer_contract import ordinary_bytes, require

LANGUAGES = ('en', 'zh-Hans', 'zh-Hant', 'he')
PERMISSION_LANGUAGES = ('en', 'zh-Hans', 'zh-Hant', 'he', 'zh_CN', 'zh_TW', 'zh_HK')
COVERAGE = {'catalogKeys': 2088, 'plainScalarKeysPerLanguage': 2081,
            'simplePluralKeys': 6, 'compoundPluralKeys': 1}
TRANSLATIONS_SHA256 = '23d7e7dc60e88e23cf80814eaf6328e998079150dbd7d10b52c38b4eafe3bcb5'
CONTRACT_SHA256 = '2c13e60cd322428393c79785e41067d60ee6f6f69a7d4ba6a09ac1fc5ff9ce9f'
CATALOG_SHA256 = 'a99d3776639f767c0b9a85432be6d129a5a95b437d0919304383ac9f4c39d9ba'
LIVE_CONTAINER_COMMIT = '545438e1f0a89fdef375f73273c5c9fc2735cbce'
MAX_RESOURCE_BYTES = 4 * 1024 * 1024
RESOURCE_NAMES = tuple(language + '.lproj/Localizable.' + suffix
                       for language in LANGUAGES for suffix in ('strings', 'stringsdict')) + tuple(
                       language + '.lproj/InfoPlist.strings' for language in PERMISSION_LANGUAGES)


def parse(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, 'duplicate resource JSON key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs)


def frozen_contract():
    root = Path(__file__).resolve().parent
    blobs = {}
    for name, expected in (('resource-contract.json', CONTRACT_SHA256),
                           ('compiled-translations.json', TRANSLATIONS_SHA256)):
        raw = ordinary_bytes(root, 'resources/' + name)
        require(hashlib.sha256(raw).hexdigest() == expected, 'frozen resource contract changed: ' + name)
        blobs[name] = parse(raw)
    contract, translations = blobs['resource-contract.json'], blobs['compiled-translations.json']
    require(contract['schema'] == 'p0-defensive-compiled-resource-contract-v1' and
            contract['livecontainer_commit'] == LIVE_CONTAINER_COMMIT and
            contract['catalog_path'] == 'Resources/Localizable.xcstrings' and
            contract['catalog_sha256'] == CATALOG_SHA256 and contract['catalog_keys'] == 2088,
            'frozen resource source identity differs')
    require(translations['schema'] == 'p2-compiled-translations-v2' and
            tuple(translations['languages']) == tuple(contract['languages']) == LANGUAGES and
            translations['coverage'] == COVERAGE, 'sealed resource inventory differs')
    require(len(contract['plural_keys']) == 6 and len(set(contract['plural_keys'])) == 6 and
            len(contract['compound_plural_keys']) == 1, 'plural inventory differs')
    require(tuple(contract['permission_languages']) == PERMISSION_LANGUAGES and
            len(contract['permission_purpose_keys']) == len(set(contract['permission_purpose_keys'])) == 32 and
            set(contract['permission_expected']) == set(PERMISSION_LANGUAGES), 'permission inventory differs')
    require(set(translations['translations']) == set(translations['compoundPlurals']) ==
            set(contract['simple_plurals']) == set(LANGUAGES), 'resource language closure differs')
    scalar_keys = None
    for language in LANGUAGES:
        keys = set(translations['translations'][language])
        require(len(keys) == 2081 and not keys & (set(contract['plural_keys']) | set(contract['compound_plural_keys'])) and
                len(keys | set(contract['plural_keys']) | set(contract['compound_plural_keys'])) == 2088,
                'scalar/plural coverage differs')
        require(scalar_keys is None or keys == scalar_keys, 'scalar keys differ between languages')
        scalar_keys = keys
        require(set(translations['compoundPlurals'][language]) == set(contract['compound_plural_keys']) and
                set(contract['simple_plurals'][language]) == set(contract['plural_keys']), 'plural language rows differ')
    return contract, translations


def check_format(value, expected):
    require(isinstance(value, str), 'plural format must be text')
    count = 0
    index = 0
    while index < len(value):
        if value[index] != '%':
            index += 1
            continue
        if value.startswith('%%', index):
            index += 2
            continue
        token = '%1$lld' if value.startswith('%1$lld', index) else '%lld' if value.startswith('%lld', index) else None
        require(token is not None, 'undeclared plural argument or format token')
        count += 1
        index += len(token)
    require(count == expected, 'plural Int64 argument count differs')


def verify_compiled_resources(read, names, livecontainer_root):
    """read takes a product-relative name; names is its retained file inventory."""
    contract, translations = frozen_contract()
    source = ordinary_bytes(Path(livecontainer_root), contract['catalog_path'])
    require(hashlib.sha256(source).hexdigest() == CATALOG_SHA256, 'current LiveContainer resource source differs')
    catalog = parse(source)
    require(len(catalog['strings']) == 2088, 'current catalog coverage differs')
    require(set(RESOURCE_NAMES) <= set(names), 'compiled product resource missing')
    compiled = {}

    def resource(name):
        raw = read(name)
        require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_RESOURCE_BYTES, 'compiled resource byte bound')
        values = plistlib.loads(raw)
        require(isinstance(values, dict) and bool(values), 'compiled resource dictionary required')
        compiled[name] = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
        return values

    for language in LANGUAGES:
        values = resource(language + '.lproj/Localizable.strings')
        plural_values = resource(language + '.lproj/Localizable.stringsdict')
        expected = translations['translations'][language]
        require(all(values.get(key) == value for key, value in expected.items()), 'compiled scalar translation differs: ' + language)
        require(not set(contract['compound_plural_keys']) & set(values), 'compound plural duplicated as scalar')
        for key, value in translations['compoundPlurals'][language].items():
            require(plural_values.get(key) == value, 'compiled compound plural differs: ' + language)
        for key in contract['plural_keys']:
            row = plural_values.get(key)
            require(isinstance(row, dict), 'missing simple plural row')
            fmt = row.get('NSStringLocalizedFormatKey')
            require(isinstance(fmt, str), 'simple plural format must be text')
            pattern = r'%(?:[1-9][0-9]*\$)?#@([A-Za-z_][A-Za-z0-9_]*)@'
            names_ = re.findall(pattern, fmt)
            require(len(names_) == 1 and fmt.count('%#') + len(re.findall(r'%[1-9][0-9]*\$#', fmt)) == 1,
                    'ambiguous compiled plural variable')
            require(all(position == '1' for position in re.findall(r'%([1-9][0-9]*)\$#', fmt)),
                    'wrong plural argument position')
            check_format(re.sub(pattern, '', fmt), 0)
            rule = row.get(names_[0])
            require(isinstance(rule, dict) and rule.get('NSStringFormatSpecTypeKey') == 'NSStringPluralRuleType' and
                    rule.get('NSStringFormatValueTypeKey') == 'lld', 'plural rule type differs')
            actual = {key_: value for key_, value in rule.items() if key_ not in
                      ('NSStringFormatSpecTypeKey', 'NSStringFormatValueTypeKey')}
            expected = contract['simple_plurals'][language][key]
            from_catalog = {category: value['stringUnit']['value'] for category, value in
                            catalog['strings'][key]['localizations'][language]['variations']['plural'].items()}
            require(actual == expected == from_catalog and actual.get('other'), 'compiled plural categories/text differ')
            for value in actual.values():
                check_format(value, 1)
    for language in PERMISSION_LANGUAGES:
        values = resource(language + '.lproj/InfoPlist.strings')
        require(set(values) == set(contract['permission_purpose_keys']) | {'CFBundleName'} and
                values.get('CFBundleName') == 'LiveContainer' and
                all(values[key] == contract['permission_expected'][language] for key in contract['permission_purpose_keys']),
                'compiled permission resource differs: ' + language)
    return {'localization': {'status': 'passed', 'failures': [], 'coverage': dict(COVERAGE),
                            'runtimePluralProof': 'requires native UI report and compound plural count combinations'},
            'exactPluralValues': {'status': 'passed', 'failures': [], 'checkedLanguageRows': 24,
                                  'runtimePluralSelection': False},
            'permissions': {'status': 'passed', 'failures': [],
                            'selection': 'OS-managed; independent of in-app language preference',
                            'inheritedTemporaryLocationDictionary': 'malformed/unconfigured entry unchanged; requires separate reviewed change'},
            'sourceContract': {'livecontainerCommit': LIVE_CONTAINER_COMMIT, 'catalogSHA256': CATALOG_SHA256,
                               'frozenContractSHA256': CONTRACT_SHA256, 'translationsSHA256': TRANSLATIONS_SHA256},
            'compiledResourceFiles': compiled}


def verify_app(app, livecontainer_root):
    app = Path(app)
    require(app.is_absolute() and app.is_dir() and app.resolve() == app, 'canonical compiled app path required')
    # The surrounding product gate proves bundle identity, executable and whole
    # product inventory. Read only the fixed resource files through this adapter.
    return verify_compiled_resources(lambda name: ordinary_bytes(app, name, MAX_RESOURCE_BYTES),
                                     RESOURCE_NAMES, livecontainer_root)
