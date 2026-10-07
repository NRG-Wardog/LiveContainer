#!/usr/bin/env python3
"""Assemble a disposable seven-owner build input; never edit or publish owners.

This is test plumbing, not the production/runtime parity tree. It performs no
network access, installs, compilation, workflow dispatch, or runtime-source transforms.
External SwiftPM resolution must pass the separate provenance gate before build.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import stat
import subprocess

BASELINE = "141776ba6ba38fc04a5e77f68b0cfc4e6c8842ee"
OWNERS = {
    "LiveContainer": ("33dd0ff070441fcfa79f3375cf898a6ec33e72ad", "f9d8560f6f35c26a66feeeb99e6ac0091d79a98b", "LiveContainer"),
    "SideStore": ("d73fd17cd7b93385c860357293ec471dd7c93628", "5e8345fb845f9954322dc9200480947f2b1827bc", "SideStore"),
    "AnisetteKit": ("0d0b777d4d4308387fb5361bd70ce667ecbd7fe4", "77bfbe938fa967b2531305ddb9264f939c90dfd6", "AnisetteKit"),
    "SideSign": ("c196183e22f1f551cf35c07f176e5aa0bad04751", "788b3adbcff935450845d57f31a33a92a497a71c", "SideStore/Dependencies/SideSign"),
    "minimuxer": ("712310158c3f8e795a6a2bb2bd32c42464eea6d2", "30aa947645c5befb0c3210700095c8b039893d83", "SideStore/Dependencies/minimuxer"),
    "idevice": ("60731ad3903e716ddd002511b8f873bc412f4842", "0a911c3397ed8fd423f6b3da32a5e7d1d92dae23", "idevice"),
    "jktcp": ("a1be799d60cd07061b8548e1c9e069a057c2257a", "6cd19fb9fa378477bfb58bd8f473049d3176b9d9", "jktcp"),
}
APP_LOCK = "AltStore.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved"
LOCAL_OWNER_DEPENDENCIES = {
    "sidestore": {"sidesign": OWNERS["SideSign"][2], "minimuxer": OWNERS["minimuxer"][2], "anisettekit": "AnisetteKit"},
    "sidesign": {"anisettekit": "AnisetteKit"},
}


def git(path, *args):
    return git_bytes(path, *args).decode().strip()


def git_bytes(path, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0", GIT_ALLOW_PROTOCOL="file")
    return subprocess.check_output(
        ["git", "--no-replace-objects", "-c", "core.hooksPath=" + os.devnull, "-C", str(path), *args],
        env=env, stderr=subprocess.PIPE,
    )


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pins(path):
    return document_pins(json.loads(path.read_text()))


def document_pins(document):
    result = {}
    for pin in document["pins"]:
        identity = pin["identity"].lower()
        if identity in result:
            raise ValueError(f"Duplicate dependency identity: {identity}")
        result[identity] = {"location": pin["location"], "state": pin["state"]}
    return result


def owner_references(reference_map=None, approved_sha256=None):
    """The approval digest must come from a separately reviewed caller/configuration.

    Never read an approval digest from the candidate workspace manifest itself.
    A map can select remapped published commits, but cannot change frozen trees.
    """
    if reference_map is None and approved_sha256 is None:
        return dict(OWNERS), None
    if reference_map is None or not re.fullmatch(r"[0-9a-f]{64}", approved_sha256 or ""):
        raise ValueError("A reference map requires its independently reviewed SHA-256")
    if digest(reference_map) != approved_sha256:
        raise ValueError("Owner reference map does not match reviewed SHA-256")
    document = json.loads(reference_map.read_text())
    if document.get("schema_version") != 1 or document.get("baseline") != BASELINE or set(document.get("owners", {})) != set(OWNERS):
        raise ValueError("Owner reference map has wrong schema, baseline, or owner set")
    references = {}
    for owner, (original_sha, tree, relative) in OWNERS.items():
        entry = document["owners"][owner]
        sha = entry.get("source_commit", "")
        if entry.get("original_source_commit") != original_sha or entry.get("source_tree") != tree or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError(owner + ": reference map changes frozen identity/tree")
        references[owner] = (sha, tree, relative)
    return references, approved_sha256


def checked_path(workspace, relative):
    candidate = workspace / relative
    if not candidate.resolve().is_relative_to(workspace.resolve()):
        raise ValueError("Input path escapes isolated workspace: " + relative)
    return candidate


def local_sign_manifest(original):
    pattern = r'\.package\(url: "https://github\.com/mahee96/AnisetteKit\.git",\s+branch: "main"\)'
    changed, count = re.subn(pattern, '.package(name: "AnisetteKit", path: "../../../AnisetteKit")', original)
    if count != 1:
        raise ValueError("Expected exactly one SideSign -> AnisetteKit dependency")
    return changed


def local_lock(original):
    document = json.loads(original)
    frozen = document_pins(document)
    if frozen.pop("anisettekit")["state"]["revision"] != "1f5a7e36553cc865b873f222b87a6486c0bcc7bf":
        raise ValueError("Unexpected frozen remote AnisetteKit pin")
    document["pins"] = [p for p in document["pins"] if p["identity"].lower() != "anisettekit"]
    document.pop("originHash", None)
    return json.dumps(document, indent=2) + "\n", frozen


def blob_id(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def tree_entries(repo, revision):
    entries = {}
    for record in git(repo, "ls-tree", "-r", "-z", revision).split("\0"):
        if record:
            metadata, path = record.split("\t", 1)
            mode, _, object_id = metadata.split()
            entries[path] = (mode, object_id)
    return entries


def verify_worktree_bytes(repo, entries, generated=()):
    """Do not let Git index flags hide changed compiler inputs."""
    for relative, (mode, object_id) in entries.items():
        if mode == "160000" or relative in generated:
            continue  # Child repositories/generated artifacts have separate gates.
        path = repo / relative
        if mode == "120000":
            if not path.is_symlink():
                raise ValueError("Working input symlink type changed: " + relative)
            data = os.fsencode(os.readlink(path))
        else:
            if not path.is_file() or path.is_symlink():
                raise ValueError("Working input file type changed: " + relative)
            data = path.read_bytes()
            if bool(path.stat().st_mode & stat.S_IXUSR) != (mode == "100755"):
                raise ValueError("Working input executable mode changed: " + relative)
        if blob_id(data) != object_id:
            raise ValueError("Working input bytes differ from frozen overlay: " + relative)


def expected_index(repo, owner, references):
    """Derive allowed staged entries from immutable objects, not candidate metadata."""
    sha, _, _ = references[owner]
    entries = tree_entries(repo, sha)
    overlays = {}
    if owner == "SideStore":
        entries["Dependencies/SideSign"] = ("160000", references["SideSign"][0])
        entries["Dependencies/minimuxer"] = ("160000", references["minimuxer"][0])
        overlays[APP_LOCK] = local_lock(git(repo, "show", sha + ":" + APP_LOCK))[0]
    elif owner == "SideSign":
        original = git_bytes(repo, "show", sha + ":Package.swift").decode()
        overlays["Package.swift"] = local_sign_manifest(original)
        overlays["Package.resolved"] = local_lock(git(repo, "show", sha + ":Package.resolved"))[0]
    for relative, content in overlays.items():
        entries[relative] = (entries[relative][0], blob_id(content.encode()))
    return entries


def expected_overrides(workspace, references):
    result = []
    for owner, relative, kind in (
        ("SideSign", "Package.swift", "test-only local owner dependency"),
        ("SideStore", APP_LOCK, "test-only lock excludes local owner; all external pins retained"),
        ("SideSign", "Package.resolved", "test-only lock excludes local owner; all external pins retained"),
    ):
        sha, _, repo_relative = references[owner]
        original = git_bytes(workspace / repo_relative, "show", sha + ":" + relative)
        changed = local_sign_manifest(original.decode()) if relative == "Package.swift" else local_lock(original.decode())[0]
        result.append({"path": repo_relative + "/" + relative, "kind": kind,
                       "before_sha256": hashlib.sha256(original).hexdigest(),
                       "after_sha256": hashlib.sha256(changed.encode()).hexdigest()})
    return result


def assemble(source_root, output, reference_map=None, approved_sha256=None):
    references, reference_digest = owner_references(reference_map, approved_sha256)
    source_root = source_root.resolve(strict=True)
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("Output must be a new directory; existing output is never overwritten")
    resolved_output = output.parent.resolve(strict=True) / output.name
    for owner in OWNERS:
        source = source_root / owner
        if resolved_output.is_relative_to(source.resolve()):
            raise ValueError("Output cannot be inside an owner checkout")
        sha, tree, _ = references[owner]
        if git(source, "rev-parse", "HEAD") != sha:
            raise ValueError(f"{owner}: unexpected source HEAD")
        if git(source, "rev-parse", sha + "^{tree}") != tree:
            raise ValueError(f"{owner}: unexpected source tree")
        if git(source, "status", "--porcelain=v1", "--untracked-files=all"):
            raise ValueError(f"{owner}: source checkout is dirty")
    output.mkdir()
    (output / "ASSEMBLY_INCOMPLETE").write_text("Do not build an incomplete assembly.\n")
    manifest = {
        "schema_version": 1,
        "purpose": "DISPOSABLE TEST ASSEMBLY, NOT PRODUCTION SOURCE OR ACTIVATION",
        "baseline": BASELINE,
        "owners": {},
        "overrides": [],
        "resolution_status": "NOT_RUN; fail-closed resolver gate required before build",
        "build_status": "NOT_RUN",
        "network_or_device_tests_allowed": False,
        "owner_reference_map_sha256": reference_digest,
    }
    for owner, (sha, tree, relative) in references.items():
        source = source_root / owner
        dest = output / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_dir():
            dest.rmdir()  # Only Git's empty, uninitialized submodule directory.
        git(output, "clone", "--local", "--no-hardlinks", "--no-checkout",
            "--no-recurse-submodules", "--quiet", str(source), str(dest))
        git(dest, "checkout", "--detach", "--quiet", sha)
        git(dest, "config", "remote.origin.pushurl", "disabled://test-assembly")
        manifest["owners"][owner] = {
            "path": relative, "source_commit": sha, "source_tree": tree,
            "production_checkout": str(source),
        }
    app = output / "SideStore"
    sign = output / OWNERS["SideSign"][2]
    sign_manifest = sign / "Package.swift"
    before = digest(sign_manifest)
    text = sign_manifest.read_text()
    sign_manifest.write_text(local_sign_manifest(text))
    manifest["overrides"].append({"path": str(sign_manifest.relative_to(output)),
        "kind": "test-only local owner dependency", "before_sha256": before,
        "after_sha256": digest(sign_manifest)})
    for label, lock in (("sidestore", app / APP_LOCK), ("sidesign", sign / "Package.resolved")):
        changed, frozen = local_lock(lock.read_text())
        manifest[label + "_expected_external_pins"] = frozen
        before = digest(lock)
        lock.write_text(changed)
        manifest["overrides"].append({"path": str(lock.relative_to(output)),
            "kind": "test-only lock excludes local owner; all external pins retained",
            "before_sha256": before, "after_sha256": digest(lock)})
    manifest["local_owner_dependencies"] = LOCAL_OWNER_DEPENDENCIES
    manifest["binary_build_input"] = {
        "path": OWNERS["minimuxer"][2] + "/DeviceGateway/LocalBinary/IDevice.xcframework",
        "status": "ABSENT; must build from this idevice + jktcp assembly on macOS",
    }
    manifest["uninitialized_livecontainer_gitlinks"] = git(output / "LiveContainer", "ls-tree", "HEAD", "OpenSSL", "litehook")
    manifest["anisette_native_ci"] = {
        "url": "https://github.com/NRG-Wardog/AnisetteKit/actions/runs/37647998503",
        "commit": "62ce85c8798d8eab8e29752aba7dc9f1f6a5b80d",
        "tree": "77bfbe938fa967b2531305ddb9264f939c90dfd6",
        "scope": "Parent-reported successful synthetic native boundary tests, not Swift/Xcode",
    }
    # Index-tree IDs describe test overlays; no commit or production gitlink is changed.
    for owner in reversed(list(OWNERS)):
        entry = manifest["owners"][owner]
        dest = output / entry["path"]
        git(dest, "add", "-A")
        entry["assembled_index_tree"] = git(dest, "write-tree")
        entry["overlay_diff"] = git(dest, "diff", "--cached", "--name-status", "HEAD")
    manifest["toolchain_available"] = {name: shutil.which(name) for name in (
        "python3", "gcc", "g++", "swift", "swiftc", "xcodebuild", "xcrun", "cargo", "rustc", "clang")}
    for owner, (sha, _, _) in references.items():
        if git(source_root / owner, "rev-parse", "HEAD") != sha or git(source_root / owner, "status", "--porcelain=v1", "--untracked-files=all"):
            raise ValueError(f"{owner}: original source changed during assembly")
    (output / "test-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (output / "ASSEMBLY_INCOMPLETE").unlink()
    print(json.dumps({"assembled": str(output), "manifest_sha256": digest(output / "test-manifest.json"), "native_build_run": False}))


def verify_inputs(workspace, reference_map=None, approved_sha256=None):
    """Reject runtime/manifest drift; allow only named generated build outputs."""
    workspace = workspace.resolve(strict=True)
    if (workspace / "ASSEMBLY_INCOMPLETE").exists():
        raise ValueError("Incomplete assembly")
    manifest = json.loads((workspace / "test-manifest.json").read_text())
    references, reference_digest = owner_references(reference_map, approved_sha256)
    if manifest.get("schema_version") != 1 or manifest.get("baseline") != BASELINE or set(manifest.get("owners", {})) != set(OWNERS):
        raise ValueError("Manifest has wrong schema, baseline, or owner set")
    if manifest.get("owner_reference_map_sha256") != reference_digest:
        raise ValueError("Candidate owner mapping lacks independent matching approval")
    if manifest.get("local_owner_dependencies") != LOCAL_OWNER_DEPENDENCIES:
        raise ValueError("Manifest local owner dependencies changed")
    generated_tracked = {
        "SideStore": {APP_LOCK}, "SideSign": {"Package.resolved"},
        "idevice": {"ffi/idevice.h", "cpp/include/idevice.h", "swift/include/idevice.h"},
    }
    generated_prefixes = {
        "SideStore": ("build/",),
        "minimuxer": ("DeviceGateway/LocalBinary/IDevice.xcframework/",),
        "idevice": ("target/", "swift/IDevice.xcframework/", "swift/libs/"),
    }
    for owner, entry in manifest["owners"].items():
        sha, tree, relative = references[owner]
        if (entry.get("source_commit"), entry.get("source_tree"), entry.get("path")) != (sha, tree, relative):
            raise ValueError(owner + ": candidate changed approved owner identity/path/tree")
        repo = checked_path(workspace, relative)
        if git(repo, "rev-parse", "HEAD") != sha or git(repo, "rev-parse", "HEAD^{tree}") != tree or git(repo, "write-tree") != entry["assembled_index_tree"]:
            raise ValueError(owner + ": test-assembly base or staged tree changed")
        staged = {}
        for record in git(repo, "ls-files", "--stage", "-z").split("\0"):
            if record:
                metadata, path = record.split("\t", 1)
                mode, object_id, stage = metadata.split()
                if stage != "0" or path in staged:
                    raise ValueError(owner + ": conflicted or duplicate staged input")
                staged[path] = (mode, object_id)
        expected = expected_index(repo, owner, references)
        if staged != expected:
            raise ValueError(owner + ": staged tree differs from frozen source plus approved overlays")
        verify_worktree_bytes(repo, expected, generated_tracked.get(owner, set()))
        dirty = set(filter(None, git(repo, "diff", "--name-only", "--ignore-submodules=all").splitlines()))
        if dirty - generated_tracked.get(owner, set()):
            raise ValueError(owner + ": unexpected tracked input drift: " + repr(sorted(dirty)))
        # Deliberately include ignored files. An ignored Swift file is still an input risk.
        untracked = list(filter(None, git(repo, "ls-files", "--others", "-z").split("\0")))
        unexpected = [p for p in untracked if p not in generated_tracked.get(owner, set())
                      and not p.startswith(generated_prefixes.get(owner, ()))]
        if unexpected:
            raise ValueError(owner + ": unexpected untracked/ignored input: " + repr(unexpected))
    if manifest.get("overrides") != expected_overrides(workspace, references):
        raise ValueError("Manifest overlay paths or hashes differ from reviewed source transformations")
    for label, lock in (("sidestore", workspace / "SideStore" / APP_LOCK),
                        ("sidesign", workspace / OWNERS["SideSign"][2] / "Package.resolved")):
        owner = "SideStore" if label == "sidestore" else "SideSign"
        relative = APP_LOCK if label == "sidestore" else "Package.resolved"
        _, frozen = local_lock(git(workspace / references[owner][2], "show", references[owner][0] + ":" + relative))
        if manifest.get(label + "_expected_external_pins") != frozen or pins(lock) != frozen:
            raise ValueError(label + ": test lock changed pinned external dependencies")
    return manifest


def verify_binary_prerequisite(workspace):
    """Reject an absent/malformed device slice; this does not prove compilation."""
    relative = OWNERS["minimuxer"][2] + "/DeviceGateway/LocalBinary/IDevice.xcframework"
    framework = checked_path(workspace, relative)
    info = framework / "Info.plist"
    if not info.is_file():
        raise ValueError("Missing locally built IDevice.xcframework prerequisite; do not build")
    try:
        document = plistlib.loads(info.read_bytes())
        matches = [lib for lib in document["AvailableLibraries"]
                   if lib.get("SupportedPlatform") == "ios" and not lib.get("SupportedPlatformVariant")
                   and "arm64" in lib.get("SupportedArchitectures", [])]
        if len(matches) != 1:
            raise ValueError("Expected exactly one iOS arm64 IDevice static-library slice")
        lib = matches[0]
        root = relative + "/" + lib["LibraryIdentifier"]
        inputs = [root + "/" + lib["LibraryPath"],
                  root + "/" + lib["HeadersPath"] + "/idevice.h",
                  root + "/" + lib["HeadersPath"] + "/module.modulemap",
                  relative + "/Info.plist"]
        if not lib["LibraryPath"].endswith(".a"):
            raise ValueError("Expected an IDevice static library")
        records = {}
        for path in inputs:
            file = checked_path(workspace, path)
            if not file.resolve().is_relative_to(framework.resolve()) or not file.is_file() or file.stat().st_size == 0:
                raise ValueError("Incomplete or escaped IDevice binary prerequisite")
            records[path] = digest(file)
        return {"status": "PRESENT_NOT_COMPILE_PROOF", "sha256": records}
    except (KeyError, TypeError, plistlib.InvalidFileException) as error:
        raise ValueError("Malformed IDevice.xcframework prerequisite") from error


def verify_resolution(workspace, label, state_file, lock_file, reference_map=None, approved_sha256=None):
    workspace = workspace.resolve(strict=True)
    # A failed rerun must not leave an older PASS artifact looking current.
    dest = workspace / (label + "-resolution-evidence.json")
    dest.unlink(missing_ok=True)
    if (workspace / "ASSEMBLY_INCOMPLETE").exists():
        raise ValueError("Incomplete assembly")
    manifest = verify_inputs(workspace, reference_map, approved_sha256)
    expected = manifest[label + "_expected_external_pins"]
    actual = pins(lock_file)
    if actual != expected:
        raise ValueError("Resolved external pins changed, or remote owner reappeared; do not build")
    local = manifest["local_owner_dependencies"][label]
    doc = json.loads(state_file.read_text())
    deps = doc["object"]["dependencies"]  # Unknown formats fail closed.
    if not isinstance(deps, list):
        raise ValueError("Unknown workspace-state dependency format")
    seen = set()
    checkout_records = {}
    for dep in deps:
        ref = dep["packageRef"]
        identity = ref["identity"].lower()
        if identity in seen:
            raise ValueError("Duplicate package identity in workspace-state: " + identity)
        seen.add(identity)
        location = ref["location"]
        if identity in local:
            if ref["kind"] != "fileSystem" or not Path(location).is_absolute() or Path(location).resolve() != (workspace / local[identity]).resolve():
                raise ValueError("Owner resolved outside explicit local assembly: " + identity)
            checkout_records[identity] = {"kind": "fileSystem", "location": location}
        elif identity in expected:
            if ref["kind"] != "remoteSourceControl" or location != expected[identity]["location"]:
                raise ValueError("Unexpected remote location/kind: " + identity)
            state = dep["state"]
            if state["name"] != "sourceControlCheckout" or state["checkoutState"]["revision"] != expected[identity]["state"]["revision"]:
                raise ValueError("Unexpected resolved checkout revision: " + identity)
            checkout = state_file.parent / "checkouts" / dep["subpath"]
            if not checkout.resolve().is_relative_to((state_file.parent / "checkouts").resolve()):
                raise ValueError("Checkout escapes isolated resolver storage")
            if git(checkout, "rev-parse", "HEAD") != expected[identity]["state"]["revision"] or git(checkout, "status", "--porcelain=v1", "--untracked-files=all"):
                raise ValueError("External dependency checkout revision/content mismatch: " + identity)
            if git(checkout, "ls-files", "--others", "-z"):
                raise ValueError("Unexpected untracked/ignored external dependency input: " + identity)
            verify_worktree_bytes(checkout, tree_entries(checkout, "HEAD"))
            checkout_records[identity] = {"location": location, "commit": git(checkout, "rev-parse", "HEAD"), "tree": git(checkout, "rev-parse", "HEAD^{tree}")}
        elif identity not in {"common", "devicegateway"} or label != "sidestore":
            raise ValueError("Unreviewed transitive dependency: " + identity)
        else:
            name = {"common": "Common", "devicegateway": "DeviceGateway"}[identity]
            target = workspace / OWNERS["minimuxer"][2] / name
            if ref["kind"] != "fileSystem" or not Path(location).is_absolute() or Path(location).resolve() != target.resolve():
                raise ValueError("Minimuxer child package escaped assembly")
            checkout_records[identity] = {"kind": "fileSystem", "location": location}
    if not set(local).issubset(seen) or not set(expected).issubset(seen):
        raise ValueError("Workspace-state does not prove all expected owner/external identities; do not build")
    if label == "sidestore" and not {"common", "devicegateway"}.issubset(seen):
        raise ValueError("Workspace-state omits required minimuxer child packages; do not build")
    binary = verify_binary_prerequisite(workspace) if label == "sidestore" else None
    evidence = {"scope": label, "status": "PASS", "test_manifest_sha256": digest(workspace / "test-manifest.json"),
        "resolved_lock_sha256": digest(lock_file), "workspace_state_sha256": digest(state_file),
        "dependencies": checkout_records,
        "binary_prerequisite": binary,
        "limitation": "Resolver provenance only; binary artifact hashes and compile-input paths still require build evidence"}
    dest.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({"passed": label, "evidence": str(dest)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    a = sub.add_parser("assemble")
    a.add_argument("--source-root", type=Path, required=True)
    a.add_argument("--out", type=Path, required=True)
    v = sub.add_parser("verify-resolution")
    v.add_argument("--workspace", type=Path, required=True)
    v.add_argument("--scope", choices=["sidestore", "sidesign"], required=True)
    v.add_argument("--state", type=Path, required=True)
    v.add_argument("--lock", type=Path, required=True)
    i = sub.add_parser("verify-inputs")
    i.add_argument("--workspace", type=Path, required=True)
    for command in (a, v, i):
        command.add_argument("--owner-reference-map", type=Path)
        command.add_argument("--owner-reference-map-sha256")
    args = parser.parse_args()
    if args.action == "assemble":
        assemble(args.source_root, args.out, args.owner_reference_map, args.owner_reference_map_sha256)
    elif args.action == "verify-resolution":
        verify_resolution(args.workspace, args.scope, args.state, args.lock, args.owner_reference_map, args.owner_reference_map_sha256)
    else:
        verify_inputs(args.workspace, args.owner_reference_map, args.owner_reference_map_sha256)
        print("PASS: assembled source inputs unchanged except explicitly named generated outputs")


if __name__ == "__main__":
    main()
