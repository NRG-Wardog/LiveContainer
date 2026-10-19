"""Derived from maintained_sources.py @767234eb; see primitives-provenance.json."""

import hashlib
import json
import os
from pathlib import Path
import subprocess

BUILD_OUTPUTS = {"idevice": ("target/", "ffi/idevice.h", "cpp/include/idevice.h", "swift/include/idevice.h", "swift/IDevice.xcframework/"),
                 "jktcp": ("target/",), "minimuxer": ("DeviceGateway/LocalBinary/IDevice.xcframework/",),
                 # Frozen Makefile clean/copy/ipa-sidebackup targets write only these.
                 "SideStore": ("build/sidebackup.xcarchive/", "build/SideBackup.ipa")}

def require(value, message):
    if not value:
        raise ValueError(message)

def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result

def git(root, *arguments, bare=False):
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
    require(git(root, "rev-parse", "HEAD").decode().strip() == commit, "origin proof checkout commit mismatch")
    origin = git(root, "remote", "get-url", "origin").decode().strip()
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
    require(git(mirror, "rev-parse", "--is-bare-repository", bare=True).strip() == b"true", "resolver mirror is not bare")
    upstream = git(mirror, "remote", "get-url", "origin", bare=True).decode().strip()
    require(upstream.removesuffix(".git") == expected_url.removesuffix(".git"), "resolver mirror upstream repository mismatch")
    require(git(mirror, "rev-parse", "--is-shallow-repository", bare=True).strip() == b"false", "shallow resolver mirror")
    # Permit exactly the object-sharing relationship created by clone --shared.
    # A second mirror/cache hop requires separately reviewed native evidence.
    require(not (mirror / "objects/info/alternates").exists(), "unapproved nested resolver object store")
    gitdir = Path(git(root, "rev-parse", "--absolute-git-dir").decode().strip()).resolve(strict=True)
    alternates = gitdir / "objects/info/alternates"
    if alternates.exists():
        require(not alternates.is_symlink(), "substituted resolver object store")
        paths = alternates.read_text().splitlines()
        require(len(paths) == 1 and Path(paths[0]).is_absolute() and
                Path(paths[0]).resolve(strict=True) == mirror / "objects", "resolver object store escaped approved mirror")
    require(git(mirror, "rev-parse", commit + "^{commit}", bare=True).decode().strip() == commit,
            "resolver mirror lacks exact commit")
    tree = git(root, "rev-parse", "HEAD^{tree}").decode().strip()
    require(git(mirror, "rev-parse", commit + "^{tree}", bare=True).decode().strip() == tree,
            "resolver mirror tree differs from checkout")
    return {"kind": "swiftpm-local-mirror", "repository": expected_url,
            "mirror": str(mirror), "commit": commit, "tree": tree}

def entries(root, revision="HEAD"):
    result = {}
    for row in git(root, "ls-tree", "-rz", revision).split(b"\0"):
        if row:
            head, name = row.split(b"\t", 1)
            result[os.fsdecode(name)] = tuple(head.decode().split())
    return result

def allowed_output(owner, name):
    return any(name.startswith(p) if p.endswith("/") else name == p for p in BUILD_OUTPUTS.get(owner, ()))

def verify_checkout(root, commit, *, owner="dependency", after_build=False, require_full_history=False, observed_lock=None):
    if observed_lock is not None:
        allowed = "Package.resolved" if owner == "SideSign" else "AltStore.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved" if owner == "SideStore" else None
        require(allowed is not None and isinstance(observed_lock, dict) and set(observed_lock) == {allowed}, "only an exact observed resolver lock override is allowed")
    root = Path(root).resolve(strict=True)
    require((root / ".git").exists(), owner + ": missing actual checkout")
    require(git(root, "rev-parse", "HEAD").decode().strip() == commit, owner + ": wrong commit")
    if require_full_history:
        require(git(root, "rev-parse", "--is-shallow-repository").strip() == b"false", owner + ": shallow owner history")
    records = entries(root)
    children = []
    for name, (mode, kind, oid) in records.items():
        target = root / name
        for parent in target.parents:
            if parent == root:
                break
            require(not parent.is_symlink(), owner + ": substituted parent for " + name)
        if mode == "160000":
            children.append({"path": name, **verify_checkout(target, oid,
                owner=name.split("/")[-1], after_build=after_build)})
            continue
        require(kind == "blob", owner + ": unsupported object")
        if mode == "120000":
            require(target.is_symlink(), owner + ": missing symlink " + name)
            content = os.fsencode(os.readlink(target))
        else:
            require(target.is_file() and not target.is_symlink(), owner + ": missing regular file " + name)
            require(("100755" if target.stat().st_mode & 0o111 else "100644") == mode,
                    owner + ": mode drift " + name)
            content = target.read_bytes()
        require(hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest() == (observed_lock.get(name, oid) if observed_lock else oid),
                owner + ": compiler input differs from commit: " + name)
    # Include ignored files: an ignored Swift file is still a compiler input.
    extras = git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
    extras += git(root, "ls-files", "--others", "--ignored", "--exclude-standard", "-z").split(b"\0")
    for name in filter(None, extras):
        relative = os.fsdecode(name)
        require(after_build and allowed_output(owner, relative), owner + ": unexpected untracked input " + relative)
    require(not git(root, "diff", "--cached", "--name-only"), owner + ": index changed")
    return {"commit": commit, "tree": git(root, "rev-parse", "HEAD^{tree}").decode().strip(),
            "tracked_entries": len(records), "submodules": children}

def pin_map(lock):
    result = {}
    for pin in lock["pins"]:
        identity = pin["identity"]
        require(identity not in result, "duplicate SwiftPM identity")
        result[identity] = pin
    return result

def verify_resolution(roots, state_path, lock_path, local, anisette=None):
    """Check the real Xcode workspace graph, including every remote checkout."""
    state_path = Path(state_path)
    state = json.loads(state_path.read_bytes())["object"]["dependencies"]
    expected = pin_map(json.loads(Path(lock_path).read_bytes()))
    seen, report = set(), {}
    for dep in state:
        ref = dep["packageRef"]
        identity = ref["identity"].lower()
        require(identity not in seen, "duplicate resolved dependency")
        seen.add(identity)
        if identity in local:
            require(ref["kind"] == "fileSystem" and Path(ref["location"]).is_absolute() and
                    Path(ref["location"]).resolve() == local[identity].resolve(), "wrong local package: " + identity)
            report[identity] = {"kind": "fileSystem", "path": str(local[identity].resolve())}
        else:
            require(identity in expected, "unreviewed transitive package: " + identity)
            pin = expected[identity]
            require(ref["kind"] == "remoteSourceControl" and ref["location"] == pin["location"] and
                    dep["state"]["name"] == "sourceControlCheckout" and
                    dep["state"]["checkoutState"]["revision"] == pin["state"]["revision"], "resolved remote pin mismatch")
            checkout = state_path.parent / "checkouts" / dep["subpath"]
            require(checkout.resolve().is_relative_to((state_path.parent / "checkouts").resolve()), "escaped remote checkout")
            if identity == "anisettekit" and anisette is not None:
                require(checkout.resolve() == Path(anisette).resolve(), "effective Anisette checkout mismatch")
            report[identity] = verify_checkout(checkout, pin["state"]["revision"], owner=identity)
            report[identity]["origin"] = verify_origin(checkout, pin["location"],
                pin["state"]["revision"], resolver_root=state_path.parent)
    require(seen == set(expected) | set(local), "resolver omitted expected dependencies")
    return report
