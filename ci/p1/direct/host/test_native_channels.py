import tempfile,unittest
from pathlib import Path
from native_channels import Channels
from native_process import clean
from test_native_process import row
class Native:
    def live(self):pass
class Tests(unittest.TestCase):
    def make(self,d,command):
        c=Channels(command,Native(),device='D',session='a'*32,app_id='app',runner_id='runner',retain=lambda *a:None,remaining=lambda x:x)
        c.hint={};return c
    def test_one_lookup_and_exact_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();calls=[]
            def command(*argv,**kw):calls.append(argv);return dict(row(argv),stdout=str(root))
            c=self.make(d,command);result=c.discover('app',30)
            self.assertEqual(result['root'],str(root));self.assertEqual(len(calls),1)
            with self.assertRaises(ValueError):c.discover('app',30)
    def test_failed_lookup_cannot_retry(self):
        with tempfile.TemporaryDirectory() as d:
            def command(*argv,**kw):return dict(row(argv),stdout=d,exit_code=-15)
            c=self.make(d,command)
            with self.assertRaises(ValueError):c.discover('app',30)
            with self.assertRaises(ValueError):c.discover('app',30)
    def test_linked_root_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d).resolve();(p/'link').symlink_to(p,target_is_directory=True)
            c=self.make(d,lambda *a,**kw:dict(row(a),stdout=str(p/'link')))
            with self.assertRaises(ValueError):c.discover('runner',30)
    def test_no_hint_no_discovery(self):
        with tempfile.TemporaryDirectory() as d:
            c=self.make(d,lambda *a,**kw:None);c.hint=None
            with self.assertRaises(ValueError):c.discover('app',30)
if __name__=='__main__':unittest.main()
