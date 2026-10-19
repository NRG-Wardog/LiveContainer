"""Synthetic original/fresh API split tests; no real API, credentials or native execution."""
import copy,io,json,os,sys,tempfile,unittest,zipfile
from pathlib import Path
from unittest import mock
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import prior_phase_a as p
from phase_a_raw_replay import sha


def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()


class ApiBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as archive:archive.writestr('evidence-index.json',b'{}')
        self.archive=stream.getvalue();self.archive_identity={'sha256':sha(self.archive),'bytes':len(self.archive)}
        self.prior=p.make_draft_prior();self.prior['expected'].update(run_id=101,run_attempt=2,host_commit='a'*40,artifact_id=202,artifact_sha256=sha(self.archive),artifact_size=len(self.archive),lock_sha256=sha(b'synthetic-lock'),evidence_index_sha256=sha(b'{}'))
        self.expected=self.prior['expected'];repo=p.REPOSITORY;url='https://api.github.com/repos/'+repo
        self.api={
            'run_api':{'id':101,'run_attempt':2,'head_sha':'a'*40,'repository':{'full_name':repo},'status':'completed','conclusion':'success','head_branch':p.PHASE_A_BRANCH,'event':'push','path':'.github/workflows/p0-defensive-diagnostic-phase-a.yml','html_url':f'https://github.com/{repo}/actions/runs/101','jobs_url':url+'/actions/runs/101/attempts/2/jobs','logs_url':url+'/actions/runs/101/attempts/2/logs','updated_at':'2026-10-19T17:30:19Z'},
            'artifact_api':{'id':202,'node_id':'synthetic-node-id','size_in_bytes':len(self.archive),'digest':'sha256:'+sha(self.archive),'expired':False,'url':url+'/actions/artifacts/202','workflow_run':{'id':101,'head_sha':'a'*40,'head_branch':p.PHASE_A_BRANCH},'name':'p0-defensive-diagnostic-phase-a-'+'a'*40+'-101-2','updated_at':'2026-10-19T17:30:07Z'},
            'commit_api':{'sha':'a'*40,'tree':{'sha':p.HOST_TREE},'parents':[{'sha':p.HOST_PARENT}]}}
        self.original={key:encoded(value) for key,value in self.api.items()}
        self.original['artifact_list_api']=encoded({'total_count':1,'artifacts':[self.api['artifact_api']]})
        self.upload=encoded({'GITHUB_REPOSITORY':repo,'GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'101','GITHUB_RUN_ATTEMPT':'2','CAPTURE_ARTIFACT_ID':'202','CAPTURE_ARTIFACT_DIGEST':sha(self.archive),'CAPTURE_ARTIFACT_URL':f'https://github.com/{repo}/actions/runs/101/artifacts/202'})
        self.prior['upload_identity_sha256']=sha(self.upload)
        self.report={'synthetic_only':True,'execution_admitted':False}
        self.hashes={key:sha(value) for key,value in self.original.items()}|{'archive':sha(self.archive),'upload_identity':sha(self.upload)}
        review={k:self.prior[k] for k in ('source_basis','expected','approved_inputs_sha256','frozen_adapter_sha256')}
        review.update(schema_version=1,status='INDEPENDENT_DEFENSIVE_DIAGNOSTIC_PHASE_A_REVIEW_PASSED',reviewer='SYNTHETIC-NOT-GENUINE',original_receipt_sha256=self.hashes,replay_report_sha256=sha(encoded(self.report)),checks={key:True for key in p.REVIEW_CHECKS},scope={'execution_admitted':False,'production_ready':False,'guest_execution':False,'live_provider_or_apple_requests':False,'compiled_final_lock_child':False})
        self.review=encoded(review);self.prior['independent_review']={'receipt_sha256':sha(self.review),'reviewer':review['reviewer']}
    def compare(self,fresh,original=None,archive=None):
        return p.validate_fresh_api(self.original if original is None else original,{key:value for key,value in fresh.items() if key!='artifact_list_api'},self.upload,self.expected,self.archive_identity if archive is None else archive)
    def stage(self,fresh=None):
        fresh={key:self.original[key] for key in p.ORIGINAL_API_FILES} if fresh is None else fresh
        for key,name in p.ORIGINAL_API_FILES.items():(self.root/name).write_bytes(self.original[key])
        (self.root/p.ORIGINAL_LISTING_FILE).write_bytes(self.original['artifact_list_api'])
        for key,name in p.RECEIPT_FILES.items():(self.root/name).write_bytes(self.archive if key=='archive' else fresh[key])
        for name,raw in [('upload-identity.json',self.upload),('independent-review.json',self.review),('retrieval-helper.json',b'{}'),('retrieval-receipts.json',b'{}')]: (self.root/name).write_bytes(raw)
    def test_json_serialization_changes_keep_distinct_raw_hashes(self):
        fresh={key:(json.dumps(value,indent=4)+'\n').encode() for key,value in self.api.items()}
        report=self.compare(fresh)
        for key,row in report['api_bodies'].items():
            self.assertNotEqual(row['original_sha256'],row['fresh_sha256']);self.assertEqual(row['classified_metadata_differences'],[])
    def test_only_valid_updated_at_metadata_can_change(self):
        values=copy.deepcopy(self.api)
        for key in ('run_api','artifact_api'):values[key]['updated_at']='2026-10-19T17:31:00.123Z'
        report=self.compare({key:encoded(value) for key,value in values.items()})
        self.assertEqual(report['api_bodies']['run_api']['classified_metadata_differences'],['updated_at'])
        self.assertEqual(report['api_bodies']['artifact_api']['classified_metadata_differences'],['updated_at'])
        self.assertEqual(report['api_bodies']['commit_api']['classified_metadata_differences'],[])
    def test_all_capture_and_source_identity_mutations_reject(self):
        changes=[('run_api','id',102),('run_api','run_attempt',3),('run_api','head_sha','b'*40),('run_api','repository',{'full_name':'other/repository'}),('run_api','status','in_progress'),('run_api','conclusion','failure'),('run_api','head_branch','other'),('run_api','path','other.yml'),('artifact_api','id',203),('artifact_api','digest','sha256:'+'b'*64),('artifact_api','size_in_bytes',1),('artifact_api','expired',True),('artifact_api','workflow_run',{'id':102,'head_sha':'a'*40,'head_branch':p.PHASE_A_BRANCH}),('commit_api','sha','b'*40),('commit_api','tree',{'sha':'b'*40}),('commit_api','parents',[{'sha':'b'*40}])]
        for kind,key,value in changes:
            values=copy.deepcopy(self.api);values[kind][key]=value
            with self.subTest(kind=kind,key=key),self.assertRaises(ValueError):self.compare({k:encoded(v) for k,v in values.items()})
    def test_unknown_metadata_and_url_variants_are_not_tolerated(self):
        changes=[('run_api','new_metadata',1),('run_api','jobs_url',self.api['run_api']['jobs_url'].replace('/attempts/2','')),('run_api','logs_url',self.api['run_api']['logs_url'].replace('/attempts/2','')),('artifact_api','node_id','different'),('commit_api','new_metadata',1)]
        for kind,key,value in changes:
            values=copy.deepcopy(self.api);values[kind][key]=value
            with self.subTest(kind=kind,key=key),self.assertRaisesRegex(ValueError,'unclassified'):self.compare({k:encoded(v) for k,v in values.items()})
        values=copy.deepcopy(self.api);del values['artifact_api']['node_id']
        with self.assertRaisesRegex(ValueError,'unclassified'):self.compare({k:encoded(v) for k,v in values.items()})
    def test_timestamp_presence_type_and_calendar_validation_reject(self):
        for value in (None,True,7,'invalid','2026-99-19T17:30:19Z','2026-10-19T17:30:19+01:00','missing'):
            values=copy.deepcopy(self.api)
            if value=='missing':del values['run_api']['updated_at']
            else:values['run_api']['updated_at']=value
            with self.subTest(value=value),self.assertRaises(ValueError):self.compare({k:encoded(v) for k,v in values.items()})
    def test_archive_identity_never_uses_metadata_exceptions(self):
        for key,value in [('sha256','b'*64),('bytes',len(self.archive)+1)]:
            with self.subTest(key=key),self.assertRaises(ValueError):self.compare(self.original,archive={**self.archive_identity,key:value})
    def test_original_api_raw_bytes_are_exactly_sealed(self):
        self.stage();self.assertEqual(p.original_api_bytes(self.prior,self.root,self.review),self.original)
        for name in (*p.ORIGINAL_API_FILES.values(),p.ORIGINAL_LISTING_FILE):
            path=self.root/name;before=path.read_bytes();path.write_bytes(before+b'\n')
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'original reviewed API bytes changed'):p.original_api_bytes(self.prior,self.root,self.review)
            path.write_bytes(before)
    def test_original_missing_linked_swapped_or_fresh_substitution_rejects(self):
        self.stage();name=self.root/p.ORIGINAL_API_FILES['run_api'];raw=name.read_bytes()
        for kind in ('missing','linked','swapped','fresh'):
            name.unlink()
            if kind=='linked':name.symlink_to(self.root/'run-api.json')
            elif kind=='swapped':name.write_bytes(self.original['artifact_api'])
            elif kind=='fresh':name.write_bytes(raw+b'\n')
            with self.subTest(kind=kind),self.assertRaises(ValueError):p.original_api_bytes(self.prior,self.root,self.review)
            if name.is_symlink() or name.exists():name.unlink()
            name.write_bytes(raw)
    def test_bound_preflight_checks_original_upload_review_and_lock_tuple(self):
        self.stage();self.assertEqual(p.validate_reviewed_original_api(self.prior,self.root),self.original)
        for key in ('lock_sha256','evidence_index_sha256','artifact_sha256'):
            altered=copy.deepcopy(self.prior);altered['expected'][key]='f'*64
            with self.subTest(key=key),self.assertRaises(ValueError):p.validate_reviewed_original_api(altered,self.root)
        (self.root/'upload-identity.json').write_bytes(self.upload+b' ')
        with self.assertRaisesRegex(ValueError,'upload'):p.validate_reviewed_original_api(self.prior,self.root)
    def test_current_replay_keeps_original_digest_and_fresh_transport_separate(self):
        values=copy.deepcopy(self.api);values['run_api']['updated_at']='2026-10-19T17:31:00Z'
        fresh={key:(json.dumps(value,indent=2)+'\n').encode() for key,value in values.items()};self.stage(fresh)
        inputs_raw=encoded({'prior_phase_a':self.prior});inputs=self.root/'inputs.json';inputs.write_bytes(inputs_raw)
        def replay(files,prior,raw,upload,*args):
            self.assertEqual(raw,self.original);self.assertEqual(upload,self.upload)
            return {'report':copy.deepcopy(self.report),'lock_bytes':b'synthetic-lock'},self.hashes
        def transport(current,receipts,identities,expected,**kwargs):
            self.assertEqual({key:row['sha256'] for key,row in identities.items()}, {key:sha(value) for key,value in fresh.items()}|{'archive':sha(self.archive)})
            return 'e'*64
        with mock.patch.object(p,'_replay_original',side_effect=replay),mock.patch('phase_a_transport_replay._validate_current_transport',side_effect=transport):
            result=p.verify_prior_capture(self.prior,self.root,None,None,{},inputs_path=inputs,inputs_raw=inputs_raw,work_root=self.root)
        self.assertEqual(result['report']['original_receipt_sha256'],self.hashes)
        self.assertEqual(result['report']['current_api_sha256'],{key:sha(value) for key,value in fresh.items()})
        self.assertEqual(json.loads(self.review)['replay_report_sha256'],sha(encoded(self.report)))
        self.assertFalse(result['report']['execution_admitted'])
    def test_fresh_body_set_swaps_missing_or_substitution_reject(self):
        for kind in ('missing','swapped','unknown'):
            values=dict(self.original)
            if kind=='missing':values.pop('run_api')
            elif kind=='swapped':values['run_api'],values['artifact_api']=values['artifact_api'],values['run_api']
            else:values['unknown_api']=b'{}'
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.compare(values)
    def test_complete_original_listing_and_unique_selection_are_required(self):
        original_listing=json.loads(self.original['artifact_list_api'])
        cases=[]
        changed=copy.deepcopy(original_listing);changed['artifacts'][0]['node_id']='different';cases.append(changed)
        changed=copy.deepcopy(original_listing);del changed['artifacts'][0]['node_id'];cases.append(changed)
        changed=copy.deepcopy(original_listing);changed['total_count']=2;cases.append(changed)
        changed=copy.deepcopy(original_listing);changed['artifacts']*=2;changed['total_count']=2;cases.append(changed)
        changed=copy.deepcopy(original_listing);changed['artifacts'][0]['id']=203;cases.append(changed)
        changed=copy.deepcopy(original_listing);changed['extra']=True;cases.append(changed)
        for listing in cases:
            with self.subTest(listing=listing),self.assertRaises(ValueError):
                self.compare(self.original,original={**self.original,'artifact_list_api':encoded(listing)})

    def test_duplicate_and_nonfinite_json_never_normalize_to_identity(self):
        for value in (b'{"id":101,"id":101}',b'{"id":NaN}',b'{"id":Infinity}'):
            with self.subTest(value=value),self.assertRaises(ValueError):self.compare({**self.original,'run_api':value})


    def test_auxiliary_failure_log_artifact_can_coexist_but_is_not_selected(self):
        auxiliary = copy.deepcopy(self.api['artifact_api'])
        auxiliary.update(id=203, name='p0-defensive-diagnostic-phase-a-failure-logs-synthetic')
        originals = {**self.original, 'artifact_list_api': encoded({
            'total_count': 2, 'artifacts': [auxiliary, self.api['artifact_api']]})}
        provenance = p.validate_original_artifact_listing(originals, self.expected)
        self.assertEqual(provenance['artifact_id'], 202)
        self.assertEqual(provenance['selected_artifact_sha256'], sha(self.original['artifact_api']))
        with self.assertRaises(ValueError):
            p.validate_original_artifact_listing({**originals, 'artifact_api': encoded(auxiliary)}, self.expected)

    def test_distinct_artifact_id_cannot_duplicate_primary_name(self):
        duplicate = copy.deepcopy(self.api['artifact_api']); duplicate['id'] = 203
        originals = {**self.original, 'artifact_list_api': encoded({
            'total_count': 2, 'artifacts': [self.api['artifact_api'], duplicate]})}
        with self.assertRaisesRegex(ValueError, 'unique original primary artifact name'):
            p.validate_original_artifact_listing(originals, self.expected)

    def test_extra_truncated_and_duplicate_auxiliary_listing_entries_reject(self):
        auxiliary = copy.deepcopy(self.api['artifact_api'])
        auxiliary.update(id=203, name='p0-defensive-diagnostic-phase-a-failure-logs-synthetic')
        for count, entries in ((1, [self.api['artifact_api'], auxiliary]),
                               (3, [self.api['artifact_api'], auxiliary]),
                               (3, [self.api['artifact_api'], auxiliary, auxiliary])):
            originals = {**self.original, 'artifact_list_api': encoded({'total_count': count, 'artifacts': entries})}
            with self.subTest(count=count, entries=len(entries)), self.assertRaises(ValueError):
                p.validate_original_artifact_listing(originals, self.expected)

    def test_overlay_basis_cannot_replace_direct_sole_host_api_parent(self):
        for parents in ([{'sha': p.OVERLAY_BASIS}], [{'sha': p.HOST_PARENT}, {'sha': p.OVERLAY_BASIS}], []):
            values = copy.deepcopy(self.api); values['commit_api']['parents'] = parents
            with self.subTest(parents=parents), self.assertRaises(ValueError):
                self.compare({key: encoded(value) for key, value in values.items()})

if __name__=='__main__':unittest.main()
