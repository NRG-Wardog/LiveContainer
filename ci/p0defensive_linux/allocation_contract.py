"""Exact prior reviewed allocation contract; only A+B source identities advance."""
from inventory import require,ordinary,parse
ALLOCATION_SOURCES = {'Native/Loader/elf_loader_emulator.cpp': '7d6877197184487db61f4acde602e14622213c97cc01424f3637a015f465464f', '.ci/native-tests/fixtures/cxx_allocation_unit.cpp': 'cbbe243428144a0584593246a4d4b92d00ee9807cff457404d8d3a18d491680c', '.ci/native-tests/fixtures/cxx_allocation_hook_unit.cpp': '0614c634f0d8ca648bde35fde4d55ec07f657becb8b2a5cd1d78a92d7a0f1c62', 'Native/Loader/cxx_allocation_runtime.h': 'b76bdc4043c497700f93aff5ad82968f7660ebb6720bb2c71ea5615000380a62', 'Native/Loader/elf_loader_emulator.h': '49cdcd0e7250837426f680ff33e721f3422044c7cf06b3a60b69d3d5b5e44bf7', 'Native/Loader/elf_metadata_bounds.h': '7acd9287cc351b55141f40a0baecda9c3d3202a420cf4b7f0f2515572d877253', 'Native/Loader/android_tls_runtime.h': '51c6c123d78b2d53f70e1720c8bf8aa934cbdb149a66df0a6763b6614f4fda07', 'Native/Loader/vm_initialization_diagnostics.h': '023b34540c9fb31fcb6059fea3236eb411fc52d0438025dbe9d72e88c9337e5c', 'Native/Loader/adi_consumption_debug.h': '077b377c87b201893f83afbff5a4dd37e01354253f08045a3831adcb50022346', 'Native/anisette_base.h': '6c47c3fef881d99082d1eb7e687fc78de6339568118259884d2b8a0d6c6e8664', 'Native/include/anisette_core.h': 'ca1ea4005f77dcca17c68965ba2dd1f65596e282a57adb4277f1d90d8bd11f02', '.ci/native-tests/test_cxx_allocation.py': 'c0f2c97e40be67ac381792a9ebae60dbdb1363e0517741b1cbfa90f0d342d3d7'}
VARIANTS=("normal","optimized","sanitized")

def verify_allocation_receipt(value):
    require(set(value)=={'results','guest_execution','leak_sanitizer_enabled','source_sha256'}, 'allocation receipt schema differs')
    require(value['guest_execution'] is False and value['leak_sanitizer_enabled'] is False, 'allocation receipt overclaims execution or sanitizer mode')
    require(ALLOCATION_SOURCES and value['source_sha256']==ALLOCATION_SOURCES, 'allocation source inventory differs')
    require(set(value['results'])==set(VARIANTS), 'all three allocation variants required')
    for result in value['results'].values():
        require(set(result)=={'allocator','hooks'}, 'allocation case schema differs')
        for label,count in (('allocator',32),('hooks',51)):
            expected={'checks':count,'failures':0,'guest_execution':False}
            require(result[label]==expected and all(type(result[label][k]) is type(v) for k,v in expected.items()), 'allocation checks failed, skipped, or differ')
    return value

def expected_commands(output, source, headers, variant, hooks):
    flags={'normal':[], 'optimized':['-O2','-DNDEBUG'], 'sanitized':['-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-fno-omit-frame-pointer']}[variant]
    common=['c++','-std=c++17','-ffunction-sections','-fdata-sections',*flags]
    for folder in (source/'Native/Loader',source/'Native',source/'Native/include',headers):common.extend(['-I',str(folder)])
    binary=output/(variant+'-hooks' if hooks else variant)
    if hooks:
        return [common+[str(source/'.ci/native-tests/fixtures/cxx_allocation_hook_unit.cpp'),'-o',str(binary)],[str(binary.resolve())]]
    obj=output/(variant+'.o')
    return [common+['-c',str(source/'Native/Loader/elf_loader_emulator.cpp'),'-o',str(obj)],
            common+['-Wl,--gc-sections',str(source/'.ci/native-tests/fixtures/cxx_allocation_unit.cpp'),str(obj),'-o',str(binary)],
            [str(binary.resolve())]]

def verify_raw_commands(output, value, source, headers):
    for variant in VARIANTS:
        for suffix,kind,count in (('', 'allocator', 3),('-hooks','hooks',2)):
            commands=parse(ordinary(output,variant+suffix+'.json').read_bytes())
            require(isinstance(commands,list) and len(commands)==count, 'allocation command count differs')
            require([x.get('command') for x in commands]==expected_commands(output,source,headers,variant,bool(suffix)), 'allocation command flags, inputs or executable differ')
            for command in commands:
                require(set(command)=={'command','exit_code','stdout','stderr'}, 'allocation command schema differs')
                require(type(command['exit_code']) is int and command['exit_code']==0, 'allocation command failed')
                require(command['stderr']=='', 'allocation command emitted diagnostics')
                require(isinstance(command['command'],list) and all(isinstance(x,str) for x in command['command']), 'allocation argv missing')
            require(parse(commands[-1]['stdout'])==value['results'][variant][kind], 'allocation raw output differs from receipt')
