import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from transport import Channel, atomic, Video
import signal
from unittest.mock import Mock

class Transport(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'app';self.root.mkdir();self.out=Path(self.temp.name)/'out';self.out.mkdir()
    def worker(self,stop):
        previous=0
        while not stop.is_set():
            try:r=json.loads((self.root/'request.json').read_text())
            except (FileNotFoundError,json.JSONDecodeError):time.sleep(.0005);continue
            if r['id']!=previous:
                previous=r['id'];now=time.monotonic()
                atomic(self.root/'response.json',dict(id=previous,appReceive=now,appSend=now,marker=r.get('marker')))
            time.sleep(.0005)
    def test_real_atomic_exchange_and_all_stages(self):
        stop=threading.Event();t=threading.Thread(target=self.worker,args=(stop,));t.start()
        try:
            def command(*args,**kwargs):Path(args[-1]).write_bytes(b'png')
            c=Channel(self.root,self.out,'fixture-only',command)
            for stage in ['pre','mid','post']:c.calibrate(stage)
            r=json.loads((self.out/'calibration.json').read_text())
            self.assertEqual(len(r['exchanges']),24);self.assertEqual(len(r['markers']),9)
            self.assertEqual({x['stage'] for x in r['exchanges']},{'pre','mid','post'})
            self.assertFalse(r['admissionEligible'])
            self.assertTrue(all(x['hostBefore']<=x['appReceive']<=x['appSend']<=x['hostAfter'] for x in r['exchanges']))
        finally:stop.set();t.join()
    def test_partial_command_is_retained_on_timeout(self):
        with patch('transport.time.monotonic',side_effect=[0,6,7]):
            c=Channel(self.root,self.out,'fixture',lambda *a,**k:None)
            with self.assertRaisesRegex(ValueError,'timed out'):c.request('clock')
        r=json.loads((self.out/'calibration.json').read_text());self.assertIsNone(r['commands'][0]['response'])
    def test_linked_channel_rejected(self):
        link=Path(self.temp.name)/'link';link.symlink_to(self.root)
        with self.assertRaises(ValueError):Channel(link,self.out,'fixture',None)
    def test_linked_response_rejected(self):
        target=self.out/'response';target.write_text('{}');(self.root/'response.json').symlink_to(target)
        c=Channel(self.root,self.out,'fixture',None)
        with self.assertRaisesRegex(ValueError,'linked response'):c.request('clock')
    def test_event_failure_preserved(self):
        (self.root/'journal-error.txt').write_text('failure')
        c=Channel(self.root,self.out,'fixture',None)
        with self.assertRaisesRegex(ValueError,'journal failed'):c.await_event('start',.1)
    def recorder(self,code):
        process=Mock();process.pid=1234;process.poll.return_value=code;process.returncode=code
        (self.out/'screen.mp4').write_bytes(b'video')
        with patch('transport.subprocess.Popen',return_value=process):return Video('fixture',self.out)
    def test_recorder_normal_exit(self):self.recorder(0).stop()
    def test_recorder_requested_sigint_exit(self):
        video=self.recorder(-signal.SIGINT);video.process.poll.return_value=None
        with patch('transport.os.killpg') as kill:video.stop()
        kill.assert_called_once_with(video.process.pid,signal.SIGINT)
        receipt=json.loads((self.out/'recording-process.json').read_text())
        self.assertTrue(receipt['stopRequested']);self.assertTrue(receipt['sigintSent'])
        self.assertLessEqual(receipt['stopRequestedHostUptime'],receipt['hostEnd'])
    def test_recorder_already_exited_sigint_rejected(self):
        with patch('transport.os.killpg') as kill:
            with self.assertRaisesRegex(ValueError,'normal exit'):self.recorder(-signal.SIGINT).stop()
        kill.assert_not_called()
        receipt=json.loads((self.out/'recording-process.json').read_text())
        self.assertTrue(receipt['stopRequested']);self.assertFalse(receipt['sigintSent'])
    def test_recorder_nonzero_rejected_and_retained(self):
        with self.assertRaisesRegex(ValueError,'normal exit'):self.recorder(1).stop()
        self.assertEqual(json.loads((self.out/'recording-process.json').read_text())['exitCode'],1)
    def test_real_event(self):
        atomic(self.root/'event-001.json',{'type':'start'})
        c=Channel(self.root,self.out,'fixture',None);self.assertEqual(c.await_event('start')[0]['type'],'start')

if __name__=='__main__':unittest.main()
