"""Offline synthetic host observer/command mutations; no guest or provider execution."""
import hashlib,json,os,subprocess,sys,tempfile,unittest,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import host_tests
from run_host_test import DRIVERS,UNIT_METHODS
from inventory import dump,parse
from lifecycle import CommandRunner

class HostTests(unittest.TestCase):
    def test_exact_safe_driver_and_unittest_inventory(self):
        self.assertEqual(DRIVERS,('test_memory_boundaries_host.py','test_vm_setup_host.py','test_elf_metadata_bounds.py','run_tests.py','run_diagnostic_checks.py','test_fault_aggregate_compatibility.py'))
        self.assertEqual(len(UNIT_METHODS),9);self.assertEqual(len(set(UNIT_METHODS)),9)
        self.assertNotIn('test_cxx_allocation.py',DRIVERS)
    def test_exact_command_arrays_do_not_select_wildcards(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();include=root/'headers';include.mkdir()
            rows=list(host_tests.commands(HERE,root/'owner',root/'work',root/'evidence',sys.executable,include))
            self.assertEqual(len(rows),6)
            for (label,args),driver in zip(rows,DRIVERS):
                self.assertEqual(args[args.index('--driver')+1],driver);self.assertEqual(args[args.index('--unicorn-include')+1],str(include));self.assertNotIn('*',' '.join(args))
                self.assertEqual(args[:3],[sys.executable,'-B',str(HERE/'run_host_test.py')])
    def test_archive_headers_pinned_and_disagreeing_slices_reject(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();archive=root/'artifact.zip'
            with zipfile.ZipFile(archive,'w') as z:
                for name in ('unicorn.h','arm64.h','platform.h'):z.writestr('A/Headers/unicorn/'+name,b'// synthetic header')
                z.writestr('A/Engine',b'NEVER EXTRACT')
            sha=hashlib.sha256(archive.read_bytes()).hexdigest()
            with self.assertRaises(ValueError):host_tests.extract_headers(archive,root/'bad','0'*64)
            result=host_tests.extract_headers(archive,root/'headers',sha);self.assertEqual(len(result),3);self.assertFalse((root/'headers/A/Engine').exists())
            with zipfile.ZipFile(archive,'a') as z:z.writestr('B/Headers/unicorn/unicorn.h',b'changed')
            with self.assertRaises(ValueError):host_tests.extract_headers(archive,root/'drift',hashlib.sha256(archive.read_bytes()).hexdigest())
    def test_observer_keeps_transient_raw_input_output_and_binary_streams(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();temporary=root/'temporary';temporary.mkdir();output=root/'output';output.mkdir();evidence=root/'evidence'
            code='''import os,sys,subprocess\nfrom pathlib import Path\nsys.path.insert(0,sys.argv[1])\nfrom observe_host_subprocess import install\ntmp,out,evidence=map(Path,sys.argv[2:])\n(tmp/'input.cpp').write_bytes(b'input bytes')\ninstall(evidence,tmp,out)\nr=subprocess.run([sys.executable,'-c',"from pathlib import Path;import sys;Path(sys.argv[1]).write_bytes(b'compiled bytes');sys.stdout.buffer.write(b'raw\\\\r\\\\nstdout')",str(out/'binary')],capture_output=True,text=True,timeout=10)\nassert r.stdout=='raw\\nstdout'\n(tmp/'input.cpp').unlink();(out/'binary').unlink()\n'''
            result=subprocess.run([sys.executable,'-B','-c',code,str(HERE),str(temporary),str(output),str(evidence)],capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual((evidence/'0001.stdout').read_bytes(),b'raw\r\nstdout')
            for phase,name,path,expected in [('before','temporary','input.cpp',b'input bytes'),('after','output','binary',b'compiled bytes')]:
                index=parse((evidence/('0001.'+phase+'.json')).read_bytes());entry=next(r for r in index[name]['entries'] if r['path']==path)
                self.assertEqual((evidence/entry['blob_path']).read_bytes(),expected)
    def test_nested_decode_failure_keeps_original_non_utf8_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();temporary=root/'temporary';temporary.mkdir();output=root/'output';output.mkdir();evidence=root/'evidence'
            code="import sys,subprocess;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from observe_host_subprocess import install;install(Path(sys.argv[2]),Path(sys.argv[3]),Path(sys.argv[4]));subprocess.run([sys.executable,'-c',\"import sys;sys.stdout.buffer.write(bytes([255,13,10]))\"],capture_output=True,text=True,timeout=10)"
            result=subprocess.run([sys.executable,'-B','-c',code,str(HERE),str(evidence),str(temporary),str(output)],capture_output=True,text=True,timeout=15)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual((evidence/'0001.stdout').read_bytes(),bytes([255,13,10]))
            self.assertEqual(parse((evidence/'0001.result.json').read_bytes())['error'],'UnicodeDecodeError')
    def test_outer_command_runner_retains_non_utf8_and_crlf_exactly(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();(root/'logs').mkdir();runner=CommandRunner();runner.evidence=root;runner.command_quiescence=[]
            with self.assertRaises(UnicodeError):runner.run('binary',[sys.executable,'-c',"import sys;sys.stdout.buffer.write(b'\\xff\\r\\n');sys.stderr.buffer.write(b'\\xfe\\r\\n')"])
            self.assertEqual((root/'logs/binary.log').read_bytes(),b'\xff\r\n');self.assertEqual((root/'logs/binary.stderr.log').read_bytes(),b'\xfe\r\n')
            self.assertTrue(runner.command_quiescence[0]['quiescent'])
    def test_result_mutations_reject_counts_types_guests_engine_starts(self):
        expected={'checks':403,'failures':0,'guest_execution':False,'engine_starts':0,'proprietary_input':False}
        host_tests.exact_result(expected,expected)
        for key,value in [('checks',402),('failures',1),('guest_execution',0),('engine_starts',1),('proprietary_input',True)]:
            bad=dict(expected);bad[key]=value
            with self.assertRaises(ValueError):host_tests.exact_result(bad,expected)
    def test_unittest_skips_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();row={'tests':9,'failures':0,'errors':0,'skips':1,'expected_failures':0,'unexpected_successes':0,'test_ids':['id'+str(x) for x in range(9)]};dump(root/'unittest-result.json',row)
            with self.assertRaises(ValueError):host_tests.verify_result('run_tests.py',root)
    def test_only_exact_diagnostic_supervisor_owns_per_command_sandbox_dispatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();include=root/'headers';include.mkdir()
            for (_,argv),driver in zip(host_tests.commands(HERE,root/'owner',root/'work',root/'evidence',sys.executable,include),DRIVERS):
                executed=host_tests.execution_command(driver,argv)
                self.assertEqual(executed,argv if driver=='run_diagnostic_checks.py' else [*host_tests.SANDBOX,*argv])
                bad=list(argv);bad[bad.index('--driver')+1]='injected'
                with self.assertRaises(ValueError):host_tests.execution_command(driver,bad)
            with self.assertRaises(ValueError):host_tests.execution_command('unknown',[])
if __name__=='__main__':unittest.main(verbosity=2)
