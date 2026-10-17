import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock
import subprocess
import sys
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('probe_capture', HERE / 'capture.py')
p = importlib.util.module_from_spec(spec); spec.loader.exec_module(p)

class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name) / 'pixels'; self.root.mkdir()
        self.trace = {'schema': 'p1-pixel-probe-v1', 'scenario': 'timeout', 'clock': 'ProcessInfo.systemUptime',
            'admissionEligible': False, 'captureFinished': True, 'captureStartUptime': 100.0,
            'checkpointUptime': 101.0, 'requestedIntervalSeconds': 0.1, 'maximumFrames': 120,
            'maximumSeconds': 12, 'frames': [{'file': 'frame-000.png', 'tickStartUptime': 100.1,
                'beforeUptime': 100.11, 'afterUptime': 100.12, 'tickEndUptime': 100.14,
                'drawHierarchyReturned': True, 'widthPoints': 400, 'heightPoints': 800, 'scale': 3}],
            'events': [{'ordinal': 1, 'uptime': 100.2, 'payload': 'safe', 'expectedPayload': 'safe',
                'clipboardExact': True, 'changeCount': 2, 'generation': 0, 'shown': True}],
            'transitions': [], 'errors': [], 'priorJournalWrites': [{'beforeUptime': 100.0, 'afterUptime': 100.01}]}
        for scenario in p.SCENARIOS:
            folder = self.root / scenario; folder.mkdir(); (folder / 'frame-000.png').write_bytes(b'png')
            value = copy.deepcopy(self.trace); value['scenario'] = scenario; p.write(folder / 'trace.json', value)
    def tearDown(self): self.tmp.cleanup()
    def update(self, change):
        path = self.root / 'timeout/trace.json'; value = p.parse(path); change(value); p.write(path, value)
    def inspect(self): return p.inspect_pixels(self.root, lambda data: data == b'png')
    def rejects(self):
        with self.assertRaises((ValueError, FileNotFoundError)): self.inspect()
    def test_complete_exact_inventory(self):
        manifest, costs, complete = self.inspect(); self.assertTrue(complete); self.assertEqual(len(manifest), 3)
        self.assertAlmostEqual(costs['timeout']['capture_png_total_seconds'], .04)
        self.assertFalse(costs['timeout']['timing_capability_proven'])
    def test_missing_scenario(self): shutil.rmtree(self.root / 'timeout'); self.rejects()
    def test_extra_scenario(self): (self.root / 'extra').mkdir(); self.rejects()
    def test_stale_png(self): (self.root / 'timeout/frame-001.png').write_bytes(b'png'); self.rejects()
    def test_missing_png(self): (self.root / 'timeout/frame-000.png').unlink(); self.rejects()
    def test_path_escape(self): self.update(lambda t: t['frames'][0].update(file='../escape.png')); self.rejects()
    def test_duplicate_frame(self): self.update(lambda t: t['frames'].append(t['frames'][0])); self.rejects()
    def test_nonmonotonic_frame(self): self.update(lambda t: t['frames'][0].update(afterUptime=99)); self.rejects()
    def test_invalid_number(self): self.update(lambda t: t['frames'][0].update(beforeUptime=True)); self.rejects()
    def test_nonfinite_number(self):
        path = self.root / 'timeout/trace.json'; path.write_text(path.read_text().replace('100.11', 'NaN')); self.rejects()
    def test_bad_png(self): (self.root / 'timeout/frame-000.png').write_bytes(b'bad'); self.rejects()
    def test_symlink_file(self):
        path = self.root / 'timeout/frame-000.png'; path.unlink(); path.symlink_to(self.root / 'replacement/frame-000.png'); self.rejects()
    def test_symlink_root(self):
        alias = self.root.parent / 'alias'; alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError): p.inspect_pixels(alias, lambda _: True)
    def test_ancestor_alias_supported(self):
        alias = self.root.parent / 'alias'; alias.symlink_to(self.root.parent, target_is_directory=True)
        self.assertTrue(p.inspect_pixels(alias / 'pixels', lambda _: True)[2])
    def test_partial_not_complete(self): self.update(lambda t: t.update(captureFinished=False)); self.assertFalse(self.inspect()[2])
    def test_render_false_not_complete(self): self.update(lambda t: t['frames'][0].update(drawHierarchyReturned=False)); self.assertFalse(self.inspect()[2])
    def test_no_events_not_complete(self): self.update(lambda t: t.update(events=[])); self.assertFalse(self.inspect()[2])
    def test_errors_not_complete(self): self.update(lambda t: t.update(errors=['interrupted'])); self.assertFalse(self.inspect()[2])
    def test_empty_partial_trace_retained(self):
        self.update(lambda t: t.update(frames=[], captureFinished=False))
        (self.root / 'timeout/frame-000.png').unlink(); self.assertFalse(self.inspect()[2])
    def test_duplicate_event_counter(self):
        self.update(lambda t: t['events'].append(dict(t['events'][0], ordinal=2))); self.rejects()
    def test_forged_payload_boolean(self): self.update(lambda t: t['events'][0].update(payload='wrong')); self.rejects()
    def test_bad_journal_clock(self): self.update(lambda t: t['priorJournalWrites'][0].update(afterUptime=99)); self.rejects()
    def test_duplicate_json_key(self):
        path = self.root / 'timeout/trace.json'; path.write_text(path.read_text().replace('"scenario": "timeout"', '"scenario": "timeout", "scenario": "timeout"')); self.rejects()
    def test_more_than_120_frames(self): self.update(lambda t: t.update(frames=t['frames'] * 121)); self.rejects()
    def test_changed_capture_bounds(self): self.update(lambda t: t.update(maximumFrames=1000)); self.rejects()
    def test_real_acquire_bootstrap_adapter(self):
        logs = self.root.parent / 'logs'; logs.mkdir()
        row = p.SOURCE
        def run(argv, **kwargs):
            self.assertEqual(kwargs['timeout'], 300)
            value = row['commit'] if argv[-1] == 'HEAD' else row['tree'] if argv[-1] == 'HEAD^{tree}' else \
                row['repository'] if argv[-3:] == ['remote', 'get-url', 'origin'] else ''
            return subprocess.CompletedProcess(argv, 0, value.encode())
        with mock.patch.object(p.subprocess, 'run', side_effect=run) as runner:
            self.assertEqual(p.acquire(self.root.parent / 'source', row, p.bootstrap_commands(logs)), row)
        self.assertEqual(runner.call_count, 8)
        self.assertTrue((logs / 'bootstrap.log').is_file())
    def test_bootstrap_failure_is_retained(self):
        with mock.patch.object(p.subprocess, 'run', return_value=subprocess.CompletedProcess(['git'], 1, b'failed')):
            with self.assertRaises(ValueError): p.bootstrap_commands(self.root.parent)('git', timeout=30)
        self.assertIn(b'failed', (self.root.parent / 'bootstrap.log').read_bytes())
    def test_journal_contract(self):
        app = (HERE / 'app.swift').read_text()
        self.assertIn('checkpoint(reason: "clipboard-event-', app); self.assertIn('checkpoint(reason: "frame")', app)
        self.assertIn('"captureFinished": finished', app); self.assertIn('options: .atomic', app)
        self.assertIn('priorJournalWrites', app); self.assertIn('scenario already exists', app)
    def test_same_identity_reopen_and_failed_arm_guard(self):
        app = (HERE / "app.swift").read_text()
        self.assertIn("}, reopen: { shown = true })", app)
        self.assertIn('tick()\n            guard state == "recording" else { return }', app)
    def test_pixels_not_expected_state(self):
        app = (HERE / 'app.swift').read_text()
        self.assertIn('window.drawHierarchy(in: bounds, afterScreenUpdates: false)', app)
        self.assertNotIn('accessibilityActivate', app); self.assertNotIn('"Copied"', app)
        self.assertNotIn('copiedDetails', app); self.assertIn('image.pngData()', app)
    def test_both_recovery_shapes(self):
        source = (HERE / 'recovery.swift').read_text()
        for marker in ['__P1_RECOVERY_DECLARATIONS__', '__P1_RECOVERY_MODIFIER__']: self.assertEqual(source.count(marker), 1)
        for token in ['TabView(selection:', 'NavigationView {', 'List {', '.listStyle(.insetGrouped)', '.automatic',
            '.safeAreaInset(edge: .bottom)', '.allowsHitTesting(false)', '.accessibilityHidden(true)']: self.assertIn(token, source)
    def test_test_ids_and_matrix(self):
        source = (HERE / 'ui_tests.swift').read_text()
        for method in p.METHODS: self.assertEqual(source.count('func ' + method + '('), 1)
        self.assertIn('for production in [false, true]', source); self.assertIn('for kind in ["none", "operation"]', source)
        self.assertIn('target.tap()', source); self.assertIn('copy.tap()', source)
    def test_diagnostic_workflow_isolation(self):
        source = (HERE.parents[2] / '.github/workflows/p1-native-candidate.yml').read_text()
        self.assertIn('ci/p1/probe/capture.py', source); self.assertNotIn('ci/p1/native_gate.py', source)
        self.assertIn('diagnostic', source); self.assertIn('timeout-minutes: 60', source)

class DeviceContinuationTests(unittest.TestCase):
    def exercise(self, first_failure):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); work = root/'work'; output = root/'evidence'
            state_queries = 0; calls = []
            def command(*args, **kwargs):
                nonlocal state_queries
                args = tuple(map(str,args)); calls.append(args)
                if args == ('xcrun','simctl','list','--json'): return '{}'
                if args == ('xcrun','simctl','list','devices','--json'):
                    state_queries += 1
                    if state_queries == 1:
                        if first_failure == 'query': raise RuntimeError('phone state query failed')
                        if first_failure == 'json': return 'malformed-json'
                        return json.dumps({'devices':{'runtime':[{'udid':'phone','state':'Shutdown'}]}})
                    return json.dumps({'devices':{'runtime':[{'udid':'tablet','state':'Booted'}]}})
                if args[:3] == ('xcrun','simctl','boot'):
                    if first_failure == 'boot': raise RuntimeError('phone boot failed')
                if args[:3] == ('xcrun','simctl','bootstatus'):
                    raise RuntimeError(args[3] + ' reached bootstatus')
                return ''
            fake_command=mock.Mock(side_effect=command)
            runner=SimpleNamespace(available_devices=lambda:[('phone','phone','runtime'),('tablet','tablet','runtime')])
            def prepare(source,builder,build,evidence):
                products=build/'DerivedData/Build/Products';products.mkdir(parents=True)
                (products/'probe.xctestrun').write_text('test fixture')
                return build/'project',SimpleNamespace(valid_png=lambda _:True)
            original_sha=p.sha
            def digest(path): return p.SOURCE_SHA if str(path).endswith(p.SHELL) else original_sha(path)
            with mock.patch.object(p,'acquire',return_value={}), mock.patch.object(p,'checkout_proof',return_value={}), \
                 mock.patch.object(p,'module',return_value=runner), mock.patch.object(p,'Commands',return_value=fake_command), \
                 mock.patch.object(p,'prepare',side_effect=prepare), mock.patch.object(p,'sha',side_effect=digest):
                result=p.execute(HERE.parents[2],work,output,HERE/'inputs.json','0'*64)
            self.assertFalse(result)
            report=p.parse(output/'diagnostic-result.json')
            self.assertEqual([r['device_class'] for r in report['reports']],['phone','tablet'])
            self.assertEqual(state_queries,2)
            self.assertIn('tablet reached bootstatus',report['reports'][1]['errors'])
            shutdowns=[a for a in calls if a[:3] == ('xcrun','simctl','shutdown')]
            self.assertEqual(shutdowns, [('xcrun','simctl','shutdown','phone')] if first_failure == 'after-boot' else [])
            self.assertTrue((output/'phone/collection-report.json').is_file())
            self.assertTrue((output/'tablet/collection-report.json').is_file())
            self.assertFalse(report['admission_eligible'])
    def test_first_device_query_failure_continues_second(self): self.exercise('query')
    def test_first_device_decode_failure_continues_second(self): self.exercise('json')
    def test_failed_boot_does_not_claim_boot_ownership(self): self.exercise('boot')
    def test_successful_boot_is_cleaned_after_failure(self): self.exercise('after-boot')


class SealTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.host = Path(self.tmp.name) / 'host'; self.host.mkdir()
        for name in p.ADAPTERS:
            target = self.host / name; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((HERE.parents[2] / name).read_bytes())
        self.input = self.host / 'inputs.json'
        self.data = {'schema':'p1-diagnostic-inputs-v1','scope':'diagnostic-only-no-admission',
            'livecontainer':dict(p.SOURCE),'builder':dict(p.BUILDER),'source_sha256':p.SOURCE_SHA,
            'adapter_files':{name:p.sha(self.host/name) for name in p.ADAPTERS}}
        self.seal()
    def tearDown(self): self.tmp.cleanup()
    def seal(self): p.write(self.input,self.data);self.approved=p.sha(self.input)
    def validate(self): return p.validate(self.host,self.input,self.approved)
    def reject(self):
        with self.assertRaises(ValueError): self.validate()
    def test_valid_exact_seal(self): self.assertEqual(self.validate(),self.data)
    def test_wrong_approved_digest(self): self.approved='0'*64;self.reject()
    def test_malformed_approved_digest(self): self.approved='not-a-digest';self.reject()
    def test_altered_adapter_bytes(self):
        path=self.host/'ci/p1/probe/app.swift';path.write_text(path.read_text()+'// drift');self.reject()
    def test_wrong_source_pin(self): self.data['livecontainer']['commit']='0'*40;self.seal();self.reject()
    def test_wrong_builder_pin(self): self.data['builder']['tree']='0'*40;self.seal();self.reject()
    def test_wrong_source_hash(self): self.data['source_sha256']='0'*64;self.seal();self.reject()
    def test_wrong_scope(self): self.data['scope']='admission';self.seal();self.reject()
    def test_missing_adapter(self): self.data['adapter_files'].pop('ci/p1/probe/app.swift');self.seal();self.reject()
    def test_extra_adapter(self): self.data['adapter_files']['other']='0'*64;self.seal();self.reject()
    def test_duplicate_input_key(self):
        text=self.input.read_text();self.input.write_text(text.replace('"scope":','"scope":"wrong", "scope":'))
        self.approved=p.sha(self.input);self.reject()
    def test_linked_adapter(self):
        path=self.host/'ci/p1/probe/app.swift';target=self.host.parent/'app.swift';path.rename(target);path.symlink_to(target);self.reject()
    def test_linked_adapter_directory(self):
        path=self.host/'ci/p1/probe';target=self.host.parent/'probe';path.rename(target);path.symlink_to(target,target_is_directory=True);self.reject()
    def test_linked_host_rejected(self):
        alias=self.host.parent/'linked';alias.symlink_to(self.host,target_is_directory=True)
        with self.assertRaises(ValueError):p.validate(alias,self.input,self.approved)
    def test_cli_rejects_linked_root(self):
        alias=self.host.parent/'linked';alias.symlink_to(self.host,target_is_directory=True)
        result=subprocess.run([sys.executable,'-B',str(HERE/'capture.py'),'--host-root',str(alias),
            '--inputs',str(self.input),'--approved-inputs-sha256',self.approved],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('linked/missing host root',result.stderr)
    def test_cli_accepts_real_sealed_root(self):
        result=subprocess.run([sys.executable,'-B',str(HERE/'capture.py'),'--host-root',str(self.host),
            '--inputs',str(self.input),'--approved-inputs-sha256',self.approved],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
    def test_parent_alias_supported(self):
        alias=self.host.parent/'ancestor';alias.symlink_to(self.host.parent,target_is_directory=True)
        self.assertEqual(p.validate(alias/'host',self.input,self.approved),self.data)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.summary = {'result':'Passed','passedTests':4,'failedTests':0,'skippedTests':0,'totalTestCount':4}
        names = [f'probe-{s}-{phase}' for s in p.SCENARIOS for phase in ['before','after']]
        names += [f'probe-recovery-{shape}-{size}-{kind}' for shape in ['production-list','synthetic-vstack']
            for size in ['default','largest'] for kind in ['none','operation']]
        self.manifest = [{'attachmentName': name, 'exportedFileName': f'{i}.png'} for i,name in enumerate(names)]
        for row in self.manifest: (self.root / row['exportedFileName']).write_bytes(b'png')
        p.write(self.root / 'manifest.json', self.manifest)
        for scenario in p.SCENARIOS: p.write(self.root / (scenario+'.json'), {'schema':'p1-probe-completion-v1','scenario':scenario,
            'admissionEligible':False,'waitCompleted':True,'status':{'label':'finished'}})
        index=0
        for shape in ['production-list','synthetic-vstack']:
            for largest in [False,True]:
                for kind in ['none','operation']:
                    p.write(self.root / f'topology-{index}.json', {'schema':'p1-probe-topology-v1','shape':shape,
                        'largestDynamicType':largest,'kind':kind,'admissionEligible':False}); index+=1
    def tearDown(self): self.tmp.cleanup()
    def inspect(self): return p.inspect_exports(self.root, self.summary, lambda data: data == b'png')
    def test_full_export_inventory(self): self.assertTrue(self.inspect()['collection_complete']); self.assertEqual(len(self.inspect()['screenshots']),14)
    def test_skips_not_complete(self): self.summary.update(skippedTests=1); self.assertFalse(self.inspect()['collection_complete'])
    def test_missing_topology(self):
        (self.root / 'topology-0.json').unlink()
        with self.assertRaises(ValueError): self.inspect()
    def test_reused_png_rejected(self):
        self.manifest[1]['exportedFileName']=self.manifest[0]['exportedFileName'];p.write(self.root/'manifest.json',self.manifest)
        with self.assertRaises(ValueError): self.inspect()
    def test_missing_screenshot_rejected(self):
        self.manifest.pop();p.write(self.root/'manifest.json',self.manifest)
        with self.assertRaises(ValueError): self.inspect()
    def test_missing_completion_rejected(self):
        (self.root/'timeout.json').unlink()
        with self.assertRaises(ValueError): self.inspect()
    def test_completion_false_not_complete(self):
        path=self.root/'timeout.json';v=p.parse(path);v['waitCompleted']=False;p.write(path,v);self.assertFalse(self.inspect()['collection_complete'])
    def test_admission_flag_rejected(self):
        path=self.root/'timeout.json';v=p.parse(path);v['admissionEligible']=True;p.write(path,v)
        with self.assertRaises(ValueError): self.inspect()
    def test_video_only_if_present(self): self.assertEqual(self.inspect()['exported_video_files'],[])

if __name__ == '__main__': unittest.main()
