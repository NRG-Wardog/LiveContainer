#!/usr/bin/env python3
"""Copy bounded, hash-verified failure logs only; never a replacement for full replay."""
import argparse, hashlib, json, re, stat
from pathlib import Path
from inventory import ordinary, parse, require, sha
MAX_FILES=128
MAX_FILE_BYTES=256*1024
MAX_TOTAL_BYTES=16*1024*1024
MAX_INDEX_BYTES=32*1024*1024
BASE=('provenance/result.json','provenance/owned-command-groups.json','provenance/reviewed-inputs.json')
DIAGNOSTIC=re.compile(r'host-tests/run-diagnostic-checks/[0-9]{4}\.(?:command\.json|result\.json|stdout|stderr)\Z')
OUTER=re.compile(r'logs/([a-zA-Z0-9_.-]+)\.exit-code\.txt\Z')
OUTER_SUFFIXES=('.command.json','.exit-code.txt','.log','.stderr.log','.settlement.json')

def read_indexed(root,index,name,limit):
    require(name in index and isinstance(index[name],str) and re.fullmatch('[0-9a-f]{64}',index[name]),'indexed failure log required')
    p=ordinary(root,name);before=p.stat();require(before.st_size<=limit,'bounded failure log required')
    raw=p.read_bytes();after=p.stat()
    identity=lambda s:(s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    require(identity(before)==identity(after) and len(raw)==before.st_size and sha(raw)==index[name],'failure log changed or differs from immutable index')
    return raw

def export(root,output):
    root=Path(root);output=Path(output)
    require(root.is_absolute() and root.resolve()==root and root.is_dir() and not root.is_symlink(),'ordinary canonical evidence required')
    require(output.is_absolute() and output.parent.resolve()==output.parent and not output.exists() and not output.is_symlink() and not output.is_relative_to(root),'fresh separate summary output required')
    p=ordinary(root,'evidence-index.json');require(p.stat().st_size<=MAX_INDEX_BYTES,'bounded evidence index required');index_raw=p.read_bytes();index=parse(index_raw)
    require(isinstance(index,dict),'evidence index object required')
    result=parse(read_indexed(root,index,BASE[0],MAX_FILE_BYTES))
    groups=parse(read_indexed(root,index,BASE[1],MAX_FILE_BYTES))
    require(result.get('writers_quiescent') is True and groups and all(r.get('quiescent') is True and r.get('pipesJoined') is True and r.get('leaderReaped') is True and not r.get('errors') for r in groups),'settled original writers required')
    if result['status']=='CAPTURED_FOR_INDEPENDENT_REVIEW':return {'created':False,'reason':'capture completed; full replay still required'}
    require(result['status']=='FAILED_OR_INCOMPLETE','known settled capture failure required')
    names=set(BASE);labels={'host-run-diagnostic-checks'}
    for name in index:
        if DIAGNOSTIC.fullmatch(name):names.add(name)
        match=OUTER.fullmatch(name)
        if match:
            raw=read_indexed(root,index,name,32)
            require(re.fullmatch(rb'-?[0-9]+\n?',raw),'outer exit code format differs')
            if int(raw)!=0:labels.add(match[1])
    for label in labels:
        names.update('logs/'+label+suffix for suffix in OUTER_SUFFIXES if 'logs/'+label+suffix in index)
    require(len(names)<=MAX_FILES,'finite failure log count exceeded')
    selected=[];omitted=[];total=0
    for name in sorted(names):
        p=ordinary(root,name);length=p.stat().st_size
        if length>MAX_FILE_BYTES:
            omitted.append(dict(path=name,observed_bytes=length,indexed_sha256=index[name],reason='per-file diagnostic-view cap; use full immutable evidence'))
            continue
        raw=read_indexed(root,index,name,MAX_FILE_BYTES);total+=len(raw)
        require(total<=MAX_TOTAL_BYTES,'aggregate failure log cap exceeded')
        selected.append((name,raw))
    receipt=dict(schema='bounded-failure-log-view-v1',purpose='DIAGNOSTIC_VIEW_ONLY_NOT_FINAL_REPLAY_EVIDENCE',full_immutable_evidence_required=True,capture_status=result['status'],run=result['run'],approved_inputs_sha256=result['approved_inputs_sha256'],source_seal_sha256=result['source_seal_sha256'],source_evidence_index_sha256=sha(index_raw),copied_bytes=total,files=[dict(path=name,bytes=len(raw),sha256=sha(raw)) for name,raw in selected],omitted=omitted)
    output.mkdir()
    for name,raw in selected:
        destination=output/name;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(raw)
    (output/'failure-summary-manifest.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
    return {'created':True,'files':len(selected),'bytes':total,'omitted':len(omitted),'full_immutable_evidence_required':True}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--evidence',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    print(json.dumps(export(a.evidence,a.output),sort_keys=True))
