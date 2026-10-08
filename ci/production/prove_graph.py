#!/usr/bin/env python3
"""Prove the actual committed production graph; never transform package sources."""
import argparse
import hashlib
import json
import os
import plistlib
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "native"))
from validate_inputs import git as acquisition_git, require, approved_file
from assemble_isolated_workspace import verify_worktree_bytes
from collect_provenance import rust_link_inputs
from generated_xcode_sources import verify_generated_sources, expected_sources

BASELINE = "141776ba6ba38fc04a5e77f68b0cfc4e6c8842ee"
ALL_OWNERS = {"LiveContainer", "SideStore", "SideSign", "AnisetteKit", "minimuxer", "idevice", "jktcp"}
ANISETTE = {"identity": "anisettekit", "kind": "remoteSourceControl",
    "location": "https://github.com/NRG-Wardog/AnisetteKit.git",
    "state": {"revision": "62ce85c8798d8eab8e29752aba7dc9f1f6a5b80d"}}
APP_LOCK = "AltStore.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved"
DIAGNOSTIC_REGISTRY = "97c9d0b81e9b59c8271ae1155393b2fcb534dc97ea367095d3adfcde8a3783ad"
DIAGNOSTIC_DELTA = "4d55fdeed931af02f9d44865c0c712695b471d8a101aa1643c3770484f158106"


def diagnostic_basis(data, phase):
    """Bind the new dependency candidate to separately approved source-only data."""
    require(phase == "sidesign", "Diagnostic two-app inputs need their later reviewed dependency closure")
    directory = Path(__file__).resolve().parent / "diagnostic"
    delta_path = directory / "accepted-to-diagnostic-delta.json"
    approved_file(delta_path, DIAGNOSTIC_DELTA)
    delta = json.loads(delta_path.read_text())
    require(data.get("source_basis") == "maintained-adi-consumption-v1" and
            data.get("source_registry_sha256") == DIAGNOSTIC_REGISTRY and
            data.get("accepted_integration") == delta["accepted_integration"]["commit"],
            "Unreviewed diagnostic source basis")
    expected = delta["diagnostic_source_tuple"]["AnisetteKit"]
    anisette = data["owners"]["AnisetteKit"]
    require(anisette["source_commit"] == expected["commit"] and anisette["source_tree"] == expected["tree"],
            "Diagnostic Anisette source identity changed")
    descriptor = data.get("dependency_basis", {})
    require(set(descriptor) == {"path", "sha256"} and descriptor["path"] == "diagnostic/dependencies/SideSign-basis.json",
            "Exact SideSign dependency basis path required")
    basis_path = Path(__file__).resolve().parent / descriptor["path"]
    approved_file(basis_path, descriptor["sha256"])
    basis = json.loads(basis_path.read_text())
    accepted = delta["accepted_graph"]["SideSign"]
    require(basis.get("accepted") == {"commit": accepted["commit"], "tree": accepted["tree"]} and
            basis.get("source_registry_sha256") == DIAGNOSTIC_REGISTRY and
            basis.get("candidate") == {"commit": data["owners"]["SideSign"]["source_commit"],
                                       "tree": data["owners"]["SideSign"]["source_tree"]},
            "SideSign candidate is not bound to its accepted source transition")
    return basis_path, descriptor["sha256"]


# Git binding and one-hop origin proof match reviewed integration b783a64b.
def git_bytes(root, *arguments, bare=False):
    root = Path(root).resolve(strict=True)
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_NO_REPLACE_OBJECTS="1", GIT_GRAFT_FILE=os.devnull,
               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", GIT_NO_LAZY_FETCH="1")
    location = ["--git-dir=" + str(root)] if bare else ["--git-dir=" + str(root / ".git"), "--work-tree=" + str(root)]
    return subprocess.check_output(["git", "--no-replace-objects", "-C", str(root), *location,
        "-c", "core.hooksPath=" + os.devnull, "-c", "core.fsmonitor=false",
        "-c", "core.untrackedCache=false", *arguments], env=env, stderr=subprocess.PIPE)


def verify_origin(root, expected_url, commit, resolver_root=None):
    """Verify direct origins, or SwiftPM's bounded checkout -> bare mirror chain.

    Noneditable SwiftPM checkouts use `clone --shared --no-checkout`, retaining
    the local canonical repository as origin. Never rewrite it to appear remote.
    """
    root = Path(root).resolve(strict=True)
    require(git_bytes(root, "rev-parse", "HEAD").decode().strip() == commit, "origin proof checkout commit mismatch")
    origin = git_bytes(root, "remote", "get-url", "origin").decode().strip()
    if resolver_root is not None:
        resolver_root = Path(resolver_root).resolve(strict=True)
        checkouts = resolver_root / "checkouts"
        require(not checkouts.is_symlink() and root.parent == checkouts,
                "resolver checkout escaped approved storage")
    if origin.removesuffix(".git") == expected_url.removesuffix(".git"):
        return {"kind": "direct", "repository": expected_url}
    require(resolver_root is not None and Path(origin).is_absolute(), "wrong acquisition repository")
    resolver_root = Path(resolver_root).resolve(strict=True)
    checkouts, repositories = resolver_root / "checkouts", resolver_root / "repositories"
    require(not checkouts.is_symlink() and not repositories.is_symlink() and
            root.parent == checkouts, "resolver repository root escaped approved storage")
    mirror_input = Path(origin)
    mirror = mirror_input.resolve(strict=True)
    require(not mirror_input.is_symlink() and mirror.parent == repositories and
            not (mirror / "objects").is_symlink(), "resolver mirror escaped approved storage")
    require(git_bytes(mirror, "rev-parse", "--is-bare-repository", bare=True).strip() == b"true", "resolver mirror is not bare")
    upstream = git_bytes(mirror, "remote", "get-url", "origin", bare=True).decode().strip()
    require(upstream.removesuffix(".git") == expected_url.removesuffix(".git"), "resolver mirror upstream repository mismatch")
    require(git_bytes(mirror, "rev-parse", "--is-shallow-repository", bare=True).strip() == b"false", "shallow resolver mirror")
    # Permit exactly the object-sharing relationship created by clone --shared.
    # A second mirror/cache hop requires separately reviewed native evidence.
    require(not (mirror / "objects/info/alternates").exists(), "unapproved nested resolver object store")
    gitdir = Path(git_bytes(root, "rev-parse", "--absolute-git-dir").decode().strip()).resolve(strict=True)
    alternates = gitdir / "objects/info/alternates"
    if alternates.exists():
        require(not alternates.is_symlink(), "substituted resolver object store")
        paths = alternates.read_text().splitlines()
        require(len(paths) == 1 and Path(paths[0]).is_absolute() and
                Path(paths[0]).resolve(strict=True) == mirror / "objects", "resolver object store escaped approved mirror")
    require(git_bytes(mirror, "rev-parse", commit + "^{commit}", bare=True).decode().strip() == commit,
            "resolver mirror lacks exact commit")
    tree = git_bytes(root, "rev-parse", "HEAD^{tree}").decode().strip()
    require(git_bytes(mirror, "rev-parse", commit + "^{tree}", bare=True).decode().strip() == tree,
            "resolver mirror tree differs from checkout")
    return {"kind": "swiftpm-local-mirror", "repository": expected_url,
            "mirror": str(mirror), "commit": commit, "tree": tree}


def git(root, *arguments, bare=False):
    return git_bytes(root, *arguments, bare=bare).decode().strip()


def tree_entries(root, revision):
    result = {}
    for record in git_bytes(root, "ls-tree", "-rz", revision).split(b"\0"):
        if record:
            metadata, name = record.split(b"\t", 1)
            mode, _, oid = metadata.decode().split()
            result[os.fsdecode(name)] = (mode, oid)
    return result


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_inputs(path, digest, phase):
    approved_file(path, digest)
    data = json.loads(path.read_text())
    require(data.get("schema_version") == 1 and data.get("baseline") == BASELINE and data.get("phase") == phase,
            "Wrong production phase, baseline or schema")
    expected = {"SideSign", "AnisetteKit"} if phase == "sidesign" else ALL_OWNERS
    require(set(data.get("owners", {})) == expected, "Incomplete production owner set")
    for owner, entry in data["owners"].items():
        require(entry.get("repository") == "NRG-Wardog/" + owner, "Unexpected owner repository")
        require(re.fullmatch(r"[0-9a-f]{40}", (entry.get("source_commit") or "")) and
                re.fullmatch(r"[0-9a-f]{40}", (entry.get("source_tree") or "")),
                owner + ": verified published commit/tree required")
    if data.get("source_basis") is not None:
        diagnostic_basis(data, phase)
        return data
    require(data["owners"]["AnisetteKit"]["source_commit"] == ANISETTE["state"]["revision"], "Anisette owner pin changed")
    native_map = Path(__file__).resolve().parents[1] / "native/owner-reference-map.json"
    approved_file(native_map, "e8f8ff60cafa78db7f6b1cd95b08d39c7d7cab964899784135382f919da762d4")
    frozen = json.loads(native_map.read_text())["owners"]
    for owner, entry in data["owners"].items():
        if owner not in {"SideSign", "SideStore"}:
            require(entry["source_commit"] == frozen[owner]["source_commit"] and
                    entry["source_tree"] == frozen[owner]["source_tree"], "Unchanged owner input drift: " + owner)
    if phase == "sidestore":
        require(data.get("sidesign_lock_metadata_reviewed") is True, "Final SideSign resolver metadata review missing")
    return data


def owner_path(root, owner, phase):
    if phase == "sidestore" and owner in {"SideSign", "minimuxer"}:
        return root / "SideStore/Dependencies" / owner
    return root / owner


def verify_source(root, owner, entry, lock=None, built=False):
    root = root.resolve(strict=True)
    require(git(root, "rev-parse", "HEAD") == entry["source_commit"], owner + ": wrong HEAD")
    require(git(root, "rev-parse", "HEAD^{tree}") == entry["source_tree"], owner + ": wrong tree")
    require(git(root, "rev-parse", "--is-shallow-repository") == "false", owner + ": shallow source")
    require(git(root, "write-tree") == entry["source_tree"], owner + ": staged source changed")
    origin = git(root, "config", "--get", "remote.origin.url")
    if "repository" in entry:
        require(origin == "https://github.com/" + entry["repository"] + ".git", owner + ": source origin changed")
    allowed = {lock} if lock else set()
    if built and owner == "idevice":
        allowed.update({"ffi/idevice.h", "cpp/include/idevice.h", "swift/include/idevice.h"})
    if built and owner == "SideStore":
        allowed.add("build/SideBackup.ipa")
    records = tree_entries(root, entry["source_commit"])
    for relative in records:
        for parent in (root / relative).parents:
            if parent == root:
                break
            require(not parent.is_symlink(), owner + ": substituted source parent: " + relative)
    verify_worktree_bytes(root, records, generated=allowed)
    if lock:
        target = root / lock
        require(target.is_file() and not target.is_symlink() and stat.S_ISREG(target.lstat().st_mode), "Unsafe lock output")
        require(not (target.stat().st_mode & 0o111), "Lock output executable mode drift")
    prefixes = ()
    if built:
        prefixes = {"SideStore": ("build/sidebackup.xcarchive/",), "minimuxer": ("DeviceGateway/LocalBinary/IDevice.xcframework/",),
                    "idevice": ("swift/IDevice.xcframework/",)}.get(owner, ())
    untracked = [p for p in git(root, "ls-files", "--others", "-z").split("\0") if p]
    unexpected = [p for p in untracked if p not in allowed and not p.startswith(prefixes)]
    require(not unexpected, owner + ": unreviewed generated/untracked paths: " + repr(unexpected))
    return {"commit": entry["source_commit"], "tree": entry["source_tree"], "origin": origin,
            "status": "PASS", "allowed_lock": lock}


def pin_map(lock):
    result = {}
    require(lock.get("version") == 3, "Unexpected resolver lock schema")
    require(set(lock).issubset({"version", "pins", "originHash"}) and {"version", "pins"}.issubset(lock), "Unknown lock fields")
    for pin in lock["pins"]:
        key = pin["identity"].lower()
        require(key not in result, "Duplicate package identity")
        result[key] = pin
    return result


def compare_locks(before, after, phase, diagnostic_anisette=None):
    old, new = pin_map(before), pin_map(after)
    expected_anisette = diagnostic_anisette or ANISETTE
    if diagnostic_anisette is not None:
        require(set(diagnostic_anisette) == set(ANISETTE) and
                {key: value for key, value in diagnostic_anisette.items() if key != "state"} ==
                {key: value for key, value in ANISETTE.items() if key != "state"} and
                set(diagnostic_anisette["state"]) == {"revision"} and
                re.fullmatch(r"[0-9a-f]{40}", diagnostic_anisette["state"]["revision"]),
                "Diagnostic resolver may only change the Anisette revision")
        require(old.get("anisettekit") in (ANISETTE, diagnostic_anisette), "Unreviewed initial Anisette lock pin")
        expected = dict(old)
        expected["anisettekit"] = diagnostic_anisette
        require(expected == new, "Resolver changed a pin outside the exact diagnostic Anisette transition")
    else:
        require(old == new, "Resolver changed a pin object; no added, removed or moved dependency is allowed")
    require(len(new) == (6 if phase == "sidesign" else 10), "Unexpected exact production pin count")
    require(new.get("anisettekit") == expected_anisette, "Anisette must select the exact reviewed remote revision")
    origin = after.get("originHash")
    require("originHash" not in after or isinstance(origin, str) and re.fullmatch(r"[0-9a-f]{64}", origin), "Malformed resolver originHash")
    return {"pins": new, "originHash": origin,
            "pin_objects_unchanged": old == new,
            "approved_diagnostic_anisette_transition": diagnostic_anisette is not None,
            "metadata_status": "resolver_hash_captured_for_review" if origin else "absent_requires_review"}


def origin_chain(checkout, expected, boundary):
    return verify_origin(checkout, expected, git(checkout, "rev-parse", "HEAD"), boundary)


def verify_resolution(root, state_path, phase, refs):
    owner = "SideSign" if phase == "sidesign" else "SideStore"
    repo = owner_path(root, owner, phase)
    lock_name = "Package.resolved" if phase == "sidesign" else APP_LOCK
    before_bytes = git_bytes(repo, "show", refs["owners"][owner]["source_commit"] + ":" + lock_name)
    after_path = repo / lock_name
    diagnostic_pin = None
    if refs.get("source_basis") == "maintained-adi-consumption-v1":
        diagnostic_pin = {**ANISETTE, "state": {"revision": refs["owners"]["AnisetteKit"]["source_commit"]}}
    comparison = compare_locks(json.loads(before_bytes), json.loads(after_path.read_text()), phase, diagnostic_pin)
    expected = comparison["pins"]
    doc = json.loads(state_path.read_text())
    deps = doc["object"]["dependencies"]
    require(isinstance(deps, list), "Unknown resolver dependency schema")
    local = {} if phase == "sidesign" else {
        "sidesign": root / "SideStore/Dependencies/SideSign", "minimuxer": root / "SideStore/Dependencies/minimuxer",
        "common": root / "SideStore/Dependencies/minimuxer/Common", "devicegateway": root / "SideStore/Dependencies/minimuxer/DeviceGateway"}
    records = {}
    for dep in deps:
        ref = dep["packageRef"]
        identity = ref["identity"].lower()
        require(identity not in records, "Duplicate resolved package identity")
        if identity in local:
            require(ref["kind"] == "fileSystem" and Path(ref["location"]).is_absolute() and
                    Path(ref["location"]).resolve() == local[identity].resolve(), "Source-owned child package path changed")
            records[identity] = {"kind": "committed_local_child", "path": str(local[identity].resolve())}
            continue
        require(identity in expected and ref["kind"] == "remoteSourceControl" and
                ref["location"] == expected[identity]["location"], "Remote dependency substituted or unreviewed")
        revision = expected[identity]["state"]["revision"]
        require(dep["state"]["name"] == "sourceControlCheckout" and
                dep["state"]["checkoutState"]["revision"] == revision, "Resolver revision differs from lock")
        checkout = (state_path.parent / "checkouts" / dep["subpath"]).resolve(strict=True)
        require(checkout.is_relative_to((state_path.parent / "checkouts").resolve()), "Checkout escaped resolver directory")
        entry = {"source_commit": revision, "source_tree": git(checkout, "rev-parse", revision + "^{tree}")}
        verify_source(checkout, identity, entry)
        if identity == "anisettekit":
            require(entry["source_tree"] == refs["owners"]["AnisetteKit"]["source_tree"], "Anisette remote tree changed")
        records[identity] = {**entry, "path": str(checkout), "origin_chain": origin_chain(checkout, ref["location"], state_path.parent)}
    require(set(records) == set(expected) | set(local), "Incomplete real resolver graph")
    comparison.update(status="PASS", dependencies=records, before_lock_sha256=hashlib.sha256(before_bytes).hexdigest(), lock_sha256=sha(after_path),
                      workspace_state_sha256=sha(state_path), production_ready=False)
    return comparison


def verify_build_products(roots, archive):
    """Bind the staged iOS slice/header to the actual Rust build outputs."""
    framework = roots["minimuxer"] / "DeviceGateway/LocalBinary/IDevice.xcframework"
    document = plistlib.loads((framework / "Info.plist").read_bytes())
    libraries = document["AvailableLibraries"]
    require(len(libraries) == 1, "exactly one built idevice slice required")
    library = libraries[0]
    require(library.get("SupportedPlatform") == "ios" and not library.get("SupportedPlatformVariant") and
            library.get("SupportedArchitectures") == ["arm64"], "wrong idevice platform/architecture")
    def checked(relative):
        path = framework / relative
        require(path.resolve().is_relative_to(framework.resolve()) and path.is_file() and
                not path.is_symlink() and path.stat().st_size, "escaped/missing idevice build product")
        return path
    def digest(path):
        value = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                value.update(chunk)
        return value.hexdigest()
    base = library["LibraryIdentifier"]
    archived = checked(base + "/" + library["LibraryPath"])
    header = checked(base + "/" + library["HeadersPath"] + "/idevice.h")
    module = checked(base + "/" + library["HeadersPath"] + "/module.modulemap")
    expected_archive = archive
    require(digest(archived) == digest(expected_archive), "staged library differs from built Rust archive")
    for relative in ("ffi/idevice.h", "cpp/include/idevice.h", "swift/include/idevice.h"):
        require(digest(header) == digest(roots["idevice"] / relative), "generated idevice header mismatch")
    require(digest(module) == digest(roots["idevice"] / "swift/include/module.modulemap"), "staged module map mismatch")
    return {"library_sha256": digest(archived), "header_sha256": digest(header),
            "module_map_sha256": digest(module), "framework_info_sha256": digest(framework / "Info.plist")}


def verify_linked_archive(results, destination):
    """Bind the actual clang argument, including -L/-l selection, to local bytes."""
    built = results / "cargo-target/aarch64-apple-ios/release/libidevice_ffi.a"
    derived = (results / "sidestore-derived").resolve(strict=True)
    report = []
    for line in (destination.parent / "logs/sidestore-production-build.log").read_text().splitlines():
        if not re.search(r"(?:^|\s)\S*/clang(?:\+\+)?\s", line) or not re.search(r"libidevice_ffi\.a|-lidevice_ffi", line):
            continue
        args = shlex.split(line)
        if not args or not Path(args[0]).is_absolute() or Path(args[0]).name not in {"clang", "clang++"}:
            continue
        require(not {"-c", "-E", "-S"}.intersection(args), "Expected an Xcode linker command, not compilation only")
        candidates = [Path(arg) for i, arg in enumerate(args) if arg.endswith("/libidevice_ffi.a")
                      and (i == 0 or args[i - 1] != "-o")]
        if "-lidevice_ffi" in args:
            directories = []
            for i, arg in enumerate(args):
                if arg == "-L":
                    require(i + 1 < len(args), "Incomplete linker search path")
                    directories.append(Path(args[i + 1]))
                elif arg.startswith("-L"):
                    directories.append(Path(arg[2:]))
            require(all(path.is_absolute() for path in directories), "Relative linker search path requires observed working-directory proof")
            require(not any((path / ("libidevice_ffi" + suffix)).exists()
                            for path in directories for suffix in (".dylib", ".tbd")),
                    "Competing dynamic IDevice library makes static archive selection unproven")
            found = [path / "libidevice_ffi.a" for path in directories
                     if (path / "libidevice_ffi.a").is_file()]
            require(found, "Linker -lidevice_ffi has no actual archive in its -L search paths")
            candidates.append(found[0])
        require(candidates, "Linker invocation does not identify an actual IDevice archive")
        for path in candidates:
            require(path.is_absolute() and path.is_file() and not path.is_symlink() and
                    path.resolve(strict=True).is_relative_to(derived), "Linked IDevice archive is absent or outside Xcode products")
            require(sha(path) == sha(built), "Actually linked IDevice archive differs from local FFI output")
            report.append({"archive": str(path.resolve()), "sha256": sha(path), "command": args})
    require(report, "Missing actual Xcode linker input for local IDevice")
    return report


def capture_compiler_inputs(root, results, destination, resolution, phase):
    expected = {"SideSign": owner_path(root, "SideSign", phase) / "Sources",
                "AnisetteKit": Path(resolution["dependencies"]["anisettekit"]["path"]) / "Sources"}
    owners = {"SideSign": owner_path(root, "SideSign", phase)}
    if phase == "sidestore":
        expected.update(SideStore=root / "SideStore/AltStore", minimuxer=owner_path(root, "minimuxer", phase),
                        LiveContainer=root / "LiveContainer/LiveContainerSwiftUI")
        owners.update({name: owner_path(root, name, phase) for name in ("SideStore", "minimuxer", "LiveContainer")})
    for identity, entry in resolution["dependencies"].items():
        if "source_commit" in entry:  # Only the already-proven remote Git roots.
            owners[identity] = Path(entry["path"])
    owners.setdefault("AnisetteKit", Path(resolution["dependencies"]["anisettekit"]["path"]))
    owned = {path.resolve(strict=True): tree_entries(path, "HEAD") for path in owners.values()}
    records = {owner: [] for owner in expected}
    generated = {}
    if phase == "sidestore":
        asset_report = destination.parent / "generated-xcode-sources.json"
        if asset_report.exists():
            generated = json.loads(asset_report.read_text())["sources"]
            known = expected_sources({name: owner_path(root, name, phase) for name in ("SideStore", "LiveContainer")}, results)
            require(set(generated) == set(known), "Unreviewed or incomplete generated-source evidence")
            for path, spec in known.items():
                require(all(generated[path].get(key) == value for key, value in spec.items()), "Generated source target/classification drift")
    destination.mkdir(parents=True, exist_ok=True)
    for file in sorted(set(results.rglob("*.SwiftFileList")) | set(results.rglob("sources"))):
        require(not file.is_symlink() and file.resolve().is_relative_to(results.resolve()), "Compiler list escaped results")
        if not file.is_file():
            continue
        text = file.read_text()
        paths = []
        for line in text.splitlines():
            if not line.strip():
                continue
            tokens = [line] if Path(line).is_file() else shlex.split(line)
            require(len(tokens) == 1, "Unknown compiler input list entry")
            paths.append(Path(tokens[0]))
        matched = [owner for owner, prefix in expected.items()
                   if any(path.resolve().is_relative_to(prefix.resolve()) for path in paths)]
        generated_here = [str(path.resolve()) for path in paths if str(path.resolve()) in generated]
        for path in generated_here:
            if generated[path]["owner"] not in matched: matched.append(generated[path]["owner"])
        if not matched:
            continue
        inputs = []
        for path in paths:
            require(path.is_absolute() and path.is_file() and not path.is_symlink(), "Compiler input does not exist as a regular source file: " + str(path))
            path = path.resolve(strict=True)
            if str(path) in generated:
                evidence = generated[str(path)]
                require(evidence["file_list"] == str(file.resolve()) and evidence["file_list_sha256"] == sha(file)
                        and evidence["sha256"] == sha(path), "Generated asset evidence does not bind this compiler input")
                inputs.append({"path": str(path), "sha256": sha(path), "generated": evidence})
                continue
            candidates = [owner for owner in owned if path.is_relative_to(owner)]
            require(candidates, "Compiler input is outside proven owner sources: " + str(path))
            owner = max(candidates, key=lambda value: len(value.parts))
            relative = str(path.relative_to(owner))
            require(relative in owned[owner] and owned[owner][relative][0] in {"100644", "100755"},
                    "Compiler input is not a committed source: " + str(path))
            verify_worktree_bytes(owner, {relative: owned[owner][relative]})
            inputs.append({"path": str(path), "sha256": sha(path), "blob": owned[owner][relative][1]})
        require(inputs, "Empty compiler input list")
        # Match parsed canonical inputs too: strings inside comments never count.
        matched = [owner for owner, prefix in expected.items()
                   if any(Path(item["path"]).is_relative_to(prefix.resolve()) for item in inputs)]
        # Generated Swift is accepted, but never supplies committed runtime coverage.
        label = hashlib.sha256(str(file).encode()).hexdigest()[:16] + ".txt"
        (destination / label).write_text("Compiler input list: " + str(file) + "\n" + text)
        for owner in matched:
            records[owner].append({"file": str(file), "sha256": sha(file), "copy": label, "inputs": inputs})
    require(all(records.values()), "Compiler input evidence missing for " + ", ".join(k for k, v in records.items() if not v))
    report = {"owners": records}
    if phase == "sidestore":
        # Preserve the native gate's Cargo and Xcode evidence, using production log names.
        rust_link_inputs(root, results, destination.parent, side_log_name="sidestore-production-build.log")
        report["actual_linker_inputs"] = verify_linked_archive(results, destination.parent)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("inputs", "owner-proof", "fetch", "sources", "resolution", "snapshot", "compiler-inputs", "build-products", "generated-sources"))
    p.add_argument("--phase", choices=("sidesign", "sidestore"), required=True)
    p.add_argument("--inputs", type=Path, required=True)
    p.add_argument("--approved-sha256", required=True)
    p.add_argument("--root", type=Path)
    p.add_argument("--state", type=Path)
    p.add_argument("--report", type=Path)
    p.add_argument("--results", type=Path)
    p.add_argument("--archive", type=Path)
    p.add_argument("--after-resolution", action="store_true")
    p.add_argument("--built", action="store_true")
    a = p.parse_args()
    refs = load_inputs(a.inputs, a.approved_sha256, a.phase)
    result = {"status": "PASS", "phase": a.phase, "approved_inputs_sha256": a.approved_sha256, "production_ready": False}
    if a.action == "owner-proof":
        basis_path, basis_sha = diagnostic_basis(refs, a.phase)
        owner = owner_path(a.root, "SideSign", a.phase)
        completed = subprocess.run([sys.executable, "-B", str(owner / ".ci/production-dependencies.py"),
            "--root", str(owner), "--diagnostic-basis", str(basis_path),
            "--diagnostic-basis-sha256", basis_sha], check=True, capture_output=True, text=True)
        proof = json.loads(completed.stdout)
        require(proof.get("status") == "diagnostic_dependency_transition_pass" and
                proof.get("production_ready") is False, "Diagnostic owner source proof failed or falsely claims readiness")
        result["owner_proof"] = proof
    elif a.action == "fetch":
        require(not a.root.exists(), "Production source output must be new")
        a.root.mkdir(parents=True)
        skip = {"SideSign", "minimuxer"} if a.phase == "sidestore" else set()
        for owner, entry in refs["owners"].items():
            if owner in skip:
                continue
            repo = owner_path(a.root, owner, a.phase)
            repo.mkdir()
            acquisition_git(repo, "init", "--quiet")
            git(repo, "remote", "add", "origin", "https://github.com/" + entry["repository"] + ".git")
            git(repo, "config", "remote.origin.pushurl", "disabled://production-validation")
            git(repo, "fetch", "--no-tags", "--no-recurse-submodules", "origin", entry["source_commit"])
            git(repo, "checkout", "--detach", "--quiet", entry["source_commit"])
            verify_source(repo, owner, entry)
    elif a.action == "sources":
        result["owners"] = {}
        for owner, entry in refs["owners"].items():
            lock = ("Package.resolved" if owner == "SideSign" else APP_LOCK) if a.after_resolution and owner == ("SideSign" if a.phase == "sidesign" else "SideStore") else None
            result["owners"][owner] = verify_source(owner_path(a.root, owner, a.phase), owner, entry, lock, a.built)
        if a.phase == "sidestore":
            for child in ("SideSign", "minimuxer"):
                record = git(a.root / "SideStore", "ls-tree", "HEAD", "Dependencies/" + child)
                require(record == "160000 commit " + refs["owners"][child]["source_commit"] + "\tDependencies/" + child,
                        "Actual SideStore gitlink does not select the final published child")
                require(git(owner_path(a.root, child, a.phase), "config", "--get", "remote.origin.url") ==
                        "https://github.com/NRG-Wardog/" + child + ".git", "Child origin differs from committed owner URL")
    elif a.action == "resolution":
        result = verify_resolution(a.root, a.state, a.phase, refs)
    elif a.action == "snapshot":
        result = {"status": "OBSERVED_NOT_ACCEPTED", "owners": {}}
        for owner in refs["owners"]:
            repo = owner_path(a.root, owner, a.phase)
            rows = {}
            for name in filter(None, git(repo, "ls-files", "--others", "-z").split("\0")):
                file = repo / name
                rows[name] = {"type": "symlink"} if file.is_symlink() else {"sha256": sha(file)} if file.is_file() else {"type": "other"}
            result["owners"][owner] = {"untracked_including_ignored": rows, "tracked_diff": git(repo, "diff", "--binary", "--ignore-submodules=all")}
    elif a.action == "build-products":
        require(a.phase == "sidestore" and a.archive is not None, "Only the staged production iOS build has local products")
        result["products"] = verify_build_products({owner: owner_path(a.root, owner, a.phase) for owner in refs["owners"]}, a.archive)
    elif a.action == "generated-sources":
        require(a.phase == "sidestore", "Generated asset proof applies only to SideStore phase")
        owners = {name: owner_path(a.root, name, a.phase) for name in ("SideStore", "LiveContainer")}
        records = {}
        for name, owner in owners.items():
            verify_source(owner, name, refs["owners"][name], APP_LOCK if name == "SideStore" else None, True)
            records[name] = tree_entries(owner, refs["owners"][name]["source_commit"])
        result["generated_sources"] = verify_generated_sources(owners, a.results, a.report.parent, records)
    elif a.action == "compiler-inputs":
        resolution = verify_resolution(a.root, a.state, a.phase, refs)
        result["compiler_inputs"] = capture_compiler_inputs(a.root, a.results,
            a.report.parent / "compiler-input-lists", resolution, a.phase)
    if a.report:
        a.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "phase": a.phase, "production_ready": False}))


if __name__ == "__main__":
    main()
