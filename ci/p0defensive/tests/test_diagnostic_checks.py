"""Offline generated-fixture/result mutation tests; never execute a real engine."""
import copy,json,re,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import diagnostic_checks as d
from inventory import parse,sha
OWNER=HERE/'tests/fixtures/diagnostic-source'

class DiagnosticTests(unittest.TestCase):
    def test_original_fixture_bytes_match_exact_reviewed_source(self):
        inventory=parse((HERE/'reviewed/aggregate-source-inventory.json').read_bytes())
        self.assertEqual(inventory['tree'],'9fa391fa6486a08e2d3db96b0fc9b1c0b372fb65')
        for path in OWNER.rglob('*'):
            if path.is_file():self.assertEqual(sha(path.read_bytes()),inventory['files'][str(path.relative_to(OWNER))]['sha256'])
    def test_native_adaptation_is_four_literal_only_fixture_replacements(self):
        actual,receipt=d.native_fixture(OWNER)
        self.assertEqual(len(receipt['literal_replacements']),4)
        original=(OWNER/'.ci/native-tests/fixtures/bounded_fault_host.cpp').read_text();text=original
        for replacement in receipt['literal_replacements']:
            self.assertEqual(text.count(replacement['before']),1)
            text=text.replace(replacement['before'],replacement['after'],1)
        self.assertEqual(actual,text);self.assertEqual(receipt['original_sha256'],sha(original.encode()));self.assertEqual(receipt['generated_sha256'],sha(actual.encode()))
        self.assertNotIn('#undef __APPLE__',actual);self.assertNotIn('openssl/',actual)
        self.assertNotIn('BOUNDED_FAULT_HOST_APPLE_DIGEST',actual)
        self.assertIn('#if defined(__APPLE__)',actual);self.assertIn('CC_SHA256_Update',actual)
        self.assertFalse(receipt['production_source_modified'])
    def test_nonunique_or_missing_transform_anchor_rejects(self):
        for text in ('','abc abc'):
            with self.assertRaises(ValueError):d.exact_replace(text,'abc','def')
    def test_cpp_commands_use_sdk_production_headers_and_no_engine_crypto_link(self):
        for variant,flags in d.VARIANTS:
            command=d.native_command(OWNER,Path('/trusted-headers'),Path('/output/fixture.cpp'),Path('/output/bin'),flags)
            self.assertEqual(command[:3],['xcrun','clang++','-std=c++17'])
            self.assertIn('-MMD',command);self.assertNotIn('-lcrypto',command);self.assertNotIn('-lunicorn',command)
            self.assertFalse(any(x.startswith('-D') and x!='-DNDEBUG' for x in command))
        self.assertIn('-fno-sanitize-recover=all',d.VARIANTS[2][1])
    def test_swift_production_extractions_are_exact_byte_spans(self):
        source,receipt=d.swift_fixture(OWNER);raw=(OWNER/'Sources/AnisetteDataProvider.swift').read_bytes()
        self.assertEqual(len(receipt['exact_byte_spans']),4)
        for span in receipt['exact_byte_spans']:
            block=raw[span['byte_start']:span['byte_end']]
            self.assertEqual(sha(block),span['sha256']);self.assertIn(block.decode(),source)
        self.assertEqual(source.count('removeValue(forKey: "v3_constructor_fault")'),3)
        self.assertNotIn('get_anisette_headers_uc(',source);self.assertNotIn('import anisette_core',source)
        self.assertIn('TemporaryConstructorFaultTrace.suffix(bad).isEmpty',source)
        self.assertIn('for value in boundaryValues',source);self.assertNotIn('URLSession',source)
        self.assertFalse(receipt['production_methods_modified'])
    def test_exact_failed_command_preserves_source_macros_and_generated_bytes(self):
        root=HERE/'tests/fixtures/failed-swift-macro-capture';receipt=parse((root/'provenance.json').read_bytes())
        for name,digest in receipt['raw_files'].items():self.assertEqual(sha((root/name).read_bytes()),digest)
        command=parse((root/'nested-0013.command.json').read_bytes());result=parse((root/'nested-0013.result.json').read_bytes())
        self.assertEqual(result['returncode'],1)
        self.assertIn(b'sandbox_apply: Operation not permitted',(root/'nested-0013.stderr').read_bytes())
        old_outer=parse((root/'host-run-diagnostic-checks.command.json').read_bytes())
        self.assertEqual(old_outer['argv'][:3],d.SANDBOX)
        plan=next(row for row in d.command_plan(receipt['command_context']) if row['label']=='swift-normal-compile')
        self.assertEqual(command['argv'],plan['logical_argv'])
        self.assertEqual(plan['argv'],command['argv'])
        self.assertIn('@TaskLocal',(OWNER/'Sources/LoginDiagnosticTrace.swift').read_text())
        original=(OWNER/'.ci/native-tests/fixtures/bounded_fault_host.cpp').read_text()
        native,_=d.adapt_native_fixture(original,Path(receipt['command_context']['owner']))
        swift,_=d.swift_fixture(OWNER)
        self.assertEqual(sha(native.encode()),receipt['native_generated_sha256'])
        self.assertEqual(sha(swift.encode()),receipt['swift_generated_sha256'])
    def context(self):
        work=Path('/reviewed/work')
        return d.command_context(work/'sources/AnisetteKit',work/'host-unicorn-headers',work/'host-tests/run-diagnostic-checks')
    def fixture(self):
        _,native=d.adapt_native_fixture((OWNER/'.ci/native-tests/fixtures/bounded_fault_host.cpp').read_text(),Path(self.context()['owner']));_,swift=d.swift_fixture(OWNER)
        inventory=parse((HERE/'reviewed/aggregate-source-inventory.json').read_bytes())
        row=dict(schema=1,guest_execution=False,real_engine_linked=False,proprietary_input=False,leak_sanitizer_enabled=False,apple_commoncrypto_validated=True,swift_boundaries_validated=True,source_sha256={p:r['sha256'] for p,r in inventory['files'].items()},native_fixture=native,swift_fixture=swift,command_context=self.context(),results=[])
        for variant,_ in d.VARIANTS:
            for stage in ('compile','run','nm','otool'):
                stdout={'compile':'','run':json.dumps(d.NATIVE_EXPECTED),'nm':'                 U _CC_SHA256_Init\n                 U _CC_SHA256_Update\n                 U _CC_SHA256_Final\n','otool':'/output/fixture:\n /usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n'}[stage]
                row['results'].append(dict(label=variant+'-'+stage,argv=['inert-fixture'],returncode=0,stdout=stdout,stderr=''))
        for variant in ('swift-normal','swift-optimized'):
            for stage in ('compile','run'):
                row['results'].append(dict(label=variant+'-'+stage,argv=['inert-fixture'],returncode=0,stdout='' if stage=='compile' else 'BOUNDED_FAULT_SWIFT_DECODER_PASS\nBOUNDED_FAULT_SWIFT_BOUNDARIES_PASS:77\n',stderr=''))
        plan={p['label']:p for p in d.command_plan(row['command_context'])}
        for result in row['results']:result.update(plan[result['label']])
        return row
    def test_finite_runtime_fixture_accepts_exact_result_only(self):
        self.assertEqual(d.verify_result(self.fixture(),self.context())['native_assertions'],1986)
    def test_source_closure_and_fixture_receipt_mutations_reject(self):
        for mutation in (lambda row:row['source_sha256'].clear(),lambda row:row['native_fixture'].update(generated_sha256='0'*64),lambda row:row['native_fixture']['literal_replacements'][0].update(after='unreviewed'),lambda row:row['swift_fixture'].update(production_methods_modified=True),lambda row:row['swift_fixture']['exact_byte_spans'][0].update(byte_end=0)):
            row=self.fixture();mutation(row)
            with self.assertRaises(ValueError):d.verify_result(row,self.context())
    def test_native_result_mutations_reject(self):
        for key,value in [('checks',661),('failures',1),('guest_execution',0),('real_engine_starts',1),('synthetic_api_starts',6)]:
            row=self.fixture();result=json.loads(row['results'][1]['stdout']);result[key]=value;row['results'][1]['stdout']=json.dumps(result)
            with self.subTest(key=key),self.assertRaises(ValueError):d.verify_result(row,self.context())
    def test_missing_swift_or_apple_runtime_and_reordered_commands_reject(self):
        for key in ('apple_commoncrypto_validated','swift_boundaries_validated'):
            row=self.fixture();row[key]=False
            with self.assertRaises(ValueError):d.verify_result(row,self.context())
        row=self.fixture();row['results'][0:2]=reversed(row['results'][0:2])
        with self.assertRaises(ValueError):d.verify_result(row,self.context())
        row=self.fixture();row['results'][-1]['stdout']='BOUNDED_FAULT_SWIFT_DECODER_PASS\n'
        with self.assertRaises(ValueError):d.verify_result(row,self.context())
    def test_actual_apple_crypto_symbols_and_no_engine_link_required(self):
        for text in ('','U _CC_SHA256_Init\n','U _uc_open\nU _CC_SHA256_Init\nU _CC_SHA256_Update\nU _CC_SHA256_Final\n'):
            row=self.fixture();row['results'][2]['stdout']=text
            with self.assertRaises(ValueError):d.verify_result(row,self.context())
        row=self.fixture();row['results'][2]['stdout']='_CC_SHA256_Init\n_CC_SHA256_Update\n_CC_SHA256_Final\n'
        d.verify_result(row,self.context())
        for library in ('Unicorn.framework/Unicorn','libcrypto.dylib','libssl.dylib'):
            row=self.fixture();row['results'][3]['stdout']+='\n'+library
            with self.assertRaises(ValueError):d.verify_result(row,self.context())
    def test_error_diagnostics_partial_output_and_wrong_counts_reject(self):
        for key,value in [('returncode',1),('stderr','warning')]:
            row=self.fixture();row['results'][0][key]=value
            with self.assertRaises(ValueError):d.verify_result(row,self.context())
        row=self.fixture();row['results'][-1]['stdout']=row['results'][-1]['stdout'].replace('77','76')
        with self.assertRaises(ValueError):d.verify_result(row,self.context())
    def test_apple_checks_refuse_nonapple_runtime_without_build(self):
        with patch.object(d.platform,'system',return_value='Linux'):
            with self.assertRaisesRegex(ValueError,'Apple arm64'):d.run(OWNER,Path('/unused'),Path('/unused'))
    def test_only_two_exact_swift_compiles_use_apple_plugin_sandbox(self):
        plan=d.command_plan(self.context())
        self.assertEqual(len(plan),16)
        self.assertEqual([r['label'] for r in plan if r['argv'][:3]!=d.SANDBOX],['swift-normal-compile','swift-optimized-compile'])
        for row in plan:
            self.assertEqual(d.dispatch_argv(self.context(),row['label'],row['logical_argv']),row)
            if row['label'].endswith('-run'):self.assertEqual(row['argv'][:3],d.SANDBOX)
            if row['sandbox_policy']=='apple_plugin_sandbox_compile':
                self.assertEqual(row['argv'],row['logical_argv']);self.assertEqual(row['argv'][0],'swiftc')
                self.assertIn('/reviewed/work/sources/AnisetteKit/Sources/LoginDiagnosticTrace.swift',row['argv'])
    def test_arbitrary_labels_flags_and_substituted_paths_reject_before_dispatch(self):
        row=next(r for r in d.command_plan(self.context()) if r['label']=='swift-normal-compile')
        for flag in ('-disable-sandbox','-load-plugin-executable','-plugin-path','-I','-F','-sdk','-resource-dir','-Xfrontend','-driver-use-frontend-path'):
            with self.subTest(flag=flag),self.assertRaises(ValueError):d.dispatch_argv(self.context(),row['label'],row['logical_argv']+[flag,'/unreviewed'])
        for label in ('swift-arbitrary-compile','injected','normal-compile','swift-normal-run'):
            with self.assertRaises(ValueError):d.dispatch_argv(self.context(),label,row['logical_argv'])
        for key in self.context():
            context=self.context();context[key]='/unreviewed/path'
            with self.assertRaises(ValueError):d.command_plan(context)
    def test_missing_wrapper_and_policy_rehash_cannot_reclassify_execution(self):
        for label in ('normal-compile','normal-run','normal-nm','swift-normal-run','swift-optimized-run'):
            row=self.fixture();target=next(r for r in row['results'] if r['label']==label)
            target['argv']=target['logical_argv'];target['sandbox_policy']='apple_plugin_sandbox_compile'
            with self.subTest(label=label),self.assertRaises(ValueError):d.verify_result(row,self.context())
        row=self.fixture();target=next(r for r in row['results'] if r['label']=='swift-normal-compile');target['argv']=[*d.SANDBOX,*target['logical_argv']]
        with self.assertRaises(ValueError):d.verify_result(row,self.context())
    def test_coherently_rehashed_substitute_roots_reject_against_outer_binding(self):
        row=self.fixture();row['command_context']={k:v.replace('/reviewed/work','/substitute/work') for k,v in row['command_context'].items()}
        for result,plan in zip(row['results'],d.command_plan(row['command_context'])):result.update(plan)
        _,row['native_fixture']=d.adapt_native_fixture((OWNER/'.ci/native-tests/fixtures/bounded_fault_host.cpp').read_text(),Path(row['command_context']['owner']))
        with self.assertRaisesRegex(ValueError,'trusted outer paths'):d.verify_result(row,self.context())
if __name__=='__main__':unittest.main()
