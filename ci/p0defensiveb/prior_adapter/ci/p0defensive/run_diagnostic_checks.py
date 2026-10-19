#!/usr/bin/env python3
"""Entry point invoked only by the owned, retained, network-denied host wrapper."""
import argparse
from pathlib import Path
from diagnostic_checks import run
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('owner','unicorn-include','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();run(a.owner.resolve(),a.unicorn_include.resolve(),a.output.resolve())
