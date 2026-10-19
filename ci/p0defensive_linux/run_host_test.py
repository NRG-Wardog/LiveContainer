#!/usr/bin/env python3
"""Four fixed source scripts only; nested argv is validated before execution."""
import argparse,json,os,runpy,sys,tempfile,shutil
from pathlib import Path
from inventory import require,verify_source
from host_contract import DRIVERS,expected_commands,command_metadata_dir,header_proof
from observe_host_subprocess import install

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('owner','output','temporary','evidence','unicorn-include'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--driver',choices=DRIVERS,required=True)
    p.add_argument('--compiler',type=Path,required=True);p.add_argument('--expected-uid',type=int,required=True);p.add_argument('--expected-gid',type=int,required=True);a=p.parse_args()
    require(a.expected_uid>0 and a.expected_gid>0 and os.getuid()==a.expected_uid and os.getgid()==a.expected_gid,'capture payload owner differs before writes')
    require(shutil.which('c++')==str(a.compiler),'capture payload selected compiler differs before writes')
    verify_source(a.owner);header_proof(a.unicorn_include)
    for name in ('output','temporary'):
        value=getattr(a,name);require(value.is_absolute() and not value.exists(),'fresh absolute '+name+' required');value.mkdir(parents=True);require(value.stat().st_uid==a.expected_uid and value.stat().st_gid==a.expected_gid,'capture output ownership differs')
    compiler=a.compiler;metadata_dir=None
    def guard(index,argv):
        nonlocal metadata_dir
        observed=command_metadata_dir(a.driver,argv,a.temporary)
        if metadata_dir is None:metadata_dir=observed
        require(observed==metadata_dir,'metadata temporary changed')
        expected=expected_commands(a.driver,a.owner,a.output,a.unicorn_include,a.temporary,compiler,metadata_dir)
        require(1<=index<=len(expected) and argv==expected[index-1],'nested compiler/runtime command differs before execution')
    os.environ['TMPDIR']=str(a.temporary);tempfile.tempdir=str(a.temporary)
    store=install(a.evidence,a.temporary,a.output,guard=guard)
    require(a.evidence.stat().st_uid==a.expected_uid and a.evidence.stat().st_gid==a.expected_gid,'nested evidence ownership differs')
    script=a.owner/'.ci/native-tests'/a.driver
    sys.argv=[str(script),'--output',str(a.output)]
    if a.driver=='test_elf_metadata_bounds.py':sys.argv+=['--disable-leak-sanitizer']
    else:sys.argv+=['--unicorn-include',str(a.unicorn_include)]
    runpy.run_path(str(script),run_name='__main__')
    (a.evidence/'final-output.json').write_text(json.dumps(store.retain_tree(a.output,label='final-output'),indent=2)+'\n')
    summary=store.summary();prior=json.loads((a.evidence/'retention-summary.json').read_text());summary['nested_commands']=prior['nested_commands']
    (a.evidence/'retention-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
if __name__=='__main__':main()
