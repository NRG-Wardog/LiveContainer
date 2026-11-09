#!/usr/bin/env python3
"""Run actual owner scheduler with builder's maintained native OS doubles.

Usage: python tests/scheduler/run_preflight_retry.py /path/to/builder
The builder must have its pinned SideStore source configured as in product CI.
This is native coordinator coverage, not an iOS/device build.
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

OWNER = Path(__file__).resolve().parents[2]
BUILDER = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(BUILDER))
from tests.support import product_sources

original_source = product_sources.owner_source

def candidate_source(path, owner='LiveContainer'):
    if owner != 'LiveContainer':
        return original_source(path, owner)
    committed = subprocess.check_output(['git', '-C', str(OWNER), 'show', f'HEAD:{path}'])
    file = OWNER / path
    if file.is_symlink() or file.read_bytes() != committed:
        raise ValueError('Candidate source differs from committed owner: ' + path)
    return committed.decode()

product_sources.owner_source = candidate_source
read = product_sources.read_product_source
roles = ['combined_failure.swift', 'v3_wire_contract.swift', 'v3_behavioral_primitives.swift']
source = '\n'.join(read(role) for role in roles)
stubs = (BUILDER / 'tests/fixtures/livecontainer_scheduler_stubs.swift').read_text()
# Explicit failure-injection hooks in OS/bridge doubles, never product code.
assert stubs.count('        runIDs.append(runID)') == 1
stubs = stubs.replace('    static var checks = 0', '    static var beforeThrow: (() -> Void)?\n    static var checks = 0')
stubs = stubs.replace('        runIDs.append(runID)', '        runIDs.append(runID)\n        beforeThrow?()')
stubs = stubs.replace('    static var fails = false', '    static var bridgeError: Error?\n    static var fails = false')
stubs = stubs.replace('        calls += 1', '        calls += 1\n        if let bridgeError { throw bridgeError }')
source += '\n' + stubs
source += '\n' + '\n'.join(read(role) for role in [
    'v3_shared_app_group.swift', 'livecontainer_refresh_policy.swift',
    'livecontainer_vpn_recovery.swift', 'livecontainer_refresh_scheduler.swift'])
source += '\n' + candidate_source('LiveContainerSwiftUI/Utilities/V3Localization.swift')
support = candidate_source('SideStoreSupport/SideStore.swift')
begin = support.index('public enum V3RefreshNotificationLocalization {')
source += '\n' + support[begin:product_sources.declaration_end(support, begin)]
source += '\n' + (OWNER / 'tests/scheduler/preflight_retry.swift').read_text()
compiler = shutil.which('swiftc')
if not compiler:
    raise SystemExit('Native test requires swiftc; not passed or skipped silently')
with tempfile.TemporaryDirectory() as directory:
    swift = Path(directory) / 'Scheduler.swift'
    binary = Path(directory) / 'scheduler'
    swift.write_text(source)
    subprocess.run([compiler, '-swift-version', '5', '-parse-as-library', str(swift), '-o', str(binary)], check=True, timeout=120)
    result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
    print(result.stdout)
    print(result.stderr, file=sys.stderr)
    if result.returncode or 'SCHEDULER_PREFLIGHT_RETRY_PASSED' not in result.stdout:
        raise SystemExit('Native scheduler regression failed')
