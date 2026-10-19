"""Actual relocated project generation; native/process/network actions forbidden."""
from pathlib import Path
import plistlib
import ast,json
from hashlib import sha256
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import native_runtime as runtime
import test_project_setup as project_fixture


class PreparationTests(unittest.TestCase):
    def setUp(self):
        # Reuse source-copy fixtures and their subprocess/network tripwires,
        # but invoke Runtime.prepare and the real project_setup implementation.
        self.source=project_fixture.ProjectPreparationTests()
        self.source.setUp();self.addCleanup(self.source.doCleanups)
        self.now=100.0;self.persisted=[];self.calls=[];self.stage_failure=None
        self.clock=patch.object(runtime.time,'monotonic',side_effect=lambda:self.now)
        self.clock.start();self.addCleanup(self.clock.stop)
        self.scope=SimpleNamespace(deadline=1000.0,cleanup_deadline=1200.0,fixture=None,creation_intent=None,rows=[])
        self.scope.persist=lambda:self.persisted.append(self.scope.deadline)
        def remaining(cap,cleanup=False):
            limit=self.scope.cleanup_deadline if cleanup else self.scope.deadline
            if limit<=self.now:raise TimeoutError('synthetic deadline')
            return min(cap,limit-self.now)
        self.scope.remaining=remaining
        r=runtime.Runtime.__new__(runtime.Runtime);self.r=r
        r.scope=self.scope;r.project_setup=self.source.adapter;r.source=self.source.source;r.builder=self.source.builder
        r.local=self.source.local;r.work=self.source.root/'runtime-work';r.work.mkdir()
        r.output=self.source.root/'runtime-output';r.output.mkdir();(r.output/'commands').mkdir()
        r.video=SimpleNamespace(__file__=str(self.source.video/'capture.py'))
        r.capture=SimpleNamespace(__file__=str(self.source.preflight/'capture.py'),RUNNER_ID='org.sidestore.fixture.p1video.uitests.xctrunner')
        r.session='a'*32;r.device=None;r.gui=None;r._evidence={}
        def observe(name):
            self.calls.append((name,self.scope.deadline,self.scope.remaining(999)))
            if self.stage_failure==name:raise RuntimeError('synthetic '+name+' failure')
        def command(*args,timeout=300,**kwargs):
            name='build' if args[0]=='xcodebuild' else str(args[2])
            observe(name);self.assertLessEqual(timeout,self.scope.deadline-self.now)
            if name=='build':
                products=r.work/'build/DerivedData/Build/Products';products.mkdir(parents=True)
                (products/'Debug-iphonesimulator/P0SignIn.app').mkdir(parents=True)
                runner=products/'Debug-iphonesimulator/P0SignInUITests-Runner.app';runner.mkdir()
                (runner/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':r.capture.RUNNER_ID}))
                recipe={'UITests':{'TestBundlePath':'P0SignInUITests.xctest','IsUITestBundle':True}}
                (products/'Original.xctestrun').write_bytes(plistlib.dumps(recipe))
            self.now+=1
            return ''
        r.command=command
        def create(scope,root,device_class='phone'):
            self.assertIs(scope,self.scope);self.assertEqual(device_class,'phone')
            root.mkdir();scope.creation_intent={'device':'owned-device'};scope.fixture={'owned_created':{'device':'owned-device'}}
            observe('create');self.now+=1;return {'device':'owned-device'}
        r.fresh=SimpleNamespace(create_for_ui=create)
        def install(command,device):
            self.assertIs(command,r.command);self.assertEqual(device,'owned-device');observe('install-preparation');return {'verified':True}
        r.capture.prepare_install=install
        def isolation(command,executable,output):
            self.assertIs(command,r.command);self.assertEqual(executable,r.work/'capture-prerequisites');self.assertEqual(output,r.output)
            observe('isolation')
        parent=self
        class GUI:
            def __init__(self,scope,device,folder):
                parent.assertIs(scope,parent.scope);parent.assertEqual(device,'owned-device')
                folder.mkdir();self.started=False
            def start(self):observe('gui');self.started=True
        r.window=SimpleNamespace(startup_isolation=isolation,OwnedGUI=GUI)
        self.storage=patch.object(runtime.artifact_budget,'preflight',side_effect=lambda root:observe('storage') or {'bounded':True})
        self.storage.start();self.addCleanup(self.storage.stop)
    def test_portable_png_fixture_is_exact_guarded_builder_extraction(self):
        raw=(self.source.builder/'scripts/run_p0_signin_rendering.py').read_bytes()
        folder=Path(__file__).resolve().parents[1]/'analysis/fixtures'
        binding=json.loads((folder/'maintained_valid_png.json').read_bytes())
        self.assertEqual(sha256(raw).hexdigest(),binding['sourceSHA256'])
        node=next(n for n in ast.parse(raw.decode()).body if isinstance(n,ast.FunctionDef) and n.name=='valid_png')
        extracted=(ast.get_source_segment(raw.decode(),node)+'\n').encode()
        self.assertEqual(extracted,(folder/'maintained_valid_png.py').read_bytes())
        self.assertEqual(sha256(extracted).hexdigest(),binding['fixtureSHA256'])
    def test_real_project_contract_and_full_preparation_order(self):
        result=self.r.prepare({},360)
        self.assertEqual([r[0] for r in self.calls],['build','create','boot','bootstatus','install-preparation','install','storage','isolation','gui'])
        self.assertTrue(all(r[1]==460 for r in self.calls));self.assertEqual(self.scope.deadline,1000)
        self.assertEqual(self.persisted,[460,1000])
        self.assertTrue((self.r.output/'preparation/direct-project-preparation.json').is_file())
        self.assertTrue((self.r.work/'build/P0SignIn.xcodeproj/project.pbxproj').is_file())
        self.assertEqual(result.value['device'],'owned-device');self.assertTrue(self.r.gui.started)
        recipe=plistlib.loads(Path(result.value['xctestrun']).read_bytes())
        self.assertEqual(recipe['UITests']['EnvironmentVariables'],{'P1_DIRECT_SESSION':'a'*32})
        self.assertTrue((self.r.output/'receipts/runner-recipe.json').is_file())
        self.assertTrue((self.r.output/'receipts/inclusive-storage-plan.json').is_file())
    def test_failed_build_restores_scope_and_never_creates_device(self):
        self.stage_failure='build'
        with self.assertRaisesRegex(RuntimeError,'build failure'):self.r.prepare({},360)
        self.assertEqual(self.scope.deadline,1000);self.assertEqual([r[0] for r in self.calls],['build'])
        self.assertIsNone(self.scope.fixture)
        self.assertTrue((self.r.output/'preparation/direct-project-preparation.json').is_file())
    def test_existing_preparation_path_rejected_by_real_project_contract(self):
        (self.r.output/'preparation').mkdir()
        with self.assertRaisesRegex(ValueError,'fresh canonical'):self.r.prepare({},360)
        self.assertEqual(self.calls,[]);self.assertEqual(self.scope.deadline,1000)
    def test_partial_create_remains_owned_after_failure_and_restoration(self):
        self.stage_failure='create'
        with self.assertRaisesRegex(RuntimeError,'create failure'):self.r.prepare({},360)
        self.assertIsNone(self.r.device)
        self.assertEqual(self.scope.fixture['owned_created']['device'],'owned-device')
        self.assertEqual(self.scope.creation_intent['device'],'owned-device')
        self.assertEqual(self.scope.deadline,1000)
    def test_gui_object_remains_retained_if_start_fails(self):
        self.stage_failure='gui'
        with self.assertRaisesRegex(RuntimeError,'gui failure'):self.r.prepare({},360)
        self.assertIsNotNone(self.r.gui);self.assertFalse(self.r.gui.started)
        self.assertEqual(self.scope.deadline,1000)
    def test_existing_earlier_scope_deadline_never_extended(self):
        self.scope.deadline=140
        self.r.prepare({},360)
        self.assertTrue(all(r[1]==140 for r in self.calls));self.assertEqual(self.scope.deadline,140)
        self.assertEqual(self.persisted,[140,140])


class DeadlineRestorationTests(unittest.TestCase):
    def object(self):return SimpleNamespace(scope=SimpleNamespace(deadline=1000,cleanup_deadline=1200,persist=lambda:None))
    def test_preparation_restores_success_body_failure_and_initial_persist_failure(self):
        for mode in ('success','body','persist'):
            with self.subTest(mode=mode),patch.object(runtime.time,'monotonic',return_value=100):
                obj=self.object();observed=[];count=0
                def persist():
                    nonlocal count
                    count+=1;observed.append(obj.scope.deadline)
                    if mode=='persist' and count==1:raise OSError('first persist')
                obj.scope.persist=persist
                @runtime.bounded_preparation
                def body(self,context,timeout):
                    self.asserted_deadline=self.scope.deadline
                    if mode=='body':raise RuntimeError('body')
                    return 7
                if mode=='success':self.assertEqual(body(obj,{},20),7)
                else:
                    with self.assertRaises((RuntimeError,OSError)):body(obj,{},20)
                self.assertEqual(obj.scope.deadline,1000);self.assertEqual(observed,[120,1000])
    def test_cleanup_restores_after_success_failure_and_nested_cap(self):
        for fail in (False,True):
            with self.subTest(fail=fail),patch.object(runtime.time,'monotonic',return_value=100):
                obj=self.object();observed=[]
                @runtime.bounded_cleanup
                def inner(self,context,timeout):
                    observed.append(self.scope.cleanup_deadline)
                    if fail:raise RuntimeError('inner')
                @runtime.bounded_cleanup
                def outer(self,context,timeout):
                    observed.append(self.scope.cleanup_deadline)
                    try:inner(self,context,5)
                    finally:observed.append(self.scope.cleanup_deadline)
                if fail:
                    with self.assertRaises(RuntimeError):outer(obj,{},20)
                else:outer(obj,{},20)
                self.assertEqual(observed,[120,105,120]);self.assertEqual(obj.scope.cleanup_deadline,1200)
    def test_cleanup_does_not_extend_prior_reserve(self):
        obj=self.object();obj.scope.cleanup_deadline=103
        @runtime.bounded_cleanup
        def body(self,context,timeout):return self.scope.cleanup_deadline
        with patch.object(runtime.time,'monotonic',return_value=100):self.assertEqual(body(obj,{},20),103)
        self.assertEqual(obj.scope.cleanup_deadline,103)
    def test_final_persist_failure_still_restores_deadline_and_chains_body_error(self):
        obj=self.object();count=0
        def persist():
            nonlocal count
            count+=1
            if count==2:raise OSError('restoration persist')
        obj.scope.persist=persist
        @runtime.bounded_preparation
        def body(self,context,timeout):raise RuntimeError('preparation body')
        with patch.object(runtime.time,'monotonic',return_value=100):
            with self.assertRaises(OSError) as caught:body(obj,{},20)
        self.assertEqual(obj.scope.deadline,1000)
        self.assertIsInstance(caught.exception.__context__,RuntimeError)
        self.assertEqual(str(caught.exception.__context__),'preparation body')

if __name__=='__main__':unittest.main()
