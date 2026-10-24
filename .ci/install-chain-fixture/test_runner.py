"""Inert evidence-runner controls. Never launches Git, Swift, fixture binaries, or a network call."""
import importlib.util
import io
import json
import os
import plistlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('install_chain_runner', Path(__file__).with_name('run.py'))
gate = importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)

class Controls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.sources = self.root / 'sources'; self.sources.mkdir()
        self.harness = self.root / 'harness'; self.harness.mkdir()
        self.output = self.root / 'evidence/fixture'; self.output.parent.mkdir()
        self.recorder = self.root / 'record.py'; self.recorder.write_text("OWNERS = {'SideStore': ('NRG-Wardog/SideStore', '" + 'a'*40 + "')}\n")
        self.swiftc = self.root / 'inert-swiftc'; self.swiftc.write_text('never executable')
        self.developer = self.root / 'Xcode.app/Contents/Developer'
        self.sdk = self.developer / 'Platforms/MacOSX.platform/Developer/SDKs/MacOSX26.4.sdk'
        self.sdk.mkdir(parents=True)
        (self.sdk / 'SDKSettings.plist').write_bytes(plistlib.dumps({'CanonicalName':'macosx26.4'}))
        (self.sources / 'source.swift').write_text('actual input placeholder')
        (self.harness / 'generate.py').write_text('inert generator placeholder')
        self.variants = [dict(name=name, group='chain', swift=name + '.swift', cases=['one','two'],
                              expected_failures=['two'] if name == 'negative' else [])
                         for name in ['positive','negative','independent']]
        self.generated = {v['swift']: 'inert generated ' + v['name'] for v in self.variants}
        self.generated['sources.json'] = json.dumps({'schema':'source-test-v1'})
        self.contract = {'schema':'install-chain-ci-contract-v1', 'recorder_sha256':gate.sha(self.recorder.read_bytes()),
            'source_pins':{'SideStore':['NRG-Wardog/SideStore','a'*40]},
            'source_inputs_sha256':{'source.swift':gate.sha((self.sources/'source.swift').read_bytes())},
            'fixture_inputs_sha256':{'generate.py':gate.sha((self.harness/'generate.py').read_bytes())},
            'generator':'generate.py', 'generated_sha256':{k:gate.sha(v.encode()) for k,v in self.generated.items()},
            'source_receipt':'sources.json','variants':self.variants}
        self.contract_path = self.harness / 'contract.json'; gate.write(self.contract_path,self.contract)
        self.names=[];self.mutation=None
    def fake(self, argv, **kwargs):
        argv=list(map(str,argv)); name=None; raw=b'';code=0
        if str(self.recorder) in argv:
            name='acquire' if argv[-1]=='acquire' else 'snapshot-before' if argv[-1]=='install-chain-before' else 'snapshot-after'
            if name!='acquire': gate.write(self.root/'evidence'/('install-chain-before.json' if name=='snapshot-before' else 'install-chain-after.json'),{'same':'source graph'})
        elif argv[0]=='xcodebuild':name='xcode-version';raw=b'Xcode 26.4.1\nBuild version synthetic\n'
        elif argv[0]=='xcrun':
            if argv[1:] == ['--find','swiftc']:name='swiftc-path';raw=(str(self.swiftc)+'\n').encode()
            else:
                self.assertEqual(argv[1:], ['--sdk','macosx','--show-sdk-path'])
                name='macos-sdk-path';raw=(str(self.sdk)+'\n').encode()
        elif argv[0]==str(self.swiftc):
            if argv[-1]=='--version':name='swift-version';raw=b'Synthetic Swift 5\n'
            else:name='compile-'+Path(argv[-1]).name;Path(argv[-1]).write_text('inert non-executable output')
        elif str(self.harness/'generate.py') in argv:
            name='generate';dest=Path(argv[-1]);dest.mkdir()
            for k,v in self.generated.items():(dest/k).write_text(v)
        else:
            variant=next(v for v in self.variants if Path(argv[0]).name==v['name']);name='run-'+variant['name']
            raw=json.dumps({'schema':'install-chain-runtime-v1','group':'chain','cases':[{'name':n,'passed':n not in variant['expected_failures']} for n in variant['cases']],
                'passed':not variant['expected_failures'],'native_signing_device_executed':False}).encode();code=1 if variant['expected_failures'] else 0
        self.names.append(name)
        if self.mutation:
            result=self.mutation(name,argv,raw,code)
            if result is not None:return result
        return subprocess.CompletedProcess(argv,code,raw)
    def run_gate(self):
        old=Path.cwd()
        try:
            os.chdir(self.root)
            with mock.patch.object(gate,'HERE',self.harness),mock.patch.object(gate,'XCODE_DEVELOPER',self.developer),mock.patch.dict(os.environ,{'DEVELOPER_DIR':str(self.developer)}),mock.patch.object(gate.subprocess,'run',side_effect=self.fake):
                return gate.run(self.sources,self.recorder,self.output,self.contract_path)
        finally:os.chdir(old)
    def test_complete_positive_and_precise_negative_controls(self):
        report=self.run_gate();self.assertEqual(report['status'],gate.PASS)
        self.assertEqual(len(self.names),14);self.assertFalse(report['native_admission'])
        self.assertTrue(report['complete_source_graph_unchanged'])
        self.assertEqual(report['runtime']['negative']['passed'],False)
    def test_every_compile_uses_exact_resolved_macos_sdk_without_target_override(self):
        report=self.run_gate();self.assertEqual(report['status'],gate.PASS)
        rows=[r for r in report['commands'] if r['name'].startswith('compile-')]
        self.assertEqual(len(rows),3)
        for row in rows:
            self.assertEqual(row['argv'][1:6],['-sdk',str(self.sdk.resolve()),'-swift-version','5','-parse-as-library'])
            self.assertNotIn('-target',row['argv'])
        self.assertEqual(report['macos_sdk']['canonical_name'],'macosx26.4')
    def test_non_macos_sdk_is_rejected_before_generation_or_compile(self):
        (self.sdk/'SDKSettings.plist').write_bytes(plistlib.dumps({'CanonicalName':'iphoneos26.4'}))
        report=self.run_gate();self.assertNotEqual(report['status'],gate.PASS)
        self.assertNotIn('generate',self.names)
        self.assertFalse(any(n.startswith('compile-') for n in self.names))
    def test_all_compiler_failures_retained_and_independent_runtime_runs(self):
        def mutate(name,argv,raw,code):
            if name in ('compile-positive','compile-negative'):return subprocess.CompletedProcess(argv,1,b'compiler failure')
        self.mutation=mutate;report=self.run_gate()
        self.assertNotEqual(report['status'],gate.PASS)
        self.assertIn('compile-independent',self.names);self.assertIn('run-independent',self.names)
        self.assertNotIn('run-positive',self.names);self.assertNotIn('run-negative',self.names)
        self.assertEqual(len([r for r in report['failures'] if r['phase']=='compile']),2)
    def test_negative_unexpected_pass_is_failure(self):
        def mutate(name,argv,raw,code):
            if name=='run-negative':
                value=json.loads(raw);value['passed']=True
                for case in value['cases']:case['passed']=True
                return subprocess.CompletedProcess(argv,0,json.dumps(value).encode())
        self.mutation=mutate;report=self.run_gate();self.assertNotEqual(report['status'],gate.PASS);self.assertIn('run-independent',self.names)
    def test_negative_crash_cannot_satisfy_expected_failure(self):
        self.mutation=lambda name,argv,raw,code:subprocess.CompletedProcess(argv,-11,b'crash') if name=='run-negative' else None
        report=self.run_gate();self.assertNotEqual(report['status'],gate.PASS);self.assertIn('run-independent',self.names)
    def test_malformed_runtime_does_not_block_independent_group(self):
        self.mutation=lambda name,argv,raw,code:subprocess.CompletedProcess(argv,0,b'[]') if name=='run-positive' else None
        report=self.run_gate();self.assertNotEqual(report['status'],gate.PASS);self.assertIn('run-independent',self.names)
    def test_wrong_source_hash_stops_before_compile(self):
        (self.sources/'source.swift').write_text('changed')
        report=self.run_gate();self.assertNotEqual(report['status'],gate.PASS);self.assertNotIn('generate',self.names)
    def test_generated_extra_file_stops_before_compile(self):
        def mutate(name,argv,raw,code):
            if name=='generate':(Path(argv[-1])/'extra.swift').write_text('extra')
        self.mutation=mutate;report=self.run_gate();self.assertNotEqual(report['status'],gate.PASS);self.assertFalse(any(n.startswith('compile-') for n in self.names))
    def test_source_change_after_runtime_denies_success(self):
        def mutate(name,argv,raw,code):
            if name=='run-independent':(self.sources/'source.swift').write_text('changed by fixture')
        self.mutation=mutate;report=self.run_gate();self.assertNotEqual(report['status'],gate.PASS)
    def test_native_execution_claim_denies_success(self):
        def mutate(name,argv,raw,code):
            if name=='run-positive':
                value=json.loads(raw);value['native_signing_device_executed']=True
                return subprocess.CompletedProcess(argv,code,json.dumps(value).encode())
        self.mutation=mutate;report=self.run_gate();self.assertNotEqual(report['status'],gate.PASS);self.assertIn('run-independent',self.names)

if __name__=='__main__':unittest.main()
