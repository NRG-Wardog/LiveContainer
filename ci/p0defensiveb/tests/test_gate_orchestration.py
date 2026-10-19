"""Synthetic full-stage orchestration; every native/source/network seam is fake."""
import os,sys,tempfile,unittest
from pathlib import Path
from unittest import mock
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import native_gate as n,graph_contract as g
from inventory import dump,parse,TOOLCHAIN


class FakeGate(n.Gate):
    def __init__(self,*args,fail=None,**kwargs):super().__init__(*args,**kwargs);self.events=[];self.fail=fail
    def event(self,name):
        self.events.append(name)
        if self.fail==name:raise ValueError('synthetic '+name+' failure')
    def run(self,name,args,**kwargs):
        self.event('run:'+name);self.command_quiescence.append({'label':name,'quiescent':True,'pipesJoined':True,'leaderReaped':True,'errors':[]})
        dump(self.evidence/('logs/'+name+'.command.json'),{});dump(self.evidence/('logs/'+name+'.settlement.json'),{})
        if name=='retrieve-prior':self.prior_receipts.mkdir();dump(self.prior_receipts/'retrieval-helper.json',{})
        if name=='xcode-version':return TOOLCHAIN['xcode']
        if name=='swift-version':(self.evidence/'logs/swift-version.stderr.log').write_text(TOOLCHAIN['swift_stderr']);return TOOLCHAIN['swift_stdout']
        if name=='clang-version':return TOOLCHAIN['clang']
        return ''
    def acquire(self):
        self.event('acquire')
        for owner in g.OWNERS:
            self.roots[owner]=self.work/'sources'/owner;self.roots[owner].mkdir()
        for owner,relative in (('SideSign','Package.resolved'),('SideStore',n.LOCK)):
            path=self.roots[owner]/relative;path.parent.mkdir(exist_ok=True,parents=True);path.write_bytes(b'synthetic original lock')
    def capture_toolchain(self,phase,include_sdk=False):self.event('tools:'+phase);return {}
    def retained_sources(self,phase,after_build=False):self.event('sources:'+phase);return {}
    def retain_prior_originals(self):self.event('retain-prior');return {}
    def run_consumers(self):self.event('consumers')
    def native_prerequisites(self):self.event('prerequisites');self.native_env={}
    def capture_native_inputs(self,phase):self.event('native-inputs:'+phase);return {}
    def transport_build(self):self.event('transport')
    def app_build(self):
        self.event('app-build');self.app_product_checks_complete=True
        self.observed_app_lock=b'synthetic genuine resolver lock';(self.roots['SideStore']/n.LOCK).write_bytes(self.observed_app_lock)
    def verify_resources(self):self.event('resources')
    def capture_generated(self,phase):self.event('generated:'+phase);return {}
    def verify_terminal_products(self):self.event('terminal-products')
    def resolved_app_graph(self):self.event('terminal-app-graph');return {}


class GateOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
        self.host=self.root/'host';review=self.host/n.ADAPTER/'reviewed';review.mkdir(parents=True)
        for name in n.REVIEWED_PRIOR_FILES:(review/name).write_text('{}')
        self.data={'graph':g.execution_draft_graph(),'prior_phase_a':{}}
    def run_gate(self,fail=None):
        gate=FakeGate(self.data,self.host,self.root/'work',self.root/'evidence','1'*64,b'{}',fail=fail)
        env={'GH_TOKEN':'synthetic-not-sent','DEVELOPER_DIR':TOOLCHAIN['developer_dir'],'GITHUB_REPOSITORY':'NRG-Wardog/LiveContainer','GITHUB_REF':'refs/heads/'+n.BRANCH,'GITHUB_SHA':'1'*40,'GITHUB_RUN_ID':'7','GITHUB_RUN_ATTEMPT':'1'}
        with mock.patch.dict(os.environ,env),mock.patch.object(n,'validate_inputs',return_value=self.data),mock.patch.object(n.platform,'system',return_value='Darwin'),mock.patch.object(n.platform,'machine',return_value='arm64'),mock.patch.object(n,'git',return_value=b'1111111111111111111111111111111111111111\n'),mock.patch.object(n,'verify_host_overlay',return_value={}),mock.patch.object(n,'verify_prior_capture',return_value={'report':{},'lock_bytes':b'synthetic original lock'}),mock.patch.object(g,'verify_source_graph',return_value={}):
            if fail:
                with self.assertRaisesRegex(ValueError,'synthetic'):gate.execute()
            else:gate.execute()
        return gate
    def test_full_capture_orders_actual_stages_before_success(self):
        gate=self.run_gate();events=gate.events
        for before,after in zip(('acquire','retain-prior','consumers','prerequisites','transport','app-build','resources'),('retain-prior','consumers','prerequisites','transport','app-build','resources','terminal-products')):
            self.assertLess(events.index(before),events.index(after))
        self.assertTrue(gate.state['app_typechecked']);self.assertFalse(gate.state['compiled_final_commit'])
        self.assertEqual(n.verify_transport(gate.evidence)['capture_status'],'CAPTURED_FOR_INDEPENDENT_REVIEW')
    def test_consumer_failure_prevents_native_product_execution(self):
        gate=self.run_gate('consumers');self.assertNotIn('prerequisites',gate.events);self.assertNotIn('app-build',gate.events)
        self.assertFalse(gate.state['app_typechecked']);self.assertNotEqual(n.verify_transport(gate.evidence)['capture_status'],'CAPTURED_FOR_INDEPENDENT_REVIEW')
    def test_resource_failure_never_becomes_product_success(self):
        gate=self.run_gate('resources');self.assertFalse(gate.state['app_typechecked']);self.assertIn('terminal-products',gate.events)
        self.assertNotEqual(gate.state['status'],'CAPTURED_FOR_INDEPENDENT_REVIEW')
    def test_terminal_failure_revokes_success_but_retains_settled_diagnostics(self):
        gate=self.run_gate('terminal-products');self.assertEqual(gate.state['status'],'FAILED_TERMINAL_RETENTION_OR_IDENTITY')
        self.assertFalse(gate.state['app_typechecked']);self.assertFalse(n.verify_transport(gate.evidence)['compiled_final_commit'])
    def test_genuine_terminal_lock_is_retained_as_original_bytes(self):
        gate=self.run_gate();raw=(gate.evidence/'provenance/SideStore.Package.resolved.terminal-observed').read_bytes()
        self.assertEqual(raw,gate.observed_app_lock)
        self.assertEqual((gate.evidence/'provenance/SideSign.Package.resolved.terminal-observed').read_bytes(),b'synthetic original lock')

if __name__=='__main__':unittest.main()
