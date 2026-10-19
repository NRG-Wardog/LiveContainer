#!/usr/bin/env python3
"""Offline original-byte replay for an independent Phase A reviewer, before Phase B.
No authenticated transport or independent approval is manufactured by this tool.
"""
import argparse
import json
from pathlib import Path
from prior_phase_a import parse,verify_original_capture

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prior-json',required=True,type=Path,help='Exact prior object, or Phase B input with prior_phase_a; independent_review may remain null')
    parser.add_argument('--receipts',required=True,type=Path)
    parser.add_argument('--prior-adapter',type=Path,default=Path(__file__).resolve().parent/'prior_adapter')
    parser.add_argument('--source-roots-json',required=True,type=Path,help='Object mapping AnisetteKit,SideSign,LiveContainer to read-only local Git roots')
    parser.add_argument('--report',type=Path,help='Optional local JSON output; excludes lock bytes and creates no independent approval')
    args=parser.parse_args()
    data=parse(args.prior_json.read_bytes());prior=data.get('prior_phase_a',data)
    result=verify_original_capture(prior,args.receipts,args.prior_adapter,parse(args.source_roots_json.read_bytes()))
    public={k:v for k,v in result.items() if k!='lock_bytes'}
    text=json.dumps(public,indent=2,sort_keys=True,allow_nan=False)+'\n'
    if args.report is not None:
        with args.report.open('x',encoding='utf-8') as output:output.write(text)
    else:print(text,end='')
if __name__=='__main__':main()
