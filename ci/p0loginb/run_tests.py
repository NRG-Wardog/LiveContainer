#!/usr/bin/env python3
"""Finite test lanes. Retained-evidence replay requires explicit local fixtures."""
import argparse,hashlib,importlib.util,json,os,sys,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parent
LANES={'self-contained':{'test_graph_contract.py':30,'test_cargo_contract.py':15,'test_macho_contract.py':10,'test_retrieve_prior.py':18,'test_native_tool_identity.py':10,'test_registry_diagnostics.py':8,'test_registry_readme_alias.py':12,'test_plist_generated_output.py':19,'test_openssl_artifact_contract.py':23,'test_product_signature_boundary.py':39,'test_product_capture_integration.py':7},
       'local-proposal':{'test_draft_gate.py':12},'local-evidence':{'test_prior_phase_a.py':27}}
def require(value,message):
    if not value:raise ValueError(message)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def flatten(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):yield from flatten(item)
        else:yield item

def run(scope,result_path,source_objects=None,prior_capture=None):
    require(scope in LANES,'unknown finite test lane')
    if scope=='local-evidence':
        require(source_objects is not None and prior_capture is not None,'explicit genuine source/evidence fixture paths required')
        for p in (source_objects,prior_capture):require(p.is_absolute() and p.is_dir() and not p.is_symlink(),'ordinary explicit fixture directory required')
        os.environ['P0LOGINB_SOURCE_OBJECTS']=str(source_objects);os.environ['P0LOGINB_PRIOR_CAPTURE']=str(prior_capture)
    else:require(source_objects is None and prior_capture is None,'fixture paths only belong to local evidence lane')
    require(not result_path.exists() and not result_path.is_symlink(),'fresh test result required')
    suite=unittest.TestSuite();sources={};expected_ids=[]
    for filename,count in LANES[scope].items():
        path=HERE/'tests'/filename;raw=path.read_bytes();sources[filename]=sha(raw)
        name=path.stem;spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        selected=unittest.defaultTestLoader.loadTestsFromModule(module);ids=[test.id() for test in flatten(selected)]
        require(len(ids)==count and len(ids)==len(set(ids)),'finite exact test inventory changed: '+filename)
        expected_ids+=ids;suite.addTests(selected)
    require(len(expected_ids)==len(set(expected_ids)),'duplicate test ID')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    value={'schema_version':1,'scope':scope,'status':'PASSED' if result.wasSuccessful() and not result.skipped and result.testsRun==len(expected_ids) else 'FAILED',
        'tests_run':result.testsRun,'expected_test_ids':expected_ids,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
        'source_sha256':sources,'driver_sha256':sha(Path(__file__).read_bytes()),'native_execution':False,
        'current_run':{k:os.environ.get(k) for k in ('GITHUB_REPOSITORY','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_SHA','GITHUB_REF')},
        'fixture_paths':{'source_objects':str(source_objects),'prior_capture':str(prior_capture)} if scope=='local-evidence' else None}
    result_path.parent.mkdir(parents=True,exist_ok=True)
    with result_path.open('x') as f:f.write(json.dumps(value,indent=2,sort_keys=True)+'\n')
    require(value['status']=='PASSED','finite test lane failed or skipped')
    return value
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--scope',choices=LANES,required=True);p.add_argument('--result',type=Path,required=True)
    p.add_argument('--source-objects',type=Path);p.add_argument('--prior-capture',type=Path);a=p.parse_args()
    try:run(a.scope,a.result.resolve(),a.source_objects.resolve() if a.source_objects else None,a.prior_capture.resolve() if a.prior_capture else None)
    except Exception as error:p.exit(2,'TEST_LANE_FAILED: '+str(error)+'\n')
