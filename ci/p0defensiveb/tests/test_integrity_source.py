"""Host-only synthetic graph and exact stored patch mutation tests; no source child."""
import copy,hashlib,io,json,sys,tempfile,unittest
from contextlib import nullcontext
from types import SimpleNamespace
from pathlib import Path
from unittest import mock
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import integrity_source as s, graph_contract as g, descendant_contract as d, execution_contract as e
from inventory import sha


def synthetic_graph():
    graph=g.execution_draft_graph()
    lock={'parent':s.BASE,'commit':'d'*40,'tree':'c'*40,'changes':{'Package.resolved':{
        'before':{'mode':'100644','type':'blob','git_object':'a'*40,'sha256':'b'*64},
        'after':{'mode':'100644','type':'blob','git_object':'b'*40,'sha256':'c'*64}}}}
    source={'parent':lock['commit'],'commit':'f'*40,'tree':'e'*40,'changes':s.patch_manifest()['changes']}
    graph.update(kind='BOUND_EXACT_SOURCE_GRAPH',lock_sha256='c'*64,sidesign_edges={'resolver_lock':lock,'integrity_source':source})
    graph['owners']['SideSign'].update(commit=source['commit'],tree=source['tree'],changes={**lock['changes'],**source['changes']})
    graph['owners']['SideStore'].update(commit='b'*40,tree='a'*40,changes={'Dependencies/SideSign':{
        'before':{'mode':'160000','type':'commit','git_object':g.OLD_SIGN},
        'after':{'mode':'160000','type':'commit','git_object':source['commit']}}})
    graph['children']=g.expected_children(graph['owners'])
    return graph


class IntegritySourceTests(unittest.TestCase):
    def test_pending_has_two_explicit_uninvented_edges(self):
        graph=g.execution_draft_graph();g.validate_graph(graph)
        self.assertEqual(graph['sidesign_edges'],s.pending_edges())
        self.assertIsNone(graph['sidesign_edges']['integrity_source']['parent'])
        self.assertIsNone(e.descendants_draft()['SideSign_lock']['commit'])
    def test_real_patch_manifest_and_independent_review_agree(self):
        manifest=s.patch_manifest();self.assertEqual(len(manifest['changes']),10)
        self.assertEqual(manifest['candidate_commit'],s.CANDIDATE)
        self.assertNotIn('Package.resolved',manifest['changes'])
        self.assertNotIn('Package.swift',manifest['changes'])
    def test_pending_rejects_any_invented_intermediate(self):
        for edge in ('resolver_lock','integrity_source'):
            for field in ('commit','tree','changes'):
                graph=g.execution_draft_graph();graph['sidesign_edges'][edge][field]='1'*40
                with self.subTest(edge=edge,field=field),self.assertRaises(ValueError):g.validate_graph(graph)
    def test_pending_rejects_source_parent_fabrication(self):
        graph=g.execution_draft_graph();graph['sidesign_edges']['integrity_source']['parent']='1'*40
        with self.assertRaises(ValueError):g.validate_graph(graph)
    def test_two_edges_bind_final_compiled_owner(self):
        graph=synthetic_graph();self.assertEqual(g.validate_graph(graph,execution=True),graph['owners'])
        self.assertEqual(graph['children']['SideStore/Dependencies/SideSign']['commit'],graph['sidesign_edges']['integrity_source']['commit'])
    def test_missing_or_extra_edge_rejected(self):
        for edge in ('resolver_lock','integrity_source','extra'):
            graph=synthetic_graph()
            if edge=='extra':graph['sidesign_edges'][edge]={}
            else:del graph['sidesign_edges'][edge]
            with self.subTest(edge=edge),self.assertRaises(ValueError):g.validate_graph(graph,execution=True)
    def test_wrong_intermediate_parent_rejected(self):
        graph=synthetic_graph();graph['sidesign_edges']['resolver_lock']['parent']='1'*40
        with self.assertRaises(ValueError):g.validate_graph(graph,execution=True)
    def test_skipped_intermediate_rejected(self):
        graph=synthetic_graph();graph['sidesign_edges']['integrity_source']['parent']=s.BASE
        with self.assertRaises(ValueError):g.validate_graph(graph,execution=True)
    def test_review_candidate_cannot_be_actual_source_child(self):
        graph=synthetic_graph();graph['sidesign_edges']['integrity_source']['commit']=s.CANDIDATE
        with self.assertRaises(ValueError):g.validate_graph(graph,execution=True)
    def test_source_child_cannot_be_relabelled_lock_only(self):
        graph=synthetic_graph();graph['sidesign_edges']['integrity_source']['changes']=graph['sidesign_edges']['resolver_lock']['changes']
        with self.assertRaises(ValueError):g.validate_graph(graph,execution=True)
    def test_source_edge_cannot_change_manifest_or_lock(self):
        for name in ('Package.swift','Package.resolved'):
            graph=synthetic_graph();graph['sidesign_edges']['integrity_source']['changes'][name]={}
            with self.subTest(path=name),self.assertRaises(ValueError):g.validate_graph(graph,execution=True)
    def test_source_edge_rejects_missing_extra_or_mutated_path(self):
        for mode in ('missing','extra','mutated'):
            graph=synthetic_graph();changes=graph['sidesign_edges']['integrity_source']['changes']
            if mode=='missing':del changes[next(iter(changes))]
            elif mode=='extra':changes['unreviewed']={}
            else:changes['Sources/Anisette/AnisetteDataManager.swift']['after']['sha256']='1'*64
            with self.subTest(mode=mode),self.assertRaises(ValueError):g.validate_graph(graph,execution=True)
    def test_lock_edge_rejects_extra_source_delta(self):
        graph=synthetic_graph();graph['sidesign_edges']['resolver_lock']['changes']['source']={}
        with self.assertRaises(ValueError):g.validate_graph(graph,execution=True)
    def test_lock_edge_rejects_mode_type_blob_digest_drift(self):
        for field,value in (('mode','100755'),('type','commit'),('git_object','0'*40),('sha256','1'*64)):
            graph=synthetic_graph();graph['sidesign_edges']['resolver_lock']['changes']['Package.resolved']['after'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):g.validate_graph(graph,execution=True)
    def test_owner_union_cannot_omit_source_edge(self):
        graph=synthetic_graph();graph['owners']['SideSign']['changes']=graph['sidesign_edges']['resolver_lock']['changes']
        with self.assertRaises(ValueError):g.validate_graph(graph,execution=True)
    def test_store_must_target_final_source_child(self):
        graph=synthetic_graph();graph['owners']['SideStore']['changes']['Dependencies/SideSign']['after']['git_object']=graph['sidesign_edges']['resolver_lock']['commit']
        with self.assertRaises(ValueError):g.validate_graph(graph,execution=True)
    def test_integrity_objects_retain_exact_lock_and_manifest(self):
        changes=s.patch_manifest()['changes']
        with mock.patch.object(d,'direct',return_value={'changes':changes}),mock.patch.object(d,'git',side_effect=lambda root,*a:b'lock' if a[-1].endswith(':Package.resolved') else b'manifest'):
            proof=d.sidesign_integrity_child(None,'d'*40,'f'*40,'e'*40,b'lock',b'lock')
        self.assertEqual(proof['parent'],'d'*40);self.assertEqual(proof['lock_sha256'],sha(b'lock'))
        self.assertFalse(proof['compiled_final_commit']);self.assertEqual(proof['independent_patch_review_sha256'],s.PATCH_REVIEW_SHA256)
    def test_integrity_lock_mutation_rejected_even_if_patch_matches(self):
        with mock.patch.object(d,'direct',return_value={'changes':s.patch_manifest()['changes']}),mock.patch.object(d,'git',return_value=b'other'):
            with self.assertRaisesRegex(ValueError,'retain exact genuine resolver lock'):d.sidesign_integrity_child(None,'d'*40,'f'*40,'e'*40,b'lock',b'lock')
    def test_integrity_manifest_mutation_rejected(self):
        def read(root,*args):return b'lock' if args[-1].endswith(':Package.resolved') else b'new' if args[-1].startswith('f'*40) else b'original'
        with mock.patch.object(d,'direct',return_value={'changes':s.patch_manifest()['changes']}),mock.patch.object(d,'git',side_effect=read):
            with self.assertRaisesRegex(ValueError,'retain exact manifest'):d.sidesign_integrity_child(None,'d'*40,'f'*40,'e'*40,b'lock',b'lock')
    def test_integrity_requires_observed_terminal_equality_before_objects(self):
        with mock.patch.object(d,'direct') as direct:
            for observed,terminal in ((None,None),(b'',b''),(b'first',b'other')):
                with self.assertRaises(ValueError):d.sidesign_integrity_child(None,None,None,None,observed,terminal)
        direct.assert_not_called()
    def test_complete_graph_calls_both_edges_in_order(self):
        graph=synthetic_graph();edges=graph['sidesign_edges'];calls=[]
        def lock(*args):calls.append('lock');return edges['resolver_lock']
        def source(*args):calls.append('source');self.assertEqual(args[1],edges['resolver_lock']['commit']);return edges['integrity_source']
        bindings={owner:{k:graph['owners'][owner][k] for k in ('commit','tree')} for owner in ('SideSign','SideStore')}
        bindings['SideSign_lock']={k:edges['resolver_lock'][k] for k in ('commit','tree')}
        with mock.patch.object(d,'sidesign_child',side_effect=lock),mock.patch.object(d,'sidesign_integrity_child',side_effect=source),mock.patch.object(d,'sidestore_capture_input',return_value={'changes':graph['owners']['SideStore']['changes']}),mock.patch.object(g,'sha',return_value='c'*64):
            actual=g.complete_graph({'SideSign':None,'SideStore':None},bindings,b'lock',b'lock')
        self.assertEqual(actual,graph);self.assertEqual(calls,['lock','source'])
    def test_old_two_binding_shape_rejected(self):
        with mock.patch.object(d,'sidesign_child') as child,self.assertRaises(ValueError):g.complete_graph({}, {'SideSign':{},'SideStore':{}},b'lock',b'lock')
        child.assert_not_called()
    def test_distinct_publication_and_review_requirements(self):
        self.assertEqual(set(e.RECEIPTS),{'SideSign-lock.publication.json','SideSign.publication.json','SideStore.publication.json','independent-descendant-clearance.json','independent-integrity-source-clearance.json'})
        self.assertEqual(set(e.descendants_draft()),{'SideSign_lock','SideSign','SideStore','receipt_sha256'})

class IntegrityAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.host=Path(self.tmp.name)
        self.directory=self.host/e.ADAPTER/'reviewed';self.directory.mkdir(parents=True)
        self.graph=synthetic_graph();self.data=e.descendants_draft();self.originals={}
        for owner in e.DESCENDANTS:
            row=self.graph['sidesign_edges']['resolver_lock'] if owner=='SideSign_lock' else self.graph['owners'][owner]
            self.data[owner]={k:row[k] for k in ('commit','tree')}
            parent=self.graph['sidesign_edges']['integrity_source']['parent'] if owner=='SideSign' else row.get('parent',row.get('base'))
            name='SideSign-lock' if owner=='SideSign_lock' else owner
            self.originals[name+'.publication.json']={'repository':'NRG-Wardog/'+('SideSign' if owner=='SideSign_lock' else owner),
                'commit':{'sha':row['commit'],'tree':{'sha':row['tree']},'parents':[{'sha':parent}]},
                'tree':{'sha':row['tree'],'truncated':False},'ref':{'object':{'sha':row['commit']}}}
        self.originals['independent-descendant-clearance.json']={'schema_version':1,'scope':'DEFENSIVE_AB_SOURCE_ONLY_DESCENDANT_EQUIVALENCE',
            'phase_a_artifact_sha256':'8'*64,**{owner:self.data[owner] for owner in e.DESCENDANTS},'compiled_final_commit':False,'phase_b_execution_approved':False}
        self.originals['independent-integrity-source-clearance.json']={'schema_version':1,'scope':'EXACT_LOCK_PRESERVING_INTEGRITY_SOURCE_CHILD',
            'patch_review_sha256':s.PATCH_REVIEW_SHA256,'SideSign_lock':self.data['SideSign_lock'],'SideSign':self.data['SideSign'],
            'lock_sha256':self.graph['lock_sha256'],'compiled_final_commit':False,'phase_b_execution_approved':False}
    def write(self):
        for name,value in self.originals.items():
            raw=(json.dumps(value,sort_keys=True)+'\n').encode();(self.directory/name).write_bytes(raw);self.data['receipt_sha256'][name]=sha(raw)
    def validate(self):
        self.write();e.validate_descendants(self.data,self.host,self.graph,execution=True)
    def test_each_distinct_original_publication_and_review_passes(self):self.validate()
    def test_integrity_parent_must_be_true_intermediate(self):
        self.originals['SideSign.publication.json']['commit']['parents']=[{'sha':s.BASE}]
        with self.assertRaisesRegex(ValueError,'parent/tree'):self.validate()
    def test_resolver_parent_must_be_captured_source(self):
        self.originals['SideSign-lock.publication.json']['commit']['parents']=[{'sha':'1'*40}]
        with self.assertRaisesRegex(ValueError,'parent/tree'):self.validate()
    def test_integrity_review_must_name_same_intermediate(self):
        self.originals['independent-integrity-source-clearance.json']['SideSign_lock']={'commit':'1'*40,'tree':'2'*40}
        with self.assertRaisesRegex(ValueError,'lineage'):self.validate()
    def test_integrity_review_must_name_same_final_source(self):
        self.originals['independent-integrity-source-clearance.json']['SideSign']={'commit':'1'*40,'tree':'2'*40}
        with self.assertRaisesRegex(ValueError,'lineage'):self.validate()
    def test_integrity_review_must_bind_same_genuine_lock(self):
        self.originals['independent-integrity-source-clearance.json']['lock_sha256']='1'*64
        with self.assertRaisesRegex(ValueError,'lineage'):self.validate()
    def test_integrity_review_must_bind_original_patch_review(self):
        self.originals['independent-integrity-source-clearance.json']['patch_review_sha256']='1'*64
        with self.assertRaisesRegex(ValueError,'scope'):self.validate()
    def test_source_reviews_cannot_claim_runtime_or_approval(self):
        for name in ('independent-integrity-source-clearance.json','independent-descendant-clearance.json'):
            for flag in ('compiled_final_commit','phase_b_execution_approved'):
                self.originals[name][flag]=True
                with self.subTest(name=name,flag=flag),self.assertRaises(ValueError):self.validate()
                self.originals[name][flag]=False
    def test_distinct_intermediate_receipt_mandatory(self):
        self.data['receipt_sha256'].pop('SideSign-lock.publication.json')
        with self.assertRaisesRegex(ValueError,'original descendant receipts'):e.validate_descendants(self.data,self.host,self.graph,execution=True)
    def test_publication_raw_bytes_mutation_rejected(self):
        self.write();path=self.directory/'SideSign-lock.publication.json';path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'receipt bytes'):e.validate_descendants(self.data,self.host,self.graph,execution=True)
    def test_missing_final_source_clearance_rejected(self):
        self.write();(self.directory/'independent-integrity-source-clearance.json').unlink()
        with self.assertRaises(ValueError):e.validate_descendants(self.data,self.host,self.graph,execution=True)
    def test_general_descendant_review_must_cover_intermediate(self):
        self.originals['independent-descendant-clearance.json'].pop('SideSign_lock')
        with self.assertRaisesRegex(ValueError,'review schema'):self.validate()


class IntermediateRetentionTests(unittest.TestCase):
    def setUp(self):
        from retention import RawStore
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);base=Path(self.tmp.name).resolve()
        self.root=base/'source';self.root.mkdir();self.store=RawStore(base/'evidence')
        self.raw=b'original intermediate source\n';self.oid=hashlib.sha1(b'blob '+str(len(self.raw)).encode()+b'\0'+self.raw).hexdigest()
        self.listing=('100644 blob '+self.oid+'\tfile\0').encode();self.head='f'*40;self.parents={'d'*40:s.BASE,'f'*40:'d'*40}
        self.calls=[];self.lock_changes={'Package.resolved':{}};self.source_changes=s.patch_manifest()['changes']
    def git(self,root,*args):
        self.calls.append(args)
        if args==('rev-parse','--show-toplevel'):return (str(self.root)+'\n').encode()
        if args==('rev-parse','HEAD'):return (self.head+'\n').encode()
        if args[:3]==('rev-list','--parents','-n'):
            commit=args[-1];return (commit+' '+self.parents[commit]+'\n').encode()
        if args==('rev-parse','d'*40+'^{tree}'):return ('c'*40+'\n').encode()
        if args==('ls-tree','-rzt','--full-tree','d'*40):return self.listing
        raise ValueError('unexpected git command: '+str(args))
    def run_retention(self,raw=None):
        data=self.raw if raw is None else raw
        stream=(self.oid+' blob '+str(len(data))+'\n').encode()+data+b'\n'
        process=SimpleNamespace(stdin=io.BytesIO(),stdout=io.BytesIO(stream))
        with mock.patch('inventory.git',side_effect=self.git),mock.patch('inventory.snapshot',side_effect=lambda root,base,commit:{'changes':self.lock_changes if base==s.BASE else self.source_changes}),mock.patch.object(self.store,'_git_batch',return_value=nullcontext(process)):
            return s.retain_lock_child_tree(self.store,self.root,'d'*40,'f'*40,label='before/SideSign-resolver-lock-child')
    def test_intermediate_retained_without_changing_final_head(self):
        value=self.run_retention();entry=value['entries'][0]
        self.assertEqual(value['commit'],'d'*40);self.assertEqual(value['source_path'],str(self.root))
        self.assertEqual(entry['label'],'before/SideSign-resolver-lock-child:file')
        self.assertEqual((self.store.root/entry['blob_path']).read_bytes(),self.raw)
        self.assertEqual(sum(command==('rev-parse','HEAD') for command in self.calls),2)
        self.assertFalse(any('checkout' in command for command in self.calls))
    def test_final_head_must_remain_final_source(self):
        self.head='d'*40
        with self.assertRaisesRegex(ValueError,'HEAD differs'):self.run_retention()
    def test_both_direct_parent_edges_required(self):
        for child in ('d'*40,'f'*40):
            old=self.parents[child];self.parents[child]='1'*40
            with self.subTest(child=child),self.assertRaisesRegex(ValueError,'sole-parent'):self.run_retention()
            self.parents[child]=old
    def test_intermediate_cannot_hide_extra_source_change(self):
        self.lock_changes['source']={}
        with self.assertRaisesRegex(ValueError,'not lock-only'):self.run_retention()
    def test_source_patch_rechecked_before_retention(self):
        self.source_changes={}
        with self.assertRaisesRegex(ValueError,'source patch differs'):self.run_retention()
    def test_intermediate_gitlink_forbidden(self):
        self.listing=('160000 commit '+'1'*40+'\tchild\0').encode()
        with self.assertRaisesRegex(ValueError,'gitlink'):self.run_retention()
    def test_raw_blob_substitution_rejected(self):
        from retention import RetentionError
        with self.assertRaises(RetentionError):self.run_retention(b'different')


class IntegrityGateIntegrationTests(unittest.TestCase):
    def setUp(self):
        import native_gate,integrity_runtime
        self.n=native_gate;self.r=integrity_runtime;self.graph=synthetic_graph()
        self.gate=native_gate.Gate({'graph':self.graph},Path('/host'),Path('/work'),Path('/evidence'),'REVIEW_REQUIRED',b'{}')
        source=self.graph['owners']['SideSign']
        self.report={'status':'CAPTURED_FOR_INDEPENDENT_REVIEW','source_commit':source['commit'],'source_tree':source['tree'],
            'results':{'tests':8,'failures':0,'errors':0,'skipped':0,'case_ids':list(integrity_runtime.CASE_IDS),'successful_case_ids':list(integrity_runtime.CASE_IDS)}}
    def test_fixture_follows_existing_full_product_build(self):
        calls=[]
        with mock.patch.object(self.n.NativeBuildMixin,'app_build',side_effect=lambda gate:calls.append('products')),mock.patch.object(self.r,'run_integrity',side_effect=lambda gate:(calls.append('integrity') or self.report)):
            self.gate.app_build()
        self.assertEqual(calls,['products','integrity']);self.assertEqual(self.gate.state['library_integrity_tests']['tests'],8)
    def test_product_failure_prevents_fixture(self):
        with mock.patch.object(self.n.NativeBuildMixin,'app_build',side_effect=ValueError('products failed')),mock.patch.object(self.r,'run_integrity') as runtime:
            with self.assertRaises(ValueError):self.gate.app_build()
        runtime.assert_not_called()
    def test_patch_candidate_cannot_be_claimed_as_compiled_source(self):
        self.report['source_commit']=s.CANDIDATE
        with mock.patch.object(self.n.NativeBuildMixin,'app_build'),mock.patch.object(self.r,'run_integrity',return_value=self.report):
            with self.assertRaisesRegex(ValueError,'actual compiled'):self.gate.app_build()
        self.assertNotIn('library_integrity_tests',self.gate.state)
    def test_summary_count_without_exact_cases_rejected(self):
        self.report['results']={'tests':8,'failures':0,'errors':0,'skipped':0}
        with mock.patch.object(self.n.NativeBuildMixin,'app_build'),mock.patch.object(self.r,'run_integrity',return_value=self.report):
            with self.assertRaisesRegex(ValueError,'complete exact8'):self.gate.app_build()
        self.assertNotIn('library_integrity_tests',self.gate.state)


if __name__=='__main__':unittest.main()
