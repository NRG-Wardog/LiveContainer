"""Exact reviewed ten-path patch; a source edge distinct from the resolver edge.

The reviewed b28-based candidate is patch identity only. It is never substituted
for the future true lock-preserving child or treated as compiled evidence.
"""
import copy,re
from pathlib import Path
from inventory import ordinary,parse,sha,require,full_sha

BASE='b28fb0b72937849d4428e9ae313209b606f859b4'
CANDIDATE='aed9e5ff3fa9d8d88c51788e82af9d780a41cbb9'
CANDIDATE_TREE='e05139bb18388abbe659f99ae0391b80fc2d3ea0'
PATCH_MANIFEST_SHA256='79d95311c698542d5ed354ad560911b9890afcbb815b64a76f8593b81155b709'
PATCH_REVIEW_SHA256='661d9573cd73f55a8a83289836f69b6a016e6723502c6460c682b37c5d5815d1'
HERE=Path(__file__).resolve().parent
EDGE_KEYS={'parent','commit','tree','changes'}


def patch_manifest():
    raw=ordinary(HERE,'reviewed/SideSign.integrity-patch.json').read_bytes()
    require(sha(raw)==PATCH_MANIFEST_SHA256,'reviewed integrity patch manifest differs')
    value=parse(raw)
    require(value['base_commit']==BASE and value['candidate_commit']==CANDIDATE and value['candidate_tree']==CANDIDATE_TREE,'reviewed patch candidate identity differs')
    identity=ordinary(HERE,'reviewed/SideSign.integrity-patch.identity.json').read_bytes()
    require(sha(identity)==value['identity_receipt_sha256'],'original patch identity receipt differs')
    review_raw=ordinary(HERE,'reviewed/SideSign.integrity-patch.independent-review.json').read_bytes()
    require(sha(review_raw)==PATCH_REVIEW_SHA256,'original independent integrity patch review differs')
    review=parse(review_raw)
    require(review['verdict']=='SOURCE_REVIEW_PASS_RUNTIME_NOT_EXECUTED' and review['candidate']['commit']==CANDIDATE and review['candidate']['tree']==CANDIDATE_TREE and review['parent']==BASE,'independent patch review identity or scope differs')
    changes=value['changes']
    require(len(changes)==10 and not ({'Package.resolved','Package.swift'} & set(changes)),'source patch cannot change resolver lock or manifest')
    require({row['path'] for row in review['changed_paths']}==set(changes),'independent review path inventory differs')
    for row in review['changed_paths']:
        require(changes[row['path']]['after']=={'mode':row['mode'],'type':'blob','git_object':row['git_blob'],'sha256':row['sha256']},'independent review source bytes differ')
    return value


def pending_edges():
    return {'resolver_lock':{'parent':BASE,'commit':None,'tree':None,'changes':None},
            'integrity_source':{'parent':None,'commit':None,'tree':None,'changes':None}}


def validate_lock_delta(changes,lock_sha256):
    require(isinstance(changes,dict) and set(changes)=={'Package.resolved'},'SideSign resolver edge must remain lock-only')
    delta=changes['Package.resolved']
    require(isinstance(delta,dict) and set(delta)=={'before','after'},'lock delta schema differs')
    for value in delta.values():
        require(isinstance(value,dict) and set(value)=={'mode','type','git_object','sha256'} and value['mode']=='100644' and value['type']=='blob','lock delta mode/type differs')
        full_sha(value['git_object']);require(isinstance(value['sha256'],str) and re.fullmatch('[0-9a-f]{64}',value['sha256']) and value['sha256']!='0'*64,'actual lock digest required')
    require(delta['before']!=delta['after'] and delta['after']['sha256']==lock_sha256,'actual new resolver lock digest required')


def validate_edges(edges,owner,lock_sha256,draft=False):
    require(isinstance(edges,dict) and set(edges)=={'resolver_lock','integrity_source'},'both explicit SideSign edges required')
    if draft:
        require(edges==pending_edges(),'pending graph cannot invent resolver or integrity children')
        return
    for row in edges.values():
        require(isinstance(row,dict) and set(row)==EDGE_KEYS,'exact SideSign edge schema required')
        for key in ('parent','commit','tree'):full_sha(row[key])
        require(row['parent']!=row['commit'],'real new SideSign edge required')
    lock=edges['resolver_lock'];source=edges['integrity_source']
    require(lock['parent']==BASE and source['parent']==lock['commit'],'SideSign resolver then integrity ancestry differs')
    require(source['commit'] not in (BASE,lock['commit'],CANDIDATE),'integrity candidate cannot replace actual lock-preserving child')
    require((source['commit'],source['tree'])==(owner['commit'],owner['tree']),'compiled owner must be exact final integrity source child')
    validate_lock_delta(lock['changes'],lock_sha256)
    require(source['changes']==patch_manifest()['changes'],'integrity source edge differs from exact independently reviewed ten-path patch')
    require(owner['changes']=={**lock['changes'],**source['changes']},'SideSign owner changes must bind both exact edges')


def edge_record(proof):
    return {key:copy.deepcopy(proof[key]) for key in ('parent','commit','tree','changes')}


def retain_lock_child_tree(store,root,commit,current,*,label):
    """Retain the immutable intermediate without moving the final checkout HEAD.

    RawStore.retain_git_tree deliberately requires revision == HEAD. Keep that
    historical safety check intact and use its bounded blob reader for this
    explicit read-only, no-gitlink, verified sole-parent ancestor case instead.
    """
    from inventory import git,snapshot
    root=Path(root);full_sha(commit);full_sha(current)
    require(root.is_absolute() and root.is_dir() and root.resolve()==root,'canonical SideSign source root required')
    require(git(root,'rev-parse','--show-toplevel').decode().strip()==str(root),'exact SideSign checkout root required')
    require(git(root,'rev-parse','HEAD').decode().strip()==current,'final SideSign checkout HEAD differs')
    require(git(root,'rev-list','--parents','-n','1',commit).decode().split()==[commit,BASE],'intermediate must be direct sole-parent b28 child')
    require(git(root,'rev-list','--parents','-n','1',current).decode().split()==[current,commit],'final source must be direct sole-parent intermediate child')
    require(set(snapshot(root,BASE,commit)['changes'])=={'Package.resolved'},'intermediate is not lock-only')
    require(snapshot(root,commit,current)['changes']==patch_manifest()['changes'],'final source patch differs before intermediate retention')
    tree=git(root,'rev-parse',commit+'^{tree}').decode().strip();full_sha(tree)
    listing=git(root,'ls-tree','-rzt','--full-tree',commit)
    require(len(listing)<=4*1024*1024 and listing.endswith(b'\0'),'bounded complete intermediate tree listing required')
    entries=[];directories=[];names=set();store._claim_directory()
    with store._git_batch(root) as process:
        for raw in listing.split(b'\0'):
            if not raw:continue
            require(len(names)<4096,'intermediate tree entry ceiling exceeded')
            header,path=raw.split(b'\t',1);mode,kind,oid=header.decode('ascii').split();name=path.decode('utf-8')
            require(name and not name.startswith('/') and '\\' not in name and all(part not in ('','.','..','.git') for part in name.split('/')) and name not in names,'unsafe or duplicate intermediate tree path')
            names.add(name);full_sha(oid)
            if mode=='040000':
                require(kind=='tree','intermediate directory object differs');store._claim_directory()
                directories.append({'path':name,'git_mode':mode,'git_tree_oid':oid});continue
            require(kind=='blob' and mode in ('100644','100755','120000'),'intermediate gitlink or special object forbidden')
            record=store._retain_git_blob(process,oid,label=label+':'+name,
                metadata={'kind':'symlink' if mode=='120000' else 'file','source_path':str(root/name),'mode':mode,'byte_source':'committed-git-object'})
            entries.append({'path':name,'git_mode':mode,'git_blob_oid':oid,**record})
    require(git(root,'rev-parse','HEAD').decode().strip()==current,'final SideSign checkout HEAD changed during ancestor retention')
    return {'label':label,'kind':'git-tree','source_path':str(root),'commit':commit,'tree':tree,'directories':directories,'entries':entries}
