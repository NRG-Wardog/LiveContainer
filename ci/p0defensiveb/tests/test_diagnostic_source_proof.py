"""Portable source/ancestry mutations of real sealed bytes, never capture evidence."""
import copy,json,sys,unittest
from pathlib import Path
from unittest import mock
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import graph_contract as g
import consumer_contract as c
from inventory import sha

class DiagnosticSourceProofTests(unittest.TestCase):
    def setUp(self):
        self.fixture=HERE/'tests/fixtures/diagnostic-source-proof'
        self.source=HERE/'tests/fixtures/diagnostic-source'
        self.signs={g.OLD_SIGN:'c733',g.PREVIOUS_SIGN:'a375',g.KNOWN['SideSign'][0]:'b28'}
        self.edges={g.PREVIOUS_SIGN:g.OLD_SIGN,g.KNOWN['SideSign'][0]:g.PREVIOUS_SIGN}
    def git(self,root,*args):
        if args[:3]==('rev-list','--parents','-n'):
            commit=args[-1];return (commit+' '+self.edges[commit]+'\n').encode()
        commit,path=args[1].split(':',1)
        if root=='sign':return (self.fixture/(self.signs[commit]+'.'+path)).read_bytes()
        if path=='Sources/AnisetteDataProvider.swift' and commit in (g.OLD_AK,g.PREVIOUS_AK):
            return (self.fixture/'AnisetteDataProvider.before.swift').read_bytes()
        return (self.source/path).read_bytes()
    def edge(self,index):
        args=[(g.OLD_SIGN,g.PREVIOUS_SIGN,g.OLD_AK,g.PREVIOUS_AK),(g.PREVIOUS_SIGN,g.KNOWN['SideSign'][0],g.PREVIOUS_AK,g.KNOWN['AnisetteKit'][0])][index]
        return g.one_pin_edge('sign',*args)
    def test_both_exact_one_pin_edges_and_original_locks(self):
        with mock.patch.object(g,'git',side_effect=self.git),mock.patch.object(g,'snapshot',return_value={'changes':{'Package.swift':{}}}):
            rows=[self.edge(i) for i in (0,1)]
        self.assertEqual(rows[0]['unchanged_lock_sha256'],rows[1]['unchanged_lock_sha256'])
        self.assertEqual(rows[0]['commit'],rows[1]['parent'])
    def test_each_ancestry_edge_rejects_wrong_parent(self):
        for index,commit in enumerate((g.PREVIOUS_SIGN,g.KNOWN['SideSign'][0])):
            with self.subTest(edge=index),mock.patch.dict(self.edges,{commit:'f'*40}),mock.patch.object(g,'git',side_effect=self.git),self.assertRaisesRegex(ValueError,'parent differs'):
                self.edge(index)
    def test_each_ancestry_edge_rejects_manifest_extra_change(self):
        for index,commit in enumerate((g.PREVIOUS_SIGN,g.KNOWN['SideSign'][0])):
            def read(root,*args):
                raw=self.git(root,*args)
                return raw+b'// unreviewed change\n' if args==('show',commit+':Package.swift') else raw
            with self.subTest(edge=index),mock.patch.object(g,'git',side_effect=read),mock.patch.object(g,'snapshot',return_value={'changes':{'Package.swift':{}}}),self.assertRaisesRegex(ValueError,'exact AK revision'):
                self.edge(index)
    def test_each_ancestry_edge_rejects_lock_change_or_extra_path(self):
        for index,commit in enumerate((g.PREVIOUS_SIGN,g.KNOWN['SideSign'][0])):
            def read(root,*args):
                raw=self.git(root,*args)
                return raw+b'\n' if args==('show',commit+':Package.resolved') else raw
            with self.subTest(edge=index),mock.patch.object(g,'git',side_effect=read),mock.patch.object(g,'snapshot',return_value={'changes':{'Package.swift':{}}}),self.assertRaisesRegex(ValueError,'fabricated'):
                self.edge(index)
            with mock.patch.object(g,'git',side_effect=self.git),mock.patch.object(g,'snapshot',return_value={'changes':{'Package.swift':{},'extra':{}}}),self.assertRaises(ValueError):self.edge(index)
    def test_changed_swift_full_file_retains_identical_adi_span(self):
        with mock.patch.object(g,'git',side_effect=self.git):proof=g.producer_proof('ak')
        row=proof['Sources/AnisetteDataProvider.swift']
        self.assertFalse(row['byte_identical']);self.assertTrue(row['adi_span_byte_identical'])
        self.assertNotEqual(row['before_sha256'],row['after_sha256'])
        self.assertEqual(row['after_sha256'],c.SOURCE_SHA256['AnisetteKit']['Sources/AnisetteDataProvider.swift'])
        for path in ('Native/Loader/adi_consumption_debug.h','Sources/LoginDiagnosticTrace.swift'):self.assertTrue(proof[path]['byte_identical'])
    def test_diagnostic_whole_file_hash_rejects_unreviewed_extension(self):
        def read(root,*args):
            raw=self.git(root,*args)
            return raw+b'\n' if args==('show',g.KNOWN['AnisetteKit'][0]+':Sources/AnisetteDataProvider.swift') else raw
        with mock.patch.object(g,'git',side_effect=read),self.assertRaisesRegex(ValueError,'Swift source hashes'):g.producer_proof('ak')
    def test_adi_span_and_appended_boundary_have_independent_guards(self):
        new=(self.source/'Sources/AnisetteDataProvider.swift').read_bytes()
        for kind,mutated in [('span',new.replace(b'private enum TemporaryADIConsumptionTrace {',b'private enum TemporaryADIConsumptionTrace {\n// drift',1)),('boundary',new.replace(g.DIAGNOSTIC_APPEND_MARKER,b'\n// changed boundary\n',1))]:
            def read(root,*args):
                return mutated if args==('show',g.KNOWN['AnisetteKit'][0]+':Sources/AnisetteDataProvider.swift') else self.git(root,*args)
            with self.subTest(kind=kind),mock.patch.object(g,'SWIFT_AFTER_SHA256',sha(mutated)),mock.patch.object(g,'git',side_effect=read),self.assertRaisesRegex(ValueError,'span changed|diagnostic boundary'):
                g.producer_proof('ak')
    def test_original_reviewed_local_identity_is_not_relabelled(self):
        inventory=json.loads((HERE/'prior_adapter/ci/p0defensive/reviewed/diagnostic-source-inventory.json').read_bytes())
        source={'commit':g.KNOWN['AnisetteKit'][0],'tree':g.KNOWN['AnisetteKit'][1],'tracked':inventory['files']}
        report=g.diagnostic_source_review(source)
        self.assertEqual(report['reviewed_local_commit'],'e0267064280008cee34846a00eba1d7eb7aeba5c')
        self.assertEqual(report['published_commit'],'227dfd8c8456cd62e4ceff4971b17afb2003d7e8')
        self.assertEqual(report['complete_tracked_files'],65)
        for field in ('commit','tree','tracked'):
            value=copy.deepcopy(source);value[field]='f'*40 if field!='tracked' else {}
            with self.subTest(field=field),self.assertRaises(ValueError):g.diagnostic_source_review(value)
    def test_adi_header_and_login_trace_whole_file_mutations_reject(self):
        for path in ('Native/Loader/adi_consumption_debug.h','Sources/LoginDiagnosticTrace.swift'):
            def read(root,*args):
                raw=self.git(root,*args)
                return raw+b'\n' if args==('show',g.KNOWN['AnisetteKit'][0]+':'+path) else raw
            with self.subTest(path=path),mock.patch.object(g,'git',side_effect=read),self.assertRaisesRegex(ValueError,'producer changed'):g.producer_proof('ak')
    def test_consumer_exact_ids_and_only_reviewed_source_hashes(self):
        self.assertEqual(sum(map(len,c.SUITE_IDS.values()))*2,38)
        self.assertEqual(c.SOURCE_BASELINES['AnisetteKit'],g.KNOWN['AnisetteKit'][0])
        self.assertEqual(c.SOURCE_SHA256['AnisetteKit']['Native/Loader/vm_initialization_diagnostics.h'],'0fbe1ac033f2d2dbe7f3c5fbd0cade277f8e7eb51529264dfec3ca75279ba862')
        self.assertEqual(c.SOURCE_SHA256['AnisetteKit']['Native/Loader/adi_consumption_debug.h'],'077b377c87b201893f83afbff5a4dd37e01354253f08045a3831adcb50022346')
        self.assertEqual(c.SOURCE_SHA256['AnisetteKit']['Sources/LoginDiagnosticTrace.swift'],'bd86c77eb520cf0721cfbbdb1e9100261bd53324ef0f912713873357fc76ae2e')

if __name__=='__main__':unittest.main()
