#!/usr/bin/env python3
"""Generate the three frozen test-only projections; never executes Swift or network."""
from pathlib import Path
import argparse, hashlib, importlib.util, json
HERE=Path(__file__).resolve().parent
SUPPORT=['generate.py','source-inputs.json','README.md','test_sources.py','chain/generate_fixture.py','chain/Doubles.swift','chain/Operations.swift','chain/Cases.swift','customization/generate.py','customization/Support.swift','customization/Cases.swift','customization/test_generator.py','customization/README.md','cache/generate.py','cache/BoundaryDoubles.swift','cache/Cases.swift','cache/test_source.py','cache/README.md']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def generate(root,output):
 root,output=Path(root).resolve(),Path(output).resolve()
 pins=json.loads((HERE/'source-inputs.json').read_text())
 for row in pins['inputs']:
  p=root/row['path'];assert sha(p)==row['sha256'],row['path']
 variants=[]
 chain=module('chain_fixture',HERE/'chain/generate_fixture.py').generate(root,output/'chain')
 for row in chain['variants']:variants.append({**row,'file':'chain/'+row['file'],'expected_exit_code':1 if row['expected_failed_names'] else 0})
 custom=module('customization_fixture',HERE/'customization/generate.py')
 for name,mutation in [('Customization.swift','none'),('NegativeDropPersistedTrue.swift','drop-persisted-true'),('NegativeBypassInfoPlist.swift','bypass-info-plist')]:
  target=output/'customization'/name;manifest=custom.generate(root,target,mutation=mutation)
  failures=custom.NEGATIVE_CONTROLS.get(mutation,{}).get('intended_failing_cases',[])
  variants.append({'file':'customization/'+name,'group':'customization','case_names':list(custom.CASE_NAMES),'expected_failed_names':failures,'expected_exit_code':1 if failures else 0,'sha256':sha(target)})
 cache=module('cache_fixture',HERE/'cache/generate.py').generate(root,output/'cache')
 for row in cache['variants']:variants.append({**row,'file':'cache/'+row['file']})
 artifacts=[{'path':str(p.relative_to(output)),'sha256':sha(p)} for p in sorted(output.rglob('*')) if p.is_file() and p.name!='sources.json']
 # Include group cache sources.json; exclude only the aggregate at output root.
 cache_receipt=output/'cache/sources.json'
 artifacts.append({'path':'cache/sources.json','sha256':sha(cache_receipt)})
 artifacts.sort(key=lambda r:r['path'])
 receipt={'schema':'install-chain-source-closure-v1','passed':True,'inputs':pins['inputs'],
  'support':[{'path':s,'sha256':sha(HERE/s)} for s in SUPPORT],
  'variants':variants,'generated_artifacts':artifacts,'runtime_schema':'install-chain-runtime-v1',
  'compile_flags':['-swift-version','5','-parse-as-library'],'compiler_minimum':'Swift 5.7; current macOS CI toolchain',
  'expected_positive_case_count':sum(len(v['case_names']) for v in variants if not v['expected_failed_names']),
  'upstream_comparison':{'repo':'SideStore/SideStore','commit':'d97ec133719d79916675bdaf722b82a8d091d545','step_definition_byte_identical_to_delivered':True,'comparison_is_audit_evidence_not_fixture_input':True},
  'production_changed':False,'swift_executed':False,'network_executed':False,'native_signing_device_executed':False,
  'limitations':['chain tests actual service input/context/20-step dispatch wiring only; all concrete operation bodies are inert, including download/ZIP/verify/install',
   'customization tests actual operation/default protocol with isolated Foundation UserDefaults and inert Auth/DB/models',
   'cache tests actual cachePayload+fingerprint on synthetic local files only',
   'no selected user IPA, security-scoped URL, Apple signing/portal, transfer, device installation, or database persistence is validated']}
 (output/'sources.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n');return receipt
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=generate(a.root,a.output);print(json.dumps({'schema':r['schema'],'passed':r['passed'],'variant_count':len(r['variants']),'positive_case_count':r['expected_positive_case_count'],'swift_executed':False}))
