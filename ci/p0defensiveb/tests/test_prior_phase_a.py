"""Portable adversarial offline replay tests; synthetic fixtures are never capture evidence."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest
import zipfile
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import prior_phase_a as p
import phase_a_raw_replay as raw
import phase_a_evidence_replay as replay
import phase_a_transport_replay as transport

HERE=Path(p.__file__).parent

def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()
def record(content,**extra):
    digest=raw.sha(content);git=b'blob '+str(len(content)).encode()+b'\0'+content
    return dict(label='synthetic-only',kind='bytes',blob_path='blobs/sha256/'+digest[:2]+'/'+digest,sha256=digest,length=len(content),git_blob_sha1=hashlib.sha1(git).hexdigest(),git_blob_sha256=hashlib.sha256(git).hexdigest(),**extra)
def bound_prior():
    prior=p.make_draft_prior();prior['expected'].update(run_id=101,run_attempt=2,host_commit='a'*40,artifact_id=202,artifact_sha256='b'*64,artifact_size=123,lock_sha256='c'*64,evidence_index_sha256='d'*64)
    prior['upload_identity_sha256']='e'*64;prior['independent_review']={'receipt_sha256':'f'*64,'reviewer':'synthetic-independent-reviewer'}
    return prior

class PriorBindingsTests(unittest.TestCase):
    def test_pending_and_partial_unknowns_are_valid_but_never_actionable(self):
        prior=p.make_draft_prior();self.assertEqual(prior['expected']['host_tree'],p.HOST_TREE)
        self.assertIsNone(prior['expected']['host_commit']);self.assertIsNone(prior['upload_identity_sha256'])
        for execution in (False,True):
            if execution:
                with self.assertRaisesRegex(ValueError,'unresolved'):p.validate_prior_inputs(prior,execution=True)
            else:self.assertFalse(p.validate_prior_inputs(prior)['execution_admitted'])
        prior['expected']['run_id']=101;p.validate_prior_inputs(prior)
        with mock.patch.object(p,'_json_bytes',side_effect=AssertionError('must not read')):
            with self.assertRaisesRegex(ValueError,'unresolved'):p.verify_prior_capture(prior,None,None,None,None)
    def test_malformed_and_obsolete_source_bindings_reject(self):
        for key,value in [('run_id',True),('run_attempt',0),('artifact_size',raw.MAX_ARCHIVE+1),('host_commit','main'),('host_tree','b'*40),('lock_sha256','0'*64),('repository','NRG-Wardog/Other')]:
            prior=bound_prior();prior['expected'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):p.validate_prior_inputs(prior)
        for key,value in [('source_basis','p0-login-trace-phase-a-v1'),('approved_inputs_sha256','a'*64),('frozen_adapter_sha256','a'*64),('schema_version',True)]:
            prior=bound_prior();prior[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):p.validate_prior_inputs(prior)
    def test_complete_tuple_cannot_omit_original_upload_or_review(self):
        for key in ('upload_identity_sha256','independent_review'):
            prior=bound_prior();prior[key]=None
            with self.assertRaisesRegex(ValueError,'unresolved'):p.validate_prior_inputs(prior,execution=True)
    def test_original_replay_is_independent_of_future_phase_b_identity_and_review(self):
        prior=bound_prior();prior['independent_review']=None;upload=b'{"original":"synthetic"}';prior['upload_identity_sha256']=raw.sha(upload)
        report={'source_basis':p.BASIS,'captured_path':'/original/capture/path','execution_admitted':False}
        expected_hashes={'archive':'a'*64,'upload_identity':raw.sha(upload)}
        fake_archive=mock.MagicMock();fake_archive.__enter__.return_value=object()
        reads=[]
        def original_read(root,name):
            reads.append(name)
            if name=='upload-identity.json':return upload
            require=name in ('run-api.json','artifact-api.json','commit-api.json','artifact-list-api.json')
            if not require:raise AssertionError('future/current receipt consulted')
            return b'{}'
        with mock.patch.dict(os.environ,{},clear=True),mock.patch.object(p,'_json_bytes',side_effect=original_read),mock.patch.object(p,'_ordinary',return_value=Path('/synthetic-only.zip')),mock.patch.object(p,'ArchiveFiles',return_value=fake_archive),mock.patch.object(p,'_replay_original',return_value=({'report':report,'lock_bytes':b'original-lock'},expected_hashes)):
            result=p.verify_original_capture(prior,'original','frozen','sources')
        self.assertEqual(result['replay_report_sha256'],raw.sha(encoded(report)));self.assertEqual(result['original_receipt_sha256'],expected_hashes)
        self.assertNotIn('independent-review.json',reads);self.assertNotIn('retrieval-helper.json',reads)
    def test_failed_original_capture_never_reaches_source_or_native_replay(self):
        gate,data,input_raw,closure=p._load_trusted_adapter(HERE/'prior_adapter')
        files={name:b'{}' for name in replay.required_metadata(gate,data)}
        files['provenance/reviewed-inputs.json']=input_raw
        files['provenance/result.json']=encoded({'status':'FAILED_OR_INCOMPLETE','last_stage':'toolchain','writers_quiescent':True})
        files['evidence-index.json']=encoded({name:raw.sha(content) for name,content in files.items()})
        with mock.patch.object(replay,'context_from_commands',side_effect=AssertionError('failed capture reached replay')):
            with self.assertRaisesRegex(ValueError,'failed or incomplete'):replay.verify_evidence(files,gate,data,input_raw,{},None,closure)
    def test_frozen_closure_load_is_private_and_byte_exact(self):
        sentinel=object();prior_module=sys.modules.get('inventory',sentinel)
        gate,data,input_raw,closure=p._load_trusted_adapter(HERE/'prior_adapter')
        self.assertEqual(raw.sha(input_raw),p.INPUT_SHA256);self.assertEqual(data['basis'],p.BASIS)
        self.assertEqual(sys.modules.get('inventory',sentinel),prior_module)
        self.assertEqual(gate.OWNERS,('AnisetteKit','SideSign'));self.assertEqual(len(closure),len(data['adapter_files'])+3)
    def test_frozen_closure_missing_extra_mutation_and_symlink_reject(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'prior';shutil.copytree(HERE/'prior_adapter',root)
            extra=root/'unreviewed.py';extra.write_text('raise RuntimeError()')
            with self.assertRaisesRegex(ValueError,'extra'):p._load_trusted_adapter(root)
            extra.unlink();path=root/'ci/p0defensive/host_tests.py';original=path.read_bytes();path.write_bytes(original+b'\n')
            with self.assertRaisesRegex(ValueError,'bytes changed'):p._load_trusted_adapter(root)
            path.unlink();path.symlink_to(HERE/'prior_adapter/ci/p0defensive/host_tests.py')
            with self.assertRaisesRegex(ValueError,'linked'):p._load_trusted_adapter(root)
    def test_independent_review_binds_actual_bytes_and_every_replay_check(self):
        prior=bound_prior();hashes={key:'a'*64 for key in ('run_api','artifact_api','commit_api','archive','upload_identity')};report={'synthetic_only':True,'ordered_commands':42}
        review={k:prior[k] for k in ('source_basis','expected','approved_inputs_sha256','frozen_adapter_sha256')}
        review.update(schema_version=1,status='INDEPENDENT_DEFENSIVE_DIAGNOSTIC_PHASE_A_REVIEW_PASSED',reviewer=prior['independent_review']['reviewer'],original_receipt_sha256=hashes,replay_report_sha256=raw.sha(encoded(report)),checks={key:True for key in p.REVIEW_CHECKS},scope={'execution_admitted':False,'production_ready':False,'guest_execution':False,'live_provider_or_apple_requests':False,'compiled_final_lock_child':False})
        original=encoded(review);prior['independent_review']['receipt_sha256']=raw.sha(original)
        self.assertEqual(p._validate_independent_review(original,prior,hashes,report),review)
        for change in ('bytes','report','receipt','check','source','reviewer','scope'):
            altered=copy.deepcopy(review);actual_report=copy.deepcopy(report);actual_hashes=dict(hashes)
            if change=='bytes':candidate=original+b' '
            else:
                if change=='report':actual_report['ordered_commands']=67
                elif change=='receipt':actual_hashes['archive']='b'*64
                elif change=='check':altered['checks']['genuine_observed_terminal_lock']=False
                elif change=='source':altered['source_basis']='p0-login-trace-phase-a-v1'
                elif change=='reviewer':altered['reviewer']='another reviewer'
                elif change=='scope':altered['scope']['compiled_final_lock_child']=True
                candidate=encoded(altered)
            with self.subTest(change=change),self.assertRaises(ValueError):p._validate_independent_review(candidate,prior,actual_hashes,actual_report)

class RawReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate,cls.data,_,_=p._load_trusted_adapter(HERE/'prior_adapter')
    def fixture(self):
        content=b'actual original bytes\x00\xff';row=record(content);files={row['blob_path']:content};return raw.RawReplay(files,self.data['retention_bounds']),row,files
    def test_raw_hash_length_git_id_and_exact_blob_reference(self):
        subject,row,files=self.fixture();self.assertEqual(subject.raw_record(row),files[row['blob_path']]);self.assertEqual(subject.finish()['unique_raw_blobs'],1)
        for key,value in [('sha256','b'*64),('length',True),('length',2),('blob_path','blobs/../untrusted'),('git_blob_sha1','a'*40),('git_blob_sha256','a'*64)]:
            changed=dict(row,**{key:value})
            with self.subTest(key=key),self.assertRaises(ValueError):subject.raw_record(changed)
    def test_hash_only_and_unreferenced_bytes_are_rejected(self):
        subject,row,files=self.fixture();files.clear()
        with self.assertRaisesRegex(ValueError,'absent'):subject.raw_record(row)
        subject,row,files=self.fixture()
        with self.assertRaisesRegex(ValueError,'unreferenced'):subject.finish()
    def test_git_tree_reconstructed_from_actual_raw_blobs(self):
        content=b'print("synthetic only")\n';row=record(content,mode='100644',source_path='/source/sub/a.py',byte_source='committed-git-object');row.update(kind='file',path='sub/a.py',git_mode='100644',git_blob_oid=raw.object_id('blob',content))
        entries={'sub/a.py':('100644','blob',row['git_blob_oid'])};tree,dirs=raw.tree_object(entries)
        proof=dict(kind='git-tree',source_path='/source',commit='a'*40,tree=tree,entries=[row],directories=[{'path':'sub','git_mode':'040000','git_tree_oid':dirs['sub']}])
        subject=raw.RawReplay({row['blob_path']:content},self.data['retention_bounds']);self.assertEqual(subject.tree(proof),entries)
        for key,value in [('tree','b'*40),('directories',[]),('entries',[row,row])]:
            with self.subTest(key=key),self.assertRaises(ValueError):subject.tree(dict(proof,**{key:value}))
    def test_filesystem_link_literal_and_escape_reject(self):
        content=b'data';file=record(content,mode='0644',source_path='/source/a');file.update(kind='file',path='a')
        link=record(b'a',mode='120000',source_path='/source/link');link.update(kind='symlink',path='link',target='a')
        proof={'kind':'filesystem-tree','source_path':'/source','entries':[{'path':'','kind':'directory','mode':'0755'},file,link]}
        files={file['blob_path']:content,link['blob_path']:b'a'};subject=raw.RawReplay(files,self.data['retention_bounds']);subject.tree(proof)
        bad=record(b'../escape',mode='120000',source_path='/source/link');bad.update(kind='symlink',path='link',target='../escape');files[bad['blob_path']]=b'../escape'
        with self.assertRaisesRegex(ValueError,'escape'):subject.tree(dict(proof,entries=[proof['entries'][0],file,bad]))
    def test_json_duplicates_and_nonfinite_reject(self):
        for content in (b'{"x":1,"x":2}',b'{"x":NaN}',b'{"x":Infinity}'):
            with self.assertRaises(ValueError):raw.parse(content)
    def test_archive_is_lazy_original_indexed_bytes_never_extracted(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'artifact.zip';content={'dangerous.py':b'raise RuntimeError("never execute")','evidence-index.json':b'{}'}
            with zipfile.ZipFile(path,'w') as archive:
                for name,value in content.items():archive.writestr(name,value)
            with raw.ArchiveFiles(path) as files:
                self.assertEqual(set(files),set(content));self.assertEqual(files['dangerous.py'],content['dangerous.py']);self.assertEqual(files.identity['sha256'],raw.sha(path.read_bytes()))
            self.assertEqual(list(Path(temporary).iterdir()),[path])
    def test_archive_path_link_collision_duplicate_and_member_bound(self):
        cases=[['../escape','evidence-index.json'],['a','a/b','evidence-index.json'],['a','A','evidence-index.json'],['nested/evidence-index.json','evidence-index.json']]
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'artifact.zip'
            for names in cases:
                with zipfile.ZipFile(path,'w') as archive:
                    for name in names:archive.writestr(name,b'{}')
                with self.subTest(names=names),self.assertRaises(ValueError):raw.ArchiveFiles(path)
            with zipfile.ZipFile(path,'w') as archive:
                link=zipfile.ZipInfo('link');link.external_attr=(stat.S_IFLNK|0o777)<<16;archive.writestr(link,b'/etc/passwd');archive.writestr('evidence-index.json',b'{}')
            with self.assertRaisesRegex(ValueError,'links'):raw.ArchiveFiles(path)
            with zipfile.ZipFile(path,'w') as archive:archive.writestr('evidence-index.json',b'{}')
            with mock.patch.object(raw,'MAX_MEMBER',1),self.assertRaisesRegex(ValueError,'large'):raw.ArchiveFiles(path)

class CommandReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.gate,cls.data,_,_=p._load_trusted_adapter(HERE/'prior_adapter')
    def fixture(self):
        context={'work':'/tmp/source-specific-work','host':'/home/capture/validation','evidence':'/home/capture/evidence','python':'/opt/python/bin/python3','environment':{'PATH':'/usr/bin:/bin:/usr/sbin:/sbin:'+self.data['toolchain']['developer_dir']+'/Toolchains/XcodeDefault.xctoolchain/usr/bin','HOME':'/tmp/source-specific-work/home','TMPDIR':'/tmp/source-specific-work/tmp','DEVELOPER_DIR':self.data['toolchain']['developer_dir'],'PYTHONDONTWRITEBYTECODE':'1'},'roots':{owner:'/tmp/source-specific-work/sources/'+owner for owner in self.data['owners']}}
        rows=replay.ordered_commands(self.gate,self.data,context);files={};groups=[]
        for index,(label,args,timeout) in enumerate(rows):
            env=self.gate._private_modules['lifecycle'].command_environment(label,args,context['environment']);argv=['git','--no-replace-objects','-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false',*args[1:]] if args[0]=='git' else args
            group=dict(pgid=index+100,quiescent=True,pipesJoined=True,signals=[],identityRetainedForSignals=False,reapedBeforeSignals=True,postReapPolicy='read-only-group-disappearance',errors=[],leaderReaped=True);groups.append(dict(label=label,**group))
            prefix='logs/'+label;files[prefix+'.command.json']=encoded(dict(argv=argv,cwd=context['work'],environment=env));files[prefix+'.settlement.json']=encoded(dict(returncode=0,terminationReturncode=0,timeout_seconds=timeout,ownedProcessGroup=group));files[prefix+'.exit-code.txt']=b'0\n';files[prefix+'.log']=b'';files[prefix+'.stderr.log']=b''
        files['provenance/owned-command-groups.json']=encoded(groups);return files,context
    def test_exact_frozen_source_command_order_excludes_old_login_count(self):
        files,context=self.fixture();result=replay.replay_commands(files,self.gate,self.data,context);self.assertEqual(len(result),31+len(replay.tool_probe_names(self.gate)))
        self.assertEqual(result[0]['label'],'xcode-version');self.assertEqual(result[-1]['label'],'host-run-diagnostic-checks');self.assertEqual(replay.context_from_commands(files,self.gate,self.data),context)
    def test_argv_cwd_environment_ownership_order_failure_mutations(self):
        for change in ('argv','cwd','environment','order','signals','returncode','timeout','extra','missing'):
            files,context=self.fixture();name='logs/xcode-version.command.json';command=raw.parse(files[name])
            if change=='argv':command['argv']=['xcodebuild','-help']
            if change=='cwd':command['cwd']='/elsewhere'
            if change=='environment':command['environment']['DYLD_INSERT_LIBRARIES']='/untrusted'
            files[name]=encoded(command)
            if change=='order':
                groups=raw.parse(files['provenance/owned-command-groups.json']);groups.reverse();files['provenance/owned-command-groups.json']=encoded(groups)
            if change in ('signals','returncode','timeout'):
                name='logs/xcode-version.settlement.json';settled=raw.parse(files[name])
                if change=='signals':settled['ownedProcessGroup']['signals']=[9]
                if change=='returncode':settled['returncode']=True
                if change=='timeout':settled['timeout_seconds']=9000
                files[name]=encoded(settled)
            if change=='extra':files['logs/unused.log']=b''
            if change=='missing':del files['logs/uname.log']
            with self.subTest(change=change),self.assertRaises((ValueError,KeyError)):replay.replay_commands(files,self.gate,self.data,context)
    def test_complete_metadata_requires_new_raw_emitter_paths(self):
        names=replay.required_metadata(self.gate,self.data)
        self.assertIn('provenance/SideSign.Package.resolved.terminal-observed',names)
        self.assertIn('provenance/after-build/SideSign/workspace-state.json',names)
        self.assertNotIn('provenance/SideSign.Package.resolved.final-observed',names)
        self.assertIn('provenance/source-after-host-test-vm-setup-host.json',names)

class CurrentTransportTests(unittest.TestCase):
    def fixture(self,root):
        import retrieve_prior as helper
        current={'repository':p.REPOSITORY,'run_id':303,'run_attempt':1,'host_commit':'e'*40}
        expected=bound_prior()['expected'];inputs_raw=encoded({'prior_phase_a':bound_prior()})
        inputs_path=root/'inputs.json';inputs_path.write_bytes(inputs_raw);work=root/'work';work.mkdir();receipts_dir=root/'receipts';receipts_dir.mkdir()
        fixed=HERE/'retrieve_prior.py';helper_raw=fixed.read_bytes();identities={key:{'sha256':raw.sha(key.encode()),'bytes':len(key)} for key in helper.endpoints(expected)}
        report={'schema_version':1,'status':'RETRIEVED_UNSETTLED','execution_admitted':False,'current_run':current,'expected':expected,'inputs':{'path':str(inputs_path),'sha256':raw.sha(inputs_raw),'bytes':len(inputs_raw)},'helper':{'path':str(fixed),'sha256':raw.sha(helper_raw),'bytes':len(helper_raw),'pid':501,'pgid':501},'limits':{'total_seconds':helper.TOTAL_SECONDS,'request_seconds':helper.REQUEST_SECONDS,'json_bytes':helper.MAX_JSON,'archive_bytes':helper.MAX_ARCHIVE,'header_bytes':helper.MAX_HEADERS,'stderr_bytes':helper.MAX_STDERR},'request_order':list(helper.endpoints(expected)),'requests':{}}
        for index,(key,url) in enumerate(helper.endpoints(expected).items()):
            report['requests'][key]={'method':'GET','url':url,'status':200,**identities[key],'headers':{'content-type':'application/json'},'stdout':{'sha256':'a'*64,'bytes':identities[key]['bytes']+64},'stderr':{'sha256':raw.sha(b''),'bytes':0},'command':{'argv':['gh','api','--method','GET','--include',url],'cwd':str(receipts_dir),'returncode':0,'pid':600+index,'pgid':501,'leaderReaped':True,'pipesJoined':True}}
        environment={'PATH':'/opt/homebrew/bin:/Users/runner/.cargo/bin:/usr/bin:/bin:/usr/sbin:/sbin','HOME':str(work/'home'),'TMPDIR':str(work/'tmp'),'DEVELOPER_DIR':'/Applications/Xcode_26.4.1.app/Contents/Developer','PYTHONDONTWRITEBYTECODE':'1','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null','GIT_ALLOW_PROTOCOL':'https','GIT_NO_REPLACE_OBJECTS':'1','GIT_GRAFT_FILE':'/dev/null','GIT_NO_LAZY_FETCH':'1','GIT_TERMINAL_PROMPT':'0','LANG':'en_US.UTF-8','LC_ALL':'en_US.UTF-8','GITHUB_REPOSITORY':p.REPOSITORY,'GITHUB_SHA':current['host_commit'],'GITHUB_RUN_ID':'303','GITHUB_RUN_ATTEMPT':'1','GITHUB_REF':p.PHASE_B_REF}
        group={'pgid':501,'quiescent':True,'pipesJoined':True,'signals':[],'identityRetainedForSignals':False,'reapedBeforeSignals':True,'postReapPolicy':'read-only-group-disappearance','errors':[],'leaderReaped':True}
        receipts={'schema_version':1,'current_run':current,'helper_report_sha256':raw.sha(encoded(report)),'outer_command':{'argv':[sys.executable,'-B',str(fixed),'--inputs',str(inputs_path),'--output-dir',str(receipts_dir)],'cwd':str(work),'environment':environment},'outer_settlement':{'returncode':0,'timeout_seconds':1800,'terminationReturncode':0,'ownedProcessGroup':group}}
        return current,expected,report,receipts,identities,dict(inputs_path=inputs_path,inputs_raw=inputs_raw,work_root=work,receipts_dir=receipts_dir),environment
    def test_exact_current_owned_transport_and_response_bindings(self):
        with tempfile.TemporaryDirectory() as temporary:
            current,expected,report,receipts,identities,kwargs,env=self.fixture(Path(temporary))
            with mock.patch.dict(os.environ,env,clear=True):
                digest=transport._validate_current_transport(current,receipts,identities,expected,helper_raw=encoded(report),**kwargs)
                self.assertEqual(len(digest),64)
    def test_current_transport_cannot_relabel_body_command_environment_or_settlement(self):
        for change in ('order','method','url','status','body','helper','group','env','token','cwd','argv','stderr','headers','timeout'):
            with tempfile.TemporaryDirectory() as temporary:
                current,expected,report,receipts,identities,kwargs,env=self.fixture(Path(temporary))
                row=report['requests']['run_api']
                if change=='order':report['request_order'].reverse()
                if change=='method':row['method']='POST'
                if change=='url':row['url']='https://attacker.invalid'
                if change=='status':row['status']=201
                if change=='body':row['sha256']='d'*64
                if change=='helper':report['helper']['sha256']='d'*64
                if change=='group':receipts['outer_settlement']['ownedProcessGroup']['pipesJoined']=False
                if change=='env':receipts['outer_command']['environment']['PATH']='/tmp/untrusted'
                if change=='token':receipts['outer_command']['environment']['GH_TOKEN']='must-never-persist'
                if change=='cwd':row['command']['cwd']='/tmp/wrong'
                if change=='argv':row['command']['argv'].append('--verbose')
                if change=='stderr':row['stderr']['bytes']=1
                if change=='headers':row['headers']['authorization']='not-permitted'
                if change=='timeout':receipts['outer_settlement']['timeout_seconds']=1801
                receipts['helper_report_sha256']=raw.sha(encoded(report))
                with mock.patch.dict(os.environ,env,clear=True),self.subTest(change=change),self.assertRaises(ValueError):
                    transport._validate_current_transport(current,receipts,identities,expected,helper_raw=encoded(report),**kwargs)

class SuccessorPreparationTests(unittest.TestCase):
    def test_reviewed_successor_stages_data_only_and_keeps_original(self):
        gate, data, input_raw, closure = p._load_trusted_adapter(HERE / 'prior_adapter')
        self.assertEqual(raw.sha(input_raw), p.INPUT_SHA256)
        self.assertEqual(len(closure), 63)
        self.assertEqual(data['host']['base'], p.HOST_PARENT)
        self.assertIsNone(p.make_draft_prior()['expected']['run_id'])
        self.assertNotEqual(p.HOST_PARENT, p.OVERLAY_BASIS)
    def test_unreviewed_delta_wrong_review_or_tree_fail_before_output_creation(self):
        original = p._json_bytes
        for name in ('emitter-freeze.json', 'emitter-independent-review.json', 'frozen-closure.json'):
            def read(root, relative):
                content = original(root, relative)
                return content + b'\n' if relative == name else content
            with self.subTest(name=name), mock.patch.object(p, '_json_bytes', side_effect=read), self.assertRaises(ValueError):
                p._load_trusted_adapter(HERE / 'prior_adapter')
    def test_unreviewed_probe_tuple_cannot_expand_capture_commands(self):
        class BadGate:
            class Gate:
                def tools(self):
                    for tool in ('swift', 'curl', 'xcodebuild'): pass
        with self.assertRaisesRegex(ValueError, 'unreviewed'):
            replay.tool_probe_names(BadGate)

if __name__=='__main__':unittest.main()
