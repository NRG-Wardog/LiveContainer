#!/usr/bin/env python3
"""Source-extracted Issue #48 fixture. No Apple account, signing or device IO.
Run generated Swift on macOS: swiftc -parse-as-library Fixture.swift -o fixture.
"""
import argparse, hashlib, json, re
from pathlib import Path

CASE_NAMES = ['fresh-nil-local-empty-excess-prompts-and-selects', 'fresh-target-also-passed-as-local-empty-excess', 'reinstall-matching-extensions', 'update-matching-extensions', 'update-added-extension-reviews-all', 'update-no-previous-extensions', 'remove-multiple-keeps-required', 'keep-all-register-individually', 'keep-all-main-profile', 'remove-all-explicit', 'cancel-no-files-removed', 'unknown-selection-no-files-removed', 'empty-selection-no-files-removed', 'no-extensions-no-prompt', 'preset-keep-no-prompt', 'preset-main-profile-no-prompt', 'preset-remove-no-prompt']
FIXTURE_FILES = ["generate_fixture.py", "Doubles.swift", "Cases.swift", "run.sh"]

def block(source, anchor):
    assert source.count(anchor) == 1, anchor
    start = source.index(anchor)
    pos = source.index('{', start)
    depth = 1
    end = pos + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]

def generate(root, output):
    ss = root/'SideStore'
    paths = {
        'service': ss/'AltStore/AppDelegate.swift',
        'handlers': ss/'SideStore/Core/Operations/PipelineExecutionHandler.swift',
        'removal': ss/'SideStore/Core/Operations/PipelineOperations/RemoveAppExtensionsOperation.swift',
        'steps': ss/'SideStore/Core/Operations/OperationStepDefinition.swift',
        'runner': ss/'SideStore/Core/Operations/PipelineRunner.swift',
        'executor': ss/'SideStore/Core/Operations/PipelineExecutor.swift',
        'profiles': ss/'SideStore/Core/Operations/PipelineOperations/FetchProvisioningProfilesOperation.swift',
        'install': ss/'SideStore/Core/Operations/PipelineOperations/InstallAppOperation.swift',
        'ui': root/'LiveContainer/LiveContainerSwiftUI/Views/V3UnifiedShell.swift',
    }
    s = {k:p.read_text() for k,p in paths.items()}
    # Integration wiring checks are STATIC, not an executed native pipeline.
    for name in ['install', 'resign']:
        body = re.search(r'static let '+name+r': \[PipelineExecutionStep\] = \[(.*?)\n    \]', s['steps'], re.S)[1]
        order = re.findall(r'PipelineExecutionStep\(\.(\w+)', body)
        assert order.index('removeAppExtensions') < order.index('fetchProvisioningProfiles') < order.index('resignApp') < order.index('installApp')
    refresh = re.search(r'static let refresh: \[PipelineExecutionStep\] = \[(.*?)\n    \]', s['steps'], re.S)[1]
    assert '.removeAppExtensions' not in refresh
    assert 'context.useMainProfile = app.useMainProfile' in s['runner']
    assert 'installedApp.useMainProfile = context.useMainProfile' in s['install']
    assert 'guard !self.context.useMainProfile, !appExtensions.isEmpty else' in s['profiles']
    assert 'let appExtensions = targetAppBundle.appExtensions' in s['profiles']
    assert 'RemoveAppExtensionsOperation(context: context, localAppExtensions: localAppExtensions)' in s['executor']
    assert 'let handler = V3HeadlessPipelineHandler(sessionID: id)' in s['service']
    assert 'handler: handler, context: baseContext)' in s['service']
    parts = []
    for key, anchor in [('handlers','enum ExtensionRemovalDecision:'), ('handlers','enum V3ReuseMainExplanation {'), ('service','enum V3ExtensionRemovalPromptPolicy {'), ('service','enum V3PromptSelectionPolicy {'), ('ui','enum V3MultiSelectPromptAnswerPolicy {'), ('removal','public enum AppExtensionCustomization:'), ('removal','final class RemoveAppExtensionsOperation:')]:
        parts.append(block(s[key], anchor))
    handler = block(s['service'], '    func selectAppExtensionsToRemove(appBundle: ALTApplication,')
    fixture = (Path(__file__).parent/'Doubles.swift').read_text() + '\n' + '\n'.join(parts)
    fixture += '\nfinal class TestHandler {\nvar answer: [String:String] = [:]\nvar prompts = 0\nvar offered: [[String:String]] = []\nfunc ask(kind: String, title: String, message: String, options: [[String:String]]) async throws -> [String:String] { prompts += 1; offered = options; return answer }\n' + handler + '\n}\n'
    fixture += (Path(__file__).parent/'Cases.swift').read_text()
    # Check member-level closure too: a type-name-only scan misses enum cases
    # and newly accessed properties at otherwise unchanged SDK boundaries.
    decision = block(s['handlers'], 'enum ExtensionRemovalDecision:')
    for case in ('cancel', 'keepAll', 'keepAllValidatedReuseMain', 'removeAll', 'removeSelected'):
        assert re.search(r'case\s+' + case + r'\b', decision), case
    for member in ('var validatedReuseMain = false', 'var isAltStoreApp = false',
                   'enum Info { static let activeBundleIdentifier'):
        assert member in fixture, member

    actual_cases = re.findall(r'try await run\("([^"]+)"', (Path(__file__).parent/'Cases.swift').read_text())
    assert actual_cases == CASE_NAMES and len(set(CASE_NAMES)) == 17
    old = 'targetExtensions: appBundle.appExtensions,'
    assert fixture.count(old) == 1
    negative = fixture.replace(old, 'targetExtensions: excessExtensions,')
    output.mkdir(parents=True, exist_ok=True)
    (output/'Fixture.swift').write_text(fixture)
    (output/'NegativeControl.swift').write_text(negative)
    receipt = {'schema':2, 'case_names':CASE_NAMES, 'fixture_files_sha256':{name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest() for name in FIXTURE_FILES}, 'generated_sha256':{'Fixture.swift':hashlib.sha256(fixture.encode()).hexdigest(), 'NegativeControl.swift':hashlib.sha256(negative.encode()).hexdigest()}, 'static_wiring_checks':'passed', 'swift_execution':'not-run-by-generator', 'native_signing_device_install':'not-run', 'source_sha256':{k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in paths.items()}, 'fixture_sha256':hashlib.sha256(fixture.encode()).hexdigest()}
    (output/'source-receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, indent=2))

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); generate(a.root,a.output)
