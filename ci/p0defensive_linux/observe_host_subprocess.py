"""Observe finite sealed host drivers; retain transient compiler inputs before cleanup."""
import json, os, subprocess
from pathlib import Path
from retention import RawStore
from source_primitives import require
SAFE_ENV=('DEVELOPER_DIR','PATH','HOME','TMPDIR','ASAN_OPTIONS','UBSAN_OPTIONS','PYTHONDONTWRITEBYTECODE')

def install(root,temporary,output,guard):
    root=Path(root);temporary=Path(temporary);output=Path(output)
    require(not root.exists(),'fresh nested evidence required');root.mkdir(parents=True)
    store=RawStore(root);original=subprocess.run;counter=0
    def save(path,value):path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
    def snapshot(prefix,phase):
        rows={}
        for name,path in [('temporary',temporary),('output',output)]:
            rows[name]=store.retain_tree(path,label=prefix.name+'/'+phase+'/'+name)
        save(prefix.with_suffix('.'+phase+'.json'),rows)
    def recorded(*args,**kwargs):
        nonlocal counter
        counter+=1;require(counter<=512,'finite nested command bound exceeded');prefix=root/f'{counter:04d}'
        argv=args[0] if args else kwargs.get('args')
        require(isinstance(argv,(list,tuple)) and argv and not kwargs.get('shell') and not kwargs.get('start_new_session') and kwargs.get('process_group') is None,'nested command must retain outer owned process group and argv form')
        require(kwargs.get('capture_output') is True and kwargs.get('timeout') and kwargs['timeout']<=120,'bounded captured nested command required')
        env=kwargs.get('env') or os.environ
        guard(counter,[str(x) for x in argv])
        record={'argv':[str(x) for x in argv],'cwd':str(kwargs.get('cwd') or Path.cwd()),'environment':{k:env[k] for k in SAFE_ENV if k in env},'returncode':None}
        save(prefix.with_suffix('.command.json'),record);snapshot(prefix,'before')
        def raw(value):return value.encode('utf-8') if isinstance(value,str) else value or b''
        try:
            require(kwargs.get('text') is True and not any(k in kwargs for k in ('encoding','errors','universal_newlines')),'reviewed UTF-8 text driver contract required')
            binary_kwargs=dict(kwargs);binary_kwargs['text']=False
            result=original(*args,**binary_kwargs)
            record.update(returncode=result.returncode)
            prefix.with_suffix('.stdout').write_bytes(raw(result.stdout));prefix.with_suffix('.stderr').write_bytes(raw(result.stderr))
            decode=lambda value:None if value is None else value.decode('utf-8').replace('\r\n','\n').replace('\r','\n')
            result.stdout=decode(result.stdout);result.stderr=decode(result.stderr)
            return result
        except BaseException as error:
            record.update(error=type(error).__name__,returncode=getattr(error,'returncode',record['returncode']))
            if not prefix.with_suffix('.stdout').exists():prefix.with_suffix('.stdout').write_bytes(raw(getattr(error,'stdout',None)))
            if not prefix.with_suffix('.stderr').exists():prefix.with_suffix('.stderr').write_bytes(raw(getattr(error,'stderr',None)))
            raise
        finally:
            snapshot(prefix,'after');save(prefix.with_suffix('.result.json'),record)
            save(root/'retention-summary.json',dict(store.summary(),nested_commands=counter))
    subprocess.run=recorded
    return store
