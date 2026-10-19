#!/usr/bin/env python3
"""Reproduce a proposal only from original receipts and actual immutable objects.
No new commit, lockfile, retrieval or native command is created by this tool.
"""
import argparse
from pathlib import Path
from inventory import *
import graph_contract as graph
import prior_phase_a as prior

def prepare(host,trees,bindings=None,descendant_trees=None):
    guard=ordinary_build_guard(host)
    require(guard['before_sha256']==sha(git(trees/'LiveContainer','show',SOURCE_LC+':'+BUILD_WORKFLOW_PATH)),'ordinary workflow before bytes differ')
    owners={owner:trees/owner for owner in graph.SOURCE_OWNERS}
    data=dict(schema_version=1,source_basis=BASIS,phase='phase-b',status='PREPARATION_ONLY',execution_review=None,
        source_seal_sha256=SEAL_SHA,publication_sha256=PUBLICATION_SHA,graph=graph.make_draft_graph(owners),prior_phase_a=prior.make_draft_prior(),
        adapter_files=adapter_inventory(host),toolchain=TOOLCHAIN,ordinary_build_guard=guard,workflow_template_sha256=sha(workflow_template(host,'0'*64)))
    if bindings is None:return data
    require(set(bindings)=={'prior_phase_a','descendants','descendant_clearance_sha256'},'exact explicit actual bindings required')
    require(descendant_trees is not None,'actual descendant object roots required')
    prior.validate_prior_inputs(bindings['prior_phase_a'],execution=True)
    sealed=host/'ci/p0loginb/prior_adapter';review_raw=ordinary(sealed,'independent-review.json').read_bytes()
    prior._validate_independent_review(review_raw,bindings['prior_phase_a'])
    require(sha(ordinary(sealed,'upload-identity.json').read_bytes())==bindings['prior_phase_a']['upload_identity_sha256'],'original upload bytes differ')
    clearance_raw=ordinary(sealed,'independent-descendant-clearance.json').read_bytes();clearance=parse(clearance_raw)
    require(sha(clearance_raw)==bindings['descendant_clearance_sha256'],'original descendant clearance bytes differ')
    require(clearance['schema']==1 and clearance['scope']=='SOURCE_ONLY_DESCENDANT_EQUIVALENCE' and clearance['phase_b_execution_approved'] is False and
        clearance['phase_a_review_sha256']==sha(review_raw),'descendant review scope differs')
    require(set(bindings['descendants'])=={'SideSign','SideStore'},'exact two descendants required')
    value=data['graph'];value['kind']='phase-b-graph-execution';value['prior_artifact']=bindings['prior_phase_a']['expected']
    for owner,bound in bindings['descendants'].items():
        require(set(bound)=={'commit','tree'} and bound=={'commit':clearance[owner]['published_commit'],'tree':clearance[owner]['tree']} and clearance[owner]['authenticated_readback'] is True,'descendant authenticated clearance differs')
        root=descendant_trees/owner;row=value['owners'][owner];actual=graph.snapshot(root,row['base'],bound['commit'],single_parent=True)
        require(actual['tree']==bound['tree'],'actual descendant tree differs')
        row.update(commit=bound['commit'],**actual)
    value['children']=graph.expected_children(value['owners'])
    sign=value['owners']['SideSign'];store=value['owners']['SideStore']
    value['final_sidesign']={'commit':sign['commit'],'tree':sign['tree'],'lock_sha256':sign['changes']['Package.resolved']['after']['sha256']}
    value['final_sidestore']={'commit':store['commit'],'tree':store['tree']}
    graph.validate_graph(value,execution=True)
    graph.verify_gitlink_descendant(descendant_trees/'SideStore',store['base'],store['commit'],graph.SOURCE_TUPLES['SideSign'][0],sign['commit'],expected_tree=store['tree'])
    # Original Phase A successful bytes were separately authenticated/replayed. The
    # descendant comparison repeats byte identity from actual objects, never writes it.
    actual_lock=git(descendant_trees/'SideSign','show',sign['commit']+':Package.resolved')
    require(sha(actual_lock)==bindings['prior_phase_a']['expected']['lock_sha256'],'actual descendant lock differs from reviewed artifact')
    graph.verify_lock_descendant(descendant_trees/'SideSign',sign['base'],sign['commit'],actual_lock,actual_lock,expected_tree=sign['tree'])
    data.update(status='BOUND_CAPTURE_PROPOSAL',prior_phase_a=bindings['prior_phase_a'])
    return data

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('host-root','trees','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--bindings',type=Path);p.add_argument('--descendant-trees',type=Path);a=p.parse_args()
    data=prepare(a.host_root.resolve(),a.trees.resolve(),parse(a.bindings.read_bytes()) if a.bindings else None,a.descendant_trees.resolve() if a.descendant_trees else None)
    dump(a.output,data);validate_inputs(a.output.read_bytes(),a.host_root.resolve());print('PROPOSAL_SHA256='+sha(a.output.read_bytes()))
