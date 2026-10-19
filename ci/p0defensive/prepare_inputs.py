#!/usr/bin/env python3
"""Freeze local review inputs. Never approves, publishes, dispatches, or runs Swift."""
import argparse
from pathlib import Path
from inventory import *
from retention import BOUNDS

def prepare(host):
    here=host/'ci/p0defensive';publication=parse(ordinary(here,'publication.json').read_bytes())
    template,anchor=workflow_template(host)
    require(anchor=='REVIEW_REQUIRED','preparation cannot alter an activated review tuple')
    proposal=parse(ordinary(here,'reviewed/inventory.proposed.json').read_bytes())
    data={'schema':1,'basis':BASIS,'phase':'phase-a','source_seal_sha256':SEAL_SHA,'owners':publication['owners'],'host':publication['host'],'toolchain':TOOLCHAIN,'test_source_audit':proposal['swift_files'],'artifacts':parse(ordinary(here,'reviewed/artifacts.json').read_bytes()),'retention_bounds':BOUNDS,'command_counts':{'owner_acquisition':8,'package_resolve':4,'package_build':2,'test_discovery':2,'filtered_test_execution':2,'selected_tests':11,'synthetic_host_suites':4},'workflow_template_sha256':sha(template)}
    data['adapter_files']={str(p.relative_to(host)):sha(p.read_bytes()) for p in here.rglob('*') if p.is_file() and not p.is_symlink() and p.name!='inputs-phase-a.json' and '__pycache__' not in p.parts}
    dump(here/'inputs-phase-a.json',data)
    raw=ordinary(here,'inputs-phase-a.json').read_bytes();_,blockers=validate_inputs(raw,host)
    return {'input_sha256':sha(raw),'activation_anchor':'REVIEW_REQUIRED','pending':blockers}
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--host-root',type=Path,required=True);a=p.parse_args()
    print(json.dumps(prepare(a.host_root.resolve()),sort_keys=True))
