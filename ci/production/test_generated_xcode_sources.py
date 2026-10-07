#!/usr/bin/env python3
"""Synthetic generator execution, real frozen intent inputs and historical commands."""
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import prove_graph as proof
import generated_xcode_sources as generated


class GeneratedSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.owners = {name: self.base / 'sources' / name for name in ('SideStore', 'LiveContainer')}
        self.results = self.base / 'results'
        self.provenance = self.base / 'artifacts/provenance'
        self.logs = self.provenance.parent / 'logs'
        for path in (*self.owners.values(), self.results, self.provenance, self.logs): path.mkdir(parents=True)
        for owner in self.owners.values(): proof.acquisition_git(owner, 'init', '-q')
        for catalogs in generated.TARGETS.values():
            for relative in catalogs:
                file = self.owners['SideStore'] / relative / 'Contents.json'
                file.parent.mkdir(parents=True)
                file.write_text('{"info":{"version":1}}\n')
        for name, _, group, relative, _, _ in generated.INTENTS:
            file = self.owners[name] / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(__file__).with_name('fixtures') / 'intentdefinitions' / (name + '-' + group + '.intentdefinition'), file)
        self.records = {}
        for name, owner in self.owners.items():
            proof.git(owner, 'add', '.')
            proof.git(owner, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Generator inputs')
            self.records[name] = proof.tree_entries(owner, 'HEAD')
        self.commands, self.file_lists, self.original = {'SideStore': [], 'LiveContainer': []}, {}, {}
        for target in generated.TARGETS:
            command, source, listing = generated.plan(self.owners['SideStore'], self.results, target)
            self.add_outputs('SideStore', command, [source], listing)
        for spec in generated.INTENTS:
            command, sources, listing = generated.intent_plan(self.owners[spec[0]], self.results, spec)
            self.add_outputs(spec[0], command, sources, listing)
        for listing, sources in self.file_lists.items():
            listing.parent.mkdir(parents=True, exist_ok=True)
            listing.write_text('\n'.join(map(str, sources)) + '\n')
        for owner, commands in self.commands.items():
            log = self.logs / ('sidestore-production-build.log' if owner == 'SideStore' else 'livecontainer-production-build.log')
            log.write_text('\n'.join(' '.join(shlex.quote(arg) if arg else '' for arg in args) for args in commands) + '\n')
        self.real_sha = generated.sha
        self.calls = []
        self.mode = 'pass'

    def add_outputs(self, name, command, sources, listing):
        self.commands[name].append(command)
        for source in sources:
            source.parent.mkdir(parents=True, exist_ok=True)
            data = ('// synthetic generated fixture: ' + str(source.relative_to(self.results)) + '\n').encode()
            source.write_bytes(data)
            self.original[str(source)] = data
        self.file_lists.setdefault(listing, []).extend(sources)

    def check_output(self, command, **kwargs):
        if command == ['xcodebuild', '-version']: return 'Xcode 26.4.1\nBuild version 17E202\n'
        if command[-1] == '--show-sdk-version': return '26.4\n'
        return str(generated.ACTOOL if command[-1] == 'actool' else generated.INTENT_TOOL) + '\n'

    def fake_run(self, command, **kwargs):
        self.calls.append(command)
        if Path(command[0]).name == 'actool':
            bundle = command[command.index('--bundle-identifier') + 1]
            target = 'AltWidgetExtension' if bundle.endswith('.AltWidget') else 'SideStore'
            _, original, _ = generated.plan(self.owners['SideStore'], self.results, target)
            for flag in generated.OUTPUT_FLAGS:
                self.assertTrue(Path(command[command.index(flag) + 1]).is_relative_to(self.results / 'generated-source-proof'))
            target = Path(command[command.index('--generate-swift-asset-symbols') + 1])
            target.write_bytes(self.original[str(original)] if self.mode != 'different' else b'changed output')
        else:
            self.assertEqual(command[command.index('-classPrefix') + 1], '')
            output = Path(command[command.index('-output') + 1])
            self.assertTrue(output.is_relative_to(self.results / 'generated-source-proof'))
            input_path = command[command.index('-input') + 1]
            spec = next(spec for spec in generated.INTENTS if str(self.owners[spec[0]] / spec[3]) == input_path
                        and spec[1] in Path(kwargs['cwd']).name)
            _, originals, _ = generated.intent_plan(self.owners[spec[0]], self.results, spec)
            for original in originals: (output / original.name).write_bytes(self.original[str(original)])
        return subprocess.CompletedProcess(command, 7 if self.mode == 'fail' else 0)

    def verify(self):
        def hashed(path):
            return 'a' * 64 if Path(path) in (generated.ACTOOL, generated.INTENT_TOOL) else self.real_sha(path)
        with mock.patch.object(generated.subprocess, 'check_output', side_effect=self.check_output), mock.patch.object(generated.subprocess, 'run', side_effect=self.fake_run), mock.patch.object(generated, 'sha', side_effect=hashed):
            return generated.verify_generated_sources(self.owners, self.results, self.provenance, self.records)

    def test_exact_nine_outputs_reproduce_without_overwriting_originals(self):
        report = self.verify()
        self.assertEqual(len(report['sources']), 9)
        self.assertEqual(len(self.calls), 6)
        for source, data in self.original.items(): self.assertEqual(Path(source).read_bytes(), data)
        self.assertEqual(set(report['sources']), set(generated.expected_sources(self.owners, self.results)))

    def test_proof_directory_symlink_cannot_redirect_generator_writes(self):
        (self.results / "generated-source-proof").symlink_to(self.owners['SideStore'], target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'proof directory was substituted'): self.verify()
        self.assertFalse(self.calls)

    def test_changed_catalog_bytes_or_mode_fail(self):
        file = self.owners['SideStore'] / generated.TARGETS['SideStore'][0] / 'Contents.json'
        file.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'executable mode'): self.verify()
        file.chmod(0o644)
        file.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'bytes differ'): self.verify()

    def test_extra_catalog_input_fails(self):
        (self.owners['SideStore'] / generated.TARGETS['SideStore'][0] / 'Injected.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'untracked generator inputs'): self.verify()

    def test_changed_recorded_generator_option_fails(self):
        log = self.logs / 'sidestore-production-build.log'
        log.write_text(log.read_text().replace('--platform iphoneos', '--platform iphonesimulator'))
        with self.assertRaisesRegex(ValueError, 'exact actool'): self.verify()

    def test_missing_or_wrong_target_compiler_list_fails(self):
        _, source, listing = generated.plan(self.owners['SideStore'], self.results, 'SideStore')
        listing.write_text(str(source.with_name('arbitrary.swift')) + '\n')
        with self.assertRaisesRegex(ValueError, 'exactly once'): self.verify()

    def test_generator_failure_or_different_bytes_fails(self):
        for mode, message in (('fail', 'regeneration failed'), ('different', 'differs from isolated')):
            self.mode = mode
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, message): self.verify()

    def test_modified_intent_input_fails(self):
        file = self.owners['SideStore'] / generated.INTENTS[0][3]
        file.write_bytes(file.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'bytes differ'): self.verify()

    def test_unobserved_intent_output_fails(self):
        _, files, _ = generated.intent_plan(self.owners['SideStore'], self.results, generated.INTENTS[0])
        (files[0].parent / 'Injected.swift').write_text('let injected = true')
        with self.assertRaisesRegex(ValueError, 'Unexpected generated intent'): self.verify()

    def test_dry_run_metadata_cannot_replace_actual_intent_generation(self):
        log = self.logs / 'livecontainer-production-build.log'
        log.write_text(log.read_text().replace('intentbuilderc generate ', 'intentbuilderc generate --dry-run '))
        with self.assertRaisesRegex(ValueError, 'real intentbuilderc'): self.verify()

    def test_historical_commands_match_only_the_six_reviewed_generators(self):
        fixture = json.loads(Path(__file__).with_name('fixtures').joinpath('xcode-generated-source-invocations.json').read_text())
        historical = []
        substitutions = {
            '/Users/runner/work/sidestore-auto-refresh/sidestore-auto-refresh/work/EmbeddedSideStore': str(self.owners['SideStore']),
            '/Users/runner/work/sidestore-auto-refresh/sidestore-auto-refresh/work/LiveContainer': str(self.owners['LiveContainer']),
            '/Users/runner/work/_temp/embedded-sidestore-derived-data': str(self.results / 'sidestore-derived'),
            '/Users/runner/work/_temp/livecontainer-derived-data': str(self.results / 'livecontainer-derived'),
        }
        for row in fixture['invocations']:
            args = row['command']
            for old, new in substitutions.items(): args = [arg.replace(old, new) for arg in args]
            historical.append(generated.normalize_intent_log(args))
        for commands in self.commands.values():
            for command in commands: self.assertIn(generated.canonical(command), historical)
        self.assertEqual(len(historical), 7)  # SideBackup remains an unselected actool command.


if __name__ == '__main__': unittest.main(verbosity=2)
