import tempfile,unittest,json
from pathlib import Path
from fixture_channel import Directory
from journal import Journal

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();self.d=Directory(self.root);self.saved=[]
        self.j=Journal(self.d,checkpoint=lambda:None,remaining=lambda v:v,retain=self.saved.append)
    def tearDown(self):self.d.close();self.temp.cleanup()
    def event(self,n,row):
        (self.root/f'event-{n:03d}.json').write_text(json.dumps(row))
    def test_immutable_prefix(self):
        self.event(1,{'type':'start'});self.assertEqual(self.j.await_event('start',1)['type'],'start')
        self.j.events();self.assertEqual(len(self.saved),1)
        self.event(1,{'type':'changed'})
        with self.assertRaises(ValueError):self.j.events()
        self.assertTrue(self.j.failed)
    def test_gap_error_and_extra_final(self):
        self.event(2,{'type':'start'})
        with self.assertRaises(ValueError):self.j.events()
    def test_duplicate_protocol_event(self):
        self.event(1,{'type':'start'});self.event(2,{'type':'start'})
        with self.assertRaises(ValueError):self.j.await_event('start',1)
    def test_complete_strip_bytes(self):
        self.event(1,{'type':'start'})
        (self.root/'strip-0001.json').write_text(json.dumps({'schema':'p1-strip-batch-v1','batch':1,'draws':[{'id':1}]}))
        (self.root/'strip-complete.json').write_text(json.dumps({'schema':'p1-strip-complete-v1','batches':1,'drawCount':1,'admissionEligible':False}))
        result=self.j.finalized();self.assertEqual(result['strip']['draws'],[{'id':1}]);self.assertEqual(len(self.saved),3)
        (self.root/'foreign').write_text('x')
        with self.assertRaises(ValueError):self.j.finalized()

if __name__=='__main__':unittest.main()
