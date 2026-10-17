import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import capture

def swift_leading_dot_fractions(text):
    # Tuple members (snapshot.0) and ranges (0..<16) are valid Swift. A numeric
    # fraction without its integer part, after whitespace/operator/punctuation,
    # is not. This targeted guard supplements, never replaces, native compilation.
    return re.findall(r"(?<![\w.])\.[0-9]+",text)

class Capture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def sealed(self):
        host=self.root/'host';host.mkdir()
        original=Path(__file__).resolve().parents[3]
        for relative in capture.ADAPTERS:
            target=host/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original/relative,target)
        data=dict(schema='p1-external-video-inputs-v1',scope='diagnostic-only-no-admission',livecontainer=capture.SOURCE,
            builder=capture.BUILDER,source_sha256=capture.SOURCE_SHA,adapter_files={name:capture.sha(host/name) for name in capture.ADAPTERS})
        path=host/'inputs.json';path.write_text(json.dumps(data));return host,path,data
    def test_real_seal(self):
        host,path,data=self.sealed();self.assertEqual(capture.validate(host,path,capture.sha(path)),data)
    def test_unapproved_digest(self):
        host,path,data=self.sealed()
        with self.assertRaisesRegex(ValueError,'unreviewed'):capture.validate(host,path,'0'*64)
    def test_altered_adapter(self):
        host,path,data=self.sealed();(host/'ci/p1/video/app.swift').write_text('altered')
        with self.assertRaisesRegex(ValueError,'adapter drift'):capture.validate(host,path,capture.sha(path))
    def test_wrong_source_pin(self):
        host,path,data=self.sealed();data['livecontainer']=dict(data['livecontainer'],commit='0'*40);path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'source pin'):capture.validate(host,path,capture.sha(path))
    def test_wrong_scope(self):
        host,path,data=self.sealed();data['scope']='admission';path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'identity'):capture.validate(host,path,capture.sha(path))
    def test_wrong_adapter_inventory(self):
        host,path,data=self.sealed();data['adapter_files'].pop('ci/p1/video/app.swift');path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'inventory'):capture.validate(host,path,capture.sha(path))
    def test_duplicate_json_key(self):
        host,path,data=self.sealed();path.write_text(path.read_text()[:-1]+',"schema":"p1-external-video-inputs-v1"}')
        with self.assertRaisesRegex(ValueError,'duplicate'):capture.validate(host,path,capture.sha(path))
    def test_linked_adapter(self):
        host,path,data=self.sealed();target=host/'ci/p1/video/app.swift';target.unlink();target.symlink_to(Path(__file__).parent/'app.swift')
        with self.assertRaisesRegex(ValueError,'linked'):capture.validate(host,path,capture.sha(path))
    def test_source_pin_pending_fails_closed(self):
        p=self.root/'inputs.json';p.write_text(json.dumps({'schema':'p1-external-video-inputs-v1','scope':'diagnostic-only-no-admission',
            'livecontainer':capture.SOURCE,'builder':capture.BUILDER,'source_sha256':capture.SOURCE_SHA,'adapter_files':{}}))
        with patch.dict(capture.SOURCE,commit=None):
            with self.assertRaisesRegex(ValueError,'source owner has not published'):capture.validate(self.root,p,capture.sha(p))
    def test_linked_host_rejected(self):
        link=self.root/'link';link.symlink_to(self.root,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'linked/missing'):capture.validate(link,self.root/'missing','a'*64)
    def test_raw_events_sequence(self):
        p=self.root/'event-001.json';p.write_text('{"type":"start"}')
        self.assertEqual(capture.read_events(self.root),[{'type':'start'}])
    def test_raw_events_missing_sequence(self):
        (self.root/'event-002.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'stale/missing'):capture.read_events(self.root)
    def test_raw_events_stale_file(self):
        (self.root/'event-001.json').write_text('{}');(self.root/'stale.png').write_text('x')
        with self.assertRaisesRegex(ValueError,'unexpected'):capture.read_events(self.root)
    def test_raw_events_link(self):
        (self.root/'target').write_text('{}');(self.root/'event-001.json').symlink_to(self.root/'target')
        with self.assertRaisesRegex(ValueError,'linked'):capture.read_events(self.root)
    def test_raw_events_error(self):
        (self.root/'event-001.json').write_text('{}');(self.root/'journal-error.txt').write_text('failed')
        with self.assertRaisesRegex(ValueError,'journal reported'):capture.read_events(self.root)
    def test_fraction_guard_reproduces_native_syntax_error(self):
        self.assertEqual(swift_leading_dot_fractions('deadline: .now() + .75; CGVector(dx: .5, dy: .5)'),['.75','.5','.5'])
        self.assertEqual(swift_leading_dot_fractions('deadline: .now() + 0.75; CGVector(dx: 0.5, dy: 0.5); snapshot.0; 0..<16'),[])
    def test_exact_source_generation(self):
        source=Path(os.environ['MAINTAINED_LIVE_CONTAINER_TEST_SOURCE'])/'LiveContainerSwiftUI/Views/V3UnifiedShell.swift'
        builder=Path(os.environ['P1_FROZEN_BUILDER_TEST_SOURCE'])
        output=self.root/'output';output.mkdir()
        project,renderer=capture.prepare(source,builder,self.root/'build',output)
        generated=(output/'sources/p0_signin_app.swift').read_text()
        self.assertEqual(generated.count('@main'),1)
        for fragment in capture.extract.fragments(source.read_text()).values():self.assertIn(fragment.rstrip('\n'),generated)
        for path in sorted((output/'sources').glob('*.swift')):
            self.assertEqual(swift_leading_dot_fractions(path.read_text()),[],str(path))
        self.assertNotIn('drawHierarchy',generated)
        self.assertNotIn('pngData()',generated)
        self.assertIn('V3PromptSection(prompt: prompt',generated)
        self.assertIn(capture.APP_ID,(project/'project.pbxproj').read_text())

if __name__=='__main__':unittest.main()

class DeviceContinuation(unittest.TestCase):
    def exercise(self,failure):
        from types import SimpleNamespace
        from unittest import mock
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);calls=[];queries=0
            def command(*args,**kwargs):
                nonlocal queries
                args=tuple(map(str,args));calls.append(args)
                if args==('xcrun','simctl','list','--json'):return '{}'
                if args==('xcrun','simctl','list','devices','--json'):
                    queries+=1
                    if queries==1:
                        if failure=='query':raise RuntimeError('phone query failed')
                        if failure=='json':return 'bad json'
                        return json.dumps({'devices':{'runtime':[{'udid':'phone','state':'Shutdown'}]}})
                    return json.dumps({'devices':{'runtime':[{'udid':'tablet','state':'Booted'}]}})
                if args[:3]==('xcrun','simctl','boot') and failure=='boot':raise RuntimeError('phone boot failed')
                if args[:3]==('xcrun','simctl','bootstatus'):raise RuntimeError(args[3]+' reached bootstatus')
                return ''
            cmd=mock.Mock(side_effect=command)
            runner=SimpleNamespace(available_devices=lambda:[('phone','phone','runtime'),('tablet','tablet','runtime')])
            def prepare(source,builder,build,evidence):
                products=build/'DerivedData/Build/Products';products.mkdir(parents=True)
                (products/'fixture.xctestrun').write_text('x');(products/'Debug-iphonesimulator/P0SignIn.app').mkdir(parents=True)
                return build/'project',SimpleNamespace(valid_png=lambda _:True)
            original=capture.sha
            def digest(path):return capture.SOURCE_SHA if str(path).endswith(capture.base.SHELL) else original(path)
            inputs=root/'inputs.json';inputs.write_text('{}')
            with mock.patch.object(capture.base,'acquire',return_value={}),mock.patch.object(capture.base,'checkout_proof',return_value={}),\
                 mock.patch.object(capture.base,'module',return_value=runner),mock.patch.object(capture,'Commands',return_value=cmd),\
                 mock.patch.object(capture,'prepare',side_effect=prepare),mock.patch.object(capture,'sha',side_effect=digest):
                result=capture.execute(Path(__file__).resolve().parents[3],root/'work',root/'evidence',inputs,'0'*64)
            self.assertFalse(result);report=capture.parse(root/'evidence/diagnostic-result.json')
            self.assertEqual([r['device_class'] for r in report['reports']],['phone','tablet']);self.assertEqual(queries,2)
            self.assertIn('tablet reached bootstatus',report['reports'][1]['errors'])
            shutdowns=[a for a in calls if a[:3]==('xcrun','simctl','shutdown')]
            self.assertEqual(shutdowns,[('xcrun','simctl','shutdown','phone')] if failure=='after-boot' else [])
    def test_query_failure_continues_tablet(self):self.exercise('query')
    def test_decode_failure_continues_tablet(self):self.exercise('json')
    def test_failed_boot_has_no_cleanup_ownership(self):self.exercise('boot')
    def test_booted_simulator_cleaned_after_failure(self):self.exercise('after-boot')
