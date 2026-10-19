"""Record nested host-fixture compiler/run commands without altering their results."""
import json, os, subprocess
from pathlib import Path
SAFE_ENV = ('DEVELOPER_DIR','PATH','HOME','TMPDIR','ASAN_OPTIONS','UBSAN_OPTIONS','DYLD_LIBRARY_PATH','LD_LIBRARY_PATH','PYTHONDONTWRITEBYTECODE')
def install(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=False)
    original=subprocess.run;counter=0
    def recorded(*args,**kwargs):
        nonlocal counter
        counter+=1;prefix=root/f'{counter:04d}'
        argv=args[0] if args else kwargs.get('args')
        if not isinstance(argv,(list,tuple)) or kwargs.get('shell') or kwargs.get('start_new_session') or kwargs.get('process_group') is not None:
            raise RuntimeError('Host fixtures must retain argv form and the outer owned process group')
        env=kwargs.get('env') or os.environ
        record={'argv':[str(x) for x in argv],'cwd':str(kwargs.get('cwd') or Path.cwd()),'environment':{k:env[k] for k in SAFE_ENV if k in env},'returncode':None}
        prefix.with_suffix('.command.json').write_text(json.dumps(record,indent=2)+'\n')
        decode=lambda value:value.decode(errors='replace') if isinstance(value,bytes) else value or ''
        try:
            result=original(*args,**kwargs)
            record.update(returncode=result.returncode,stdout=decode(result.stdout),stderr=decode(result.stderr))
            return result
        except BaseException as error:
            record.update(error=type(error).__name__,returncode=getattr(error,'returncode',None),stdout=decode(getattr(error,'stdout',None)),stderr=decode(getattr(error,'stderr',None)))
            raise
        finally:
            prefix.with_suffix('.result.json').write_text(json.dumps(record,indent=2)+'\n')
    subprocess.run=recorded
