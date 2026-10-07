#!/usr/bin/env python3
"""Run every required pristine suite, then gate assembly on complete evidence.

Ordinary failures do not hide later suites. Interruptions stop suite execution,
retain explicit NOT_RUN records, attempt all source checks, and exit nonzero.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

from run_fork_suite import EXPECTED
from validate_inputs import OWNERS, load_map, verify_checkout

SUITES = ("LiveContainer", "SideStore", "AnisetteKit", "SideSign", "minimuxer", "idevice", "jktcp")
HERE = Path(__file__).resolve().parent
SANDBOX = ["/usr/bin/sandbox-exec", "-p", "(version 1) (allow default) (deny network*)"]
SUITE_TIMEOUT_SECONDS = 900
SIDESIGN_SOURCE_CHECKPOINT = "aaa4375a59075a7b0a446cf4c2dc8193c247a875"
SIDESIGN_TEST_ONLY_CHANGES = [{
    "path": "Tests/SideSignTests/SideSignTests.swift",
    "change": "add explicit Foundation import",
    "frozen_sha256": "064d2f8852eb5de2aff47a6a781a74f84c408b2e84d88a5c3842733940100c20",
    "new_sha256": "511c3fe77e5b4e5e8903ada85e8b2ee4b17f08016cf6ac8db90446158bcd0ad6",
}]


class Interrupted(BaseException):
    def __init__(self, signum):
        self.exit_code = 128 + signum


def interrupt_handler(signum, frame):
    raise Interrupted(signum)


def write_json(path, document):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, indent=2) + "\n")
    temporary.replace(path)


def run_command(command, log):
    with log.open("w") as stream:
        process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            return process.wait(timeout=SUITE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            return 124
        except BaseException:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            raise


def cancellation_code(returncode):
    if returncode in (130, 143):
        return returncode
    if returncode in (-signal.SIGINT, -signal.SIGTERM):
        return 128 - returncode
    return None


def valid_suite(row):
    if row.get("state") != "FINISHED" or row.get("returncode") != 0:
        return False
    result = row.get("result")
    if not isinstance(result, dict):
        return False
    owner = row["owner"]
    if owner in EXPECTED:
        return (result.get("owner") == owner and result.get("status") == "PASS"
                and result.get("expected") == EXPECTED[owner]
                and result.get("executed") == EXPECTED[owner]
                and result.get("skipped") == [] and result.get("failures") == 0
                and result.get("errors") == 0)
    count = result.get("product_files_verified")
    if owner == "SideSign":
        # This one reviewed test import is separate from the frozen runtime
        # proof. Do not turn its status into a generic test-drift exception.
        return (result.get("owner") == owner
                and result.get("status") == "exact_frozen_runtime_with_test_import_pass"
                and result.get("source_checkpoint") == SIDESIGN_SOURCE_CHECKPOINT
                and result.get("test_only_changes") == SIDESIGN_TEST_ONLY_CHANGES
                and type(count) is int and count == 61
                and type(result.get("migrated_files")) is int and result["migrated_files"] == 4
                and result.get("behavior_changes") == []
                and result.get("fork_commit") == row.get("expected_commit"))
    return (result.get("owner") == owner and result.get("status") == "exact_frozen_source_pass"
            and type(count) is int and count > 0 and result.get("behavior_changes") == []
            and "test_only_changes" not in result
            and result.get("fork_commit") == row.get("expected_commit"))


def gate_exit(report):
    if report.get("interruption") in (130, 143):
        return report["interruption"]
    suites = report.get("suites", [])
    checks = report.get("integrity", [])
    if (len(suites) != len(SUITES) or {r.get("owner") for r in suites} != set(SUITES)
            or len(checks) != len(OWNERS) or {r.get("owner") for r in checks} != set(OWNERS)):
        return 1
    for row in suites:
        cancelled = cancellation_code(row.get("returncode"))
        if cancelled:
            return cancelled
    return 0 if all(valid_suite(row) for row in suites) and all(
        row.get("status") == "PASS" for row in checks) else 1


def run_gate(source_root, evidence, document, digest, runner=run_command, verify=verify_checkout):
    logs, provenance = evidence / "logs", evidence / "provenance"
    logs.mkdir(parents=True, exist_ok=True)
    provenance.mkdir(parents=True, exist_ok=True)
    report_path = provenance / "pristine-suite-gate.json"
    report = {"schema_version": 1, "status": "RUNNING", "approved_reference_map_sha256": digest,
        "suites": [{"owner": owner, "state": "NOT_RUN", "returncode": None, "result": None,
                    "log": str(logs / ("pristine-" + owner + ".log")),
                    "expected_count": EXPECTED.get(owner, 1),
                    "count_kind": "unit-tests" if owner in EXPECTED else "source-parity-check",
                    "expected_commit": document["owners"][owner]["source_commit"]} for owner in SUITES],
        "integrity": [{"owner": owner, "status": "NOT_RUN"} for owner in OWNERS], "interruption": None}
    write_json(report_path, report)  # Invalidate any stale prior PASS immediately.
    for row in report["suites"]:
        owner = row["owner"]
        result_path = provenance / ("pristine-" + owner + "-tests.json")
        result_path.unlink(missing_ok=True)
        if owner in EXPECTED:
            command = SANDBOX + [sys.executable, "-B", str(HERE / "run_fork_suite.py"), owner,
                                 str(source_root / owner), str(result_path)]
        else:
            command = SANDBOX + [sys.executable, "-B", str(source_root / owner / ".ci/source-parity.py")]
        row.update(state="RUNNING", command=command)
        write_json(report_path, report)
        print("Running pristine suite: " + owner, flush=True)
        try:
            row["returncode"] = runner(command, Path(row["log"]))
            row["state"] = "FINISHED"
        except (Interrupted, KeyboardInterrupt) as error:
            report["interruption"] = error.exit_code if isinstance(error, Interrupted) else 130
            row.update(state="INTERRUPTED", returncode=report["interruption"])
        except Exception as error:
            row.update(state="FAILED_TO_RUN", runner_error=str(error))
        try:
            row["result"] = json.loads((result_path if owner in EXPECTED else Path(row["log"])).read_text())
        except (OSError, ValueError) as error:
            row["result_error"] = str(error)
        row["passed"] = valid_suite(row)
        row["executed_count"] = (row["result"].get("executed") if owner in EXPECTED
                                  else int(row["passed"])) if isinstance(row["result"], dict) else None
        report["interruption"] = report["interruption"] or cancellation_code(row["returncode"])
        write_json(report_path, report)
        print(f"Pristine {owner}: exit={row['returncode']} count={row['executed_count']} pass={row['passed']}", flush=True)
        if report["interruption"]:
            break
    # Always attempt source checks after ordinary failures, including failed setup
    # or missing reports. Repeated cancellation can leave explicit NOT_RUN rows.
    for row in report["integrity"]:
        owner = row["owner"]
        entry = document["owners"][owner]
        try:
            verify(source_root / owner, entry["source_commit"], entry["source_tree"])
            row["status"] = "PASS"
        except (Interrupted, KeyboardInterrupt) as error:
            row["status"] = "INTERRUPTED"
            report["interruption"] = error.exit_code if isinstance(error, Interrupted) else 130
            break
        except Exception as error:
            row.update(status="FAIL", error=str(error))
        write_json(report_path, report)
    code = gate_exit(report)
    report.update(status="PASS" if code == 0 else "INTERRUPTED" if report["interruption"] else "FAIL",
                  exit_code=code, assembly_allowed=code == 0)
    write_json(provenance / "pristine-after-tests.json", {
        "status": "PASS" if all(r["status"] == "PASS" for r in report["integrity"]) else "FAIL_OR_INCOMPLETE",
        "approved_reference_map_sha256": digest, "owners": report["integrity"]})
    write_json(report_path, report)
    return code, report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root", type=Path, required=True)
    p.add_argument("--evidence", type=Path, required=True)
    p.add_argument("--map", type=Path, required=True)
    p.add_argument("--approved-sha256", required=True)
    a = p.parse_args()
    signal.signal(signal.SIGINT, interrupt_handler)
    signal.signal(signal.SIGTERM, interrupt_handler)
    refs = load_map(a.map, a.approved_sha256)
    code, report = run_gate(a.source_root, a.evidence, refs, a.approved_sha256)
    raise SystemExit(code)
