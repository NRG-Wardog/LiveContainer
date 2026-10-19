#!/usr/bin/env python3
"""Focused Linux successor guard mutations; synthetic data only."""
import contextlib,copy,hashlib,io,json,os,re,shutil,subprocess,sys,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch,MagicMock,mock_open
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import inventory as inv
import native_gate as gate
import host_contract as c
from evidence import safe_index,verify_transport
from run_host_test import DRIVERS
from retention import RawStore
class CaptureTests(unittest.TestCase):
    def test_fixed_driver_inventory(self):
        self.assertEqual(DRIVERS,('test_vm_setup_host.py','test_memory_boundaries_host.py','test_cxx_allocation.py','test_elf_metadata_bounds.py'))
        self.assertNotIn('run_tests.py',DRIVERS)
    def test_source_commit_tree_parent_and_twelve_headers(self):
        seal=inv.source_seal();self.assertEqual(seal['commit'],'e72d04b84123823c93e9162daffa73b7afcfd2c9');self.assertEqual(seal['tree'],'a03f5a4284b67560629cdb52b8e6b246b835a56a');self.assertEqual(seal['parent'],'e6e9d4aac698de2a5219aaef02c9a417da45f4e9');self.assertEqual(len(seal['files']),58);self.assertEqual(len(seal['headers']),12)
    def test_approval_anchor_refuses_execution(self):
        raw=(HERE/'inputs-linux.json').read_bytes();digest=inv.sha(raw)
        # A private fixture tests dormant refusal independently of whether this
        # suite itself is running in a legitimately activated reviewed checkout.
        with tempfile.TemporaryDirectory() as t:
            host=Path(t);shutil.copytree(HERE,host/'ci/p0defensive_linux')
            (host/'.github/workflows').mkdir(parents=True)
            for path in (inv.BUILD,inv.WORKFLOW):shutil.copyfile(HERE.parents[1]/path,host/path)
            workflow=host/inv.WORKFLOW
            dormant=re.sub(r'(?m)^(      APPROVED_P0DEFENSIVE_LINUX_INPUTS_SHA256: ).+$',r'\g<1>REVIEW_REQUIRED',workflow.read_text())
            workflow.write_text(dormant);inv.validate_inputs(raw,host)
            for approved in ('REVIEW_REQUIRED',None,digest):
                with self.assertRaises(ValueError):inv.validate_inputs(raw,host,approved,execute=True)
            workflow.write_text(dormant.replace('APPROVED_P0DEFENSIVE_LINUX_INPUTS_SHA256: REVIEW_REQUIRED','APPROVED_P0DEFENSIVE_LINUX_INPUTS_SHA256: '+digest))
            inv.validate_inputs(raw,host,digest,execute=True)
            with self.assertRaises(ValueError):inv.validate_inputs(raw,host,'0'*64,execute=True)
    def host_fixture(self,root):
        def git(*args):return subprocess.check_output(['git','-C',str(root),'-c','user.name=Local test','-c','user.email=test@example.invalid',*args],stderr=subprocess.PIPE).decode().strip()
        git('init');(root/'capture.py').write_text('synthetic capture code\n');git('add','capture.py')
        for name,oid in inv.HOST_GITLINKS.items():
            git('update-index','--add','--cacheinfo','160000,'+oid+','+name);(root/name).mkdir()
        git('commit','-m','Local synthetic host');return git,git('rev-parse','HEAD')
    def test_exact_unmaterialized_host_gitlinks_pass(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);git,commit=self.host_fixture(root);proof=inv.verify_capture_host_checkout(root,commit)
            self.assertFalse(proof['gitlinks_materialized']);self.assertEqual(proof['gitlinks'],inv.HOST_GITLINKS)
    def test_host_blob_gitlink_and_materialized_child_mutations_reject(self):
        for mutation in ('blob','gitlink','materialized','ignored'):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as t:
                root=Path(t);git,commit=self.host_fixture(root)
                if mutation=='blob':(root/'capture.py').write_text('modified')
                elif mutation=='gitlink':
                    git('update-index','--cacheinfo','160000,'+'1'*40+',OpenSSL');git('commit','-m','Changed child');commit=git('rev-parse','HEAD')
                elif mutation=='materialized':(root/'OpenSSL/extra').write_text('unused child must remain absent')
                else:(root/'extra').write_text('untracked source')
                with self.assertRaises(ValueError):inv.verify_capture_host_checkout(root,commit)
    def test_namespace_invocation_drops_identity_groups_and_capabilities(self):
        with patch.object(os,'getuid',return_value=1001),patch.object(os,'getgid',return_value=1002),patch.dict(os.environ,{'PATH':'/usr/bin:/bin','HOME':'/home/runner'}):
            self.assertEqual(gate.linux_sandbox(),['sudo','-n','/usr/bin/unshare','--net','--','/usr/bin/setpriv','--reuid=1001','--regid=1002','--clear-groups','--inh-caps=-all','--ambient-caps=-all','--bounding-set=-all','--no-new-privs','--','/usr/bin/env','-i','PATH=/usr/bin:/bin','HOME=/home/runner','PYTHONDONTWRITEBYTECODE=1','LANG=C.UTF-8'])
        with patch.object(os,'getuid',return_value=0),self.assertRaises(ValueError):gate.linux_sandbox()
    def test_namespace_probe_identity_compiler_group_capability_fail_closed(self):
        import socket
        for mutation in ('none','uid','compiler','groups','capabilities','network'):
            sock=MagicMock();sock.connect.side_effect=None if mutation=='network' else OSError('denied')
            status=''.join(k+':\t'+('1' if mutation=='capabilities' and k=='CapEff' else '0')+'\n' for k in ('CapInh','CapPrm','CapEff','CapBnd','CapAmb'))
            with self.subTest(mutation=mutation),patch.object(os,'getuid',return_value=0 if mutation=='uid' else 1001),patch.object(os,'getgid',return_value=1002),patch.object(os,'getgroups',return_value=[1002] if mutation=='groups' else []),patch.object(shutil,'which',return_value='/different/c++' if mutation=='compiler' else '/usr/bin/c++'),patch.object(socket,'socket',return_value=sock),patch('builtins.open',mock_open(read_data=status)),contextlib.redirect_stdout(io.StringIO()):
                if mutation=='none':exec(gate.namespace_probe(1001,1002,Path('/usr/bin/c++')), {})
                else:
                    with self.assertRaises(SystemExit):exec(gate.namespace_probe(1001,1002,Path('/usr/bin/c++')), {})
    def test_nested_wrong_owner_refuses_before_any_output(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);args=[sys.executable,'-B',str(HERE/'run_host_test.py'),'--owner',str(root/'absent-source'),'--output',str(root/'out'),'--temporary',str(root/'temp'),'--evidence',str(root/'evidence'),'--unicorn-include',str(root/'headers'),'--driver',DRIVERS[0],'--compiler',shutil.which('c++'),'--expected-uid',str(os.getuid()+1),'--expected-gid',str(os.getgid())]
            result=subprocess.run(args,capture_output=True,text=True,timeout=10)
            self.assertNotEqual(result.returncode,0);self.assertIn('owner differs before writes',result.stderr)
            self.assertEqual(list(root.iterdir()),[])
    def test_source_counts_guest_engine_types(self):
        for driver,expected in c.EXPECTED.items():
            c.exact(expected,expected)
            for key,value in expected.items():
                bad=dict(expected);bad[key]=(not value) if type(value) is bool else value+1
                with self.assertRaises(ValueError):c.exact(bad,expected)
            bad=dict(expected);bad['guest_execution']=0
            with self.assertRaises(ValueError):c.exact(bad,expected)
    def test_allocation_source_and_count_mutations(self):
        row={'results':{v:{'allocator':{'checks':32,'failures':0,'guest_execution':False},'hooks':{'checks':51,'failures':0,'guest_execution':False}} for v in c.VARIANTS},'guest_execution':False,'leak_sanitizer_enabled':False,'source_sha256':c.allocation.ALLOCATION_SOURCES}
        c.allocation.verify_allocation_receipt(row)
        for bad in [dict(row,source_sha256={}),dict(row,guest_execution=True),dict(row,leak_sanitizer_enabled=True)]:
            with self.assertRaises(ValueError):c.allocation.verify_allocation_receipt(bad)
        bad=copy.deepcopy(row);bad['results']['normal']['hooks']['checks']=50
        with self.assertRaises(ValueError):c.allocation.verify_allocation_receipt(bad)
    def fixture(self,root,driver):
        source=root/'source';output=root/'output';nested=root/'nested';headers=root/'headers';temporary=root/'temporary';compiler=Path('/usr/bin/c++')
        for p in (source,output,nested,headers,temporary):p.mkdir()
        commands=c.expected_commands(driver,source,output,headers,temporary,compiler,temporary/'elf-metadata-unit-test')
        results=[];store=RawStore(nested)
        if driver=='test_vm_setup_host.py':(output/'core_setup_slice.inc').write_bytes(b'synthetic core setup input')
        for i,cmd in enumerate(commands):
            prefix=f'{i+1:04d}';variant=c.VARIANTS[i//2];stage=('compile','run')[i%2];stdout=json.dumps(c.EXPECTED[driver])+'\n' if i%2 else ''
            env={'ASAN_OPTIONS':'detect_leaks=0:halt_on_error=1','UBSAN_OPTIONS':'halt_on_error=1'}
            row={'argv':cmd,'cwd':str(root),'environment':env,'returncode':None};inv.dump(nested/(prefix+'.command.json'),row);inv.dump(nested/(prefix+'.result.json'),dict(row,returncode=0))
            (nested/(prefix+'.stdout')).write_text(stdout);(nested/(prefix+'.stderr')).write_text('')
            for phase in ('before','after'):
                if phase=='after' and '-o' in cmd:Path(cmd[cmd.index('-o')+1]).write_bytes(b'synthetic compiled binary')
                inv.dump(nested/(prefix+'.'+phase+'.json'),{'temporary':store.retain_tree(temporary,label='temporary'),'output':store.retain_tree(output,label='output')})
            item={'variant':variant,'stage':stage,'returncode':0,'stdout':stdout,'stderr':''}
            if driver=='test_memory_boundaries_host.py':item['command']=cmd
            results.append(item)
        row={'results':results,'source_sha256':{p:inv.source_seal()['files'][p]['sha256'] for p in c.SOURCES[driver]},'guest_execution':False,'leak_sanitizer_enabled':False}
        name='setup-check-results.json' if driver=='test_vm_setup_host.py' else 'memory-check-results.json';inv.dump(output/name,row)
        return (driver,output,nested,source,headers,temporary,compiler),name,row
    def test_exact_setup_and_memory_receipts(self):
        for driver in DRIVERS[:2]:
            with self.subTest(driver=driver),tempfile.TemporaryDirectory() as t:
                args,name,row=self.fixture(Path(t),driver);self.assertEqual(c.verify_result(*args)['checks'],693 if driver==DRIVERS[0] else 1209)
    def test_missing_raw_compiler_output_rejects(self):
        with tempfile.TemporaryDirectory() as t:
            args,name,row=self.fixture(Path(t),DRIVERS[0]);path=args[2]/'0001.after.json';raw=inv.parse(path.read_bytes());raw['output']['entries']=[r for r in raw['output']['entries'] if r['path']!='setup-normal'];inv.dump(path,raw)
            with self.assertRaises(ValueError):c.verify_result(*args)
    def test_raw_stdout_mutation_rejects(self):
        with tempfile.TemporaryDirectory() as t:
            args,name,row=self.fixture(Path(t),DRIVERS[0]);(args[2]/'0002.stdout').write_text('{}')
            with self.assertRaises(ValueError):c.verify_result(*args)
    def test_missing_source_hash_rejects(self):
        with tempfile.TemporaryDirectory() as t:
            args,name,row=self.fixture(Path(t),DRIVERS[1]);row['source_sha256'].pop(next(iter(row['source_sha256'])));inv.dump(args[1]/name,row)
            with self.assertRaises(ValueError):c.verify_result(*args)
    def test_command_flags_and_extra_command_reject(self):
        for kind in ('flag','extra'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as t:
                args,name,row=self.fixture(Path(t),DRIVERS[0]);p=args[2]/'0001.command.json';command=inv.parse(p.read_bytes())
                if kind=='flag':command['argv'].insert(1,'-DUNSAFE');inv.dump(p,command)
                else:inv.dump(args[2]/'0007.command.json',command)
                with self.assertRaises(ValueError):c.verify_result(*args)
    def test_unknown_driver_and_temporary_escape_reject(self):
        with self.assertRaises(ValueError):c.expected_commands('run_tests.py',Path('/a'),Path('/b'),Path('/c'),Path('/d'),Path('/e'))
        with self.assertRaises(ValueError):c.command_metadata_dir('test_elf_metadata_bounds.py',['c++','-o','/escaped/normal'],Path('/safe'))
    def archive(self,root,mutation=None):
        names=list(inv.source_seal()['headers']);archive=root/'archive.zip';headers={name:inv.sha(('header '+name).encode()) for name in names}
        with zipfile.ZipFile(archive,'w') as z:
            for name in names:z.writestr('A/Headers/unicorn/'+name,('changed' if mutation=='bytes' and name==names[0] else 'header '+name).encode())
            if mutation=='extra':z.writestr('A/Headers/unicorn/extra.h',b'x')
            if mutation=='nested':z.writestr('../unicorn/escape.h',b'x')
            if mutation=='symlink':
                info=zipfile.ZipInfo('B/Headers/unicorn/'+names[0]);info.external_attr=(0o120777<<16);z.writestr(info,b'target')
            z.writestr('A/Engine',b'NOT EXTRACTED')
        return archive,{'archive_sha256':inv.sha(archive.read_bytes()),'headers':headers}
    def test_exact_twelve_archive_headers_only(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);archive,seal=self.archive(root)
            with patch.object(c,'source_seal',return_value=seal):self.assertEqual(c.extract_headers(archive,root/'headers'),seal['headers'])
            self.assertEqual(len(list((root/'headers').rglob('*.h'))),12);self.assertFalse((root/'headers/A/Engine').exists())
    def test_header_bytes_extra_path_special_and_archive_hash_reject(self):
        for mutation in ('bytes','extra','nested','symlink','checksum'):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as t:
                root=Path(t);archive,seal=self.archive(root,mutation)
                if mutation=='checksum':seal['archive_sha256']='0'*64
                with patch.object(c,'source_seal',return_value=seal),self.assertRaises(ValueError):c.extract_headers(archive,root/'headers')
    def evidence(self,root):
        (root/'provenance').mkdir();inv.dump(root/'provenance/result.json',{'writers_quiescent':True,'retention_errors':[],'status':'LOCAL_HOST_REPLAY_FOR_REVIEW','authenticated_capture':False});inv.dump(root/'provenance/owned-command-groups.json',[{'quiescent':True,'pipesJoined':True,'leaderReaped':True,'errors':[]}]);inv.dump(root/'evidence-index.json',safe_index(root))
    def test_root_index_only_exemption(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);self.evidence(root);(root/'provenance/evidence-index.json').write_text('nested is evidence')
            with self.assertRaises(ValueError):verify_transport(root)
            inv.dump(root/'evidence-index.json',safe_index(root));verify_transport(root)
            self.assertIn('provenance/evidence-index.json',safe_index(root)['files'])
    def test_extra_evidence_file_and_empty_directory_reject(self):
        for kind in ('file','directory'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as t:
                root=Path(t);self.evidence(root)
                if kind=='file':(root/'extra').write_text('x')
                else:(root/'empty').mkdir()
                with self.assertRaises(ValueError):verify_transport(root)
    def test_special_symlink_hardlink_and_root_index_reject(self):
        for kind in ('fifo','symlink','hardlink','index-fifo'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as t:
                root=Path(t);self.evidence(root)
                if kind=='fifo':os.mkfifo(root/'evidence-index-other.json')
                elif kind=='symlink':(root/'nested').symlink_to(root/'provenance',target_is_directory=True)
                elif kind=='hardlink':os.link(root/'provenance/result.json',root/'copy')
                else:(root/'evidence-index.json').unlink();os.mkfifo(root/'evidence-index.json')
                with self.assertRaises(ValueError):safe_index(root)
    def test_unsettled_writer_blocks_transport(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);self.evidence(root);inv.dump(root/'provenance/owned-command-groups.json',[{'quiescent':False,'pipesJoined':True,'leaderReaped':True,'errors':[]}]);inv.dump(root/'evidence-index.json',safe_index(root))
            with self.assertRaises(ValueError):verify_transport(root)
if __name__=='__main__':unittest.main(verbosity=2)
