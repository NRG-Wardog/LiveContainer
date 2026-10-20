"""Compile exactly the sealed benign source with the installed pinned toolchain."""
import errno
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import time
import helper_sample as h

DEVELOPER=Path('/Applications/Xcode_26.4.1.app/Contents/Developer')
TOOLCHAIN=DEVELOPER/'Toolchains/XcodeDefault.xctoolchain/usr/bin'
CLANG=TOOLCHAIN/'clang'
SDK=DEVELOPER/'Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk'
SOURCE=Path(__file__).resolve().with_name('probe.c')
COMPILE_SECONDS=20
FLAGS=('-std=c11','-O0','-Wall','-Wextra','-Werror')

class ProbeFailure(ValueError):
    def __init__(self,status,stage,code):
        self.status=status;self.stage=stage;self.code=code
        super().__init__(code)


def prepare(experiment):
    result=None
    try:
        experiment.stage='native-source'
        manifest=json.loads(SOURCE.with_name('closure.json').read_bytes())
        raw=SOURCE.read_bytes()
        digest=sha256(raw).hexdigest()
        if SOURCE.is_symlink() or not 0<len(raw)<=4096 or digest!=manifest['ci/p1/sample_capability/probe.c']:
            raise ProbeFailure('unsupported','native-source','source-seal-mismatch')
        experiment.stage='native-toolchain'
        if not CLANG.is_file() or not SDK.is_dir():
            raise ProbeFailure('unavailable','native-toolchain','pinned-toolchain-absent')
        resolved=CLANG.resolve(strict=True)
        if not resolved.is_relative_to(TOOLCHAIN.resolve(strict=True)):
            raise ProbeFailure('unsupported','native-toolchain','compiler-outside-pinned-toolchain')
        if not os.access(CLANG,os.X_OK):
            raise ProbeFailure('denied','native-toolchain','compiler-not-executable')
        # Fresh private directory and fixed leaf avoid collision and image substitution.
        work=Path(tempfile.mkdtemp(prefix='native-probe-',dir=experiment.output)).resolve(strict=True)
        image_path=work/'p1-owned-native-probe'
        argv=[str(CLANG),*FLAGS,'-isysroot',str(SDK),str(SOURCE),'-o',str(image_path)]
        experiment.row['nativeProbe']={'sourceSHA256':digest,'compiler':str(CLANG),'resolvedCompiler':str(resolved),
            'sdk':str(SDK),'compileArgv':argv,'compileSecondsLimit':COMPILE_SECONDS,'sourceBytes':len(raw),
            'rawCompilerOutputRetained':False,'execsAnotherProgram':False}
        experiment.stage='native-compile'
        result=experiment._run(argv,min(experiment.scope.deadline,time.monotonic()+COMPILE_SECONDS))
        experiment.row['nativeProbe'].update(compilerPID=result['samplerPID'],compilerExitCode=result['code'])
        if result['status'] is not None:
            raise ProbeFailure(result['status'],'native-compile','bounded-compile-incomplete')
        classification=h.outcome(result['code'],result['raw'])
        if classification=='denied':raise ProbeFailure('denied','native-compile','compiler-permission-denied')
        if result['code']!=0:raise ProbeFailure(classification,'native-compile','compiler-nonzero')
        experiment.stage='native-image'
        if image_path.is_symlink() or not os.access(image_path,os.X_OK):
            raise ProbeFailure('unsupported','native-image','native-image-not-executable')
        image=h.image_identity(image_path)
        experiment.row['expectedImage']=image
        return [str(image_path)],image
    except OSError as error:
        denied=error.errno in (errno.EPERM,errno.EACCES)
        raise ProbeFailure('denied' if denied else 'unsupported',experiment.stage,
                           'filesystem-permission-denied' if denied else 'filesystem-operation-failed') from None
    finally:
        if result is not None:result['raw']=b''
