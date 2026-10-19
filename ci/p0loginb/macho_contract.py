"""Read-only bounded Mach-O product checks; never loads or executes a product.
Format constants: Apple XNU EXTERNAL_HEADERS/mach-o/loader.h and
osfmk/mach/machine.h at https://github.com/apple-oss-distributions/xnu .
"""
import hashlib,io,json,plistlib,re,stat,struct,zipfile
from pathlib import Path
from source_primitives import require
MAX_BINARY=512*1024*1024

def version(value):return [value>>16,(value>>8)&255,value&255]
def inspect_binary(raw, *, filetype=2, preexisting_signature=False):
    require(isinstance(raw,bytes) and 32<=len(raw)<=MAX_BINARY,'bounded Mach-O executable bytes required')
    raw_sha=hashlib.sha256(raw).hexdigest()
    require(not preexisting_signature or raw_sha in (OPENSSL_BINARY_SHA,CYDIA_BINARY_SHA,SIDESTORE_OPENSSL_BINARY_SHA),'only exact reviewed prebuilt signatures are permitted')
    expected_type=filetype
    magic,cpu,subtype,filetype,ncmds,sizeofcmds,flags,reserved=struct.unpack_from('<8I',raw)
    require(magic==0xfeedfacf,'thin little-endian 64-bit Mach-O required')
    require(cpu==0x0100000c and subtype==0,'exact generic arm64 architecture required')
    require(filetype in (2,6) and filetype==expected_type and reserved==0,'exact Mach-O product filetype required')
    require(0<ncmds<=4096 and ncmds*8<=sizeofcmds<=len(raw)-32 and sizeofcmds%8==0,'invalid bounded load-command table')
    end=32+sizeofcmds;offset=32;build=[];main=[];text=[];signatures=[]
    for _ in range(ncmds):
        require(offset+8<=end,'truncated load command');cmd,size=struct.unpack_from('<2I',raw,offset)
        require(size>=8 and size%8==0 and offset+size<=end,'invalid load-command size')
        if cmd==0x1d:
            require(preexisting_signature and size==16,'unexpected code signature in newly built product')
            start,length=struct.unpack_from('<2I',raw,offset+8);require(start>=end and length>0 and start+length<=len(raw),'invalid preexisting signature range');signatures.append({'offset':start,'bytes':length})
        if cmd in (0x24,0x25,0x2f,0x30):
            require(preexisting_signature and raw_sha==CYDIA_BINARY_SHA and cmd==0x25 and size==16,'legacy platform command only allowed for exact CydiaSubstrate input')
            minimum,sdk=struct.unpack_from('<2I',raw,offset+8);require(minimum>0,'invalid legacy iOS version')
            build.append({'platform':'iOS','platform_id':2,'minimum_os':version(minimum),'sdk':version(sdk),'tools':[],'version_command':'LC_VERSION_MIN_IPHONEOS_PINNED_PREBUILT'})
        if cmd==0x32:
            require(size>=24,'truncated build version');_,_,platform,minos,sdk,ntools=struct.unpack_from('<6I',raw,offset)
            require(size==24+ntools*8 and ntools<=128,'malformed build-version tools')
            require(platform==2 and minos>0 and sdk>=minos,'iOS device platform and valid deployment/sdk versions required')
            tools=[list(struct.unpack_from('<2I',raw,offset+24+i*8)) for i in range(ntools)]
            require(len({r[0] for r in tools})==len(tools),'duplicate build tool')
            build.append({'platform':'iOS','platform_id':platform,'minimum_os':version(minos),'sdk':version(sdk),'tools':tools})
        if cmd==0x80000028:
            require(size==24,'malformed LC_MAIN');entry,stack=struct.unpack_from('<2Q',raw,offset+8)
            require(end<=entry<len(raw),'entry offset is outside actual executable bytes');main.append({'entryoff':entry,'stacksize':stack})
        if cmd==0x19:
            require(size>=72,'truncated segment');name=raw[offset+8:offset+24].split(b'\0',1)[0];vmaddr,vmsize,fileoff,filesize=struct.unpack_from('<4Q',raw,offset+24);maxprot,initprot,nsects,segmentflags=struct.unpack_from('<4I',raw,offset+56)
            require(size==72+nsects*80 and fileoff<=len(raw) and filesize<=len(raw)-fileoff,'segment/section table or file extent invalid')
            if name==b'__TEXT':
                require(fileoff==0 and filesize>end and initprot&4,'actual executable __TEXT segment required');text.append((fileoff,filesize))
        offset+=size
    require(offset==end and len(build)==len(text)==1 and len(main)==(1 if filetype==2 else 0),'exact platform, entry policy and text segment required')
    require(len(signatures)==(1 if preexisting_signature else 0),'preexisting signature policy differs')
    if main:require(text[0][0]<=main[0]['entryoff']<sum(text[0]),'entrypoint outside __TEXT file bytes')
    return {'format':'MH_MAGIC_64','architecture':'arm64','cpu_type':cpu,'cpu_subtype':subtype,'filetype':'MH_EXECUTE' if filetype==2 else 'MH_DYLIB','bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'ncmds':ncmds,'sizeofcmds':sizeofcmds,'unsigned':not preexisting_signature,'signature_kind':'PINNED_PREEXISTING_METADATA_NOT_VALIDATED' if preexisting_signature else 'ABSENT','executed':False,**build[0],**(main[0] if main else {}), 'signatures':signatures}

def inspect_executable(raw):return inspect_binary(raw,filetype=2)

MAGICS={b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xce\xfa\xed\xfe',b'\xfe\xed\xfa\xce',b'\xca\xfe\xba\xbe',b'\xbe\xba\xfe\xca',b'\xca\xfe\xba\xbf',b'\xbf\xba\xfe\xca'}
CYDIA_BINARY_SHA='bca859c9413cb85ca0d3ecfca494c61d67e4acd5846660e618526a152963965b'
OPENSSL_BINARY_SHA='df7faa880948b310527a191362fda21b31f6d9d261731ec1fe1ab9b7728854a4'
OPENSSL_RESOURCES_SHA='2beea0ebb64b00bee3956cbc18c690fd67cd7955a088472ce863bcacc580768d'
MAX_PRODUCT_BYTES=2*1024*1024*1024
SIDESTORE_OPENSSL_BINARY_SHA='355ff3a21cb4eb8ef86bfba202414de1a9070b3ddf8703d03cedfcacbe9e5431'
MAX_PRODUCT_REPORT_BYTES=8*1024*1024
MAX_PRODUCT_REPORT_PATH_BYTES=1024

class ProductValidationError(ValueError):
    """Failed static validation with bounded, non-executable product evidence."""
    def __init__(self, message, diagnostic):
        super().__init__(message)
        self.diagnostic=diagnostic

def _digest_json(value):
    digest=hashlib.sha256()
    for part in json.JSONEncoder(sort_keys=True,separators=(',',':'),ensure_ascii=True).iterencode(value):
        digest.update(part.encode('ascii'))
    return digest.hexdigest()

def _bounded_text(value):
    if value is None or type(value) is bool:return value
    raw=str(value).encode('utf-8',errors='backslashreplace')
    return str(value) if len(raw)<=MAX_PRODUCT_REPORT_PATH_BYTES else {'omitted_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}

def product_inventory(files, owner, *, status='PRODUCT_HASH_INVENTORY_CAPTURED', context=None, reason=None):
    """Hash-only complete inventory or fixed bounded fallback, never product bytes."""
    require(owner in (None,'SideStore','LiveContainer','SideBackup'),'finite product owner required')
    require(status in ('PRODUCT_HASH_INVENTORY_CAPTURED','PRODUCT_STATIC_VALIDATION_FAILED'),'finite product report status required')
    rows={name:{'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)} for name,raw in sorted(files.items())}
    context={key:_bounded_text(value) for key,value in (context or {}).items() if key in ('stage','bundle','executable','executable_path','member','snapshot_complete')}
    snapshot_complete=context.get('snapshot_complete',True) is not False
    result={'schema_version':1,'status':status,'owner':owner,'complete':False,
        'snapshot_complete':snapshot_complete,'unobserved_files_unknown':not snapshot_complete,
        'file_count':len(rows),'total_bytes':sum(row['bytes'] for row in rows.values()),
        'inventory_sha256':_digest_json(rows),'omitted_files':len(rows),'context':context,
        'reason':_bounded_text(reason),'executed':False,
        'limits':{'files':20000,'path_utf8_bytes':MAX_PRODUCT_REPORT_PATH_BYTES,'serialized_bytes':MAX_PRODUCT_REPORT_BYTES}}
    if len(rows)>20000:
        result['bound_failure']='FILE_COUNT_LIMIT';return result
    if any(len(name.encode('utf-8',errors='backslashreplace'))>MAX_PRODUCT_REPORT_PATH_BYTES for name in rows):
        result['bound_failure']='PATH_LENGTH_LIMIT';return result
    signatures={name:row for name,row in rows.items() if '/_CodeSignature/' in '/'+name}
    executable=(context or {}).get('executable_path')
    full=dict(result,complete=snapshot_complete,omitted_files=0,inventory=rows,signature_resources=signatures,
              executable=rows.get(executable) if isinstance(executable,str) else None)
    if len((json.dumps(full,sort_keys=True,indent=2)+'\n').encode())>MAX_PRODUCT_REPORT_BYTES:
        result['bound_failure']='SERIALIZED_SIZE_LIMIT';return result
    return full

def _failure(files,owner,context,error):
    return ProductValidationError(str(error),product_inventory(files,owner,status='PRODUCT_STATIC_VALIDATION_FAILED',context=context,reason=str(error)))


def _safe_name(name):
    require(isinstance(name,str) and name and not name.startswith('/') and '\\' not in name and '\0' not in name and all(part not in ('','.','..') for part in name.split('/')),'unsafe product member path')
    return name

def _inspect_files_impl(files, *, root_bundle, allow_pinned_prebuilt=False, owner=None, sidestore_openssl_proof=None, context):
    require(not allow_pinned_prebuilt or owner in (None,'LiveContainer'),'legacy prebuilt allowance belongs only to LiveContainer')
    require(len(files)<=20000 and sum(len(raw) for raw in files.values())<=MAX_PRODUCT_BYTES,'bounded product inventory required')
    for name in files:_safe_name(name)
    if sidestore_openssl_proof is not None:
        require(owner=='SideStore' and root_bundle=='','SideStore source proof is owner/root scoped')
        require('Frameworks/OpenSSL.framework/Info.plist' in files,'verified SideStore OpenSSL copied framework is mandatory')
    bundles={root_bundle}
    for name in files:
        parts=name.split('/')
        bundles.update('/'.join(parts[:i+1]) for i,p in enumerate(parts[:-1]) if p.endswith(('.app','.appex','.framework')))
    binaries={};resources={};selected={}
    for bundle in sorted(bundles):
        context.clear();context.update(stage='bundle',bundle=bundle)
        prefix=bundle+'/' if bundle else '';info_name=prefix+'Info.plist'
        require(info_name in files and len(files[info_name])<=1024*1024,'actual bundle Info.plist absent or too large')
        info=plistlib.loads(files[info_name]);executable=info.get('CFBundleExecutable')
        require(isinstance(executable,str) and re.fullmatch('[A-Za-z0-9_.+-]+',executable) and executable not in ('.','..'),'safe actual CFBundleExecutable required')
        name=prefix+executable;context.update(executable=executable,executable_path=name)
        require(name in files,'actual Info.plist executable missing')
        framework=bundle.endswith('.framework');expected_type=6 if framework else 2
        openssl=allow_pinned_prebuilt and bundle.endswith('/OpenSSL.framework') and executable=='OpenSSL'
        cydia=allow_pinned_prebuilt and bundle.endswith('/CydiaSubstrate.framework') and executable=='CydiaSubstrate'
        sidestore_openssl=(owner=='SideStore' and bundle=='Frameworks/OpenSSL.framework' and executable=='OpenSSL' and sidestore_openssl_proof is not None)
        prebuilt=openssl or cydia or sidestore_openssl
        signature_prefix=prefix+'_CodeSignature/'
        signed_names={key for key in files if key.startswith(signature_prefix)}
        if sidestore_openssl:
            from openssl_artifact_contract import EXPECTED_PRODUCT_FILES,validate_source_proof
            validate_source_proof(sidestore_openssl_proof)
            actual={key[len(prefix):]:{'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)} for key,raw in files.items() if key.startswith(prefix)}
            require(actual==EXPECTED_PRODUCT_FILES==sidestore_openssl_proof['expected_product_files'],'SideStore copied OpenSSL framework differs from verified binary artifact')
            require(hashlib.sha256(files[name]).hexdigest()==SIDESTORE_OPENSSL_BINARY_SHA,'pinned SideStore OpenSSL binary bytes differ')
            require(signed_names=={signature_prefix+'CodeResources'},'exact SideStore OpenSSL signature resources required')
            resources.update({key:hashlib.sha256(files[key]).hexdigest() for key in signed_names})
        elif openssl:
            require(hashlib.sha256(files[name]).hexdigest()==OPENSSL_BINARY_SHA,'pinned OpenSSL binary bytes differ')
            signature=signature_prefix+'CodeResources'
            require(signed_names=={signature} and hashlib.sha256(files[signature]).hexdigest()==OPENSSL_RESOURCES_SHA,'pinned OpenSSL signature resources differ')
            resources[signature]=hashlib.sha256(files[signature]).hexdigest()
        elif cydia:
            require(hashlib.sha256(files[name]).hexdigest()==CYDIA_BINARY_SHA and not signed_names,'pinned CydiaSubstrate binary/signature resources differ')
        else:require(not signed_names,'newly built bundle unexpectedly has signature resources')
        report=inspect_binary(files[name],filetype=expected_type,preexisting_signature=prebuilt)
        report.update(executable=executable,info_plist_sha256=hashlib.sha256(files[info_name]).hexdigest(),bundle=bundle)
        if sidestore_openssl:report['preexisting_source_proof_sha256']=_digest_json(sidestore_openssl_proof)
        binaries[name]=report;selected[bundle]=name
    for name,raw in files.items():
        if name in binaries:continue
        context.clear();context.update(stage='unselected-member',executable_path=name)
        require('/_CodeSignature/' not in '/'+name or name in resources,'unbound signature resources')
        if raw[:4] in MAGICS:
            require(len(raw)>=16,'truncated unknown Mach-O product')
            kind=struct.unpack_from('<I',raw,12)[0]
            require(kind in (2,6),'unrecognized embedded Mach-O filetype')
            binaries[name]=inspect_binary(raw,filetype=kind)
        elif name.endswith('.dylib'):require(False,'dylib product is not recognized Mach-O')
    return {'executed':False,'selected_bundle_executables':selected,'binaries':binaries,'preexisting_signature_resources':resources,
        'inventory':{name:{'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)} for name,raw in sorted(files.items())}}

def _inspect_files(files, *, root_bundle, allow_pinned_prebuilt=False, owner=None, sidestore_openssl_proof=None):
    context={'stage':'product','bundle':root_bundle}
    try:
        return _inspect_files_impl(files,root_bundle=root_bundle,allow_pinned_prebuilt=allow_pinned_prebuilt,
            owner=owner,sidestore_openssl_proof=sidestore_openssl_proof,context=context)
    except ProductValidationError:raise
    except Exception as error:raise _failure(files,owner,context,error) from error

def _ordinary_files(root,owner=None):
    result={};total=0;context={'stage':'filesystem-snapshot','snapshot_complete':False}
    try:
        root=Path(root);require(root.is_dir() and all(not p.is_symlink() for p in (root,*root.parents)),'ordinary product directory required')
        for p in sorted(root.rglob('*')):
            context['member']=p.relative_to(root).as_posix()
            require(not p.is_symlink(),'symlink product member')
            if p.is_dir():continue
            require(p.is_file() and p.stat().st_size<=MAX_BINARY,'ordinary bounded product member required')
            raw=p.read_bytes();total+=len(raw);require(total<=MAX_PRODUCT_BYTES,'product byte limit exceeded');result[p.relative_to(root).as_posix()]=raw
        return result
    except Exception as error:raise _failure(result,owner,context,error) from error

def capture_app_inventory(app,owner):
    return product_inventory(_ordinary_files(app,owner),owner,context={'stage':'snapshot-complete','bundle':'','snapshot_complete':True})

def inspect_app(app, *, allow_pinned_prebuilt=False, owner=None, sidestore_openssl_proof=None, on_inventory=None):
    files={}
    try:
        files=_ordinary_files(app,owner)
        inventory=product_inventory(files,owner,context={'stage':'snapshot-complete','bundle':''})
        if on_inventory is not None:on_inventory(inventory)
        require(inventory['complete'],'bounded complete product inventory required')
        report=_inspect_files(files,root_bundle='',allow_pinned_prebuilt=allow_pinned_prebuilt,
            owner=owner,sidestore_openssl_proof=sidestore_openssl_proof)
        main=report['binaries'][report['selected_bundle_executables']['']]
        return {**main,'product':report}
    except ProductValidationError:raise
    except Exception as error:raise _failure(files,owner,{'stage':'product-snapshot','bundle':''},error) from error

def inspect_internal_ipa(path, *, on_inventory=None):
    files={};context={'stage':'internal-archive-snapshot','snapshot_complete':False}
    try:
        path=Path(path);require(path.is_file() and all(not p.is_symlink() for p in (path,*path.parents)) and path.stat().st_size<=MAX_BINARY,'ordinary bounded internal IPA required')
        raw=path.read_bytes();total=0
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            require(len(archive.infolist())<=20000,'IPA member limit exceeded')
            for member in archive.infolist():
                name=member.filename[:-1] if member.is_dir() else member.filename;context['member']=name;_safe_name(name)
                mode=member.external_attr>>16;require(not stat.S_ISLNK(mode),'IPA symlink forbidden')
                if member.is_dir():continue
                require(name not in files and member.file_size<=MAX_BINARY and not member.flag_bits&1,'duplicate/encrypted/oversized IPA member')
                total+=member.file_size;require(total<=MAX_PRODUCT_BYTES,'IPA expanded byte limit exceeded');files[name]=archive.read(member)
        context={'stage':'internal-archive-members','snapshot_complete':True}
        inventory=product_inventory(files,'SideBackup',context=context)
        if on_inventory is not None:on_inventory(inventory)
        require(inventory['complete'],'bounded complete internal product inventory required')
        roots={name.split('/')[1] for name in files if name.startswith('Payload/') and len(name.split('/'))>=3}
        require(len(roots)==1 and next(iter(roots)).endswith('.app') and all(name.startswith('Payload/'+next(iter(roots))+'/') for name in files),'exact one internal Payload app required')
        bundle='Payload/'+next(iter(roots));report=_inspect_files(files,root_bundle=bundle,owner='SideBackup')
        return {'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'kind':'internal-build-resource','distributed':False,'executed':False,'product':report}
    except ProductValidationError:raise
    except Exception as error:raise _failure(files,'SideBackup',context,error) from error
