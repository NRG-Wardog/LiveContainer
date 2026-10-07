#!/usr/bin/env python3
"""Reproduce only the exact actool/intentbuilderc Swift outputs observed in Mac logs."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import tempfile

from assemble_isolated_workspace import verify_worktree_bytes
from validate_inputs import require

ACTOOL = Path('/Applications/Xcode_26.4.1.app/Contents/Developer/usr/bin/actool')
INTENT_TOOL = ACTOOL.with_name('intentbuilderc')
TARGETS = {
    'SideStore': ('AltStore/Core/Resources/Colors.xcassets', 'AltStore/Resources/Assets.xcassets', 'AltStore/Resources/Icons.xcassets'),
    'AltWidgetExtension': ('AltWidget/Assets.xcassets',),
}
OUTPUT_FLAGS = ('--compile', '--export-dependency-info', '--output-partial-info-plist',
                '--generate-swift-asset-symbols', '--generate-objc-asset-symbols', '--generate-asset-symbol-index')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plan(owner, results, target):
    require(target in TARGETS, 'Unreviewed generated Swift target')
    owner, results = owner.resolve(), results.resolve()
    base = results / 'sidestore-derived/Build/Intermediates.noindex/AltStore.build/Release-iphoneos' / (target + '.build')
    generated = base / 'DerivedSources/GeneratedAssetSymbols.swift'
    extension = '.app' if target == 'SideStore' else '.appex'
    args = [str(ACTOOL)] + [str(owner / path) for path in TARGETS[target]]
    args += ['--compile', str(results / 'sidestore-derived/Build/Products/Release-iphoneos' / (target + extension)),
             '--output-format', 'human-readable-text', '--notices', '--warnings',
             '--export-dependency-info', str(base / 'assetcatalog_dependencies'),
             '--output-partial-info-plist', str(base / 'assetcatalog_generated_info.plist')]
    if target == 'SideStore': args += ['--app-icon', 'AppIcon']
    args += ['--compress-pngs', '--enable-on-demand-resources', 'YES' if target == 'SideStore' else 'NO']
    args += ['--optimization', 'space'] if target == 'SideStore' else ['--standalone-icon-behavior', 'all']
    args += ['--development-region', 'en', '--target-device', 'iphone', '--target-device', 'ipad',
             '--minimum-deployment-target', '15.0', '--platform', 'iphoneos', '--bundle-identifier',
             'com.SideStore.SideStore' + ('.AltWidget' if target == 'AltWidgetExtension' else ''),
             '--generate-swift-asset-symbol-extensions', 'NO', '--generate-swift-asset-symbols', str(generated),
             '--generate-objc-asset-symbols', str(generated.with_suffix('.h')),
             '--generate-asset-symbol-index', str(generated.with_name('GeneratedAssetSymbols-Index.plist'))]
    file_list = base / 'Objects-normal/arm64' / (target + '.SwiftFileList')
    return args, generated, file_list


def canonical(args):
    return [str(Path(arg).resolve()) if Path(arg).is_absolute() else arg for arg in args]


def catalog_proof(owner, entries, target):
    catalogs = TARGETS[target]
    selected = {name: value for name, value in entries.items() if any(name.startswith(path + '/') for path in catalogs)}
    require(selected, 'No committed asset catalog inputs')
    actual = set()
    for catalog in catalogs:
        directory = owner / catalog
        require(directory.is_dir() and not directory.is_symlink(), 'Missing/substituted asset catalog')
        for file in directory.rglob('*'):
            require(not file.is_symlink(), 'Asset catalog symlink is unreviewed')
            if file.is_file(): actual.add(str(file.relative_to(owner)))
    require(actual == set(selected), 'Asset catalog has missing or untracked generator inputs')
    for relative in selected:
        for parent in (owner / relative).parents:
            if parent == owner: break
            require(not parent.is_symlink(), 'Asset catalog parent was substituted')
    verify_worktree_bytes(owner, selected)
    return {name: {'mode': mode, 'blob': blob, 'sha256': sha(owner / name)} for name, (mode, blob) in selected.items()}


def verify_assets(owner, results, provenance, entries):
    owner, results = owner.resolve(strict=True), results.resolve(strict=True)
    versions = subprocess.check_output(['xcodebuild', '-version'], text=True).strip().splitlines()
    require(versions == ['Xcode 26.4.1', 'Build version 17E202'], 'Unreviewed asset generator toolchain')
    require(subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-version'], text=True).strip() == '26.4', 'Unreviewed asset generator SDK')
    tool = Path(subprocess.check_output(['xcrun', '--find', 'actool'], text=True).strip())
    require(tool.resolve() == ACTOOL.resolve(), 'Asset generator is outside the reviewed Xcode')
    log = provenance.parent / 'logs/sidestore-production-build.log'
    invocations = [shlex.split(line) for line in log.read_text().splitlines() if '--generate-swift-asset-symbols' in line]
    proof_root = results / 'generated-source-proof'
    proof_root.mkdir(exist_ok=True)
    require(not proof_root.is_symlink() and proof_root.resolve() == proof_root, 'Generator proof directory was substituted')
    report = {'toolchain': versions, 'actool': str(tool), 'actool_sha256': sha(tool), 'build_log_sha256': sha(log), 'sources': {}}
    for target in TARGETS:
        wanted, generated, file_list = plan(owner, results, target)
        matching = [args for args in invocations if canonical(args) == canonical(wanted)]
        require(len(matching) == 1, 'Missing, duplicated or changed exact actool invocation for ' + target)
        catalogs = catalog_proof(owner, entries, target)
        require(generated.is_file() and not generated.is_symlink() and generated.resolve() == generated,
                'Generated asset Swift path is missing or substituted')
        require(file_list.is_file() and not file_list.is_symlink() and file_list.resolve() == file_list, 'Target Swift compiler list is missing or substituted')
        listed = []
        for line in file_list.read_text().splitlines():
            tokens = [line] if Path(line).is_file() else shlex.split(line)
            require(len(tokens) == 1, 'Unknown target compiler list entry')
            listed.append(Path(tokens[0]).resolve())
        require(listed.count(generated) == 1, 'Generated asset Swift must occur exactly once in its target compiler list')
        original = generated.read_bytes()
        with tempfile.TemporaryDirectory(prefix=target + '-', dir=proof_root) as scratch:
            scratch = Path(scratch)
            replay = list(wanted)
            redirected = {}
            for flag in OUTPUT_FLAGS:
                index = replay.index(flag) + 1
                destination = scratch / flag.removeprefix('--') / Path(replay[index]).name
                destination.parent.mkdir(parents=True, exist_ok=True)
                if flag == '--compile': destination.mkdir()
                redirected[flag] = destination
                replay[index] = str(destination)
            stdout = provenance / (target + '-actool-reproduction.stdout.txt')
            stderr = provenance / (target + '-actool-reproduction.stderr.txt')
            with stdout.open('w') as out, stderr.open('w') as err:
                result = subprocess.run(replay, cwd=scratch, stdout=out, stderr=err, timeout=180, check=False)
            command_report = {'original': matching[0], 'replay': replay, 'exit_code': result.returncode,
                              'outputs': {flag: str(path) for flag, path in redirected.items()}}
            (provenance / (target + '-actool-commands.json')).write_text(json.dumps(command_report, indent=2) + '\n')
            require(result.returncode == 0, 'Asset symbol regeneration failed for ' + target)
            recreated = redirected['--generate-swift-asset-symbols']
            require(recreated.is_file() and not recreated.is_symlink() and recreated.resolve().is_relative_to(scratch), 'Regenerated asset Swift is absent or escaped proof scratch')
            require(original == recreated.read_bytes(), 'Generated asset Swift differs from isolated reproduction')
        require(generated.read_bytes() == original, 'Original generated Swift changed during proof')
        catalog_proof(owner, entries, target)
        copy = target + '-GeneratedAssetSymbols.swift.txt'
        (provenance / copy).write_bytes(original)
        report['sources'][str(generated)] = {'kind': 'reproduced-actool-assets', 'target': target,
            'configuration': 'Release-iphoneos', 'architecture': 'arm64', 'sha256': sha(generated),
            'file_list': str(file_list), 'file_list_sha256': sha(file_list), 'catalogs': catalogs, 'copy': copy}
    (provenance / 'generated-asset-sources.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


# Exact observed target/input/output inventory; no general DerivedSources exemption.
INTENTS = (
    ('SideStore', 'SideStore', 'ViewApp', 'Shared/Intents/ViewApp.intentdefinition', ('ViewAppIntent.swift', 'App.swift'), '0ef32fe205add816a385503c5f377d6ce9597bb4'),
    ('SideStore', 'SideStore', 'Intents', 'AltStore/Intents/Legacy/Intents.intentdefinition', ('RefreshAllIntent.swift',), '2271d049d0a24684f50d8ca5a52ca1b9c47ebbe9'),
    ('SideStore', 'AltWidgetExtension', 'ViewApp', 'Shared/Intents/ViewApp.intentdefinition', ('ViewAppIntent.swift', 'App.swift'), '0ef32fe205add816a385503c5f377d6ce9597bb4'),
    ('LiveContainer', 'LiveContainerSwiftUI', 'ViewApp', 'LiveContainerSwiftUI/ViewApp.intentdefinition', ('ViewAppIntent.swift', 'App.swift'), '8d8b3a167893bf346ff7f1fd89112471c8c50cdf'),
)


def intent_plan(owner, results, spec):
    name, target, group, source, files, _ = spec
    result_name, project = ('sidestore-derived', 'AltStore') if name == 'SideStore' else ('livecontainer-derived', 'LiveContainer')
    base = results.resolve() / result_name / 'Build/Intermediates.noindex' / (project + '.build') / 'Release-iphoneos' / (target + '.build')
    output = base / 'DerivedSources/IntentDefinitionGenerated' / group
    args = [str(INTENT_TOOL), 'generate', '-input', str(owner.resolve() / source), '-output', str(output),
            '-classPrefix', '', '-language', 'Swift', '-swiftVersion', '5.0', '-visibility', 'public']
    if name == 'LiveContainer': args += ['-moduleName', 'LiveContainerSwiftUI']
    return args, [output / file for file in files], base / 'Objects-normal/arm64' / (target + '.SwiftFileList')


def normalize_intent_log(args):
    # Xcode's textual command loses only this known empty value. Do not replay
    # '-language' as classPrefix or normalize other unknown missing arguments.
    args = list(args)
    if '-classPrefix' in args:
        position = args.index('-classPrefix') + 1
        if position < len(args) and args[position] == '-language': args.insert(position, '')
    return canonical(args)


def expected_sources(owners, results):
    known = {}
    for target in TARGETS:
        _, source, file_list = plan(owners['SideStore'], results, target)
        known[str(source)] = {'owner': 'SideStore', 'target': target, 'file_list': str(file_list), 'kind': 'reproduced-actool-assets'}
    for spec in INTENTS:
        _, files, file_list = intent_plan(owners[spec[0]], results, spec)
        for source in files:
            known[str(source)] = {'owner': spec[0], 'target': spec[1], 'file_list': str(file_list), 'kind': 'reproduced-intentbuilderc'}
    return known


def verify_generated_sources(owners, results, provenance, records):
    report = verify_assets(owners['SideStore'], results, provenance, records['SideStore'])
    require(Path(subprocess.check_output(['xcrun', '--find', 'intentbuilderc'], text=True).strip()).resolve() == INTENT_TOOL.resolve(), 'Intent generator is outside reviewed Xcode')
    report['intentbuilderc_sha256'] = sha(INTENT_TOOL)
    proof_root = results / 'generated-source-proof'
    for spec in INTENTS:
        name, target, group, relative, filenames, frozen_blob = spec
        owner = owners[name].resolve(strict=True)
        require(records[name].get(relative) == ('100644', frozen_blob), 'Unreviewed intentdefinition source identity')
        source = owner / relative
        for parent in source.parents:
            if parent == owner: break
            require(not parent.is_symlink(), 'Intent input parent substituted')
        verify_worktree_bytes(owner, {relative: records[name][relative]})
        wanted, generated, file_list = intent_plan(owner, results, spec)
        log = provenance.parent / 'logs' / ('sidestore-production-build.log' if name == 'SideStore' else 'livecontainer-production-build.log')
        matching = [shlex.split(line) for line in log.read_text().splitlines()
                    if 'intentbuilderc generate ' in line and normalize_intent_log(shlex.split(line)) == canonical(wanted)]
        require(len(matching) == 1, 'Missing, duplicated or changed real intentbuilderc command for ' + target + '/' + group)
        require(file_list.is_file() and not file_list.is_symlink() and file_list.resolve() == file_list, 'Intent target compiler list is missing/substituted')
        listed = []
        for line in file_list.read_text().splitlines():
            if not line.strip(): continue
            tokens = [line] if Path(line).is_file() else shlex.split(line)
            require(len(tokens) == 1, 'Unknown intent compiler list entry')
            listed.append(Path(tokens[0]).resolve())
        directory = generated[0].parent
        require(set(directory.rglob('*.swift')) == set(generated), 'Unexpected generated intent Swift inventory')
        originals = {}
        for file in generated:
            require(file.is_file() and not file.is_symlink() and file.resolve() == file and listed.count(file) == 1, 'Intent Swift is missing/substituted or absent from its exact target compiler list')
            originals[file.name] = file.read_bytes()
        label = target + '-' + group
        with tempfile.TemporaryDirectory(prefix=label + '-', dir=proof_root) as scratch:
            scratch = Path(scratch)
            replay = list(wanted)
            output = scratch / 'output'
            output.mkdir()
            replay[replay.index('-output') + 1] = str(output)
            with (provenance / (label + '-intentbuilderc.stdout.txt')).open('w') as out, (provenance / (label + '-intentbuilderc.stderr.txt')).open('w') as err:
                completed = subprocess.run(replay, cwd=scratch, stdout=out, stderr=err, timeout=180, check=False)
            (provenance / (label + '-intentbuilderc-commands.json')).write_text(json.dumps({'original': matching[0], 'replay': replay, 'exit_code': completed.returncode}, indent=2) + '\n')
            require(completed.returncode == 0, 'Intent Swift regeneration failed')
            require(set(output.rglob('*.swift')) == {output / file for file in filenames}, 'Unexpected regenerated intent Swift inventory')
            for file in generated:
                reproduced = output / file.name
                require(not reproduced.is_symlink() and reproduced.resolve().is_relative_to(scratch) and reproduced.read_bytes() == originals[file.name], 'Intent Swift differs from isolated reproduction')
        verify_worktree_bytes(owner, {relative: records[name][relative]})
        for file in generated:
            require(file.read_bytes() == originals[file.name], 'Original intent Swift changed during proof')
            copy = label + '-' + file.name + '.txt'
            (provenance / copy).write_bytes(originals[file.name])
            report['sources'][str(file)] = {'kind': 'reproduced-intentbuilderc', 'owner': name, 'target': target,
                'configuration': 'Release-iphoneos', 'architecture': 'arm64', 'sha256': sha(file), 'file_list': str(file_list),
                'file_list_sha256': sha(file_list), 'input': {'path': relative, 'mode': '100644', 'blob': frozen_blob, 'sha256': sha(source)},
                'build_log_sha256': sha(log), 'copy': copy}
    for row in report['sources'].values(): row.setdefault('owner', 'SideStore')
    require(set(report['sources']) == set(expected_sources(owners, results)), 'Incomplete reviewed generated Swift inventory')
    (provenance / 'generated-xcode-sources.json').write_text(json.dumps(report, indent=2) + '\n')
    return report
