"""Read-only exact descendant equivalence, after independent raw evidence replay.

These object proofs do not authenticate a supplied artifact or authorize a build.
They never manufacture Package.resolved or imply a final child was compiled.
"""
from inventory import git, snapshot, full_sha, require, check_lock, sha
from graph_contract import KNOWN, OLD_SIGN
APP_LOCK='AltStore.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved'


def direct(root, parent, commit, expected_tree):
    for value in (parent,commit,expected_tree):full_sha(value)
    require(commit!=parent,'real new descendant required')
    require(git(root,'rev-list','--parents','-n','1',commit).decode().split()==[commit,parent], 'exact direct sole-parent descendant required')
    result=snapshot(root,parent,commit)
    require(result['tree']==expected_tree,'descendant tree differs')
    return result


def observed_lock_child(root,parent,commit,tree,observed,terminal,path):
    require(isinstance(observed,bytes) and 0<len(observed)<=16*1024*1024 and observed==terminal,
            'genuine independently reviewed observed and terminal raw lock equality required')
    actual=direct(root,parent,commit,tree)
    require(set(actual['changes'])=={path},'lock child changed other source paths')
    change=actual['changes'][path]
    require(all(value and value['mode']=='100644' and value['type']=='blob' for value in change.values()),'lock mode/type differs')
    before=git(root,'cat-file','blob',change['before']['git_object'])
    after=git(root,'cat-file','blob',change['after']['git_object'])
    require(after==observed,'published lock blob differs from genuine observed bytes')
    check_lock(before,after,KNOWN['AnisetteKit'][0])
    return {'parent':parent,'commit':commit,'tree':tree,'lock_blob':change['after']['git_object'],
            'lock_sha256':sha(observed),'changes':actual['changes'],'compiled_final_commit':False}


def sidesign_child(root,commit,tree,observed,terminal):
    proof=observed_lock_child(root,KNOWN['SideSign'][0],commit,tree,observed,terminal,'Package.resolved')
    proof['equivalence']='Phase A manifest-only source parent plus genuine observed resolver lock'
    return proof


def sidesign_integrity_child(root,parent,commit,tree,observed,terminal):
    from integrity_source import patch_manifest,PATCH_REVIEW_SHA256
    require(isinstance(observed,bytes) and 0<len(observed)<=16*1024*1024 and observed==terminal,
            'genuine independently reviewed observed and terminal raw lock equality required')
    actual=direct(root,parent,commit,tree)
    require(actual['changes']==patch_manifest()['changes'],'integrity child exceeds independently reviewed source patch')
    before=git(root,'show',parent+':Package.resolved');after=git(root,'show',commit+':Package.resolved')
    require(before==after==observed,'integrity source child must retain exact genuine resolver lock')
    manifest=git(root,'show',KNOWN['SideSign'][0]+':Package.swift')
    require(git(root,'show',parent+':Package.swift')==git(root,'show',commit+':Package.swift')==manifest,'integrity source child must retain exact manifest')
    return {'parent':parent,'commit':commit,'tree':tree,'changes':actual['changes'],
            'lock_sha256':sha(observed),'independent_patch_review_sha256':PATCH_REVIEW_SHA256,
            'equivalence':'exact reviewed integrity source patch atop genuine resolver-lock-only child; unchanged lock',
            'compiled_final_commit':False}


def sidestore_capture_input(root,commit,tree,sign_commit):
    full_sha(sign_commit);parent=KNOWN['SideStore'][0]
    actual=direct(root,parent,commit,tree)
    expected={'Dependencies/SideSign':{'before':{'mode':'160000','type':'commit','git_object':OLD_SIGN},
              'after':{'mode':'160000','type':'commit','git_object':sign_commit}}}
    require(actual['changes']==expected,'Phase B SideStore input must change only exact SideSign gitlink')
    return {'parent':parent,'phase_b_tested_gitlink_commit':commit,'tree':tree,'changes':actual['changes'],
            'app_lock_input_unchanged':True,'compiled':False}


def sidestore_final_app_lock_child(root,tested_commit,final_commit,final_tree,observed,frozen,terminal):
    require(isinstance(frozen,bytes) and frozen==observed==terminal,'actual resolve/frozen-repeat/terminal locks must be byte-identical')
    proof=observed_lock_child(root,tested_commit,final_commit,final_tree,observed,terminal,APP_LOCK)
    proof.update(tested_commit=tested_commit,final_commit=final_commit,
                 equivalence='all tracked inputs identical except exact Phase B observed app lock',compiled_final_commit=False)
    return proof
