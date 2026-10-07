#!/usr/bin/env python3
"""A bounded localhost control proves the existing offline wrapper denies connect."""
import errno
import json
from pathlib import Path
import socket
import subprocess
import sys


def child(port):
    result = {"child_executed": True, "operation": "socket", "connected": False, "errno": None}
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.settimeout(3)
            result["operation"] = "connect"
            client.connect(("127.0.0.1", port))
            result["connected"] = True
    except OSError as error:
        result["errno"] = error.errno
    return result


def validate(control, denied):
    if control != {"child_executed": True, "operation": "connect", "connected": True, "errno": None}:
        raise ValueError("Unsandboxed localhost positive control did not connect")
    if not (denied.get("child_executed") is True and denied.get("operation") == "connect"
            and denied.get("connected") is False and denied.get("errno") in {errno.EPERM, errno.EACCES}):
        raise ValueError("Sandboxed connect did not establish explicit permission denial")


def run(output):
    report = {"status": "FAIL", "endpoint": "temporary IPv4 loopback listener",
              "launcher": "existing exported offline shell function", "commands": []}
    def launch(command):
        completed = subprocess.run(command, capture_output=True, text=True, timeout=10)
        report["commands"].append({"command": command, "exit_code": completed.returncode,
            "stdout": completed.stdout[:2048], "stderr": completed.stderr[:2048]})
        if completed.returncode != 0 or len(completed.stdout) > 2048:
            raise ValueError("Canary child failed to execute or returned unbounded output")
        return json.loads(completed.stdout)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(2)
            listener.settimeout(5)
            command = [sys.executable, "-B", str(Path(__file__).resolve()), "--child", str(listener.getsockname()[1])]
            control = launch(command)
            # Confirm the control reached this still-open listener, then free its
            # backlog slot so a permitted second connect could not fake denial.
            accepted, address = listener.accept()
            accepted.close()
            denied = launch(["/bin/bash", "-c", 'offline "$@"', "network-sandbox-canary", *command])
            report.update(control=control, sandboxed=denied)
            validate(control, denied)
            report["status"] = "PASS"
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        print(json.dumps(child(int(sys.argv[2]))))
    else:
        run(Path(sys.argv[1]))
