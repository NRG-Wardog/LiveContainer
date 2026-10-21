#!/usr/bin/env python3
"""Inspect built archives/headers only; never link or execute target-native code."""
import argparse,hashlib,json,plistlib,subprocess
from pathlib import Path

def require(condition,message):
    if not condition:
        raise RuntimeError(message)
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def selected_slice(root):
    info=plistlib.loads((root/'Info.plist').read_bytes())
    libs=[x for x in info['AvailableLibraries'] if x['SupportedPlatform']=='ios' and not x.get('SupportedPlatformVariant') and x['SupportedArchitectures']==['arm64']]
    require(len(libs)==1,'Expected exactly one non-simulator iOS arm64 archive slice')
    lib=libs[0];folder=root/lib['LibraryIdentifier'];archive=folder/lib['LibraryPath'];headers=folder/lib['HeadersPath']
    for path in (archive,headers):
        require(path.resolve().is_relative_to(root.resolve()),'Framework slice escapes its root')
    require(archive.is_file() and archive.suffix=='.a','Framework must contain the generated static archive')
    require((headers/'idevice.h').is_file(),'Framework lacks generated idevice.h')
    return archive,headers

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--framework',type=Path,required=True);p.add_argument('--staged-framework',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    spec=json.loads((Path(__file__).parent/'required-symbols.json').read_text())
    archive=args.source/'target/aarch64-apple-ios/release/libidevice_ffi.a';header=args.source/'ffi/idevice.h'
    require(archive.is_file() and header.is_file(),'Native build outputs are missing')
    sdk=subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-path'],text=True).strip()
    artifacts=[('cargo',archive,args.source/'ffi')]
    for name,root in [('framework',args.framework),('staged',args.staged_framework)]:
        a,h=selected_slice(root);require(digest(a)==digest(archive),'Archive bytes changed in '+name);require(digest(h/'idevice.h')==digest(header),'Generated header bytes changed in '+name);artifacts.append((name,a,h))
    result={'status':'COMPILE_ONLY_ABI_INSPECTION_PASS_NOT_RUNTIME_VALIDATION','target_executed':False,'archive_sha256':digest(archive),'generated_header_sha256':digest(header),'required_symbols':[x['name'] for x in spec['symbols']],'artifacts':[]}
    for name,a,headers in artifacts:
        nm_cmd=['xcrun','nm','-arch','arm64','-gUj',str(a)]
        output=subprocess.check_output(nm_cmd,text=True)
        defined=set(output.splitlines())
        for symbol in spec['symbols']:
            require(symbol['mach_o_symbol'] in defined,'Missing defined external symbol in '+name+': '+symbol['name'])
        clang_cmd=['xcrun','--sdk','iphoneos','clang','-target','arm64-apple-ios15.0','-isysroot',sdk,'-std=c11','-Werror','-fsyntax-only','-I',str(headers),str(Path(__file__).parent/'assert_header.c')]
        subprocess.run(clang_cmd,check=True)
        result['artifacts'].append({'name':name,'archive':str(a),'header':str(headers/'idevice.h'),'nm_command':nm_cmd,'clang_command':clang_cmd,'required_symbols_defined':True,'header_signature_and_layout_checks':True})
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
