"""Finite A+B host drivers; exact source scripts, artifact headers, raw nested capture."""
from pathlib import Path
from source_primitives import require
from inventory import parse,ordinary
from run_host_test import DRIVERS,AGGREGATE_DRIVER,verify_unittest_result
from capture_contract import SANDBOX

def commands(here,owner,work,evidence,python,include):
    require(include.is_absolute() and include.is_dir() and not include.is_symlink(),'actual pinned artifact header directory required')
    for driver in DRIVERS:
        label=driver.removesuffix('.py').replace('_','-')
        yield label,[python,'-B',str(here/'run_host_test.py'),'--owner',str(owner),'--driver',driver,'--output',str(work/'host-tests'/label),'--temporary',str(work/'host-temporary'/label),'--evidence',str(evidence/'host-tests'/label),'--unicorn-include',str(include)]

def execution_command(driver,argv):
    require(driver in DRIVERS and argv.count('--driver')==1 and argv[argv.index('--driver')+1]==driver,'exact reviewed host driver required')
    # Only this trusted supervisor dispatches its own exact per-command sandboxes.
    # Apple macro compilation keeps the compiler's own plugin sandbox intact.
    return list(argv) if driver=='run_diagnostic_checks.py' else [*SANDBOX,*argv]

def exact_result(actual,expected):
    require(actual==expected and all(type(actual[k]) is type(v) for k,v in expected.items()),'host result/count/type differs')

def verify_result(driver,output,evidence=None):
    require(driver in DRIVERS,'exact reviewed host result driver required')
    if driver==AGGREGATE_DRIVER:
        from aggregate_checks import verify_result as verify_aggregate
        require(evidence is not None,'aggregate nested evidence required')
        work=output.parent.parent
        return verify_aggregate(output,evidence,work/'sources/AnisetteKit',work/'host-temporary'/output.name,work)
    if driver=='run_diagnostic_checks.py':
        from diagnostic_checks import verify_result,command_context
        work=output.parent.parent
        context=command_context(work/'sources/AnisetteKit',work/'host-unicorn-headers',output)
        return verify_result(parse(ordinary(output,'diagnostic-results.json').read_bytes()),context)
    if driver=='run_tests.py':
        row=parse(ordinary(output,'unittest-result.json').read_bytes())
        verify_unittest_result(driver,row)
        return {'tests':9,'skipped':0}
    if driver=='test_elf_metadata_bounds.py':
        row=parse(ordinary(output,'result.json').read_bytes());require(set(row['results'])=={'normal','optimized','sanitized'},'metadata variants differ')
        for value in row['results'].values():exact_result(value,{'schema':1,'checks':713,'failures':0,'guest_execution':False,'proprietary_input':False})
        return {'assertions':2139,'guest_execution':False}
    name='memory-check-results.json' if driver=='test_memory_boundaries_host.py' else 'setup-check-results.json'
    row=parse(ordinary(output,name).read_bytes());require(row['guest_execution'] is False and row['leak_sanitizer_enabled'] is False,'host execution scope differs')
    expected={'checks':403,'failures':0,'guest_execution':False,'engine_starts':0,'proprietary_input':False} if driver=='test_memory_boundaries_host.py' else {'checks':239,'setup_fault_points_per_mode':17,'guest_execution':False,'engine_starts':0}
    require([(r['variant'],r['stage']) for r in row['results']]==[(v,s) for v in ('normal','optimized','sanitized') for s in ('compile','run')],'host variants/order differ')
    for item in row['results']:
        require(item['returncode']==0 and not item['stderr'],'host compile/run failure or diagnostics')
        if item['stage']=='run':exact_result(parse(item['stdout']),expected)
    return {'assertions':expected['checks']*3,'guest_execution':False,'engine_starts':0}

def extract_headers(archive,destination,expected_sha):
    """Prior Linux capture pattern: headers only, from the exact retained binary archive."""
    import hashlib,zipfile,stat
    require(hashlib.sha256(archive.read_bytes()).hexdigest()==expected_sha,'pinned header archive mismatch')
    found={}
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            parts=Path(item.filename).parts
            require(not item.filename.startswith('/') and '..' not in parts,'unsafe artifact archive path')
            if len(parts)<2 or parts[-2]!='unicorn' or not parts[-1].endswith('.h'):continue
            require(not stat.S_ISLNK(item.external_attr>>16) and item.file_size<1024*1024,'unsafe engine header')
            raw=z.read(item);require(parts[-1] not in found or found[parts[-1]]==raw,'header slices disagree');found[parts[-1]]=raw
    require({'unicorn.h','arm64.h','platform.h'}<=set(found),'required pinned headers absent')
    (destination/'unicorn').mkdir(parents=True)
    for name,raw in found.items():(destination/'unicorn'/name).write_bytes(raw)
    return {name:hashlib.sha256(raw).hexdigest() for name,raw in sorted(found.items())}
