"""Local byte/source/adapter tests; mock Commands never launch native software."""
import copy
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
import zlib
import offline_analysis as o


def png(channel=255):
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',100,100,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+bytes([channel])*300)*100))+chunk(b'IEND',b'')


def receipt(argv):
    return dict(argv=list(map(str,argv)),command_id='command-0001',exit_code=0,failure_type=None,primary_error=None,
                writer_settled=True,cleanup_errors=[],stdout='',stderr='',launch_receipt=dict(state='pre-exec-observed',closed=True,eof=True,exec_failure=None))


class MockCommands:
    behavior=None
    def __init__(self,scope,folder):self.folder=folder
    def __call__(self,*argv,**kwargs):
        row=receipt(argv)
        if type(self).behavior is not None:type(self).behavior(argv,row)
        (self.folder/'command-0001.stdout').write_bytes(row['stdout'].encode())
        (self.folder/'command-0001.stderr').write_bytes(row['stderr'].encode())
        return row


class Tests(unittest.TestCase):
    def runtime(self,folder):
        retained=[];remaining=[]
        runtime=SimpleNamespace(ps=SimpleNamespace(Commands=MockCommands),scope=object(),
                 retain=lambda name,raw:retained.append((name,raw)),
                 remaining=lambda cap:remaining.append(cap) or min(cap,10),local=o.LOCAL,
                 video=SimpleNamespace(__file__=str(o.timeout_case.VIDEO/'capture.py')))
        runtime.retained=retained;runtime.allowances=remaining
        MockCommands.behavior=None
        return runtime
    def test_source_guards_and_generated_independent_source(self):
        with tempfile.TemporaryDirectory() as d:
            r=self.runtime(Path(d));paths=o.source_guard(r)
            self.assertEqual(set(paths),{'control','independent'})
            r.local=Path(d)
            with self.assertRaisesRegex(ValueError,'source root'):o.source_guard(r)
    def test_command_success_keeps_empty_real_logs(self):
        with tempfile.TemporaryDirectory() as d:
            r=self.runtime(Path(d));c=o.Commands(r,Path(d)/'logs')
            self.assertEqual(c('swift','input',timeout=600),'')
            self.assertEqual(c.stdout(['swift','input']),b'')
            self.assertEqual(r.allowances,[600,1]);self.assertEqual(len(r.retained),1)
    def test_command_failure_retained_before_rejection(self):
        with tempfile.TemporaryDirectory() as d:
            r=self.runtime(Path(d));c=o.Commands(r,Path(d)/'logs')
            MockCommands.behavior=lambda argv,row:row.update(exit_code=1,failure_type='CalledProcessError',stderr='failed')
            with self.assertRaises(ValueError):c('swift','input')
            self.assertEqual(json.loads(r.retained[0][1])['exit_code'],1)
    def test_deadline_is_not_reset(self):
        with tempfile.TemporaryDirectory() as d:
            r=self.runtime(Path(d));r.remaining=lambda cap:(_ for _ in ()).throw(TimeoutError('expired'))
            c=o.Commands(r,Path(d)/'logs')
            with self.assertRaises(TimeoutError):c('swift','input')
            self.assertEqual(c.rows,[])
    def test_decoder_exact_source_input_output_and_receipt_hashes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);r=self.runtime(root);c=o.Commands(r,root/'logs')
            source=root/'source.swift';source.write_bytes(b'// synthetic, never executed')
            pixels=root/'pixels.bgra';pixels.write_bytes(b'pixels')
            def success(argv,row):Path(argv[-1]).write_bytes(b'{"answer":1}')
            MockCommands.behavior=success
            result=o.decoder(c,r,root,'unit',source,b'{"input":1}',root,[pixels])
            self.assertEqual(result,{'answer':1})
            binding=json.loads(r.retained[-1][1]);self.assertTrue(binding['completed'])
            self.assertEqual(binding['sourceSHA256'],sha256(source.read_bytes()).hexdigest())
            self.assertEqual(binding['outputSHA256'],sha256(b'{"answer":1}').hexdigest())
            self.assertEqual(binding['commandReceiptSHA256'],sha256(o.canonical(c.rows[-1])).hexdigest())
    def test_decoder_mutated_source_pixels_or_input_is_failure(self):
        for which in ('source','pixels','input'):
            with self.subTest(which=which),tempfile.TemporaryDirectory() as d:
                root=Path(d);r=self.runtime(root);c=o.Commands(r,root/'logs')
                source=root/'source.swift';source.write_bytes(b'// synthetic')
                pixels=root/'pixels.bgra';pixels.write_bytes(b'pixels')
                def mutate(argv,row):
                    Path(argv[-1]).write_bytes(b'{}')
                    {'source':source,'pixels':pixels,'input':Path(argv[2])}[which].write_bytes(b'changed')
                MockCommands.behavior=mutate
                with self.assertRaisesRegex(ValueError,'changed'):o.decoder(c,r,root,'unit',source,b'{}',root,[pixels])
                self.assertFalse(json.loads(r.retained[-1][1])['completed'])
    def test_decoder_does_not_swallow_execution_failure(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);r=self.runtime(root);c=o.Commands(r,root/'logs');source=root/'s.swift';source.write_bytes(b'// test')
            MockCommands.behavior=lambda argv,row:row.update(exit_code=1,failure_type='error')
            with self.assertRaises(ValueError):o.decoder(c,r,root,'unit',source,b'{}',root,[])
            self.assertFalse(json.loads(r.retained[-1][1])['completed'])
    def test_independent_original_measured_geometry_and_png_dimensions(self):
        events=[dict(type='marker-geometry',rect=[10,70,80,10],screenPoints=[100,100],scale=1)]
        controls=dict(markerFrame=[10,70,80,10],copyFrame=[20,20,60,10],copyHittable=True,copyLabel='Copy Details')
        paths={'before':'/before.png','after':'/after.png'};raw={'before':png(254),'after':png(255)}
        value=o.independent_input(events,controls,paths,raw)
        self.assertEqual(value['markerRectPixels'],[10,70,80,10]);self.assertEqual(value['copyRectPixels'],[20,20,60,10])
        self.assertEqual(value['pixelSize'],[100,100])
        for change in (lambda e,c:e[0].update(scale=2),lambda e,c:c.update(markerFrame=[12,70,80,10]),lambda e,c:e[0].update(scale=True)):
            e=copy.deepcopy(events);c=copy.deepcopy(controls);change(e,c)
            with self.assertRaises(ValueError):o.independent_input(e,c,paths,raw)
    def test_missing_or_corrupt_png_never_accepted(self):
        e=[dict(type='marker-geometry',rect=[10,70,80,10],screenPoints=[100,100],scale=1)]
        c=dict(markerFrame=[10,70,80,10],copyFrame=[20,20,60,10],copyHittable=True,copyLabel='Copy Details')
        with self.assertRaises(ValueError):o.independent_input(e,c,{'before':'b','after':'a'},{'before':png(),'after':b'bad'})
    def test_symlink_and_fifo_retained_evidence_rejected(self):
        import os
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'real').write_bytes(b'bytes');(root/'linked').symlink_to(root/'real');os.mkfifo(root/'fifo')
            for leaf in ('linked','fifo'):
                with self.assertRaises((ValueError,OSError)):o.read(root/leaf)
    def test_failed_case_cannot_start_offline_commands_and_retains_failure(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);r=self.runtime(root);r.output=root;r.session='a'*32
            r.ps.atomic=lambda path,value:path.write_bytes(o.canonical(value))
            (root/'case-sequence.json').write_bytes(o.canonical(dict(session=r.session,sequenceCompleted=False,failed=True,errors=['native failed'])))
            with self.assertRaisesRegex(ValueError,'settled case'):o.run(r,dict(session=r.session,scenario='timeout'))
            result=json.loads((root/'offline-analysis/result.json').read_bytes())
            self.assertFalse(result['completed']);self.assertIn('error',result)
            self.assertFalse((root/'offline-analysis/commands').exists())
    def test_rational_output_remains_exact(self):
        self.assertEqual(o.json_value({'x':Fraction(1,3)}),{'x':{'numerator':1,'denominator':3}})

    def test_final_full_context_requires_actual_bytes_not_flag(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);directory=o.Directory(root)
            self.addCleanup(directory.close)
            plan=dict(windowID=99,sourceWidth=2,sourceHeight=2,sourceStride=8)
            pixels=b'\xff'*16
            row=dict(schema='p1-direct-registration-buffer-v1',format='BGRA8',session='a'*32,windowID=99,width=2,height=2,stride=8,bytes=16,sha256=sha256(pixels).hexdigest(),displayTimeEstablished=False,admissionEligible=False)
            (root/'final.json').write_bytes(o.canonical(row));(root/'final.bgra').write_bytes(pixels)
            self.assertEqual(o.final_context(directory,plan,'a'*32)['bytes'],16)
            for mode in ('bytes','window','bool','clock'):
                bad=copy.deepcopy(row)
                if mode=='window':bad['windowID']=100
                elif mode=='bool':bad['width']=True
                elif mode=='clock':bad['displayTimeEstablished']=True
                (root/'final.json').write_bytes(o.canonical(bad));(root/'final.bgra').write_bytes(b'bad' if mode=='bytes' else pixels)
                with self.assertRaises(ValueError):o.final_context(directory,plan,'a'*32)
    def test_frame_file_census_has_no_success_subset(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);directory=o.Directory(root);self.addCleanup(directory.close)
            rows=[{'newFrame':False},{'newFrame':True,'packedPixels':'frame-00001.rois.bgra'}]
            (root/'frame-00001.rois.bgra').write_bytes(b'pixels')
            o.frame_inventory(directory,rows)
            (root/'frame-00002.rois.bgra').write_bytes(b'unknown complete frame')
            with self.assertRaisesRegex(ValueError,'census'):o.frame_inventory(directory,rows)


class ActualRasterReplay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_registration_bridge as fixture
        fixture.BridgeTests.setUpClass();helper=fixture.BridgeTests()
        baseline=helper.run_bridge();row,packed=helper.stream_frame(baseline)
        row.update(index=0,packedPixels='frame-00000.rois.bgra')
        first=o.canonical(row)
        cls.binding=o.bridge.RegistrationJoin(baseline,expected_baseline_proof_sha256=baseline.proof_sha256).promote(
            first,packed,expected_manifest_sha256=sha256(first).hexdigest(),timebase=(1,1))
        second=copy.deepcopy(row);second.update(index=1,packedPixels='frame-00001.rois.bgra',displayTimeMach=300,callbackBeforeMach=400,callbackAfterMach=410)
        samples=dict(frames=[row,second],completeFrames=2,deliveredRecords=2,overflowRecords=0,copiedBytes=2*len(packed),error=None)
        cls.records=o.packed_frames.inspect(samples,json.loads(baseline.plan_bytes),timebase=(1,1),load=lambda n:packed,
                                            expected_geometry=(row['contentRect'],row['contentScale'],row['scaleFactor']))
    def test_all_actual_raster_frames_replayed_from_bound_first(self):
        with tempfile.TemporaryDirectory() as d:
            proofs=o.replay_frames(self.binding,self.records,Path(d)/'proofs',lambda n:n)
            self.assertEqual([p['nativeIndex'] for p in proofs],[0,1])
            self.assertEqual([p['actualMarker'] for p in proofs],[456,456])
            self.assertEqual(len(list((Path(d)/'proofs').iterdir())),2)
    def test_skipped_first_or_mutated_actual_crop_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'restart'):o.replay_frames(self.binding,self.records[1:],Path(d)/'skip',lambda n:n)
            rows=copy.deepcopy(self.records);raw=rows[1]['crops']['marker'];rows[1]['crops']['marker']=b'X'+raw[1:]
            with self.assertRaises(ValueError):o.replay_frames(self.binding,rows,Path(d)/'mutated',lambda n:n)
            self.assertTrue((Path(d)/'mutated/frame-00000.json').is_file())
            self.assertFalse((Path(d)/'mutated/frame-00001.json').exists())

if __name__=='__main__':unittest.main()
