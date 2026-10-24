#!/usr/bin/env python3
from pathlib import Path
import argparse,importlib.util,json,tempfile
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args()
here=Path(__file__).parent
spec=importlib.util.spec_from_file_location('install_chain_generator',here/'generate.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
with tempfile.TemporaryDirectory() as d:
 out=Path(d);r=m.generate(a.root,out)
 assert r['expected_positive_case_count']==31
 assert len(r['variants'])==11
 assert len({v['file'] for v in r['variants']})==11
 for v in r['variants']:
  assert len(v['case_names'])==len(set(v['case_names']))
  assert set(v['expected_failed_names'])<=set(v['case_names'])
  assert v['expected_exit_code']==(1 if v['expected_failed_names'] else 0)
  text=(out/v['file']).read_text();assert '@main' in text and 'install-chain-runtime-v1' in text
  assert str(a.root) not in json.dumps(r)
 chain=json.loads((out/'chain/chain-sources.json').read_text())
 assert len(chain['excluded_executor_arms'])==11 and len(chain['install_steps'])==20
 for rel in ['chain/InstallChain.swift','customization/Customization.swift','cache/Cache.swift']:
  assert (out/rel).is_file()
print('PASS source-only closure: 3 groups, 31 positive cases, 8 negative variants; swift_executed=false')
