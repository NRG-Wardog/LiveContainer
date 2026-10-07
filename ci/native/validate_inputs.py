#!/usr/bin/env python3
"""Independent, fail-closed acquisition of the frozen seven owner trees."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess

BASELINE = "141776ba6ba38fc04a5e77f68b0cfc4e6c8842ee"
OWNERS = {
    "LiveContainer": ("b226f9903a3c96acdb76fe32033569388e1e48cf", "30076d28fe5dc99d98fee842be56b340cb17a45c"),
    "SideStore": ("c4eb2705ed8dfd0dcb585cd41d21d54e4287f03e", "aee5909c3813560fea82e678d96c12bed34d0fc5"),
    "AnisetteKit": ("0d0b777d4d4308387fb5361bd70ce667ecbd7fe4", "77bfbe938fa967b2531305ddb9264f939c90dfd6"),
    "SideSign": ("c196183e22f1f551cf35c07f176e5aa0bad04751", "788b3adbcff935450845d57f31a33a92a497a71c"),
    "minimuxer": ("712310158c3f8e795a6a2bb2bd32c42464eea6d2", "30aa947645c5befb0c3210700095c8b039893d83"),
    "idevice": ("60731ad3903e716ddd002511b8f873bc412f4842", "0a911c3397ed8fd423f6b3da32a5e7d1d92dae23"),
    "jktcp": ("a1be799d60cd07061b8548e1c9e069a057c2257a", "6cd19fb9fa378477bfb58bd8f473049d3176b9d9"),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def approved_file(path, digest):
    require(re.fullmatch(r"[0-9a-f]{64}", digest or ""), "Missing independent reviewed SHA-256")
    require(path.is_file() and not path.is_symlink(), "Reviewed input absent or symlink: " + str(path))
    require(sha256(path) == digest, "Reviewed SHA-256 mismatch: " + str(path))


def load_map(path, approved_digest):
    approved_file(path, approved_digest)
    document = json.loads(path.read_text())
    require(set(document) == {"schema_version", "baseline", "owners"}, "Unknown reference-map fields")
    require(document["schema_version"] == 1 and document["baseline"] == BASELINE, "Wrong baseline/schema")
    require(set(document["owners"]) == set(OWNERS), "Exactly seven frozen owners required")
    for name, (original, tree) in OWNERS.items():
        entry = document["owners"][name]
        require(set(entry) == {"source_commit", "source_tree", "original_source_commit"}, "Unknown owner fields")
        require(entry["original_source_commit"] == original and entry["source_tree"] == tree,
                name + ": changed frozen identity/tree")
        require(re.fullmatch(r"[0-9a-f]{40}", entry["source_commit"] or ""),
                name + ": missing reviewed exact published commit")
    return document


def git(root, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0", GIT_ALLOW_PROTOCOL="https:file")
    return subprocess.check_output(
        ["git", "--no-replace-objects", "-c", "core.hooksPath=" + os.devnull,
         "-C", str(root), *args], env=env).decode().strip()


def verify_checkout(root, commit, tree):
    require(git(root, "rev-parse", "HEAD") == commit, "Checkout commit mismatch")
    require(git(root, "rev-parse", "HEAD^{tree}") == tree, "Checkout tree mismatch")
    require(git(root, "rev-parse", "--is-shallow-repository") == "false", "Full history required")
    require(not git(root, "status", "--porcelain=v1", "--untracked-files=all"), "Dirty source checkout")
    require(not git(root, "ls-files", "--others"), "Untracked or ignored source injection")
    require(not (root / ".git/objects/info/alternates").exists(), "Shared Git object alternates forbidden")
    for record in git(root, "ls-tree", "-r", "-z", "HEAD").split("\0"):
        if not record:
            continue
        metadata, relative = record.split("\t", 1)
        mode, kind, oid = metadata.split()
        path = root / relative
        if kind == "commit":
            require(path.is_dir() and not path.is_symlink() and not list(path.iterdir()),
                    "Pristine suite must not initialize child gitlinks")
            continue
        require(path.is_symlink() if mode == "120000" else path.is_file() and not path.is_symlink(),
                "Working input mode changed: " + relative)
        data = os.fsencode(os.readlink(path)) if mode == "120000" else path.read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        require(actual == oid, "Working input byte drift: " + relative)
        if mode != "120000":
            require(bool(path.stat().st_mode & stat.S_IXUSR) == (mode == "100755"),
                    "Working input executable mode drift: " + relative)


def fetch_owners(document, destination):
    require(not destination.exists() and not destination.is_symlink(), "Acquisition output must be new")
    destination.mkdir(parents=True)
    rows = {}
    for name, entry in document["owners"].items():
        root = destination / name
        root.mkdir()
        url = "https://github.com/NRG-Wardog/" + name + ".git"
        git(root, "init", "--quiet")
        git(root, "remote", "add", "origin", url)
        git(root, "config", "remote.origin.pushurl", "disabled://isolated-native-validation")
        # No depth, moving branch, submodule recursion, owner workflow or credentials.
        git(root, "fetch", "--no-tags", "--no-recurse-submodules", "origin", entry["source_commit"])
        git(root, "checkout", "--quiet", "--detach", entry["source_commit"])
        verify_checkout(root, entry["source_commit"], entry["source_tree"])
        rows[name] = {"remote": url, "commit": entry["source_commit"], "tree": entry["source_tree"],
                      "full_history": True, "push_disabled": True, "path": str(root)}
    return rows


def verify_submodules(root, output):
    expected = {"OpenSSL": "623c84da314e85363236507ca38a4bde65df21c3",
                "litehook": "8025e0c8ebdf5cdd1d2a4f45025813234bf9dc55"}
    rows = {}
    def check(parent, relative, commit):
        child = parent / relative
        require(child.resolve().is_relative_to(root.resolve()), "Submodule escaped LiveContainer")
        require(git(child, "rev-parse", "HEAD") == commit, "Submodule commit drift: " + relative)
        require(not git(child, "status", "--porcelain=v1", "--untracked-files=all"), "Dirty submodule")
        require(not git(child, "ls-files", "--others"), "Ignored/untracked submodule input")
        rows[str(child.relative_to(root))] = {"commit": commit, "tree": git(child, "rev-parse", "HEAD^{tree}")}
        for record in git(child, "ls-tree", "-r", "-z", "HEAD").split("\0"):
            if not record:
                continue
            metadata, name = record.split("\t", 1)
            mode, kind, oid = metadata.split()
            if kind == "commit":
                check(child, name, oid)
                continue
            path = child / name
            require(path.is_symlink() if mode == "120000" else path.is_file() and not path.is_symlink(),
                    "Submodule input type changed")
            data = os.fsencode(os.readlink(path)) if mode == "120000" else path.read_bytes()
            require(hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == oid,
                    "Submodule input bytes changed")
            if mode != "120000":
                require(bool(path.stat().st_mode & stat.S_IXUSR) == (mode == "100755"), "Submodule file mode drift")
    for relative, commit in expected.items():
        record = git(root, "ls-tree", "HEAD", relative)
        require(record == "160000 commit " + commit + "\t" + relative, "Frozen parent gitlink changed")
        check(root, relative, commit)
    output.write_text(json.dumps({"status": "PASS", "submodules": rows}, indent=2) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("approve", "fetch", "verify-pristine", "verify-submodules"))
    p.add_argument("--map", type=Path, required=True)
    p.add_argument("--approved-sha256", required=True)
    p.add_argument("--assembler", type=Path)
    p.add_argument("--assembler-sha256")
    p.add_argument("--root", type=Path)
    p.add_argument("--report", type=Path)
    a = p.parse_args()
    document = load_map(a.map, a.approved_sha256)
    if a.action == "approve":
        require(a.assembler is not None, "Reviewed assembler is required")
        approved_file(a.assembler, a.assembler_sha256)
        spec = importlib.util.spec_from_file_location("reviewed_assembler", a.assembler)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.owner_references(a.map, a.approved_sha256)
        if a.report:
            a.report.write_text(json.dumps({"status": "PASS", "baseline": BASELINE,
                "approved_reference_map_sha256": a.approved_sha256,
                "approved_assembler_sha256": a.assembler_sha256,
                "validation_host_commit": os.environ.get("GITHUB_SHA"),
                "validation_host_repository": os.environ.get("GITHUB_REPOSITORY"),
                "run_id": os.environ.get("GITHUB_RUN_ID"),
                "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT")}, indent=2) + "\n")
        print("PASS: independently pinned complete owner map and reviewed assembler")
        return
    require(a.root is not None and a.report is not None, "Root/report required")
    if a.action == "verify-submodules":
        verify_submodules(a.root, a.report)
        return
    if a.action == "fetch":
        rows = fetch_owners(document, a.root)
    else:
        rows = {}
        for name, entry in document["owners"].items():
            verify_checkout(a.root / name, entry["source_commit"], entry["source_tree"])
            rows[name] = {"commit": entry["source_commit"], "tree": entry["source_tree"], "pristine": True}
    a.report.write_text(json.dumps({"status": "PASS", "baseline": BASELINE,
        "approved_reference_map_sha256": a.approved_sha256, "owners": rows}, indent=2) + "\n")


if __name__ == "__main__":
    main()
