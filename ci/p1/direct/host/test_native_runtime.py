import tempfile,unittest,time
from pathlib import Path
from types import SimpleNamespace
from native_runtime import Runtime
class Tests(unittest.TestCase):
    def bare(self,d,fixture=None):
        r=Runtime.__new__(Runtime);r.output=Path(d);r.scope=SimpleNamespace(fixture=fixture,rows=[],creation_intent=None,cleanup_deadline=time.monotonic()+120)
        r.channels=None;r.capture_binding=None;r._evidence={};r.retain=lambda *a:None
        r.scope.fixture_deleted=lambda value:r.scope.fixture.update(deleted=value)
        r.scope.fixture_stopped=lambda value:r.scope.fixture.update(stopped=value)
        r.scope.fixture_cleanup_failure=lambda:r.scope.fixture.update(cleanup_command_failed=True)
        return r
    def test_cleanup_unknown_create_not_cleared(self):
        with tempfile.TemporaryDirectory() as d:
            r=self.bare(d);r.scope.creation_intent={'pending':True}
            with self.assertRaises(ValueError):r.verify_cleanup({},10)
    def test_cleanup_actual_api_and_failure_latch(self):
        with tempfile.TemporaryDirectory() as d:
            r=self.bare(d,{'owned_created':{'device':'D'},'deleted':False});called=[]
            r.fresh=SimpleNamespace(Commands=lambda scope,root,proof:called.append((scope,root,proof)) or 'command',
                cleanup=lambda command,proof,settled: {'deleted':True,'observed_shutdown':True,'command_failed':True})
            with self.assertRaises(ValueError):r.cleanup_device({},75)
            self.assertEqual(len(called),1);self.assertTrue(r.scope.fixture['deleted']);self.assertTrue(r.scope.fixture['cleanup_command_failed'])
            with self.assertRaises(ValueError):r.verify_cleanup({},10)
    def test_unsettled_host_writer_blocks_cleanup_claim(self):
        with tempfile.TemporaryDirectory() as d:
            r=self.bare(d);r.scope.rows=[{'settled':False}]
            with self.assertRaises(ValueError):r.verify_cleanup({},10)
    def test_no_resource_cleanup_is_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            r=self.bare(d);self.assertEqual(r.cleanup_device({},75).value,{})
            self.assertTrue(r.verify_cleanup({},10).value['allWritersSettled'])
    def test_native_failure_not_turned_into_completion(self):
        with tempfile.TemporaryDirectory() as d:
            r=self.bare(d);r.native_receipt=None
            r.native=SimpleNamespace(result=lambda timeout:(_ for _ in ()).throw(ValueError('failed')))
            with self.assertRaises(ValueError):r.await_native_result({'protocol':{}},60)
            self.assertIsNone(r.native_receipt)
if __name__=='__main__':unittest.main()
