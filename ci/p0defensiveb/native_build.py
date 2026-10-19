"""Ordinary native/Xcode command families; used only after future reviewed admission.
No archive or executable is run. The normal SideStore build creates an internal
SideBackup.ipa resource; that is explicitly retained as build output evidence.
"""
import os,shutil,stat
from pathlib import Path
import source_primitives as primitives
import cargo_contract as cargo_proof
from inventory import TOOLCHAIN,check_lock,dump,sha,require
LOCK='AltStore.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved'
SETTINGS=['-sdk','iphoneos','-configuration','Release','-destination','generic/platform=iOS','CODE_SIGNING_ALLOWED=NO','CODE_SIGNING_REQUIRED=NO','CODE_SIGN_IDENTITY=','DEVELOPMENT_TEAM=','build']
# Historical genuine release receipts supply these expectations; the reviewed
# adapter digest binds them. The current run must still observe them itself.
RUST_TOOLCHAIN='1.98.1-aarch64-apple-darwin'
RUSTC_VERSION='rustc 1.98.1 (48a229cea 2026-09-01)'
RUSTC_VERBOSE=(RUSTC_VERSION+'\nbinary: rustc\ncommit-hash: 48a229ceaefd4985c50990b14116b6d856af0985\n'
              'commit-date: 2026-09-01\nhost: aarch64-apple-darwin\nrelease: 1.98.1\nLLVM version: 22.1.8\n')
CARGO_VERSION='cargo 1.98.1 (797e8a9bc 2026-08-05)'
OPENSSL_VERSION='3.6.5'
NATIVE_ENV_KEYS=('PATH','HOME','TMPDIR','DEVELOPER_DIR','LANG','LC_ALL','LC_CTYPE','USER','LOGNAME','SHELL')
HOST_OPENSSL_OVERRIDES=('OPENSSL_DIR','OPENSSL_INCLUDE_DIR','OPENSSL_LIB_DIR','PKG_CONFIG_PATH','PKG_CONFIG_LIBDIR')
def native_environment(work,base):
    """Allow only ordinary host context, then explicitly set owned build state."""
    env={k:base[k] for k in NATIVE_ENV_KEYS if k in base}
    require(env.get('PATH') and env.get('HOME') and env.get('DEVELOPER_DIR')==TOOLCHAIN['developer_dir'],
            'actual host PATH/HOME and reviewed Xcode selection required')
    env.update(CARGO_HOME=str(work/'cargo-home'),CARGO_TARGET_DIR=str(work/'cargo-target'),
               CARGO_INSTALL_ROOT=str(work/'cargo-tools'),RUSTUP_HOME=str(work/'rustup-home'),
               RUSTUP_TOOLCHAIN=RUST_TOOLCHAIN,HOMEBREW_NO_AUTO_UPDATE='1',PYTHONDONTWRITEBYTECODE='1')
    return env
def rust_command(rustup,tool,*args):
    require(tool in ('cargo','rustc'),'unsupported fixed Rust command family')
    return [rustup,'run',RUST_TOOLCHAIN,tool,*args]
def cargo_metadata_command(rustup,idevice):
    return rust_command(rustup,'cargo','metadata','--format-version','1','--locked','--offline',
                        '--manifest-path',idevice/'ffi/Cargo.toml','--features','obfuscate',
                        '--filter-platform','aarch64-apple-ios')
def tool_resolution(path):
    """Observe all symlink hops without changing the selected invocation path."""
    path=Path(path)
    require(path.is_absolute() and '..' not in path.parts,'absolute unambiguous native invocation path required')
    pending=list(path.parts[1:]);current=Path('/');links=[]
    while pending:
        part=pending.pop(0)
        if part in ('','.'):continue
        if part=='..':current=current.parent;continue
        candidate=current/part;mode=candidate.lstat().st_mode
        if stat.S_ISLNK(mode):
            target=os.readlink(candidate)
            require(target and len(target)<=4096 and len(links)<40,'invalid or cyclic native tool symlink chain')
            links.append({'path':str(candidate),'target':target})
            if target.startswith('/'):current=Path('/')
            pending=target.split('/')+pending
        else:
            require(stat.S_ISDIR(mode) if pending else stat.S_ISREG(mode),'native invocation resolves through non-directory or non-file')
            current=candidate
    return current,links

def native_tool(path):
    """Keep argv[0] semantics; attest resolved bytes and each observed symlink."""
    selected=Path(path);resolved,links=tool_resolution(selected)
    cargo_proof.ordinary(resolved)
    require(os.access(selected,os.X_OK),'native tool is not executable')
    raw=resolved.read_bytes()
    require(tool_resolution(selected)==(resolved,links),'native invocation retargeted during observation')
    return {'path':str(selected),'resolved_path':str(resolved),'symlink_chain':links,'sha256':sha(raw)}

def app_base(root,work):return ['-project',root/'AltStore.xcodeproj','-scheme','SideStore','-clonedSourcePackagesDirPath',work/'sidestore-packages','-derivedDataPath',work/'sidestore-derived','-disablePackageRepositoryCache']
def app_commands(roots,work):
    base=app_base(roots['SideStore'],work)
    return [
      ('sidestore-resolve',['xcodebuild','-resolvePackageDependencies',*base]),
      ('sidestore-frozen-resolve',['xcodebuild','-resolvePackageDependencies',*base,'-onlyUsePackageVersionsFromResolvedFile']),
      ('sidestore-build',['xcodebuild',*base,'-onlyUsePackageVersionsFromResolvedFile','-disableAutomaticPackageResolution',*SETTINGS]),
      ('livecontainer-build',['xcodebuild','-project',roots['LiveContainer']/'LiveContainer.xcodeproj','-scheme','LiveContainer','-derivedDataPath',work/'livecontainer-derived',*SETTINGS])]
def file_inventory(root):
    require(root.is_dir() and not root.is_symlink(),'ordinary output directory required');result={}
    for p in sorted(root.rglob('*')):
        name=str(p.relative_to(root))
        if p.is_symlink():
            target=os.readlink(p);require(not Path(target).is_absolute() and root.resolve() in p.resolve().parents,'output symlink escapes product')
            result[name]={'kind':'symlink','target':target}
        elif p.is_file():result[name]={'kind':'file','bytes':p.stat().st_size,'sha256':sha(p.read_bytes())}
    require(result,'empty output product');return result
class NativeBuildMixin:
    def verify_native_tools(self):
        if getattr(self,'native_tools',None):
            require({name:native_tool(row['path']) for name,row in self.native_tools.items()}==self.native_tools,
                    'native invocation path, symlink chain or executable bytes changed')
    def native_run(self,name,args,**kwargs):
        # Bounded re-observation before and after each owned native command. This
        # detects substitutions at these checkpoints; it is not an atomic exec seal.
        self.verify_native_tools()
        result=self.run(name,args,**kwargs)
        self.verify_native_tools()
        return result
    def check_cargo_storage(self,*,before_setup=False):
        require(not any(key in self.native_env for key in HOST_OPENSSL_OVERRIDES),
                'macOS OpenSSL/pkg-config overrides must not enter the iOS transport environment')
        return cargo_proof.validate_cargo_home(self.work/'cargo-home',self.work/'cargo-target',self.work/'cargo-tools',
                 rustup_home=self.work/'rustup-home',cwd=self.work,env=self.native_env,before_setup=before_setup)
    def native_prerequisites(self):
        # Every external action uses the owned, bounded runner, including setup.
        self.native_env=native_environment(self.work,getattr(self,'base_env',os.environ))
        dump(self.evidence/'provenance/cargo-storage-fresh.json',self.check_cargo_storage(before_setup=True))
        for name in ('cargo-home','cargo-target','cargo-tools','rustup-home'):(self.work/name).mkdir()
        self.native_tools={}
        for name in ('rustup','brew'):
            selected=shutil.which(name,path=self.native_env['PATH']);require(selected,'required host tool absent: '+name)
            self.native_tools[name]=native_tool(selected)
        self.rustup=Path(self.native_tools['rustup']['path']);brew=Path(self.native_tools['brew']['path'])
        dump(self.evidence/'provenance/native-bootstrap-tools.json',self.native_tools)
        self.native_run('rust-toolchain-install',[self.rustup,'toolchain','install',RUST_TOOLCHAIN,'--profile','minimal','--no-self-update'],
                 cwd=self.work,env=self.native_env,timeout=1200)
        rustup_version=self.native_run('rustup-version',[self.rustup,'--version'],cwd=self.work,env=self.native_env,stdout_only=True)
        for name in ('cargo','rustc'):
            path=self.native_run(name+'-path',[self.rustup,'which','--toolchain',RUST_TOOLCHAIN,name],cwd=self.work,env=self.native_env,stdout_only=True).strip()
            expected=self.work/'rustup-home/toolchains'/RUST_TOOLCHAIN/'bin'/name
            require(Path(path)==expected,'Rust binary escaped isolated exact toolchain')
            self.native_tools[name]=native_tool(path)
        toolbin=self.work/'rustup-home/toolchains'/RUST_TOOLCHAIN/'bin'
        self.native_env['PATH']=os.pathsep.join((str(self.work/'cargo-tools/bin'),str(toolbin),self.native_env['PATH']))
        rustc=self.native_run('rustc-version',rust_command(self.rustup,'rustc','-Vv'),cwd=self.work,env=self.native_env,stdout_only=True)
        cargo=self.native_run('cargo-version',rust_command(self.rustup,'cargo','-Vv'),cwd=self.work,env=self.native_env,stdout_only=True)
        require(rustc==RUSTC_VERBOSE,'exact historical Rust compiler identity differs')
        require(cargo.splitlines() and cargo.splitlines()[0]==CARGO_VERSION,'exact historical Cargo version differs')
        dump(self.evidence/'provenance/rust-toolchain.json',{'toolchain':RUST_TOOLCHAIN,'rustup_version':rustup_version,
             'rustc_verbose':rustc,'cargo_verbose':cargo,'cargo_reviewed_identity':CARGO_VERSION,
             'cargo_remaining_verbose_fields':'observed in this run; no historical byte-equivalence claim','binaries':self.native_tools})
        self.native_run('rust-target',[self.rustup,'target','add','--toolchain',RUST_TOOLCHAIN,'aarch64-apple-ios'],cwd=self.work,env=self.native_env,timeout=1200)
        self.check_cargo_storage()
        self.native_run('bindgen-prerequisite',rust_command(self.rustup,'cargo','install','--locked','--root',self.work/'cargo-tools',
                 'bindgen-cli','--version','0.72.1'),cwd=self.work,env=self.native_env,timeout=1200)
        bindgen=self.work/'cargo-tools/bin/bindgen'
        self.native_tools['bindgen']=native_tool(bindgen)
        version=self.native_run('bindgen-version',[bindgen,'--version'],cwd=self.work,env=self.native_env,stdout_only=True)
        require(version.strip()==TOOLCHAIN['bindgen'],'bindgen version differs')
        self.bindgen_provenance=cargo_proof.verify_bindgen_install(self.work/'cargo-tools',version)
        dump(self.evidence/'provenance/bindgen-install.json',self.bindgen_provenance)
        self.native_run('openssl-prerequisite',[brew,'install','openssl@3'],cwd=self.work,env=self.native_env,timeout=1200)
        info=self.native_run('openssl-info',[brew,'info','--json=v2','openssl@3'],cwd=self.work,env=self.native_env,stdout_only=True)
        prefix=self.native_run('openssl-prefix',[brew,'--prefix','openssl@3'],cwd=self.work,env=self.native_env,stdout_only=True).strip()
        openssl=Path(prefix)/'bin/openssl'
        self.native_tools['openssl']=native_tool(openssl)
        version=self.native_run('openssl-version',[openssl,'version','-a'],cwd=self.work,env=self.native_env,stdout_only=True)
        self.openssl_provenance=cargo_proof.verify_openssl_provenance(info,prefix,version,expected_version=OPENSSL_VERSION)
        cellar=Path(self.openssl_provenance['real_prefix'])
        for path in (cellar/'include',cellar/'lib',cellar/'lib/pkgconfig'):cargo_proof.ordinary(path,directory=True)
        # This Homebrew installation contains host macOS libraries. The exact
        # ffi defaults use aws-lc; do not redirect aarch64-apple-ios discovery to
        # this Cellar with unqualified OpenSSL/pkg-config variables. The prior
        # successful transport command did not introduce those overrides.
        self.openssl_provenance.update(role='host prerequisite inventory only',target_environment={},
             target_library_compatibility_verified=False,target_library_consumption_claimed=False)
        dump(self.evidence/'provenance/openssl.json',self.openssl_provenance)
        dump(self.evidence/'provenance/native-tools-before.json',self.native_tools)
        dump(self.evidence/'provenance/cargo-storage-after-setup.json',self.check_cargo_storage())
    def capture_cargo_metadata(self,when,before=None):
        require(when in ('before','after'),'finite Cargo metadata checkpoint required')
        self.check_cargo_storage()
        raw=self.native_run('cargo-metadata-'+when,cargo_metadata_command(self.rustup,self.roots['idevice']),
                     cwd=self.work,env=self.native_env,stdout_only=True)
        (self.evidence/('provenance/Cargo.metadata.'+when+'.json')).write_text(raw)
        snapshots={}
        try:
            proof=cargo_proof.verify_cargo_metadata(raw,self.roots,self.work/'cargo-home',self.work/'cargo-target',
                phase=when,before=before,generated_snapshots=snapshots)
        except cargo_proof.RegistrySourceMismatch as error:
            dump(self.evidence/('provenance/cargo-registry-mismatch-'+when+'.json'),error.diagnostic)
            raise
        finally:
            if snapshots:
                require(when=='after' and set(snapshots)=={cargo_proof.PLIST_SNAPSHOT_KEY},'finite generated-header evidence required')
                snapshot=snapshots[cargo_proof.PLIST_SNAPSHOT_KEY]
                require(0<len(snapshot)<=cargo_proof.PLIST_GENERATED_MAX_BYTES,'bounded generated-header evidence required')
                # The immutable byte snapshot already supplied the inventory
                # hash. Never reread the registry path for evidence retention.
                output=self.evidence/'provenance/plist_ffi.generated.plist.h'
                require(not output.exists() and not output.is_symlink(),'fresh generated-header evidence required')
                output.write_bytes(snapshot)
        dump(self.evidence/('provenance/cargo-resolved-'+when+'.json'),proof)
        return proof
    def transport_build(self):
        idevice=self.roots['idevice'];mini=self.roots['minimuxer'];cargo=self.work/'cargo-target'
        self.check_cargo_storage()
        dump(self.evidence/'provenance/cargo-inputs-before-fetch.json',cargo_proof.source_inputs(self.roots))
        sdk_output=self.native_run('iphoneos-sdk-path',['xcrun','--sdk','iphoneos','--show-sdk-path'],cwd=self.work,env=self.native_env,stdout_only=True).strip()
        require(Path(sdk_output).is_absolute(),'actual absolute SDK path required')
        sdk=cargo_proof.ordinary(Path(sdk_output).resolve(strict=True),directory=True)
        require(sdk.is_relative_to(Path(TOOLCHAIN['developer_dir'])),'actual SDK is outside selected Xcode')
        dump(self.evidence/'provenance/iphoneos-sdk.json',{'xcrun_path':sdk_output,'resolved_path':str(sdk)})
        self.native_env.update(IPHONEOS_DEPLOYMENT_TARGET='15.0',BINDGEN_EXTRA_CLANG_ARGS='--sysroot='+str(sdk))
        for relative in ('ffi/idevice.h','cpp/include/idevice.h','swift/include/idevice.h','swift/IDevice.xcframework'):
            path=idevice/relative;require(not path.exists() and not path.is_symlink(),'generated transport output must be fresh')
        lib=cargo/'aarch64-apple-ios/release/libidevice_ffi.a';require(not lib.exists() and not lib.is_symlink(),'transport library must be fresh')
        self.native_run('idevice-fetch',rust_command(self.rustup,'cargo','fetch','--locked','--manifest-path',idevice/'ffi/Cargo.toml'),env=self.native_env,cwd=self.work)
        before=self.capture_cargo_metadata('before')
        build_command=rust_command(self.rustup,'cargo','build','--frozen','--release','--target','aarch64-apple-ios',
                 '--features','obfuscate','--manifest-path',idevice/'ffi/Cargo.toml','--verbose')
        self.native_run('idevice-build',build_command,env=self.native_env,cwd=self.work)
        execution=cargo_proof.verify_generated_build_receipt(
            (self.evidence/'logs/idevice-build.command.json').read_bytes(),
            (self.evidence/'logs/idevice-build.settlement.json').read_bytes(),
            (self.evidence/'logs/idevice-build.exit-code.txt').read_bytes(),build_command,self.work)
        after=self.capture_cargo_metadata('after',before)
        transition=cargo_proof.verify_generated_transition(before,after,execution)
        dump(self.evidence/'provenance/cargo-generated-transition.json',transition)
        self.cargo_expected=after
        lib=cargo/'aarch64-apple-ios/release/libidevice_ffi.a';require(lib.is_file() and not lib.is_symlink(),'actual transport library absent')
        header=idevice/'ffi/idevice.h';require(header.is_file() and not header.is_symlink() and header.stat().st_size>0,'actual generated header absent')
        cpp=cargo_proof.ordinary(idevice/'cpp/include/idevice.h');require(cpp.read_bytes()==header.read_bytes(),'generated C/C++ headers differ')
        shutil.copyfile(header,idevice/'swift/include/idevice.h')
        require((idevice/'swift/include/idevice.h').read_bytes()==header.read_bytes(),'staged Swift header differs')
        xc=idevice/'swift/IDevice.xcframework';require(not xc.exists(),'framework output must be fresh')
        self.native_run('idevice-xcframework',['xcodebuild','-create-xcframework','-library',lib,'-headers',idevice/'swift/include','-output',xc],cwd=self.work,env=self.native_env)
        staged=mini/'DeviceGateway/LocalBinary/IDevice.xcframework';staged.parent.mkdir(parents=True,exist_ok=True);require(not staged.exists(),'staged framework must be fresh');shutil.copytree(xc,staged)
        expected=file_inventory(xc);require(file_inventory(staged)==expected,'staged transport differs')
        self.transport_expected=expected;self.transport_source=xc;self.transport_staged=staged
        dump(self.evidence/'provenance/transport.json',{'library_sha256':sha(lib.read_bytes()),'header_sha256':sha(header.read_bytes()),'framework':expected})
        require({name:native_tool(row['path']) for name,row in self.native_tools.items()}==self.native_tools,'native tool binary changed during transport build')
        dump(self.evidence/'provenance/native-tools-after.json',self.native_tools)
        dump(self.evidence/'provenance/cargo-storage-after-build.json',self.check_cargo_storage())
    def resolved_app_graph(self):
        packages=self.work/'sidestore-packages';states=list(packages.rglob('workspace-state.json'));require(len(states)==1,'one actual app workspace state required')
        local={'sidesign':self.roots['SideSign'],'minimuxer':self.roots['minimuxer'],'common':self.roots['minimuxer']/'Common','devicegateway':self.roots['minimuxer']/'DeviceGateway'}
        graph=primitives.verify_resolution(self.roots,states[0],self.roots['SideStore']/LOCK,local)
        expected=self.data['graph']['owners']['AnisetteKit'];require(graph['anisettekit']['commit']==expected['commit'] and graph['anisettekit']['tree']==expected['tree'],'actual app AK source differs')
        return graph
    def capture_sidestore_openssl(self,when,resolved,*,download=False):
        """Bind the exact separately sourced SideStore binary artifact, never execute it."""
        import openssl_artifact_contract as openssl
        require(when in ('before','after'),'finite OpenSSL artifact checkpoint required')
        packages=self.work/'sidestore-packages'
        states=list(packages.rglob('workspace-state.json'));require(len(states)==1,'one actual app workspace state required')
        try:
            state=openssl.snapshot_workspace_state(states[0])
            (self.evidence/('provenance/SideStore.workspace-state.'+when+'.json')).write_bytes(state)
            archive=self.evidence/'provenance/SideStore.OpenSSL.source.zip'
            if download:
                require(when=='before' and not archive.exists() and not archive.is_symlink(),'fresh reviewed OpenSSL archive required')
                self.run('sidestore-openssl-archive',['/usr/bin/curl','--fail','--location','--silent','--show-error',
                    '--proto','=https','--proto-redir','=https','--max-time','300','--max-filesize',str(openssl.ARCHIVE_BYTES),
                    '--output',archive,openssl.ARCHIVE_URL],cwd=self.work,timeout=330)
            proof=openssl.verify_sidestore_openssl(packages/'checkouts/RemotePairingKit',resolved['remotepairingkit'],state,packages,archive)
        except openssl.OpenSSLArtifactError as error:
            dump(self.evidence/('provenance/SideStore.OpenSSL.failure-'+when+'.json'),error.diagnostic)
            raise
        dump(self.evidence/('provenance/SideStore.OpenSSL.source-'+when+'.json'),proof)
        return proof
    def app_build(self):
        root=self.roots['SideStore'];lock=root/LOCK;before=lock.read_bytes();commands=app_commands(self.roots,self.work)
        (self.evidence/'provenance/SideStore.Package.resolved.before').write_bytes(before)
        self.run(*commands[0],cwd=self.work);after=lock.read_bytes();self.observed_app_lock=after
        (self.evidence/'provenance/SideStore.Package.resolved.after').write_bytes(after)
        checked=check_lock(before,after,self.data['graph']['owners']['AnisetteKit']['commit'])
        self.run(*commands[1],cwd=self.work);require(lock.read_bytes()==after,'frozen app resolve changed lock')
        resolved_before=self.resolved_app_graph();dump(self.evidence/'provenance/app-resolved-before-build.json',resolved_before)
        self.capture_sidestore_openssl('before',resolved_before,download=True)
        self.verify_working_sources(after_build=True)
        for command in commands[2:]:self.run(*command,cwd=self.work)
        from macho_contract import inspect_app,inspect_internal_ipa,capture_app_inventory,ProductValidationError
        products={};machos={}
        try:
            # Persist both whole-product hash inventories before semantic checks.
            # An early SideStore failure must not hide the later LC inventory.
            for owner,folder in (('SideStore','sidestore-derived'),('LiveContainer','livecontainer-derived')):
                app=self.work/folder/'Build/Products/Release-iphoneos'/(owner+'.app')
                snapshot=capture_app_inventory(app,owner)
                dump(self.evidence/('provenance/product-inventory-'+owner+'.json'),snapshot)
                require(snapshot['complete'],'complete bounded product inventory required')
                products[owner]=snapshot['inventory']
            require(lock.read_bytes()==after,'app build changed genuine resolver lock')
            resolved_after=self.resolved_app_graph();dump(self.evidence/'provenance/app-resolved-after-build.json',resolved_after)
            openssl_proof=self.capture_sidestore_openssl('after',resolved_after)
            require(file_inventory(self.transport_source)==self.transport_expected==file_inventory(self.transport_staged),'native transport mutated during app build')
            for owner,folder in (('SideStore','sidestore-derived'),('LiveContainer','livecontainer-derived')):
                app=self.work/folder/'Build/Products/Release-iphoneos'/(owner+'.app')
                def retain_snapshot(value,owner=owner):
                    dump(self.evidence/('provenance/product-inspection-snapshot-'+owner+'.json'),value)
                    require(value.get('complete') is True and value.get('inventory')==products[owner],'product changed before static inspection')
                machos[owner]=inspect_app(app,allow_pinned_prebuilt=owner=='LiveContainer',owner=owner,
                    sidestore_openssl_proof=openssl_proof if owner=='SideStore' else None,on_inventory=retain_snapshot)
                require(products[owner]==machos[owner]['product']['inventory'],'product bytes changed during Mach-O inspection')
                dump(self.evidence/('provenance/macho-product-'+owner+'.json'),machos[owner])
            backup=root/'build/SideBackup.ipa';require(backup.is_file() and not backup.is_symlink(),'normal internal SideBackup archive resource absent')
            embedded=self.work/'sidestore-derived/Build/Products/Release-iphoneos/SideStore.app/SideBackup.ipa'
            require(embedded.is_file() and not embedded.is_symlink() and embedded.read_bytes()==backup.read_bytes(),'embedded SideBackup resource differs from actual internal build output')
            backup_proof=inspect_internal_ipa(backup,on_inventory=lambda value:dump(self.evidence/'provenance/product-inventory-SideBackup.json',value))
            dump(self.evidence/'provenance/macho-products.json',machos)
            # Preserve the historical successful aggregate inventory schema.
            dump(self.evidence/'provenance/unsigned-products.json',{owner:{name:{'kind':'file',**row} for name,row in rows.items()} for owner,rows in products.items()})
            dump(self.evidence/'provenance/internal-sidebackup-resource.json',{'path':'SideStore/build/SideBackup.ipa',**backup_proof})
        except ProductValidationError as error:
            dump(self.evidence/'provenance/product-static-failure.json',error.diagnostic)
            raise
        self.app_product_checks_complete=True
        self.state.update(new_app_executables_unsigned=True,inherited_prebuilt_signatures_separately_inventoried=True,internal_sidebackup_archive_built=True,distribution_ipa_built=False,resolved_app_lock=checked)
