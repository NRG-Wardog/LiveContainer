#!/usr/bin/env python3
"""Prepare pending or truly bound capture inputs. Never approve or execute them."""
import argparse,json,shutil
from pathlib import Path
from inventory import dump,sha,parse,ordinary,require,TOOLCHAIN
from graph_contract import BASIS,observe_known_sources,execution_draft_graph,complete_graph
from execution_contract import INPUT_PATH,ADAPTER,CLAIMS,BOUNDS,files,workflow,descendants_draft,validate_inputs
from prior_phase_a import make_draft_prior,validate_prior_inputs,REVIEWED_PRIOR_FILES


def prepare(host,roots,*,bindings=None,observed=None,terminal=None,reviewed_dir=None):
    host=Path(host);observation=observe_known_sources(roots)
    dump(host/ADAPTER/'known-source-observation.json',observation)
    graph=execution_draft_graph();prior=make_draft_prior();descendants=descendants_draft();status='PENDING_GENUINE_CAPTURE_BINDINGS'
    if bindings is not None:
        require(set(bindings)=={'prior_phase_a','descendants'},'exact true evidence and descendant bindings required')
        require(observed is not None and terminal is not None and reviewed_dir is not None,'original Phase A observed/terminal locks and review receipts required')
        prior=bindings['prior_phase_a'];validate_prior_inputs(prior,execution=True)
        descendants=bindings['descendants'];graph=complete_graph(roots,{owner:descendants[owner] for owner in ('SideSign_lock','SideSign','SideStore')},observed,terminal)
        require(sha(observed)==prior['expected']['lock_sha256'],'bound lock bytes differ from genuine Phase A')
        target=host/ADAPTER/'reviewed';target.mkdir(exist_ok=True)
        names=(*REVIEWED_PRIOR_FILES,*descendants['receipt_sha256'])
        for name in names:
            source=ordinary(reviewed_dir,name);destination=target/name
            require(not destination.is_symlink(),'linked original receipt destination')
            if destination.exists():require(destination.read_bytes()==source.read_bytes(),'existing original receipt differs')
            else:shutil.copyfile(source,destination)
        require(sha((target/'upload-identity.json').read_bytes())==prior['upload_identity_sha256'] and sha((target/'independent-review.json').read_bytes())==prior['independent_review']['receipt_sha256'],'original Phase A review receipt digests differ')
        status='BOUND_CAPTURE_PROPOSAL'
    else:
        require(observed is terminal is reviewed_dir is None,'partial binding arguments forbidden')
    data={'schema_version':2,'basis':BASIS,'phase':'phase-b','status':status,'execution_review':None,'graph':graph,
          'prior_phase_a':prior,'descendants':descendants,'toolchain':TOOLCHAIN,'retention_bounds':BOUNDS,
          'adapter_files':files(host),'workflow':workflow(host)[0],'claims':CLAIMS,'compiled_final_commit':False}
    raw=(json.dumps(data,indent=2,sort_keys=True)+'\n').encode();validate_inputs(raw,host)
    (host/INPUT_PATH).write_bytes(raw)
    return {'status':status,'input_sha256':sha(raw),'complete_inputs':bindings is not None,'execution_admitted':False,'frozen_for_publication':False,'compiled_final_commit':False}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--host-root',type=Path,required=True)
    for owner in ('AnisetteKit','SideSign','SideStore','LiveContainer'):p.add_argument('--'+owner,type=Path,required=True)
    for name in ('bindings','observed-lock','terminal-lock','reviewed-dir'):p.add_argument('--'+name,type=Path)
    a=p.parse_args()
    try:
        print(json.dumps(prepare(a.host_root.resolve(),{owner:getattr(a,owner).resolve() for owner in ('AnisetteKit','SideSign','SideStore','LiveContainer')},
            bindings=parse(a.bindings.read_bytes()) if a.bindings else None,observed=a.observed_lock.read_bytes() if a.observed_lock else None,
            terminal=a.terminal_lock.read_bytes() if a.terminal_lock else None,reviewed_dir=a.reviewed_dir),sort_keys=True))
    except Exception as error:p.exit(2,'BLOCKED: '+str(error)+'\n')
if __name__=='__main__':main()
