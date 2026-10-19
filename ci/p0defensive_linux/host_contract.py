"""Only the four exact Linux synthetic scripts and their nested command arrays."""
import re,stat,zipfile
from pathlib import Path
from inventory import require,parse,ordinary,sha,source_seal
import allocation_contract as allocation
DRIVERS=('test_vm_setup_host.py','test_memory_boundaries_host.py','test_cxx_allocation.py','test_elf_metadata_bounds.py')
VARIANTS=('normal','optimized','sanitized')
FLAGS={'normal':[],'optimized':['-O2','-DNDEBUG'],'sanitized':['-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-fno-omit-frame-pointer']}
SOURCES={
 'test_vm_setup_host.py':['Native/Loader/elf_loader_emulator.cpp','Native/Loader/elf_loader_emulator.h','Native/Loader/elf_metadata_bounds.h','Native/Loader/android_tls_runtime.h','Native/Loader/cxx_allocation_runtime.h','Native/anisette_core_uc.cpp','.ci/native-tests/fixtures/vm_setup_host.cpp','.ci/native-tests/test_vm_setup_host.py'],
 'test_memory_boundaries_host.py':['Native/Loader/elf_loader_emulator.cpp','Native/Loader/elf_loader_emulator.h','Native/Loader/elf_metadata_bounds.h','Native/Loader/android_tls_runtime.h','Native/Loader/cxx_allocation_runtime.h','Native/Loader/adi_consumption_debug.h','Native/anisette_base.h','Native/include/anisette_core.h','.ci/native-tests/fixtures/memory_boundaries_host.cpp','.ci/native-tests/test_memory_boundaries_host.py'],
 'test_elf_metadata_bounds.py':['Native/Loader/elf_metadata_bounds.h','Native/anisette_base.h','Native/include/anisette_core.h','.ci/native-tests/fixtures/elf_metadata_bounds_unit.cpp']}
EXPECTED={
 'test_vm_setup_host.py':{'checks':231,'setup_fault_points_per_mode':16,'guest_execution':False,'engine_starts':0},
 'test_memory_boundaries_host.py':{'checks':403,'failures':0,'guest_execution':False,'engine_starts':0,'proprietary_input':False},
 'test_elf_metadata_bounds.py':{'schema':1,'checks':713,'failures':0,'guest_execution':False,'proprietary_input':False}}
def exact(actual,expected):
    require(actual==expected and type(actual) is type(expected),'exact value/count differs')
    if isinstance(expected,dict):
        for key in expected:exact(actual[key],expected[key])
    elif isinstance(expected,list):
        for a,b in zip(actual,expected):exact(a,b)
def extract_headers(archive,destination):
    seal=source_seal();require(sha(archive.read_bytes())==seal['archive_sha256'],'exact fork archive checksum differs');found={};names=set()
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            parts=Path(item.filename).parts
            require(item.filename and not item.filename.startswith('/') and '\\' not in item.filename and '..' not in parts and item.filename not in names,'unsafe/duplicate archive path');names.add(item.filename)
            if len(parts)<2 or parts[-2]!='unicorn' or not parts[-1].endswith('.h'):continue
            mode=(item.external_attr>>16)&0o170000
            require(mode in (0,stat.S_IFREG) and item.file_size<1024*1024,'special/oversized engine header')
            raw=z.read(item);require(parts[-1] not in found or found[parts[-1]]==raw,'header slices disagree');found[parts[-1]]=raw
    exact({name:sha(raw) for name,raw in sorted(found.items())},seal['headers'])
    require(len(found)==12,'exact 12-header dictionary required')
    require(not destination.exists(),'fresh header destination required');(destination/'unicorn').mkdir(parents=True)
    for name,raw in found.items():(destination/'unicorn'/name).write_bytes(raw)
    return seal['headers']
def header_proof(root):
    found={}
    for p in root.rglob('*'):
        require(not p.is_symlink(),'linked header path')
        if p.is_dir():require(p==root/'unicorn','unexpected header directory');continue
        raw=ordinary(root,str(p.relative_to(root))).read_bytes();require(p.parent==root/'unicorn','unexpected header path');found[p.name]=sha(raw)
    exact(found,source_seal()['headers']);return found

def expected_commands(driver,source,output,headers,temporary,compiler,metadata_dir=None):
    require(driver in DRIVERS,'unapproved script')
    rows=[]
    for variant in VARIANTS:
        flags=FLAGS[variant]
        if driver=='test_cxx_allocation.py':
            rows+=allocation.expected_commands(output,source,headers,variant,False)+allocation.expected_commands(output,source,headers,variant,True);continue
        if driver=='test_elf_metadata_bounds.py':
            require(metadata_dir is not None and metadata_dir.parent==temporary and re.fullmatch('elf-metadata-unit-[a-z0-9_]+',metadata_dir.name),'bounded metadata temporary required')
            binary=metadata_dir/variant;cmd=[str(compiler),'-std=c++17','-Wall','-Wextra','-Werror',*flags]
            for folder in ('Native/Loader','Native','Native/include'):cmd+=['-I',str(source/folder)]
            cmd+=[str(source/'.ci/native-tests/fixtures/elf_metadata_bounds_unit.cpp'),'-o',str(binary)]
        else:
            label='setup' if driver=='test_vm_setup_host.py' else 'memory';binary=output/(label+'-'+variant)
            cmd=['c++','-std=c++17',*flags,'-I',str(headers),'-I',str(source/'Native'),'-I',str(source/'Native/include')]
            if label=='setup':cmd+=['-DLOADER_SOURCE="'+str(source/'Native/Loader/elf_loader_emulator.cpp')+'"','-DCORE_SETUP_SLICE="'+str(output/'core_setup_slice.inc')+'"']
            cmd+=[str(source/('.ci/native-tests/fixtures/'+('vm_setup_host.cpp' if label=='setup' else 'memory_boundaries_host.cpp'))),'-o',str(binary)]
        rows+=[cmd,[str(binary)]]
    return rows

def command_metadata_dir(driver,args,temporary):
    if driver!='test_elf_metadata_bounds.py':return None
    path=Path(args[args.index('-o')+1]) if '-o' in args else Path(args[0])
    require(path.is_absolute() and path.parent.parent==temporary,'metadata command escaped temporary');return path.parent

def verify_observer(driver,nested,source,output,headers,temporary,compiler):
    count=15 if driver=='test_cxx_allocation.py' else 6
    actual=[];results=[];cache={}
    require(len(list(nested.glob('*.command.json')))==count,'nested command count differs')
    for index in range(1,count+1):
        label=f'{index:04d}';row=parse(ordinary(nested,label+'.command.json').read_bytes());result=parse(ordinary(nested,label+'.result.json').read_bytes())
        require(set(row)=={'argv','cwd','environment','returncode'} and row['returncode'] is None,'nested command schema differs')
        exact(result,{**row,'returncode':0});require(ordinary(nested,label+'.stderr').read_bytes()==b'','nested diagnostics')
        expected_env='detect_leaks=0:halt_on_error=1:abort_on_error=1' if driver=='test_elf_metadata_bounds.py' else 'detect_leaks=0:halt_on_error=1'
        require(row['environment']['ASAN_OPTIONS']==expected_env and row['environment']['UBSAN_OPTIONS']==('halt_on_error=1:abort_on_error=1' if driver=='test_elf_metadata_bounds.py' else 'halt_on_error=1'),'sanitizer environment differs')
        actual.append(row['argv']);results.append(ordinary(nested,label+'.stdout').read_bytes())
        snapshots={}
        for phase in ('before','after'):
            retained=parse(ordinary(nested,label+'.'+phase+'.json').read_bytes());require(set(retained)=={'temporary','output'},'raw compiler input/output retention missing')
            snapshots[phase]={}
            for key,path in [('temporary',temporary),('output',output)]:snapshots[phase].update(verify_retained_tree(nested,retained[key],path,cache))
        argv=row['argv']
        if '-o' in argv:
            target=argv[argv.index('-o')+1];require(target in snapshots['after'],'raw compiler output missing')
            for arg in argv:
                if arg!=target and (arg.startswith(str(output)+'/') or arg.startswith(str(temporary)+'/')):require(arg in snapshots['before'],'raw compiler input missing')
            if driver=='test_vm_setup_host.py':require(str(output/'core_setup_slice.inc') in snapshots['before'],'raw generated core setup slice missing')
        else:require(argv[0] in snapshots['before'],'raw runtime executable missing')
    meta=command_metadata_dir(driver,actual[0],temporary)
    exact(actual,expected_commands(driver,source,output,headers,temporary,compiler,meta))
    return results

def verify_result(driver,output,nested,source,headers,temporary,compiler):
    streams=verify_observer(driver,nested,source,output,headers,temporary,compiler)
    if driver=='test_cxx_allocation.py':
        row=allocation.verify_allocation_receipt(parse(ordinary(output,'result.json').read_bytes()));allocation.verify_raw_commands(output,row,source,headers)
        for vi,v in enumerate(VARIANTS):
            for offset,suffix in ((0,''),(3,'-hooks')):
                raw=parse(ordinary(output,v+suffix+'.json').read_bytes())
                for i,item in enumerate(raw):require(streams[vi*5+offset+i].decode()==item['stdout'],'CXX raw observer stdout differs')
        return {'checks':249,'variants':3}
    if driver=='test_elf_metadata_bounds.py':
        row=parse(ordinary(output,'result.json').read_bytes())
        require(set(row)=={'schema','source_sha256','results','sanitizers','leak_sanitizer_enabled','guest_execution','device_validation','proprietary_input'},'metadata receipt schema differs')
        exact(row['schema'],1);exact(row['sanitizers'],['address','undefined']);require(row['device_validation'] is False and row['proprietary_input'] is False,'metadata execution overclaim')
        require(set(row['results'])==set(VARIANTS),'metadata variants differ')
        for vi,v in enumerate(VARIANTS):
            exact(row['results'][v],EXPECTED[driver]);exact(parse(streams[vi*2+1]),EXPECTED[driver])
            for si,phase in enumerate(('compile','run')):
                label=v+'-'+phase
                require(ordinary(output,label+'.stdout').read_bytes()==streams[vi*2+si] and ordinary(output,label+'.stderr').read_bytes()==b'' and ordinary(output,label+'.exit-code.txt').read_text()=='0\n','metadata raw output differs')
                exact(parse(ordinary(output,label+'.command.json').read_bytes()),parse(ordinary(nested,f'{vi*2+si+1:04d}.command.json').read_bytes())['argv'])
    else:
        receipt='setup-check-results.json' if driver=='test_vm_setup_host.py' else 'memory-check-results.json';row=parse(ordinary(output,receipt).read_bytes())
        require(set(row)=={'source_sha256','guest_execution','leak_sanitizer_enabled','results'},'host receipt schema differs')
        require(len(row['results'])==6,'host command count differs')
        for index,item in enumerate(row['results']):
            variant=VARIANTS[index//2];stage=('compile','run')[index%2]
            keys={'variant','stage','returncode','stdout','stderr'}|({'command'} if driver=='test_memory_boundaries_host.py' else set())
            require(set(item)==keys and item['variant']==variant and item['stage']==stage and type(item['returncode']) is int and item['returncode']==0 and item['stderr']=='','host command/result differs')
            require(item['stdout']==streams[index].decode(),'raw output differs')
            if stage=='run':exact(parse(streams[index]),EXPECTED[driver])
            else:require(streams[index]==b'','compiler stdout differs')
            if 'command' in item:exact(item['command'],parse(ordinary(nested,f'{index+1:04d}.command.json').read_bytes())['argv'])
    require(row['guest_execution'] is False and row['leak_sanitizer_enabled'] is False,'host execution or LSan overclaim')
    exact(row['source_sha256'],{p:source_seal()['files'][p]['sha256'] for p in SOURCES[driver]})
    return {'checks':EXPECTED[driver]['checks']*3,'variants':3}

def verify_retained_tree(root,row,source_path,cache):
    """Verify raw blob links and source-path binding without the old work tree."""
    require(set(row)=={'kind','label','source_path','entries'} and row['kind']=='filesystem-tree' and row['source_path']==str(source_path),'retained compiler tree identity differs')
    require(isinstance(row['entries'],list),'retained compiler entries missing');found={};seen=set()
    for item in row['entries']:
        name=item['path'];require(name not in seen,'duplicate retained compiler entry');seen.add(name)
        require(name=='' or (not Path(name).is_absolute() and all(p not in ('','.','..') for p in name.split('/'))),'unsafe retained compiler path')
        if item['kind']=='directory':continue
        require(item['kind']=='file' and item['source_path']==str(source_path/name),'retained compiler file identity differs')
        h=item['sha256'];require(re.fullmatch('[0-9a-f]{64}',h) and item['blob_path']=='blobs/sha256/'+h[:2]+'/'+h,'retained compiler blob reference differs')
        if h not in cache:
            raw=ordinary(root,item['blob_path']).read_bytes();require(sha(raw)==h,'retained compiler raw bytes differ');cache[h]=len(raw)
        require(type(item['length']) is int and item['length']==cache[h],'retained compiler length differs');found[str(source_path/name)]=item
    require('' in seen,'retained compiler root missing');return found
