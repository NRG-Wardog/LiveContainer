"""Bounded synthetic-only diagnostic checks; no production rewrite or real engine."""
import ast, hashlib, json, os, platform, re, subprocess
from pathlib import Path
from inventory import ordinary, parse, sha
from source_primitives import require
from capture_contract import SANDBOX
HERE=Path(__file__).resolve().parent
VARIANTS=(('normal',[]),('optimized',['-O2','-DNDEBUG']),('sanitized',['-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-fno-omit-frame-pointer']))
NATIVE_EXPECTED={'checks':662,'failures':0,'guest_execution':False,'real_engine_starts':0,'proprietary_input':False,'synthetic_api_starts':5}
PREAMBLE='''#ifdef BOUNDED_FAULT_HOST_APPLE_DIGEST
#define __APPLE__ 1
#include "../../../Native/Loader/bounded_asset_digest.h"
#undef __APPLE__
#endif'''
APPLE_HELPER='''#include <CommonCrypto/CommonDigest.h>
using SHA256_CTX = CC_SHA256_CTX;
static int SHA256_Init(SHA256_CTX *p) { return CC_SHA256_Init(p); }
static int SHA256_Update(SHA256_CTX *p, const void *b, size_t n) {
    if (n > UINT32_MAX) return 0;
    return CC_SHA256_Update(p, b, static_cast<CC_LONG>(n));
}
static int SHA256_Final(unsigned char *b, SHA256_CTX *p) { return CC_SHA256_Final(b, p); }'''

def exact_replace(text,before,after):
    require(text.count(before)==1,'literal-only Apple fixture adaptation anchor differs')
    return text.replace(before,after,1)

def adapt_native_fixture(original,owner):
    path=owner/'.ci/native-tests/fixtures/bounded_fault_host.cpp'
    changes=[(PREAMBLE,'// Apple SDK fixture: keep the compiler-provided __APPLE__ definition.'),
             ('#include "../../../Native/Loader/elf_loader_emulator.cpp"','#include '+json.dumps(str(owner/'Native/Loader/elf_loader_emulator.cpp'))),
             ('#include <openssl/sha.h>',APPLE_HELPER),
             ('#ifdef BOUNDED_FAULT_HOST_APPLE_DIGEST','#if defined(__APPLE__)')]
    text=original
    for before,after in changes:text=exact_replace(text,before,after)
    return text,{'source_path':str(path),'original_sha256':sha(original.encode()),'generated_sha256':sha(text.encode()),'literal_replacements':[{'before':a,'after':b} for a,b in changes], 'production_source_modified':False}

def native_fixture(owner):
    return adapt_native_fixture(ordinary(owner,'.ci/native-tests/fixtures/bounded_fault_host.cpp').read_text(),owner)

def source_closure(owner):
    closure=parse(ordinary(HERE,'reviewed/diagnostic-source-inventory.json').read_bytes())
    actual={}
    for path,row in closure['files'].items():
        p=ordinary(owner,path);raw=p.read_bytes()
        require(sha(raw)==row['sha256'] and len(raw)==row['bytes'],'diagnostic source closure differs: '+path)
        require(('100755' if p.stat().st_mode&0o111 else '100644')==row['mode'],'diagnostic source mode differs')
        actual[path]=sha(raw)
    return actual

def swift_fixture(owner):
    raw=ordinary(owner,'Sources/AnisetteDataProvider.swift').read_bytes();text=raw.decode();spans=[]
    def span(start,end=None):
        require(text.count(start)==1 and (end is None or text.count(end)==1),'Swift extraction anchor differs')
        a=text.index(start);b=text.index(end,a) if end is not None else len(text)
        part=text[a:b];spans.append({'start':start,'end':end,'byte_start':len(text[:a].encode()),'byte_end':len(text[:b].encode()),'sha256':sha(part.encode())})
        return part
    parts=[span('public protocol AnisetteDataProvider: Sendable {','public struct UnicornAnisetteDataProvider:'),
           span('private enum TemporaryAnisetteNativeTrace {','// V3_ISOLATED_ANISETTE_OTP_V1.'),
           span('private enum TemporaryADIConsumptionTrace {','// Independent optional wire:'),
           span('private enum TemporaryConstructorFaultTrace {')]
    driver=ordinary(owner,'.ci/native-tests/test_bounded_fault_host.py').read_text()
    assignments=[node for node in ast.parse(driver).body if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='harness' for t in node.targets)]
    require(len(assignments)==1,'exact reviewed decoder harness required')
    harness=ast.literal_eval(assignments[0].value);require(isinstance(harness,str),'literal Swift harness required')
    boundary=ordinary(HERE,'fixtures/diagnostic-boundary.swift').read_text()
    source='import Foundation\n'+'\n'.join(parts)+'\n'+harness+'\n'+boundary
    return source,{'source_path':'Sources/AnisetteDataProvider.swift','source_sha256':sha(raw),'exact_byte_spans':spans,'decoder_harness_source_sha256':sha(driver.encode()),'decoder_harness_sha256':sha(harness.encode()),'boundary_harness_sha256':sha(boundary.encode()),'generated_sha256':sha(source.encode()),'production_methods_modified':False}

def native_command(owner,include,source,binary,flags):
    return ['xcrun','clang++','-std=c++17','-Wno-deprecated-declarations',*flags,'-MMD','-MF',str(binary)+'.d','-I',str(include),'-I',str(owner/'Native'),'-I',str(owner/'Native/include'),str(source),'-o',str(binary)]

def command_context(owner,include,out):
    return dict(owner=str(owner),include=str(include),output=str(out))

def command_plan(context):
    require(set(context)=={'owner','include','output'},'diagnostic command context differs')
    for value in context.values():
        require(isinstance(value,str) and Path(value).is_absolute() and '..' not in Path(value).parts,'canonical absolute diagnostic command paths required')
    owner,include,out=(Path(context[k]) for k in ('owner','include','output'))
    require(owner.parts[-2:]==('sources','AnisetteKit'),'fixed diagnostic owner layout required')
    work=owner.parent.parent
    require(include==work/'host-unicorn-headers' and out==work/'host-tests/run-diagnostic-checks','fixed diagnostic include/output layout required')
    logical=[]
    for variant,flags in VARIANTS:
        binary=out/('bounded-fault-'+variant)
        logical.extend([(variant+'-compile',native_command(owner,include,out/'bounded-fault-apple.cpp',binary,flags)),
                        (variant+'-run',[str(binary)]),(variant+'-nm',['xcrun','nm','-u',str(binary)]),
                        (variant+'-otool',['xcrun','otool','-L',str(binary)])])
    dependencies=[str(owner/'Sources'/name) for name in ('AnisetteDataResponse.swift','AnisetteError.swift','Constants.swift','LoginDiagnosticTrace.swift')]
    for variant,flags in (('normal',[]),('optimized',['-O'])):
        binary=out/('swift-boundaries-'+variant)
        logical.extend([('swift-'+variant+'-compile',['swiftc',*flags,str(out/'main.swift'),*dependencies,'-o',str(binary)]),
                        ('swift-'+variant+'-run',[str(binary)])])
    rows=[]
    for label,argv in logical:
        compile_only=label in ('swift-normal-compile','swift-optimized-compile')
        rows.append(dict(label=label,logical_argv=argv,argv=argv if compile_only else [*SANDBOX,*argv],
                         sandbox_policy='apple_plugin_sandbox_compile' if compile_only else 'network_denied'))
    return rows

def dispatch_argv(context,label,logical_argv):
    matches=[r for r in command_plan(context) if r['label']==label]
    require(len(matches)==1 and matches[0]['logical_argv']==logical_argv,'exact finite diagnostic command dispatch required')
    return matches[0]

def verify_result(row,expected_context):
    require(set(row)=={'schema','guest_execution','real_engine_linked','proprietary_input','leak_sanitizer_enabled','apple_commoncrypto_validated','swift_boundaries_validated','source_sha256','native_fixture','swift_fixture','command_context','results'},'diagnostic result schema differs')
    require(row['schema']==1 and type(row['schema']) is int,'diagnostic schema differs')
    inventory=parse(ordinary(HERE,'reviewed/diagnostic-source-inventory.json').read_bytes())
    require(row['source_sha256']=={p:r['sha256'] for p,r in inventory['files'].items()},'exact diagnostic runtime source closure differs')
    fixture_root=HERE/'tests/fixtures/diagnostic-source'
    native_path=Path(row['native_fixture']['source_path'])
    require(native_path.is_absolute() and native_path.parts[-4:]==('.ci','native-tests','fixtures','bounded_fault_host.cpp'),'native fixture source path differs')
    original=ordinary(fixture_root,'.ci/native-tests/fixtures/bounded_fault_host.cpp').read_text()
    require(sha(original.encode())==inventory['files']['.ci/native-tests/fixtures/bounded_fault_host.cpp']['sha256'],'original native fixture bytes differ')
    _,native_expected=adapt_native_fixture(original,native_path.parents[3])
    _,swift_expected=swift_fixture(fixture_root)
    require(row['native_fixture']==native_expected and row['swift_fixture']==swift_expected,'generated diagnostic fixture receipt differs')

    for key in ('guest_execution','real_engine_linked','proprietary_input','leak_sanitizer_enabled'):require(row[key] is False,'diagnostic scope differs')
    require(row['apple_commoncrypto_validated'] is True and row['swift_boundaries_validated'] is True,'Apple/Swift runtime validation incomplete')
    require(row['command_context']==expected_context,'diagnostic command context differs from trusted outer paths')
    plan=command_plan(row['command_context']);require(row['command_context']['owner']==str(native_path.parents[3]),'diagnostic command owner differs from fixture')
    results=row['results'];require([r['label'] for r in results]==[r['label'] for r in plan],'finite diagnostic command order differs')
    for r,expected in zip(results,plan):
        require(set(r)=={'label','logical_argv','argv','sandbox_policy','returncode','stdout','stderr'} and all(r[k]==v for k,v in expected.items()),'diagnostic logical/executed command or sandbox policy differs')
        require(r['returncode']==0 and r['stderr']=='','diagnostic command failed or emitted diagnostics')
        if r['label'] in [v+'-run' for v,_ in VARIANTS]:
            value=parse(r['stdout']);require(value==NATIVE_EXPECTED and all(type(value[k]) is type(v) for k,v in NATIVE_EXPECTED.items()),'diagnostic native runtime differs')
        if r['label'].endswith('-nm'):
            for symbol in ('_CC_SHA256_Init','_CC_SHA256_Update','_CC_SHA256_Final'):require(re.search(r'^\s*(?:U\s+)?'+symbol+r'\s*$',r['stdout'],re.M),'real CommonCrypto symbol reference missing')
            require(not re.search(r'^\s*(?:U\s+)?_uc_\w+',r['stdout'],re.M),'real engine reference in synthetic fixture')
        if r['label'].endswith('-otool'):
            require('/usr/lib/libSystem.B.dylib' in r['stdout'] and not re.search('unicorn|libcrypto|libssl',r['stdout'],re.I),'unexpected native diagnostic linkage')
        if r['label'] in ('swift-normal-run','swift-optimized-run'):
            require(r['stdout']=='BOUNDED_FAULT_SWIFT_DECODER_PASS\nBOUNDED_FAULT_SWIFT_BOUNDARIES_PASS:77\n','exact Swift decoder/boundary runtime completion required')
    return {'native_assertions':1986,'swift_boundary_checks':154,'swift_decoder_variants':2,'guest_execution':False,'real_engine_starts':0,'apple_commoncrypto_validated':True}

def run(owner,include,out):
    require(platform.system()=='Darwin' and platform.machine()=='arm64','Apple arm64 SDK execution required')
    before=source_closure(owner);rows=[];context=command_context(owner,include,out)
    cpp,cpp_receipt=native_fixture(owner);swift,swift_receipt=swift_fixture(owner)
    (out/'bounded-fault-apple.cpp').write_text(cpp);(out/'main.swift').write_text(swift)
    for label,receipt in [('native-fixture',cpp_receipt),('swift-fixture',swift_receipt)]:
        (out/(label+'.json')).write_text(json.dumps(receipt,indent=2)+'\n')
    row=dict(schema=1,guest_execution=False,real_engine_linked=False,proprietary_input=False,leak_sanitizer_enabled=False,apple_commoncrypto_validated=False,swift_boundaries_validated=False,source_sha256=before,native_fixture=cpp_receipt,swift_fixture=swift_receipt,command_context=context,results=rows)
    def save():(out/'diagnostic-results.json').write_text(json.dumps(row,indent=2)+'\n')
    def command(label,argv,env=None):
        dispatch=dispatch_argv(context,label,argv)
        result=subprocess.run(dispatch['argv'],capture_output=True,text=True,timeout=120,env=env)
        rows.append(dict(dispatch,returncode=result.returncode,stdout=result.stdout,stderr=result.stderr));save()
        require(result.returncode==0 and result.stderr=='','diagnostic command failed: '+label)
    for variant,flags in VARIANTS:
        binary=out/('bounded-fault-'+variant)
        command(variant+'-compile',native_command(owner,include,out/'bounded-fault-apple.cpp',binary,flags))
        command(variant+'-run',[str(binary)],dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
        command(variant+'-nm',['xcrun','nm','-u',str(binary)])
        command(variant+'-otool',['xcrun','otool','-L',str(binary)])
    row['apple_commoncrypto_validated']=True;save()
    dependencies=[str(ordinary(owner,'Sources/'+name)) for name in ('AnisetteDataResponse.swift','AnisetteError.swift','Constants.swift','LoginDiagnosticTrace.swift')]
    for variant,flags in (('normal',[]),('optimized',['-O'])):
        binary=out/('swift-boundaries-'+variant)
        command('swift-'+variant+'-compile',['swiftc',*flags,str(out/'main.swift'),*dependencies,'-o',str(binary)])
        command('swift-'+variant+'-run',[str(binary)])
    row['swift_boundaries_validated']=True;save()
    require(before==source_closure(owner),'diagnostic sources changed during runtime checks')
    verify_result(row,context)
