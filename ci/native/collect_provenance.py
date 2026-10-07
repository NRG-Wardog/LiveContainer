#!/usr/bin/env python3
"""Export only logs/metadata; never publish application/framework binaries."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


def sha256(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def compile_inputs(workspace, results, destination):
    required = {
        "SideStore": workspace / "SideStore/AltStore",
        "SideSign": workspace / "SideStore/Dependencies/SideSign",
        "AnisetteKit": workspace / "AnisetteKit",
        "minimuxer": workspace / "SideStore/Dependencies/minimuxer",
        "LiveContainer": workspace / "LiveContainer/LiveContainerSwiftUI",
    }
    evidence = {name: [] for name in required}
    listings = destination / "compiler-file-lists"
    listings.mkdir(exist_ok=True)
    for path in sorted(results.rglob("*.SwiftFileList")):
        contents = path.read_text()
        label = hashlib.sha256(str(path).encode()).hexdigest()[:16] + ".txt"
        (listings / label).write_text("Compiler file list: " + str(path) + "\n" + contents)
        for name, prefix in required.items():
            if str(prefix) + "/" in contents:
                evidence[name].append({"file_list": str(path), "sha256": sha256(path), "copy": label})
    missing = [name for name, rows in evidence.items() if not rows]
    (destination / "compiler-input-proof.json").write_text(json.dumps({"owners": evidence,
        "missing": missing, "scope": "Actual Xcode compiler input lists; read with successful build logs"}, indent=2) + "\n")
    if missing:
        raise ValueError("Native compiler input evidence missing for " + ", ".join(missing))
    rust_link_inputs(workspace, results, destination)


def rust_link_inputs(workspace, results, destination, side_log_name="sidestore-build.log"):
    """Shared required Cargo owner/iOS compilation and Xcode archive evidence."""
    metadata = json.loads((destination / "idevice-cargo-metadata.json").read_text())
    packages = {p["name"]: p for p in metadata["packages"] if p["name"] in {"idevice", "idevice-ffi", "jktcp"}}
    paths = {"idevice": workspace / "idevice/idevice/Cargo.toml", "idevice-ffi": workspace / "idevice/ffi/Cargo.toml",
             "jktcp": workspace / "jktcp/Cargo.toml"}
    cargo_log = (destination.parent / "logs/idevice-build.log").read_text()
    for name, path in paths.items():
        package = packages[name]
        if package["source"] is not None or Path(package["manifest_path"]).resolve() != path.resolve():
            raise ValueError("Rust owner resolved outside explicit local assembly: " + name)
        if not any("--crate-name " + name.replace("-", "_") + " " in line and "--target aarch64-apple-ios" in line
                   for line in cargo_log.splitlines()):
            raise ValueError("Missing iOS rustc compilation command: " + name)
    side_log = (destination.parent / "logs" / side_log_name).read_text()
    # Xcode links a copied static archive; accept only an actual clang/link command
    # that names that archive, or its -L path with the matching -l argument.
    link_lines = [line for line in side_log.splitlines()
                  if re.search(r"(?:^|\s)\S*/clang(?:\+\+)?\s", line)
                  and re.search(r"libidevice_ffi\.a|-lidevice_ffi", line)]
    if not link_lines:
        raise ValueError("Missing Xcode clang linker invocation for local libidevice_ffi")
    built = results / "cargo-target/aarch64-apple-ios/release/libidevice_ffi.a"
    linked_archives = list((results / "sidestore-derived").rglob("libidevice_ffi.a"))
    if not linked_archives or any(sha256(path) != sha256(built) for path in linked_archives):
        raise ValueError("Xcode staged IDevice archive absent or different from local FFI output")
    (destination / "local-ffi-link-hashes.json").write_text(json.dumps(
        {str(path): sha256(path) for path in [built, *linked_archives]}, indent=2) + "\n")
    (destination / "local-ffi-link-invocations.txt").write_text("\n".join(link_lines) + "\n")


def independent_objects(workspace, destination):
    manifest = json.loads((workspace / "test-manifest.json").read_text())
    rows = {}
    for name, entry in manifest["owners"].items():
        repo = workspace / entry["path"]
        objects = repo / ".git/objects"
        if not objects.is_dir() or (objects / "info/alternates").exists():
            raise ValueError("Owner assembly uses missing/shared Git storage: " + name)
        files = [p for p in objects.rglob("*") if p.is_file()]
        if not files or any(p.is_symlink() or p.stat().st_nlink != 1 for p in files):
            raise ValueError("Owner assembly object storage is linked: " + name)
        rows[name] = {"object_files": len(files), "all_link_counts_one": True, "alternates": False}
    (destination / "independent-git-objects.json").write_text(json.dumps(rows, indent=2) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("workspace", type=Path)
    p.add_argument("results", type=Path)
    p.add_argument("destination", type=Path)
    p.add_argument("phase")
    p.add_argument("exit_code", type=int)
    p.add_argument("--require-compile-inputs", action="store_true")
    a = p.parse_args()
    a.destination.mkdir(parents=True, exist_ok=True)
    for name in ("test-manifest.json", "sidestore-resolution-evidence.json", "sidesign-resolution-evidence.json"):
        source = a.workspace / name
        if source.is_file():
            shutil.copyfile(source, a.destination / name)
    inventory = {}
    # Explicit generated ABI/framework evidence and lockfiles, never full products.
    roots = [a.workspace / "idevice/ffi/idevice.h", a.workspace / "idevice/cpp/include/idevice.h",
             a.workspace / "idevice/swift/include/idevice.h", a.workspace / "idevice/swift/IDevice.xcframework",
             a.workspace / "SideStore/Dependencies/minimuxer/DeviceGateway/LocalBinary/IDevice.xcframework",
             a.results / "cargo-target/aarch64-apple-ios/release/libidevice_ffi.a"]
    paths = []
    for root in roots:
        paths.extend(root.rglob("*") if root.is_dir() else [root])
    for root in (a.workspace, a.results):
        for pattern in ("Cargo.lock", "Package.resolved", "workspace-state.json"):
            paths.extend(root.rglob(pattern))
    for path in sorted(set(paths)):
        if path.is_file() and ".git" not in path.parts:
            inventory[str(path)] = {"sha256": sha256(path), "bytes": path.stat().st_size}
            if path.name in {"Cargo.lock", "Package.resolved", "workspace-state.json"}:
                directory = a.destination / "resolver-inputs"
                directory.mkdir(exist_ok=True)
                filename = hashlib.sha256(str(path).encode()).hexdigest()[:16] + "-" + path.name + ".txt"
                shutil.copyfile(path, directory / filename)
                inventory[str(path)]["copy"] = "resolver-inputs/" + filename
    (a.destination / "generated-and-lock-hashes.json").write_text(json.dumps(inventory, indent=2) + "\n")
    if a.require_compile_inputs:
        independent_objects(a.workspace, a.destination)
        compile_inputs(a.workspace, a.results, a.destination)
    (a.destination / "native-run-status.json").write_text(json.dumps({"phase": a.phase, "exit_code": a.exit_code,
        "status": "PASS" if a.exit_code == 0 and a.phase == "complete" else "INCOMPLETE_OR_FAILED",
        "scope": "Selected account-free tests and separate unsigned builds",
        "excluded": ["Apple provisioning", "device/VPN testing", "combined packaging", "signing", "release", "deployment"]}, indent=2) + "\n")


if __name__ == "__main__":
    main()
