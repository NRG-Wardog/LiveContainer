"""Actual raw source/compiler/product checkpoints with one aggregate budget."""
import os,sys,shutil
from pathlib import Path
from inventory import dump,parse,ordinary,git,sha,require,TOOLCHAIN
from retention import RawStore,BOUNDS
from native_build import LOCK,RUST_TOOLCHAIN
import graph_contract as graph


class CaptureRetentionMixin:
    def save(self,label,value):dump(self.evidence/('provenance/'+label+'.json'),value)

    def merge_nested_budget(self,summary):
        fields={'logical_files':'file_count','logical_bytes':'total_bytes','directories':'directory_count'}
        limits={'logical_files':'files','logical_bytes':'total_bytes','directories':'directories'}
        for key,attribute in fields.items():
            value=summary.get(key);require(type(value) is int and value>=0,'invalid nested retention budget')
            require(getattr(self.store,attribute)+value<=BOUNDS[limits[key]],'aggregate nested/product retention ceiling exceeded')
        for key,attribute in fields.items():setattr(self.store,attribute,getattr(self.store,attribute)+summary[key])

    def retained_sources(self,phase,after_build=False):
        proof=self.verify_working_sources(after_build=after_build)
        for name,row in self.data['graph']['owners'].items():
            root=self.roots[name]
            prefix=next((path for path,owner in graph.OWNER_CHILDREN.items() if owner==name),name)
            allowed={path[len(prefix)+1:]:value['commit'] for path,value in graph.child_requirements(prefix,root,row['commit'],self.data['graph']).items()}
            proof['owners'][name]['raw_tree']=self.store.retain_git_tree(root,row['commit'],label=phase+'/'+name,approved_gitlinks=allowed)
            proof['owners'][name]['raw_identity_objects']={}
            revisions={row['base'],row['commit']}
            if name=='SideSign':
                edge=self.data['graph']['sidesign_edges']['resolver_lock']
                revisions.add(edge['commit'])
                from integrity_source import retain_lock_child_tree
                proof['owners'][name]['raw_resolver_lock_child_tree']=retain_lock_child_tree(self.store,root,edge['commit'],row['commit'],label=phase+'/'+name+'-resolver-lock-child')
            for revision in revisions:
                for kind,raw in [('commit',git(root,'cat-file','commit',revision)),('tree-listing',git(root,'ls-tree','-rz',revision))]:
                    proof['owners'][name]['raw_identity_objects'][revision+'/'+kind]=self.store.retain_bytes(raw,label=phase+'/'+name+'/'+revision+'/'+kind)
            lock=root/('Package.resolved' if name=='SideSign' else LOCK if name=='SideStore' else '__no_lock__')
            if lock.exists():proof['owners'][name]['actual_lock']=self.store.retain_file(lock,label=phase+'/'+name+'/actual-lock')
        for path,row in self.data['graph']['children'].items():
            if path in graph.OWNER_CHILDREN:continue
            proof['children'][path]['raw_tree']=self.store.retain_git_tree(self.children[path],row['commit'],label=phase+'/'+path)
            proof['children'][path]['raw_commit']=self.store.retain_bytes(git(self.children[path],'cat-file','commit',row['commit']),label=phase+'/'+path+'/commit')
        self.save('source-'+phase,proof);return proof

    def retained_app_dependencies(self,phase,resolved):
        packages=self.work/'sidestore-packages'
        states=list(packages.rglob('workspace-state.json'));require(len(states)==1,'one actual Xcode workspace state required')
        state=states[0];raw=ordinary(state.parent,state.name).read_bytes();require(len(raw)<=4*1024*1024,'bounded workspace state required')
        self.save(phase+'/app-workspace-state',self.store.retain_bytes(raw,label=phase+'/workspace-state'))
        obj=parse(raw)['object'];proof={}
        for row in obj['dependencies']:
            identity=row['packageRef']['identity'].lower()
            if row['packageRef']['kind']=='fileSystem':continue
            checkout=state.parent/'checkouts'/row['subpath'];record=resolved[identity]
            require(checkout.resolve().is_relative_to((state.parent/'checkouts').resolve()),'escaped dependency source')
            proof[identity]={'identity':record,'raw_tree':self.store.retain_git_tree(checkout,record['commit'],label=phase+'/app-checkouts/'+identity),
                'raw_commit':self.store.retain_bytes(git(checkout,'cat-file','commit',record['commit']),label=phase+'/app-checkouts/'+identity+'/commit')}
        artifacts=packages/'artifacts'
        if artifacts.exists():proof['binary_artifacts']={'raw_tree':self.store.retain_tree(artifacts,label=phase+'/app-binary-artifacts')}
        self.save(phase+'/app-dependencies-raw',proof)
        return resolved

    def capture_generated(self,phase):
        result={}
        for name in ('cargo-target','sidestore-derived','livecontainer-derived'):
            root=self.work/name
            if root.exists():result[name]=self.store.retain_tree(root,label=phase+'/'+name)
        for owner,relative in (('idevice','ffi/idevice.h'),('idevice','cpp/include/idevice.h'),('idevice','swift/include/idevice.h'),('idevice','swift/IDevice.xcframework'),('minimuxer','DeviceGateway/LocalBinary/IDevice.xcframework'),('SideStore','build/sidebackup.xcarchive'),('SideStore','build/SideBackup.ipa')):
            root=self.roots.get(owner)
            if root is None:continue
            path=root/relative
            if path.exists():
                require(not path.is_symlink(),'linked generated product root')
                key=owner+'/'+relative
                result[key]=self.store.retain_tree(path,label=phase+'/'+key) if path.is_dir() else self.store.retain_file(path,label=phase+'/'+key)
        self.save(phase+'/generated-inputs-and-products',result)
        return result

    def capture_cargo_raw(self,phase):
        root=self.work/'cargo-home/registry';rows={}
        # The exact package proof authenticates archive checksums/source inventories.
        # Retain both archive bytes and extracted compiler inputs, excluding indexes.
        for name in ('cache','src'):
            path=root/name
            require(path.is_dir() and not path.is_symlink(),'actual Cargo '+name+' missing')
            rows[name]=self.store.retain_tree(path,label=phase+'/cargo-registry/'+name)
        self.save(phase+'/cargo-registry-raw',rows)

    def capture_native_inputs(self,phase):
        rows={}
        for name,path in (('rust-toolchain',self.work/'rustup-home/toolchains'/RUST_TOOLCHAIN),
                          ('installed-bindgen',self.work/'cargo-tools')):
            require(path.is_dir() and not path.is_symlink(),'actual native compiler/runtime tree missing')
            rows[name]=self.store.retain_tree(path,label=phase+'/'+name)
        if hasattr(self,'openssl_provenance'):
            path=Path(self.openssl_provenance['real_prefix'])
            require(path.is_relative_to(Path('/opt/homebrew/Cellar')),'unreviewed host OpenSSL prefix')
            rows['host-openssl-prerequisite']=self.store.retain_tree(path,label=phase+'/host-openssl-prerequisite')
        self.save(phase+'/native-compiler-runtime-inputs',rows)
        def stable(value):
            if isinstance(value,dict):return {key:stable(item) for key,item in value.items() if key!='label'}
            if isinstance(value,list):return [stable(item) for item in value]
            return value
        identity=stable(rows)
        if hasattr(self,'native_input_identities'):require(identity==self.native_input_identities,'native compiler/runtime input tree changed')
        else:self.native_input_identities=identity
        return rows

    def capture_toolchain(self,phase,include_sdk=False):
        paths={}
        names=('swift','swiftc','swift-frontend','swift-symbolgraph-extract','clang','clang++','ld','ar','dsymutil','git','xcodebuild')
        for name in names:
            path=Path(self.run('tool-'+phase+'-'+name.replace('+','x'),['xcrun','--find',name],cwd=self.work,stdout_only=True,timeout=120).strip())
            require(path.is_absolute(),'actual absolute compiler tool path required')
            paths[name]=self.store.retain_executable(path,label=phase+'/tools/'+name,approved_roots=[Path(TOOLCHAIN['developer_dir']),Path('/usr/bin')])
        for name in ('python3','git','xcodebuild','swift','swiftc','xcrun','sandbox-exec','curl','c++'):
            selected=sys.executable if name=='python3' else shutil.which(name,path=self.base_env['PATH'])
            require(selected,'actual launcher missing: '+name)
            roots=[Path(TOOLCHAIN['developer_dir']),Path('/usr/bin'),Path('/opt/homebrew'),Path('/Library/Frameworks'),self.work]
            roots=[root for root in roots if root.is_dir() and not root.is_symlink()]
            paths['launcher-'+name]=self.store.retain_executable(Path(selected),label=phase+'/launchers/'+name,approved_roots=roots)
        for name,row in getattr(self,'native_tools',{}).items():
            path=Path(row['path']);paths['native-'+name]=self.store.retain_executable(path,label=phase+'/native-tools/'+name,approved_roots=[root for root in (Path('/opt/homebrew'),Path('/Users/runner/.cargo'),self.work) if root.is_dir() and not root.is_symlink()])
        self.save('tool-identities-'+phase,paths)
        if include_sdk:
            for sdk_name in ('macosx','iphoneos'):
                raw=self.run('sdk-'+phase+'-'+sdk_name,['xcrun','--sdk',sdk_name,'--show-sdk-path'],cwd=self.work,stdout_only=True,timeout=120).strip()
                sdk=Path(raw).resolve(strict=True);require(sdk.is_relative_to(Path(TOOLCHAIN['developer_dir'])),'SDK outside selected Xcode')
                record=self.store.retain_tree(sdk,label=phase+'/'+sdk_name+'-sdk')
                self.save(phase+'/'+sdk_name+'-sdk-raw',record)
                stable=lambda value: {key:stable(item) for key,item in value.items() if key!='label'} if isinstance(value,dict) else [stable(item) for item in value] if isinstance(value,list) else value
                if not hasattr(self,'sdk_identities'):self.sdk_identities={}
                if sdk_name in self.sdk_identities:require(stable(record)==self.sdk_identities[sdk_name],'selected SDK bytes or modes changed')
                else:self.sdk_identities[sdk_name]=stable(record)
        return paths
