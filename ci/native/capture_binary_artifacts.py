#!/usr/bin/env python3
"""Record resolved binary URLs, independent archive hashes, and extracted files.

The archive fetch is a checksummed acquisition proof, not a claim that SwiftPM
retained its own original download. SwiftPM must independently enforce checksum.
Unknown resolver artifact schemas or nonliteral manifest checksums fail closed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import stat
import urllib.parse
import urllib.request
import zipfile

from validate_inputs import git


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_extracted_archive(archive, path):
    """Bind the actual selected framework bytes/links to the verified ZIP payload."""
    with zipfile.ZipFile(archive) as zipped:
        entries = zipped.infolist()
        names = [entry.filename for entry in entries]
        if len(set(names)) != len(names):
            raise ValueError("Duplicate binary archive entry")
        prefixes = set()
        for name in names:
            parts = PurePosixPath(name).parts
            if name.startswith("/") or ".." in parts:
                raise ValueError("Escaped binary archive entry")
            if path.name in parts:
                index = parts.index(path.name)
                prefixes.add("/".join(parts[:index + 1]) + "/")
        if len(prefixes) != 1:
            raise ValueError("Archive does not uniquely identify the resolved framework root")
        prefix = next(iter(prefixes))
        expected = {}
        for entry in entries:
            if entry.is_dir() or not entry.filename.startswith(prefix):
                continue
            relative = entry.filename[len(prefix):]
            is_link = stat.S_ISLNK(entry.external_attr >> 16)
            expected[relative] = {"sha256": hashlib.sha256(zipped.read(entry)).hexdigest(), "symlink": is_link}
        actual = {}
        for file in path.rglob("*"):
            if not file.is_file() and not file.is_symlink():
                continue
            if not file.resolve().is_relative_to(path):
                raise ValueError("Extracted artifact file escaped its resolved directory")
            is_link = file.is_symlink()
            data = os.fsencode(os.readlink(file)) if is_link else file.read_bytes()
            actual[str(file.relative_to(path))] = {"sha256": hashlib.sha256(data).hexdigest(), "symlink": is_link}
        if not actual or actual != expected:
            raise ValueError("Resolved binary bytes/links differ from the checksummed archive")
        return actual


def manifest_declarations(workspace, state_file, document):
    roots = [workspace / relative for relative in (
        "AnisetteKit", "SideSign", "SideStore", "SideStore/Dependencies/SideSign",
        "SideStore/Dependencies/minimuxer", "LiveContainer", "idevice", "jktcp")]
    for dependency in document["object"]["dependencies"]:
        if dependency["packageRef"]["kind"] == "remoteSourceControl":
            root = state_file.parent / "checkouts" / dependency["subpath"]
            if not root.resolve().is_relative_to((state_file.parent / "checkouts").resolve()):
                raise ValueError("Remote package declaration escaped proven checkouts")
            roots.append(root)
    declarations = {}
    pattern = r'url:\s*"(https://[^"\s]+)"\s*,\s*checksum:\s*"([0-9a-f]{64})"'
    for root in roots:
        if not root.exists():
            continue
        commit = git(root, "rev-parse", "HEAD")
        # Read declarations only from committed owner/external package objects,
        # never generated directories or other untracked Package.swift files.
        for record in git(root, "ls-tree", "-r", "-z", "HEAD").split("\0"):
            if not record:
                continue
            metadata, relative = record.split("\t", 1)
            mode, kind, oid = metadata.split()
            if kind != "blob" or not re.fullmatch(r"Package(?:@swift-[0-9.]+)?\.swift", Path(relative).name):
                continue
            contents = git(root, "cat-file", "blob", oid)
            for url, checksum in re.findall(pattern, contents):
                declarations[(url, checksum)] = str(root) + "@" + commit + ":" + relative
    return declarations


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("state", type=Path)
    p.add_argument("workspace", type=Path)
    p.add_argument("results", type=Path)
    p.add_argument("report", type=Path)
    a = p.parse_args()
    document = json.loads(a.state.read_text())
    artifacts = document["object"]["artifacts"]
    if not isinstance(artifacts, list):
        raise ValueError("Unknown binary artifact resolver schema")
    declarations = manifest_declarations(a.workspace, a.state, document)
    rows = []
    archive_root = a.results / "archive-proofs"
    archive_root.mkdir(exist_ok=True)
    for artifact in artifacts:
        source = artifact["source"]
        if source["type"] == "local":
            continue  # Locally built IDevice is hashed independently.
        if source["type"] != "remote":
            raise ValueError("Unknown artifact source schema")
        url, checksum = source["url"], source["checksum"]
        if (url, checksum) not in declarations or urllib.parse.urlsplit(url).scheme != "https":
            raise ValueError("Artifact lacks an exact frozen manifest URL/checksum")
        archive = archive_root / (checksum + ".zip")
        if not archive.exists():
            with urllib.request.urlopen(url, timeout=120) as response:
                if urllib.parse.urlsplit(response.geturl()).scheme != "https":
                    raise ValueError("Artifact redirected outside HTTPS")
                with archive.open("xb") as output:
                    for chunk in iter(lambda: response.read(1024 * 1024), b""):
                        output.write(chunk)
        actual = file_hash(archive)
        if actual != checksum:
            raise ValueError("Downloaded binary archive checksum mismatch")
        path = Path(artifact["path"]).resolve(strict=True)
        if not path.is_relative_to(a.results.resolve()):
            raise ValueError("Resolved binary artifact escaped isolated results")
        hashes = verify_extracted_archive(archive, path)
        rows.append({"url": url, "declared_checksum": checksum, "independent_archive_sha256": actual,
            "manifest": declarations[(url, checksum)], "resolved_path": str(path), "resolved_files": hashes,
            "extracted_payload_matches_verified_archive": True})
    if not rows:
        raise ValueError("Expected remote binary artifact evidence is absent")
    a.report.write_text(json.dumps({"state_sha256": file_hash(a.state), "artifacts": rows,
        "archive_proof_kind": "independent checksummed reacquisition; SwiftPM download not retained"}, indent=2) + "\n")


if __name__ == "__main__":
    main()
