import json,os,tempfile,unittest
from pathlib import Path
from fixture_channel import Directory,FixtureChannel,parse

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();self.d=Directory(self.root)
    def tearDown(self):self.d.close();self.tmp.cleanup()
    def test_roundtrip(self):
        self.d.publish('request.json',b'{"id":1}');self.assertEqual(self.d.read('request.json'),b'{"id":1}')
    def test_symlink_fifo_hardlink(self):
        for kind in ('link','fifo','hard'):
            p=self.root/'bad'
            if kind=='link':p.symlink_to('absent')
            elif kind=='fifo':os.mkfifo(p)
            else:
                (self.root/'source').write_bytes(b'a');os.link(self.root/'source',p)
            with self.assertRaises((ValueError,OSError)):self.d.read('bad')
            p.unlink()
    def test_size_bound(self):
        (self.root/'bad').write_bytes(b'ab')
        with self.assertRaises(ValueError):self.d.read('bad',1)
    def test_replaced_root(self):
        old=self.root/'moved';self.root.rename(str(self.root)+'-old');self.root.mkdir()
        try:
            with self.assertRaises(ValueError):self.d.read('anything')
        finally:
            self.root.rmdir();Path(str(self.root)+'-old').rename(self.root)
    def test_duplicate_json(self):
        with self.assertRaises(ValueError):parse(b'{"id":1,"id":2}')
    def channel(self,wrong=False):
        self.rows=[];self.t=0
        def now():self.t+=1_000;return self.t
        def check():
            raw=self.d.read('request.json')
            if raw:
                value=json.loads(raw);n=value['id']
                (self.root/'response.json').write_text(json.dumps({'id':n+1 if wrong else n,'appReceive':1,'appSend':1}))
        return FixtureChannel(self.d,checkpoint=check,remaining=lambda t:t,retain=self.rows.append,monotonic_ns=now,sleep=lambda t:None)
    def test_exchange(self):
        c=self.channel();row=c.exchange(1,'clock');self.assertEqual(row['response']['id'],1)
        self.assertIsNone(self.rows[-1]['errorType']);self.assertEqual(len(self.rows),1)
        self.assertEqual(row['hostAfterNs'],self.rows[-1]['hostAfterNs'])
    def test_future_response_fails_no_retry(self):
        c=self.channel(True)
        with self.assertRaises(ValueError):c.exchange(1,'clock')
        with self.assertRaises(ValueError):c.exchange(2,'clock')
        self.assertEqual(len(self.rows),1);self.assertTrue(c.failed)
    def test_retention_failure_latches(self):
        c=self.channel()
        def fail(row):raise OSError('retention failed')
        c.retain=fail
        with self.assertRaises(OSError):c.exchange(1,'clock')
        self.assertTrue(c.failed)
        with self.assertRaises(ValueError):c.exchange(2,'clock')
    def test_stale_channel(self):
        (self.root/'response.json').write_text('{}')
        with self.assertRaises(ValueError):self.channel()

if __name__=='__main__':unittest.main()
