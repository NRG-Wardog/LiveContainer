#!/usr/bin/env python3
"""Run the exact sealed host driver with observational nested command receipts."""
import os, runpy, sys
from pathlib import Path
from observe_subprocess import install
install(Path(os.environ['P0LOGIN_NESTED_COMMANDS']))
script=Path(sys.argv[1])
if not script.is_absolute() or not script.is_file() or script.is_symlink():
    raise SystemExit('exact ordinary absolute host driver path required')
sys.argv=sys.argv[1:]
runpy.run_path(str(script),run_name='__main__')
