"""Exact header-only aggregate unittest and its four retained nested commands."""
from pathlib import Path
from inventory import ordinary,parse
from source_primitives import require
from run_host_test import AGGREGATE_DRIVER,expected_test_ids,verify_unittest_result

EXPECTED_STDOUT=b'{"checks":18,"guest_execution":false,"engine_linked":false}\n'
STRICT_FLAGS=['-std=c++17','-Wall','-Wextra','-Werror','-pedantic']
VARIANTS=(('normal',[]),('optimized',['-O2','-DNDEBUG']))

def source_hashes():
    inventory=parse(ordinary(Path(__file__).resolve().parent,'reviewed/aggregate-source-inventory.json').read_bytes())
    require(len(inventory['files'])==67,'exact 67-file aggregate source closure required')
    return {p:r['sha256'] for p,r in inventory['files'].items()}

def verify_nested(evidence,owner,temporary,work):
    """Bind finite argv and original streams to independent observer receipts."""
    for path in (evidence,owner,temporary,work):
        require(path.is_absolute() and '..' not in path.parts,'absolute aggregate capture context required')
    summary=parse(ordinary(evidence,'retention-summary.json').read_bytes())
    require(type(summary['nested_commands']) is int and summary['nested_commands']==4,'exact four aggregate nested commands required')
    require({p.name for p in evidence.glob('*.command.json')}=={f'{i:04d}.command.json' for i in range(1,5)},'aggregate nested command inventory differs')
    require({p.name for p in evidence.glob('*.result.json')}=={f'{i:04d}.result.json' for i in range(1,5)},'aggregate nested result inventory differs')
    binaries=set();rows=[]
    for index,(variant,flags) in enumerate(VARIANTS):
        binary=None
        for offset,stage in ((1,'compile'),(2,'run')):
            label=f'{index*2+offset:04d}'
            command=parse(ordinary(evidence,label+'.command.json').read_bytes())
            result=parse(ordinary(evidence,label+'.result.json').read_bytes())
            require(set(command)=={'argv','cwd','environment','returncode'} and command['returncode'] is None,'aggregate command receipt schema differs')
            require(set(result)==set(command) and type(result['returncode']) is int and result==dict(command,returncode=0),'aggregate nested command failed or receipt differs')
            require(command['cwd']==str(work),'aggregate command cwd differs from outer work')
            require(command['environment'].get('TMPDIR')==str(temporary),'aggregate temporary root differs')
            argv=command['argv']
            if stage=='compile':
                require(isinstance(argv,list) and len(argv)==len(STRICT_FLAGS)+len(flags)+6,'aggregate compile argv length differs')
                binary=Path(argv[-1])
                require(binary.is_absolute() and '..' not in binary.parts and binary.name=='aggregate-contract' and binary.parent.parent==temporary and binary.parent.name.startswith('tmp'),'aggregate compiler output escaped retained temporary root')
                require(str(binary) not in binaries,'aggregate variants reused one output');binaries.add(str(binary))
                expected=['/usr/bin/c++',*STRICT_FLAGS,*flags,'-I',str(owner/'Native/Loader'),str(owner/'.ci/native-tests/fixtures/fault_aggregate_compatibility.cpp'),'-o',str(binary)]
                require(argv==expected,'aggregate compiler command differs from strict reviewed argv')
            else:require(argv==[str(binary)],'aggregate executable differs from compiled output')
            stdout=ordinary(evidence,label+'.stdout').read_bytes();stderr=ordinary(evidence,label+'.stderr').read_bytes()
            require(stderr==b'','aggregate command emitted diagnostics')
            require(stdout==(b'' if stage=='compile' else EXPECTED_STDOUT),'aggregate command output differs')
            rows.append(dict(variant=variant,stage=stage,nested_command=label,argv=argv))
    return rows

def verify_result(output,evidence,owner,temporary,work):
    row=parse(ordinary(output,'aggregate-result.json').read_bytes())
    require(set(row)=={'schema','source_sha256','unittest','nested_commands'},'aggregate result schema differs')
    require(type(row['schema']) is int and row['schema']==1,'aggregate result schema version differs')
    require(row['source_sha256']==source_hashes(),'aggregate result source closure differs')
    verify_unittest_result(AGGREGATE_DRIVER,row['unittest'])
    require(row['nested_commands']==verify_nested(evidence,owner,temporary,work),'aggregate result differs from nested raw receipts')
    return {'tests':1,'test_ids':expected_test_ids(AGGREGATE_DRIVER),'variants':2,'assertions':36,'guest_execution':False,'engine_linked':False}
