"""Synthetic compiler failure/image binding tests, not macOS execution."""
from hashlib import sha256
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'ci/p1/direct/host'),str(ROOT/'ci/p1/preflight')]
import native_probe as n

class NativeProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.source=self.root/'probe.c';self.source.write_bytes(n.SOURCE.read_bytes())
        self.manifest=self.source.with_name('closure.json');self.manifest.write_text(json.dumps({'ci/p1/sample_capability/probe.c':sha256(self.source.read_bytes()).hexdigest()}))
        self.bin=self.root/'toolchain';self.bin.mkdir();self.clang=self.bin/'clang';self.clang.write_bytes(b'fake');self.clang.chmod(0o700)
        self.sdk=self.root/'sdk';self.sdk.mkdir();self.output=self.root/'output';self.output.mkdir()
        self.calls=[];self.result={'raw':b'COMPILER_OUTPUT_SENTINEL','status':None,'code':0,'samplerPID':11}
        self.e=SimpleNamespace(output=self.output,scope=SimpleNamespace(deadline=time.monotonic()+60),row={},stage='')
        def run(argv,deadline):
            self.calls.append((argv,deadline))
            image=Path(argv[-1]);image.write_bytes(struct.pack('<8I',0xfeedfacf,0x100000c,0,2,1,24,0,0)+struct.pack('<II',0x1b,24)+uuid.UUID('01234567-89ab-cdef-0123-456789abcdef').bytes);image.chmod(0o700)
            return self.result
        self.e._run=run
        for key,value in [('SOURCE',self.source),('CLANG',self.clang),('SDK',self.sdk),('TOOLCHAIN',self.bin)]:
            p=patch.object(n,key,value);p.start();self.addCleanup(p.stop)
    def test_fixed_command_and_expected_image(self):
        argv,image=n.prepare(self.e)
        command,deadline=self.calls[0]
        self.assertEqual(command[:-1],[str(self.clang),*n.FLAGS,'-isysroot',str(self.sdk),str(self.source),'-o'])
        self.assertEqual(argv,[command[-1]]);self.assertEqual(image,self.e.row['expectedImage'])
        self.assertEqual(Path(argv[0]).parent.parent,self.output)
        self.assertEqual(image['sha256'],sha256(Path(argv[0]).read_bytes()).hexdigest())
        self.assertEqual(len(image['uuids']),1);self.assertEqual(self.result['raw'],b'')
        self.assertNotIn('COMPILER_OUTPUT_SENTINEL',json.dumps(self.e.row))
    def test_seal_failure_never_compiles(self):
        self.source.write_bytes(b'changed')
        with self.assertRaises(n.ProbeFailure) as cm:n.prepare(self.e)
        self.assertEqual(cm.exception.code,'source-seal-mismatch');self.assertEqual(self.calls,[])
    def test_tool_absence_never_compiles(self):
        self.clang.unlink()
        with self.assertRaises(n.ProbeFailure) as cm:n.prepare(self.e)
        self.assertEqual((cm.exception.status,cm.exception.code),('unavailable','pinned-toolchain-absent'));self.assertEqual(self.calls,[])
    def test_tool_permission_never_compiles(self):
        self.clang.chmod(0o600)
        with self.assertRaises(n.ProbeFailure) as cm:n.prepare(self.e)
        self.assertEqual(cm.exception.code,'compiler-not-executable');self.assertEqual(self.calls,[])
    def test_compile_failure_classifications_and_discard(self):
        for code,status,raw,want in [(1,None,b'error','failed'),(1,None,b'permission denied','denied'),(1,None,b'unknown option','unsupported'),(None,'timeout',b'x','timeout'),(None,'output-limit',b'x','output-limit')]:
            self.result.update(code=code,status=status,raw=raw)
            with self.assertRaises(n.ProbeFailure) as cm:n.prepare(self.e)
            self.assertEqual(cm.exception.status,want);self.assertEqual(cm.exception.stage,'native-compile');self.assertEqual(self.result['raw'],b'')
    def test_compiler_outside_pinned_toolchain_rejected(self):
        outside=self.root/'external';outside.write_bytes(b'fake');outside.chmod(0o700);self.clang.unlink();self.clang.symlink_to(outside)
        with self.assertRaises(n.ProbeFailure) as cm:n.prepare(self.e)
        self.assertEqual(cm.exception.code,'compiler-outside-pinned-toolchain');self.assertEqual(self.calls,[])
    def test_non_macho_rejected(self):
        def run(argv,deadline):
            Path(argv[-1]).write_bytes(b'not-macho');Path(argv[-1]).chmod(0o700);return self.result
        self.e._run=run
        with self.assertRaises(ValueError):n.prepare(self.e)
        self.assertEqual(self.result['raw'],b'');self.assertEqual(self.e.stage,'native-image')

if __name__=='__main__':unittest.main()
