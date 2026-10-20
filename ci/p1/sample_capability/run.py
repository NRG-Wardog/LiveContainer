"""Verify sealed closure, then one benign owned-child preflight, never native UI."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[3]

def verify(expected):
    manifest=Path(__file__).with_name('closure.json')
    raw=manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('closure seal mismatch')
    rows=json.loads(raw)
    for rel,digest in rows.items():
        p=ROOT/rel
        if not p.is_file() or p.is_symlink() or p.resolve()!=p or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:
            raise ValueError('closure file mismatch')
    return rows


def main():
    p=argparse.ArgumentParser();p.add_argument('--seal',required=True);p.add_argument('--output',type=Path);p.add_argument('--verify-only',action='store_true');a=p.parse_args()
    verify(a.seal)
    if a.verify_only:return 0
    if a.output is None:raise ValueError('output required')
    output=a.output.resolve();output.mkdir(parents=True,exist_ok=False)
    sys.path[:0]=[str(ROOT/'ci/p1/direct/host'),str(ROOT/'ci/p1/preflight')]
    import process_scope
    from diagnostic import Diagnostic
    scope=process_scope.Scope(output,capture_prerequisites=True)
    experiment=Diagnostic(scope,process_scope,output,uuid.uuid4().hex,'','')
    try:experiment.preflight()
    finally:
        try:scope.close()
        finally:experiment.finish(0)
    row=experiment.row
    # Success means compatible owned-child report, not full P1 admission.
    return 0 if row['status']=='available' else 2

if __name__=='__main__':raise SystemExit(main())
