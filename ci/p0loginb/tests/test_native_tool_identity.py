"""Synthetic multicall/path tests; never invoke Rust, brew or native app targets."""
import copy,hashlib,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest import mock
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import native_build as native
class NativeToolIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        self.cellar=self.root/'Cellar/rustup/1.29.0/bin';self.cellar.mkdir(parents=True)
        self.binary=self.cellar/'rustup-init';self.binary.write_text('#!/bin/sh\nprintf "%s\\n" "$0"\n');self.binary.chmod(0o755)
        self.proxy=self.cellar/'rustup';self.proxy.symlink_to('rustup-init')
        self.bin=self.root/'bin';self.bin.mkdir();self.selected=self.bin/'rustup';self.selected.symlink_to('../Cellar/rustup/1.29.0/bin/rustup')
    def test_selected_multicall_invocation_is_preserved_and_resolved_bytes_attested(self):
        proof=native.native_tool(self.selected)
        self.assertEqual(proof['path'],str(self.selected));self.assertEqual(proof['resolved_path'],str(self.binary))
        self.assertEqual(proof['sha256'],hashlib.sha256(self.binary.read_bytes()).hexdigest())
        self.assertEqual(proof['symlink_chain'],[{'path':str(self.selected),'target':'../Cellar/rustup/1.29.0/bin/rustup'},{'path':str(self.proxy),'target':'rustup-init'}])
        command=native.rust_command(Path(proof['path']),'cargo','-Vv')
        self.assertEqual(command[0],self.selected);self.assertNotEqual(command[0],self.binary)
        # Controlled host shell fixture demonstrates basename-sensitive dispatch.
        observed=subprocess.check_output([proof['path']],timeout=5).decode().strip()
        wrong=subprocess.check_output([proof['resolved_path']],timeout=5).decode().strip()
        self.assertEqual(Path(observed).name,'rustup');self.assertEqual(Path(wrong).name,'rustup-init')
    def test_parent_directory_symlink_is_recorded_without_changing_invocation(self):
        alias=self.root/'opt';alias.symlink_to(self.cellar,target_is_directory=True)
        selected=alias/'rustup';proof=native.native_tool(selected)
        self.assertEqual(proof['path'],str(selected));self.assertEqual(proof['resolved_path'],str(self.binary))
        self.assertEqual(proof['symlink_chain'][0],{'path':str(alias),'target':str(self.cellar)})
    def test_chain_retarget_to_identical_bytes_is_rejected_before_owned_command(self):
        candidate=native.NativeBuildMixin();candidate.native_tools={'rustup':native.native_tool(self.selected)}
        other=self.cellar/'other';other.write_bytes(self.binary.read_bytes());other.chmod(0o755)
        self.proxy.unlink();self.proxy.symlink_to('other')
        candidate.run=mock.Mock()
        with self.assertRaisesRegex(ValueError,'symlink chain or executable bytes changed'):candidate.native_run('tool',[self.selected])
        candidate.run.assert_not_called()
    def test_same_target_chain_rewrite_and_executable_mutation_reject(self):
        proof=native.native_tool(self.selected);self.selected.unlink();self.selected.symlink_to(self.proxy)
        self.assertNotEqual(native.native_tool(self.selected),proof)
        candidate=native.NativeBuildMixin();candidate.native_tools={'rustup':native.native_tool(self.selected)};candidate.run=mock.Mock()
        self.binary.write_text('#!/bin/sh\nexit 9\n')
        with self.assertRaises(ValueError):candidate.native_run('tool',[self.selected])
        candidate.run.assert_not_called()
    def test_retarget_during_hash_observation_rejects(self):
        original=native.tool_resolution;calls=[]
        def changing(path):
            resolved,links=original(path);calls.append(1)
            return (resolved,links) if len(calls)==1 else (resolved,links+[{'path':'/synthetic','target':'changed'}])
        with mock.patch.object(native,'tool_resolution',side_effect=changing),self.assertRaisesRegex(ValueError,'during observation'):native.native_tool(self.selected)
    def test_post_command_retarget_prevents_success(self):
        candidate=native.NativeBuildMixin();candidate.native_tools={'rustup':native.native_tool(self.selected)}
        def change(*args,**kwargs):self.proxy.unlink();self.proxy.symlink_to(self.binary);return 'synthetic-success'
        candidate.run=mock.Mock(side_effect=change)
        with self.assertRaises(ValueError):candidate.native_run('tool',[self.selected])
        candidate.run.assert_called_once()
    def test_cycle_broken_non_executable_and_non_file_reject(self):
        self.proxy.unlink();self.proxy.symlink_to('rustup')
        with self.assertRaises(ValueError):native.native_tool(self.selected)
        self.proxy.unlink();self.proxy.symlink_to('missing')
        with self.assertRaises(FileNotFoundError):native.native_tool(self.selected)
        self.proxy.unlink();self.proxy.symlink_to('rustup-init');self.binary.chmod(0o644)
        with self.assertRaises(ValueError):native.native_tool(self.selected)
        with self.assertRaises(ValueError):native.native_tool(self.cellar)
        with self.assertRaises(ValueError):native.native_tool(Path('relative/rustup'))
    def test_regular_tool_and_later_executable_bit_removal(self):
        proof=native.native_tool(self.binary)
        self.assertEqual(proof['path'],proof['resolved_path']);self.assertEqual(proof['symlink_chain'],[])
        candidate=native.NativeBuildMixin();candidate.native_tools={'rustup':proof};candidate.run=mock.Mock(return_value='synthetic')
        self.assertEqual(candidate.native_run('rustc-version',native.rust_command(self.binary,'rustc','-Vv')),'synthetic')
        self.binary.chmod(0o644)
        with self.assertRaises(ValueError):candidate.native_run('rustc-version',native.rust_command(self.binary,'rustc','-Vv'))
        candidate.run.assert_called_once()
    def test_first_toolchain_install_passes_selected_alias_to_owned_runner(self):
        class StopBeforeAnyNativeExecution(Exception):pass
        candidate=native.NativeBuildMixin();candidate.work=self.root/'work';candidate.work.mkdir();candidate.evidence=self.root/'evidence'
        brew=self.bin/'brew';brew.write_text('#!/bin/sh\nexit 0\n');brew.chmod(0o755)
        candidate.run=mock.Mock(side_effect=StopBeforeAnyNativeExecution)
        with mock.patch.dict(os.environ,{'PATH':str(self.bin),'HOME':str(self.root),'DEVELOPER_DIR':native.TOOLCHAIN['developer_dir']}):
            with self.assertRaises(StopBeforeAnyNativeExecution):candidate.native_prerequisites()
        candidate.run.assert_called_once();label,argv=candidate.run.call_args.args
        self.assertEqual(label,'rust-toolchain-install');self.assertEqual(argv[0],self.selected)
        self.assertEqual(argv[1:4],['toolchain','install',native.RUST_TOOLCHAIN])
        self.assertEqual(candidate.native_tools['rustup']['resolved_path'],str(self.binary))
    def test_actual_failed_capture_proves_old_argv_and_preserves_failure(self):
        root=HERE/'tests/fixtures/rustup-multicall-failure';provenance=json.loads((root/'provenance.json').read_bytes())
        self.assertEqual(provenance['artifact_sha256'],'7573467ccabea8f8aa0513a93b88f6f81cf234a472f7c780fd8458685831cad6')
        for original,digest in provenance['members'].items():self.assertEqual(hashlib.sha256((root/Path(original).name).read_bytes()).hexdigest(),digest)
        command=json.loads((root/'rust-toolchain-install.command.json').read_bytes());settled=json.loads((root/'rust-toolchain-install.settlement.json').read_bytes())
        self.assertEqual(command['argv'][0],'/opt/homebrew/Cellar/rustup/1.29.0/bin/rustup-init')
        self.assertEqual(command['argv'][1:4],['toolchain','install',native.RUST_TOOLCHAIN]);self.assertEqual(settled['returncode'],1)
        self.assertIn("unexpected argument 'toolchain'",(root/'rust-toolchain-install.stderr.log').read_text())
        self.assertFalse(provenance['compilation_started'])
if __name__=='__main__':unittest.main(verbosity=2)
