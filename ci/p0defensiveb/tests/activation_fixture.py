"""Exact retained pending workflow and local-only test-host helpers.

The fixture is copied from the frozen pending proposal, never synthesized from an
activated workflow. No sibling checkout is consulted at test execution time.
"""
from contextlib import contextmanager, ExitStack
from pathlib import Path
import shutil
import tempfile
from unittest import mock

import execution_contract as execution
from inventory import parse, sha

ADAPTER = Path(__file__).resolve().parents[1]
HOST = ADAPTER.parents[1]
PENDING_WORKFLOW = ADAPTER/'tests/fixtures/activation/pending-phase-b-workflow.yml'
PENDING_WORKFLOW_SHA256 = 'c8c54690aae317048de69982ffee98da5befb444362cdd821dd14845dbfec1a2'


def pending_workflow_bytes():
    raw = PENDING_WORKFLOW.read_bytes()
    if sha(raw) != PENDING_WORKFLOW_SHA256:
        raise ValueError('retained exact pending workflow changed')
    return raw


def make_pending_host(host):
    """Two exact workflow files suffice for pending admission unit tests."""
    host = Path(host)
    workflow = host/execution.WORKFLOW
    workflow.parent.mkdir(parents=True)
    workflow.write_bytes(pending_workflow_bytes())
    (workflow.parent/'build.yml').write_bytes((HOST/'.github/workflows/build.yml').read_bytes())
    (host/execution.ADAPTER).mkdir(parents=True)
    return host


@contextmanager
def pending_host():
    with tempfile.TemporaryDirectory() as temporary:
        yield make_pending_host(Path(temporary).resolve())


@contextmanager
def no_execution():
    """Even execution=True below is schema-only, never Gate.execute()."""
    with ExitStack() as stack:
        checks = [stack.enter_context(mock.patch(name, side_effect=AssertionError('schema-only activation test attempted '+name)))
                  for name in ('subprocess.Popen', 'subprocess.run', 'subprocess.check_output',
                               'os.system', 'socket.socket', 'urllib.request.urlopen')]
        yield
        for check in checks:
            check.assert_not_called()


def validate_actual_outer(host=HOST):
    raw = (host/execution.INPUT_PATH).read_bytes()
    digest = sha(raw)
    with no_execution():
        _, anchor = execution.workflow(host, digest)
        active = parse(raw)['status'] == 'BOUND_CAPTURE_PROPOSAL' and anchor == digest
        value = execution.validate_inputs(raw, host, digest, execution=active)
    return value, active


def copy_actual_host(destination):
    """Copy exact current bytes for negative tests, without mutating the candidate."""
    destination = Path(destination)
    shutil.copytree(HOST/execution.ADAPTER, destination/execution.ADAPTER, ignore=shutil.ignore_patterns('__pycache__'))
    (destination/execution.WORKFLOW).parent.mkdir(parents=True)
    for relative in (execution.WORKFLOW, '.github/workflows/build.yml'):
        (destination/relative).write_bytes((HOST/relative).read_bytes())
    return destination
