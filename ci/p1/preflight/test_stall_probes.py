import tempfile
from pathlib import Path
import unittest
import probe_pair
import process_scope

class ProbeTests(unittest.TestCase):
    def test_pair_and_sampler(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out=root/'commands';out.mkdir()
            scope=process_scope.Scope(root);cmd=process_scope.Commands(scope,out)
            sampler=probe_pair.Sampler();sampler.start()
            try:
                rows=[probe_pair.pair(cmd,x) for x in ['before-boot','after-boot']]
                for row in rows:
                    for p in row['probes']:
                        self.assertEqual(p['exit_code'],0);self.assertIsNone(p['failure'])
                        if p['mode'] in ['full','minimal']:
                            r=p['launch_receipt'];self.assertEqual(r['state'],'pre-exec-observed')
                            e=r['pre_exec'];self.assertLessEqual(e['first_python'],e['imports_complete'])
                            self.assertLessEqual(e['imports_complete'],e['gate_enter'])
                            self.assertLessEqual(e['gate_enter'],e['gate_exit'])
                            self.assertLessEqual(e['gate_exit'],e['child_monotonic'])
            finally:
                metrics=sampler.finish();scope.close()
            self.assertTrue(metrics['terminal']);self.assertIsNone(metrics['error']);metrics=metrics['rows']
            self.assertTrue(metrics);self.assertLessEqual(len(metrics),240)
            self.assertEqual(set(metrics[0]),{'monotonic','loadavg','self_user_seconds','self_system_seconds','self_maxrss_native_units'})
    def test_sampler_failure_is_explicit(self):
        from unittest import mock
        s=probe_pair.Sampler()
        with mock.patch.object(probe_pair.os,'getloadavg',side_effect=OSError('secret')):
            s.start();s.thread.join(timeout=2);result=s.finish()
        self.assertEqual(result['error'],{'type':'OSError'})
        self.assertTrue(result['terminal']);self.assertNotIn('secret',str(result))
    def test_phase_rejected(self):
        with self.assertRaises(ValueError):probe_pair.pair(None,'other')
    def test_sampler_double_start(self):
        s=probe_pair.Sampler();s.start()
        try:
            with self.assertRaises(ValueError):s.start()
        finally:s.finish()

if __name__=='__main__':unittest.main()
