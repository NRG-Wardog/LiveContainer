"""Offline failure-path tests. These tests never execute a guest or engine."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import allocation_gate as gate


class AllocationCaptureTests(unittest.TestCase):
    def receipt(self):
        return {'guest_execution':False,'leak_sanitizer_enabled':False,'source_sha256':dict(gate.ALLOCATION_SOURCES),
                'results':{v:{'allocator':{'checks':32,'failures':0,'guest_execution':False},'hooks':{'checks':51,'failures':0,'guest_execution':False}} for v in gate.VARIANTS}}
    def reject(self,value):
        with self.assertRaises((ValueError,KeyError,TypeError)):gate.verify_allocation_receipt(value)
    def inputs(self):return json.loads((ROOT/'inputs-allocation.json').read_bytes())
    def validate(self,value):
        raw=json.dumps(value).encode();return gate.native.validate_inputs(raw,gate.sha(raw),ROOT.parents[1])
    def test_exact_raw_receipt_and_sources(self):
        self.assertEqual(len(gate.ALLOCATION_SOURCES),12)
        self.assertEqual(gate.verify_allocation_receipt(self.receipt()),self.receipt())
    def test_missing_and_extra_receipt_fields(self):
        for key in self.receipt():
            value=self.receipt();del value[key];self.reject(value)
        value=self.receipt();value['production_ready']=True;self.reject(value)
    def test_source_omission_or_changed_bytes_rejected(self):
        for key in gate.ALLOCATION_SOURCES:
            value=self.receipt();del value['source_sha256'][key];self.reject(value)
            value=self.receipt();value['source_sha256'][key]='a'*64;self.reject(value)
    def test_no_success_from_skipped_failed_or_coerced_cases(self):
        for variant in gate.VARIANTS:
            for kind in ('allocator','hooks'):
                for key,values in {'checks':[True,0,'32',33,52],'failures':[False,1,'0'],'guest_execution':[0,True,None]}.items():
                    for bad in values:
                        value=self.receipt();value['results'][variant][kind][key]=bad;self.reject(value)
    def test_variant_missing_or_extra_rejected(self):
        for variant in gate.VARIANTS:
            value=self.receipt();del value['results'][variant];self.reject(value)
        value=self.receipt();value['results']['extra']=copy.deepcopy(value['results']['normal']);self.reject(value)
    def test_guest_and_leak_claim_types_strict(self):
        for key in ('guest_execution','leak_sanitizer_enabled'):
            for bad in (True,0,None,'false'):
                value=self.receipt();value[key]=bad;self.reject(value)
    def raw_fixture(self,root):
        source=root/'source';headers=root/'headers';output=root/'allocation';output.mkdir()
        value=self.receipt()
        for variant in gate.VARIANTS:
            for suffix,kind in (('','allocator'),('-hooks','hooks')):
                commands=[{'command':argv,'exit_code':0,'stdout':'','stderr':''} for argv in gate.expected_commands(output,source,headers,variant,bool(suffix))]
                commands[-1]['stdout']=json.dumps(value['results'][variant][kind])
                gate.dump(output/(variant+suffix+'.json'),commands)
        return source,headers,output,value
    def test_all_six_exact_command_arrays(self):
        with tempfile.TemporaryDirectory() as d:
            source,headers,output,value=self.raw_fixture(Path(d));gate.verify_raw_commands(output,value,source,headers)
    def test_unexpected_flags_linked_engine_or_output_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            source,headers,output,value=self.raw_fixture(Path(d));path=output/'sanitized.json';original=json.loads(path.read_bytes())
            for mutate in (lambda x:x[1]['command'].append('-lunicorn'),lambda x:x[0]['command'].remove('-fsanitize=address,undefined'),lambda x:x[-1].update(stdout='{}'),lambda x:x[0].update(exit_code=False),lambda x:x[0].update(stderr='warning')):
                changed=copy.deepcopy(original);mutate(changed);gate.dump(path,changed)
                with self.assertRaises(ValueError):gate.verify_raw_commands(output,value,source,headers)
    def test_exact_allocation_phase_inputs(self):self.validate(self.inputs())
    def test_wrong_phase_or_extra_owner_rejected(self):
        value=self.inputs();value['phase']='sidesign'
        with self.assertRaises(ValueError):self.validate(value)
        value=self.inputs();value['owners']['SideSign']=copy.deepcopy(value['owners']['AnisetteKit'])
        with self.assertRaises(ValueError):self.validate(value)
    def test_allocation_cannot_add_suites_or_children(self):
        for key in ('test_suites','submodules'):
            value=self.inputs();value[key]={'extra':'no'}
            with self.assertRaises(ValueError):self.validate(value)
    def test_allocation_cannot_run_macos_gate(self):
        with tempfile.TemporaryDirectory() as d:
            g=gate.native.Gate(self.inputs(),ROOT.parents[1],Path(d)/'work',Path(d)/'evidence','a'*64)
            with mock.patch.object(gate.native.platform,'system',return_value='Darwin'),self.assertRaises(ValueError):g.execute(None)
    def test_linux_gate_rejects_macos_before_creating_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);g=gate.AllocationGate(self.inputs(),ROOT.parents[1],root/'work',root/'evidence','a'*64)
            with mock.patch.object(gate.platform,'system',return_value='Darwin'),self.assertRaises(ValueError):g.execute()
            self.assertFalse((root/'work').exists());self.assertFalse((root/'evidence').exists())
    def archive_fixture(self,root,extra=None):
        archive=root/'engine.zip'
        with zipfile.ZipFile(archive,'w') as z:
            for name in ('unicorn.h','arm64.h','platform.h'):
                z.writestr('Unicorn.xcframework/macos/include/unicorn/'+name,'header '+name)
            z.writestr('Unicorn.xcframework/macos/libunicorn.a','not executed')
            if extra:z.writestr(*extra)
        return archive
    def test_only_checksum_proved_headers_are_extracted(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);archive=self.archive_fixture(root)
            with mock.patch.object(gate,'FORK_SHA',gate.sha(archive.read_bytes())):result=gate.extract_headers(archive,root/'headers')
            self.assertEqual(set(result),{'unicorn.h','arm64.h','platform.h'})
            self.assertEqual(len(list((root/'headers').rglob('*'))),4)
    def test_archive_hash_traversal_and_inconsistent_headers_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);archive=self.archive_fixture(root)
            with self.assertRaises(ValueError):gate.extract_headers(archive,root/'headers')
            for extra in (('../escaped.h','bad'),('Unicorn.xcframework/ios/include/unicorn/arm64.h','different')):
                archive=self.archive_fixture(root,extra)
                with mock.patch.object(gate,'FORK_SHA',gate.sha(archive.read_bytes())),self.assertRaises(ValueError):gate.extract_headers(archive,root/'headers')
    def test_linux_workflow_and_engine_prohibitions(self):
        text=(ROOT.parents[1]/'.github/workflows/p0-cxx-allocation-linux.yml').read_text()
        self.assertIn('runs-on: ubuntu-24.04',text);self.assertIn('validation/p0-cxx-allocation-linux',text)
        self.assertIn("if: always() && steps.transport.outputs.settled == 'true'",text)
        source=(ROOT/'allocation_gate.py').read_text()
        self.assertNotIn('test_constructor_diagnostics.py',source)
        self.assertNotIn('android_tls_constructor.cpp',source)
        self.assertIn("sandbox=['sudo','-n','unshare','--net','--']",source)


if __name__=='__main__':unittest.main()
