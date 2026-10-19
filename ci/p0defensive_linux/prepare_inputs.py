#!/usr/bin/env python3
"""Refresh local review proposal only; never activates the workflow."""
from inventory import *
from host_contract import DRIVERS
host=HERE.parents[1]
workflow,anchor=workflow_bytes(host);require(anchor=='REVIEW_REQUIRED','cannot regenerate activated inputs')
files=adapter_inventory(HERE)
data={'schema':1,'basis':BASIS,'host':{'base':HOST_BASE,'tree':HOST_TREE,'branch':BRANCH,'build_guard':BUILD_GUARD},'source_seal_sha256':SEAL_SHA,'adapter_files':files,'workflow_template_sha256':sha(workflow),'drivers':list(DRIVERS),'retained_patterns_status':'PENDING_INDEPENDENT_CAPTURE_REVIEW'}
dump(HERE/'inputs-linux.json',data)
print(sha((HERE/'inputs-linux.json').read_bytes()))
