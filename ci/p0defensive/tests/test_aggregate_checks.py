"""Portable synthetic receipt tests only; no compiler, Apple, engine or guest run."""
import copy,inspect,json,sys,tempfile,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import aggregate_checks as a
import host_tests
import diagnostic_checks
from inventory import dump,parse,sha
from run_host_test import AGGREGATE_DRIVER,UNIT_METHODS,expected_test_ids,verify_unittest_result

class AggregateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.work=self.root/'work'
        self.owner=self.work/'sources/AnisetteKit';self.temporary=self.work/'host-temporary/test-fault-aggregate-compatibility'
        self.output=self.work/'host-tests/test-fault-aggregate-compatibility';self.output.mkdir(parents=True)
        self.evidence=self.root/'evidence/host-tests/test-fault-aggregate-compatibility';self.evidence.mkdir(parents=True)
        self.unit={'tests':1,'failures':0,'errors':0,'skips':0,'expected_failures':0,'unexpected_successes':0,'test_ids':expected_test_ids(AGGREGATE_DRIVER)}
        dump(self.evidence/'retention-summary.json',{'nested_commands':4})
        for index,(variant,flags) in enumerate(a.VARIANTS):
            binary=self.temporary/('tmp'+variant)/'aggregate-contract'
            commands=[['/usr/bin/c++',*a.STRICT_FLAGS,*flags,'-I',str(self.owner/'Native/Loader'),str(self.owner/'.ci/native-tests/fixtures/fault_aggregate_compatibility.cpp'),'-o',str(binary)],[str(binary)]]
            for offset,argv in enumerate(commands,1):
                label=f'{2*index+offset:04d}'
                record={'argv':argv,'cwd':str(self.work),'environment':{'TMPDIR':str(self.temporary)},'returncode':None}
                dump(self.evidence/(label+'.command.json'),record);dump(self.evidence/(label+'.result.json'),dict(record,returncode=0))
                (self.evidence/(label+'.stdout')).write_bytes(b'' if offset==1 else a.EXPECTED_STDOUT)
                (self.evidence/(label+'.stderr')).write_bytes(b'')
        self.save_result()
    def save_result(self):
        self.row={'schema':1,'source_sha256':a.source_hashes(),'unittest':copy.deepcopy(self.unit),'nested_commands':a.verify_nested(self.evidence,self.owner,self.temporary,self.work)}
        dump(self.output/'aggregate-result.json',self.row)
    def verify(self):return host_tests.verify_result(AGGREGATE_DRIVER,self.output,self.evidence)
    def rewrite_command(self,label,change):
        record=parse((self.evidence/(label+'.command.json')).read_bytes());change(record)
        dump(self.evidence/(label+'.command.json'),record);dump(self.evidence/(label+'.result.json'),dict(record,returncode=0))
    def test_exact_one_unittest_two_variants_36_inert_assertions(self):
        result=self.verify();self.assertEqual(result['tests'],1);self.assertEqual(result['assertions'],36)
        self.assertEqual(expected_test_ids(AGGREGATE_DRIVER),['test_fault_aggregate_compatibility.FaultAggregateCompatibilityTests.test_warning_clean_legacy_and_explicit_aggregates'])
        self.assertEqual(len(UNIT_METHODS),9)
    def test_no_nested_receipts_cannot_admit(self):
        with self.assertRaisesRegex(ValueError,'nested evidence'):host_tests.verify_result(AGGREGATE_DRIVER,self.output)
    def test_exact_source_delta_preserves_all_historical_files(self):
        old=parse((HERE/'reviewed/diagnostic-source-inventory.json').read_bytes());new=parse((HERE/'reviewed/aggregate-source-inventory.json').read_bytes())
        self.assertEqual(len(old['files']),65);self.assertEqual(len(new['files']),67)
        self.assertEqual(set(new['files'])-set(old['files']),{'.ci/native-tests/fixtures/fault_aggregate_compatibility.cpp','.ci/native-tests/test_fault_aggregate_compatibility.py'})
        self.assertEqual([p for p in old['files'] if old['files'][p]!=new['files'][p]],['Native/Loader/vm_initialization_diagnostics.h'])
        self.assertEqual(old['files']['.ci/native-tests/run_tests.py'],new['files']['.ci/native-tests/run_tests.py'])
        seal=parse((HERE/'reviewed/aggregate-source-seal.json').read_bytes())
        self.assertEqual(seal['predecessor_seal_sha256'],sha((HERE/'reviewed/defensive-source-seal.json').read_bytes()))
        self.assertEqual(seal['source_inventory_sha256'],sha((HERE/'reviewed/aggregate-source-inventory.json').read_bytes()))
        self.assertEqual(seal['source_review_sha256'],sha((HERE/'reviewed/aggregate-source-review.json').read_bytes()))
    def test_source_hash_missing_added_or_old_header_rejects(self):
        for change in (lambda r:r['source_sha256'].pop('.ci/native-tests/test_fault_aggregate_compatibility.py'),lambda r:r['source_sha256'].update(extra='0'*64),lambda r:r['source_sha256'].update({'Native/Loader/vm_initialization_diagnostics.h':'0fbe1ac033f2d2dbe7f3c5fbd0cade277f8e7eb51529264dfec3ca75279ba862'})):
            row=copy.deepcopy(self.row);change(row);dump(self.output/'aggregate-result.json',row)
            with self.assertRaises(ValueError):self.verify()
    def test_unittest_count_id_skips_failures_boolean_mutations_reject(self):
        for key,value in [('tests',9),('tests',True),('test_ids',['different']),('test_ids',self.unit['test_ids']*2),('skips',1),('errors',1),('failures',1),('expected_failures',1),('unexpected_successes',1),('skips',False)]:
            unit=copy.deepcopy(self.unit);unit[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):verify_unittest_result(AGGREGATE_DRIVER,unit)
    def test_all_nine_main_unittest_ids_stay_separate(self):
        main=dict(self.unit,tests=9,test_ids=expected_test_ids('run_tests.py'));verify_unittest_result('run_tests.py',main)
        with self.assertRaises(ValueError):verify_unittest_result(AGGREGATE_DRIVER,main)
        main['test_ids'][-1]='unknown'
        with self.assertRaises(ValueError):verify_unittest_result('run_tests.py',main)
    def test_missing_strict_warning_flag_rejects(self):
        self.rewrite_command('0001',lambda r:r['argv'].remove('-Werror'))
        with self.assertRaises(ValueError):self.verify()
    def test_injected_compile_flag_rejects(self):
        self.rewrite_command('0001',lambda r:r['argv'].insert(1,'-Wno-missing-field-initializers'))
        with self.assertRaises(ValueError):self.verify()
    def test_untrusted_compiler_rejects(self):
        self.rewrite_command('0001',lambda r:r['argv'].__setitem__(0,'/untrusted/c++'))
        with self.assertRaises(ValueError):self.verify()
    def test_normal_and_optimized_variants_cannot_be_substituted(self):
        self.rewrite_command('0003',lambda r:r['argv'].remove('-O2'))
        with self.assertRaises(ValueError):self.verify()
    def test_owner_source_or_output_substitution_rejects(self):
        for index,value in [(7,'/unreviewed/headers'),(8,'/unreviewed/test.cpp'),(-1,'/unreviewed/aggregate-contract')]:
            original=(self.evidence/'0001.command.json').read_bytes()
            self.rewrite_command('0001',lambda r:r['argv'].__setitem__(index,value))
            with self.assertRaises(ValueError):self.verify()
            (self.evidence/'0001.command.json').write_bytes(original);dump(self.evidence/'0001.result.json',dict(parse(original),returncode=0))
    def test_binary_mismatch_rejects(self):
        self.rewrite_command('0002',lambda r:r['argv'].__setitem__(0,'/unreviewed/aggregate-contract'))
        with self.assertRaises(ValueError):self.verify()
    def test_nested_count_extra_or_missing_receipt_rejects(self):
        for value in (3,5,True):
            dump(self.evidence/'retention-summary.json',{'nested_commands':value})
            with self.assertRaises(ValueError):self.verify()
        dump(self.evidence/'retention-summary.json',{'nested_commands':4});dump(self.evidence/'0005.command.json',{})
        with self.assertRaises(ValueError):self.verify()
        (self.evidence/'0005.command.json').unlink();(self.evidence/'0002.result.json').unlink()
        with self.assertRaises(ValueError):self.verify()
    def test_raw_counts_guest_engine_warnings_and_extra_output_rejects(self):
        for bad in (a.EXPECTED_STDOUT.replace(b'18',b'17'),a.EXPECTED_STDOUT.replace(b'false',b'true',1),a.EXPECTED_STDOUT.replace(b'false',b'0'),a.EXPECTED_STDOUT+b'extra\n'):
            (self.evidence/'0002.stdout').write_bytes(bad)
            with self.assertRaises(ValueError):self.verify()
        (self.evidence/'0002.stdout').write_bytes(a.EXPECTED_STDOUT);(self.evidence/'0001.stderr').write_bytes(b'warning')
        with self.assertRaises(ValueError):self.verify()
    def test_raw_result_and_cached_summary_must_agree(self):
        result=parse((self.evidence/'0001.result.json').read_bytes());result['returncode']=False;dump(self.evidence/'0001.result.json',result)
        with self.assertRaises(ValueError):self.verify()
    def test_coherent_rewrite_cannot_escape_outer_context(self):
        for name in ('0001','0002','0003','0004'):
            self.rewrite_command(name,lambda r:r.update(cwd='/different/work'))
        with self.assertRaises(ValueError):self.verify()
    def test_copied_sandbox_contract_unchanged(self):
        context=diagnostic_checks.command_context(Path('/reviewed/work/sources/AnisetteKit'),Path('/reviewed/work/host-unicorn-headers'),Path('/reviewed/work/host-tests/run-diagnostic-checks'))
        plan=diagnostic_checks.command_plan(context)
        self.assertEqual([r['label'] for r in plan if r['argv'][:3]!=host_tests.SANDBOX],['swift-normal-compile','swift-optimized-compile'])
        self.assertEqual(host_tests.execution_command(AGGREGATE_DRIVER,['python','--driver',AGGREGATE_DRIVER]),[*host_tests.SANDBOX,'python','--driver',AGGREGATE_DRIVER])

if __name__=='__main__':unittest.main(verbosity=2)
