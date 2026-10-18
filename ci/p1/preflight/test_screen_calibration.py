import inspect
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import capture

class ScreenCalibration(unittest.TestCase):
    def test_error_path_settles_recorder_before_shutdown_and_reads(self):
        for recording_failure in [False,True]:
            with self.subTest(recording_failure=recording_failure),tempfile.TemporaryDirectory() as tmp:
                order=[];command=mock.Mock();recorder=mock.Mock()
                def stop():
                    order.append('recording')
                    if recording_failure:raise ValueError('recording settlement failed')
                recorder.stop.side_effect=stop
                def stop_fixture(*args):
                    self.assertIn('recording',order);order.append('shutdown')
                    return not recording_failure
                def copy(*args):self.assertIn('shutdown',order);order.append('copy')
                with mock.patch.object(capture,'container',return_value=Path(tmp)),mock.patch.object(capture,'settle_discovery_observers'),mock.patch.object(capture,'ManagedVideo',return_value=recorder),mock.patch.object(capture,'ThreadPoolExecutor',side_effect=ValueError('injected before protocol')),mock.patch.object(capture,'stop_fixture',side_effect=stop_fixture),mock.patch.object(capture,'copy_channel',side_effect=copy),mock.patch.object(capture,'channel_root',return_value=None):
                    row=capture.run_calibration(command,Path('recipe'),'device','a'*32,Path(tmp)/'calibration',lambda _:True)
                self.assertFalse(row['collection_complete']);self.assertFalse(row['calibration_feasible'])
                if recording_failure:self.assertNotIn('copy',order)
                else:self.assertIn('copy',order)
    def test_success_path_recorder_precedes_owned_shutdown(self):
        source=inspect.getsource(capture.run_calibration)
        main=source.split('    finally:',1)[0]
        self.assertLess(main.index('recorder.stop();recorder=None'),main.index('fixture_stopped=stop_fixture'))
        self.assertLess(main.index('fixture_stopped=stop_fixture'),main.index('copy_channel('))
        self.assertIn("for ordinal in range(1,4)",main)
        self.assertIn("['pre','mid','post']",main)
        self.assertIn("'-maximum-test-execution-time-allowance','240'",main)
        self.assertIn('timeout=360',main)
    def test_profile_flags_are_exclusive(self):
        for other in ['full_recovery','default_tabs','install_diagnostic']:
            with self.assertRaisesRegex(ValueError,'incompatible collection profiles'):
                capture.execute(Path('.'),Path('unused'),Path('unused2'),Path('unused3'),'a'*64,'phone',calibration_only=True,**{other:True})

if __name__=='__main__':unittest.main()
