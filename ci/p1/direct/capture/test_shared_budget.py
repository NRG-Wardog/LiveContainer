import unittest
from pathlib import Path
from assemble import assemble

class Tests(unittest.TestCase):
    def test_stage_clamp_and_terminal_independence(self):
        source=(Path(__file__).parent/'session_io.swift').read_text()
        self.assertIn('let allowance = min(maximum, remaining)',source)
        self.assertIn('stage.arm(min(allowance, seconds(until: stageCutoff)), phase)',source)
        self.assertIn('stage.cancel(); armedCutoff = nil',source)
        self.assertIn('guard mach_absolute_time() < limit',source)
        self.assertIn('guard mach_absolute_time() < cleanup',source)
        self.assertIn('"actualAllowanceSeconds": allowance',source)
        self.assertIn('"cleanup-cutoff"',source)
    def test_cleanup_mode_covers_success_and_recovery(self):
        source=assemble()
        self.assertIn('deadline.beginCleanup()\n            deadline.arm(10, "stream-stop")',source)
        self.assertIn('deadline.beginCleanup()\n        if startAttempted',source)
        self.assertIn('DirectDeadline(directory, observation: observationDeadline, cleanup: cleanupDeadline)',source)
        self.assertIn('args.count == 7',source)

if __name__=='__main__':unittest.main()
