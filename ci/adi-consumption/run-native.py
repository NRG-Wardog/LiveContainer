#!/usr/bin/env python3
"""Exact-source, account-free ADI producer/decoder tests; no package assembly."""
import argparse
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import unittest

OWNERS = {name: "https://github.com/NRG-Wardog/" + name + ".git"
          for name in ("AnisetteKit", "SideStore", "LiveContainer")}
SUITES = {"AnisetteKit": (".ci/native-tests/run_tests.py", 7),
          "SideStore": ("tests/adi_consumption/test_contract.py", 6)}
OFFLINE = ["/usr/bin/sandbox-exec", "-p", "(version 1) (allow default) (deny network*)"]
HERE = Path(__file__).resolve()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate input key: " + key)
        result[key] = value
    return result


def read_inputs(path, approved):
    require(re.fullmatch(r"[0-9a-f]{64}", approved), "reviewed input digest required")
    data = path.read_bytes()
    require(hashlib.sha256(data).hexdigest() == approved, "input digest differs from workflow approval")
    result = json.loads(data, object_pairs_hook=unique_pairs)
    require(set(result) == {"schema", "scope", "integration_checkpoint", "owners"}, "unexpected input fields")
    require(result.get("schema") == 1 and result.get("scope") == "adi-consumption-native-only",
            "unexpected native validation scope")
    require(result["integration_checkpoint"] == "f9f23d980df363eb0f6eb5093b48e3639b03e137",
            "unexpected maintained-source checkpoint")
    require(set(result.get("owners", {})) == set(OWNERS), "exact three diagnostic owners required")
    for owner, expected_url in OWNERS.items():
        item = result["owners"][owner]
        require(set(item) == {"repository", "commit", "tree"}, "unexpected owner fields")
        require(item["repository"] == expected_url, "unexpected owner repository")
        for field in ("commit", "tree"):
            require(isinstance(item[field], str) and re.fullmatch(r"[0-9a-f]{40}", item[field]),
                    "exact published " + owner + " " + field + " required")
    return result


def git(root, *args):
    return subprocess.check_output(["git", "--no-replace-objects", "-c", "core.hooksPath=/dev/null",
        "-C", str(root), *args], stderr=subprocess.PIPE)


def snapshot(root, expected):
    require(git(root, "rev-parse", "HEAD").decode().strip() == expected["commit"], "source commit mismatch")
    require(git(root, "rev-parse", "HEAD^{tree}").decode().strip() == expected["tree"], "source tree mismatch")
    require(git(root, "remote", "get-url", "origin").decode().strip() == expected["repository"],
            "source origin mismatch")
    files, gitlinks = {}, {}
    for record in git(root, "ls-tree", "-rz", "HEAD").split(b"\0"):
        if not record:
            continue
        header, raw_name = record.split(b"\t", 1)
        mode, kind, oid = header.decode().split()
        name = os.fsdecode(raw_name)
        path = root / name
        for parent in path.parents:
            if parent == root:
                break
            require(not parent.is_symlink(), "linked source parent: " + name)
        if mode == "160000":
            # No package/submodule build is performed by these extracted tests.
            gitlinks[name] = oid
            continue
        require(kind == "blob", "unexpected source object")
        if mode == "120000":
            require(path.is_symlink(), "missing source link: " + name)
            data = os.fsencode(os.readlink(path))
        else:
            require(path.is_file() and not path.is_symlink(), "missing regular source: " + name)
            require(("100755" if path.stat().st_mode & 0o111 else "100644") == mode,
                    "source mode changed: " + name)
            data = path.read_bytes()
        require(hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == oid,
                "source bytes changed: " + name)
        files[name] = {"mode": mode, "git_blob": oid, "sha256": hashlib.sha256(data).hexdigest()}
    require(not git(root, "diff", "--cached", "--name-only"), "source index changed")
    for extra_args in (("--others", "--exclude-standard"), ("--others", "--ignored", "--exclude-standard")):
        require(not git(root, "ls-files", *extra_args, "-z"), "unexpected untracked source input")
    return {**expected, "files": files, "unfetched_gitlinks": gitlinks}


def suite(path, expected_count, output):
    spec = importlib.util.spec_from_file_location("adi_native_suite", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tests = unittest.defaultTestLoader.loadTestsFromModule(module)
    discovered = tests.countTestCases()
    require(discovered == expected_count, "native test discovery count changed")
    started = time.monotonic()
    result = unittest.TextTestRunner(verbosity=2).run(tests)
    passed = (result.wasSuccessful() and result.testsRun == expected_count and not result.skipped
              and not result.expectedFailures and not result.unexpectedSuccesses)
    save(output, {"status": "PASS" if passed else "FAIL", "discovered": discovered,
        "tests_run": result.testsRun, "expected": expected_count,
        "skipped": [(test.id(), reason) for test, reason in result.skipped],
        "failures": len(result.failures), "errors": len(result.errors),
        "expected_failures": len(result.expectedFailures), "elapsed_seconds": time.monotonic() - started})
    require(passed, "required native suite failed, skipped, or changed its test count")


def network_child(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=3):
            return {"connected": True, "errno": None}
    except OSError as error:
        return {"connected": False, "errno": error.errno}


def network_proof(output):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(2)
        listener.settimeout(5)
        command = [sys.executable, "-B", str(HERE), "network-child", str(listener.getsockname()[1])]
        control = json.loads(subprocess.check_output(command, timeout=10))
        accepted, _ = listener.accept()
        accepted.close()
        denied = json.loads(subprocess.check_output(OFFLINE + command, timeout=10))
    save(output, {"control": control, "sandboxed": denied})
    require(control == {"connected": True, "errno": None}, "loopback positive control failed")
    require(denied["connected"] is False and denied["errno"] in {errno.EPERM, errno.EACCES},
            "native test wrapper did not deny network access")


def run(args):
    require(platform.system() == "Darwin" and platform.machine() == "arm64", "macOS ARM64 required")
    host_commit, run_id = os.environ.get("GITHUB_SHA", ""), os.environ.get("GITHUB_RUN_ID", "")
    require(re.fullmatch(r"[0-9a-f]{40}", host_commit) and re.fullmatch(r"[1-9][0-9]*", run_id)
            and os.environ.get("GITHUB_REPOSITORY") == "NRG-Wardog/LiveContainer"
            and os.environ.get("GITHUB_REF") == "refs/heads/validation/adi-consumption-native",
            "exact validation host/run identity required")
    for tool in ("git", "xcodebuild", "xcrun", "swiftc", "c++"):
        require(shutil.which(tool), "missing native tool: " + tool)
    versions = subprocess.check_output(["xcodebuild", "-version"], text=True)
    require(versions.splitlines() == ["Xcode 26.4.1", "Build version 17E202"], "unreviewed Xcode build")
    inputs = read_inputs(args.inputs, args.approved_sha256)
    require(not args.work.exists() and not args.work.is_symlink(), "fresh isolated source root required")
    args.work.mkdir(parents=True)
    args.evidence.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.inputs, args.evidence / "inputs.json")
    save(args.evidence / "toolchain.json", {"xcodebuild": versions,
        "swiftc": subprocess.check_output(["swiftc", "--version"], text=True),
        "cxx": subprocess.check_output(["c++", "--version"], text=True), "python": sys.version})
    roots, before, failures = {}, {}, []
    for owner, expected in inputs["owners"].items():
        root = args.work / owner
        subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "clone", "--no-checkout",
                        expected["repository"], str(root)], check=True, timeout=300)
        git(root, "checkout", "--detach", expected["commit"])
        roots[owner] = root
        before[owner] = snapshot(root, expected)
    save(args.evidence / "sources-before.json", before)
    network_proof(args.evidence / "network-denial.json")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
        ADI_CONSUMPTION_PEER_ROOT=str(roots["LiveContainer"]),
        ADI_CONSUMPTION_PRODUCER_ROOT=str(roots["AnisetteKit"]))
    try:
        for owner, (relative, count) in SUITES.items():
            print("Running " + owner + " native suite; required tests=" + str(count), flush=True)
            with (args.evidence / (owner + "-tests.log")).open("w") as log:
                try:
                    result = subprocess.run(OFFLINE + [sys.executable, "-B", str(HERE), "suite",
                        str(roots[owner] / relative), str(count), str(args.evidence / (owner + "-tests.json"))],
                        env=env, stdout=log, stderr=subprocess.STDOUT, timeout=720)
                    if result.returncode:
                        failures.append(owner + ": exit " + str(result.returncode))
                except subprocess.TimeoutExpired:
                    failures.append(owner + ": native suite timeout")
            result_path = args.evidence / (owner + "-tests.json")
            if result_path.exists():
                print(result_path.read_text(), flush=True)
    finally:
        after = {owner: snapshot(root, inputs["owners"][owner]) for owner, root in roots.items()}
        save(args.evidence / "sources-after.json", after)
        require(after == before, "source inputs changed during native tests")
        require(read_inputs(args.inputs, args.approved_sha256) == inputs, "approved input file changed during tests")
    save(args.evidence / "result.json", {"status": "FAIL" if failures else "PASS", "failures": failures,
        "validation_host_commit": host_commit,
        "run_url": "https://github.com/NRG-Wardog/LiveContainer/actions/runs/" + run_id,
        "scope": "synthetic native producer/decoder tests only; no package build or device authentication",
        "integration_checkpoint": inputs["integration_checkpoint"], "expected_tests": {k: v[1] for k, v in SUITES.items()},
        "input_sha256": args.approved_sha256, "source_inputs_unchanged": True})
    require(not failures, "; ".join(failures))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "network-child":
        print(json.dumps(network_child(int(sys.argv[2]))))
    elif len(sys.argv) == 5 and sys.argv[1] == "suite":
        suite(Path(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4]))
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--inputs", type=Path, required=True)
        parser.add_argument("--approved-sha256", required=True)
        parser.add_argument("--work", type=Path, required=True)
        parser.add_argument("--evidence", type=Path, required=True)
        run(parser.parse_args())
