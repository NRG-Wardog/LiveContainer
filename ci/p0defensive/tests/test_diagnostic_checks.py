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
        inventory=parse((HERE/'reviewed/diagnostic-source-inventory.json').read_bytes())
        self.assertEqual(inventory['tree'],'4d31646c46a7af3d911bb9d52eeffe9cbc26a3dd')
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
    def fixture(self):
        _,native=d.native_fixture(OWNER);_,swift=d.swift_fixture(OWNER)
        inventory=parse((HERE/'reviewed/diagnostic-source-inventory.json').read_bytes())
        row=dict(schema=1,guest_execution=False,real_engine_linked=False,proprietary_input=False,leak_sanitizer_enabled=False,apple_commoncrypto_validated=True,swift_boundaries_validated=True,source_sha256={p:r['sha256'] for p,r in inventory['files'].items()},native_fixture=native,swift_fixture=swift,results=[])
        for variant,_ in d.VARIANTS:
            for stage in ('compile','run','nm','otool'):
                stdout={'compile':'','run':json.dumps(d.NATIVE_EXPECTED),'nm':'                 U _CC_SHA256_Init\n                 U _CC_SHA256_Update\n                 U _CC_SHA256_Final\n','otool':'/output/fixture:\n /usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n'}[stage]
                row['results'].append(dict(label=variant+'-'+stage,argv=['inert-fixture'],returncode=0,stdout=stdout,stderr=''))
        for variant in ('swift-normal','swift-optimized'):
            for stage in ('compile','run'):
                row['results'].append(dict(label=variant+'-'+stage,argv=['inert-fixture'],returncode=0,stdout='' if stage=='compile' else 'BOUNDED_FAULT_SWIFT_DECODER_PASS\nBOUNDED_FAULT_SWIFT_BOUNDARIES_PASS:77\n',stderr=''))
        return row
    def test_finite_runtime_fixture_accepts_exact_result_only(self):
        self.assertEqual(d.verify_result(self.fixture())['native_assertions'],1986)
    def test_source_closure_and_fixture_receipt_mutations_reject(self):
        for mutation in (lambda row:row['source_sha256'].clear(),lambda row:row['native_fixture'].update(generated_sha256='0'*64),lambda row:row['native_fixture']['literal_replacements'][0].update(after='unreviewed'),lambda row:row['swift_fixture'].update(production_methods_modified=True),lambda row:row['swift_fixture']['exact_byte_spans'][0].update(byte_end=0)):
            row=self.fixture();mutation(row)
            with self.assertRaises(ValueError):d.verify_result(row)
    def test_native_result_mutations_reject(self):
        for key,value in [('checks',661),('failures',1),('guest_execution',0),('real_engine_starts',1),('synthetic_api_starts',6)]:
            row=self.fixture();result=json.loads(row['results'][1]['stdout']);result[key]=value;row['results'][1]['stdout']=json.dumps(result)
            with self.subTest(key=key),self.assertRaises(ValueError):d.verify_result(row)
    def test_missing_swift_or_apple_runtime_and_reordered_commands_reject(self):
        for key in ('apple_commoncrypto_validated','swift_boundaries_validated'):
            row=self.fixture();row[key]=False
            with self.assertRaises(ValueError):d.verify_result(row)
        row=self.fixture();row['results'][0:2]=reversed(row['results'][0:2])
        with self.assertRaises(ValueError):d.verify_result(row)
        row=self.fixture();row['results'][-1]['stdout']='BOUNDED_FAULT_SWIFT_DECODER_PASS\n'
        with self.assertRaises(ValueError):d.verify_result(row)
    def test_actual_apple_crypto_symbols_and_no_engine_link_required(self):
        for text in ('','U _CC_SHA256_Init\n','U _uc_open\nU _CC_SHA256_Init\nU _CC_SHA256_Update\nU _CC_SHA256_Final\n'):
            row=self.fixture();row['results'][2]['stdout']=text
            with self.assertRaises(ValueError):d.verify_result(row)
        row=self.fixture();row['results'][2]['stdout']='_CC_SHA256_Init\n_CC_SHA256_Update\n_CC_SHA256_Final\n'
        d.verify_result(row)
        for library in ('Unicorn.framework/Unicorn','libcrypto.dylib','libssl.dylib'):
            row=self.fixture();row['results'][3]['stdout']+='\n'+library
            with self.assertRaises(ValueError):d.verify_result(row)
    def test_error_diagnostics_partial_output_and_wrong_counts_reject(self):
        for key,value in [('returncode',1),('stderr','warning')]:
            row=self.fixture();row['results'][0][key]=value
            with self.assertRaises(ValueError):d.verify_result(row)
        row=self.fixture();row['results'][-1]['stdout']=row['results'][-1]['stdout'].replace('77','76')
        with self.assertRaises(ValueError):d.verify_result(row)
    def test_apple_checks_refuse_nonapple_runtime_without_build(self):
        with patch.object(d.platform,'system',return_value='Linux'):
            with self.assertRaisesRegex(ValueError,'Apple arm64'):d.run(OWNER,Path('/unused'),Path('/unused'))
if __name__=='__main__':unittest.main()
