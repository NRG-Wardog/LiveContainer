#!/usr/bin/env python3
"""Extract delivered cachePayload and complete real fingerprint for macOS CI.

Generation is Python-only. It never invokes Swift, native signing, a device,
network activity, app builds, or files outside the chosen input/output roots.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re


SOURCE_BLOBS = {
    "SideStore/Core/Operations/PipelineOperations/CacheAppOperation.swift":
        "6c33795361405dcd8c64d3de9514165bcf2a3c61",
    "SideStore/Utils/common/AppBundleFingerprint.swift":
        "e41610c65bb47b933739a45c5d063092c0d88566",
}
EXPECTED_CASE_NAMES = [
    "new_cache_publishes_verified_payload",
    "identical_cache_reuses_existing_payload",
    "same_size_content_change_changes_key",
    "root_symlink_input_rejected_preserving_files",
    "nested_symlink_input_rejected_preserving_files",
    "existing_key_conflict_preserves_original_bytes",
    "obstructed_destination_parent_preserves_files",
    "copy_modes_umask_022_directories_777",
    "copy_modes_umask_022_directories_755",
    "copy_modes_umask_022_directories_700",
    "copy_modes_umask_077_directories_777",
    "copy_modes_umask_077_directories_755",
    "copy_modes_umask_077_directories_700",
    "copy_modes_umask_000_directories_777",
    "copy_modes_umask_000_directories_755",
    "copy_modes_umask_000_directories_700",
    "composed_unicode_names_copy_preserves_identity",
    "decomposed_unicode_names_copy_preserves_identity",
    "permission_change_publishes_new_key_preserving_previous_cache",
    "hidden_file_content_change_publishes_new_key",
]
NEGATIVE_CONTROLS = {
    "CacheNegativeSameSize.swift": ["same_size_content_change_changes_key"],
    "CacheNegativeConflict.swift": ["existing_key_conflict_preserves_original_bytes"],
}


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def replace_once(source, before, after):
    if source.count(before) != 1:
        raise ValueError(f"Mutation anchor must occur exactly once: {before!r}")
    return source.replace(before, after, 1)


def extract_cache_method(source):
    start_marker = "    @discardableResult\n    static func cachePayload(for bundleURL: URL)"
    end_marker = "\n    static func pruneUnusedCaches("
    if source.count(start_marker) != 1 or source.count(end_marker) != 1:
        raise ValueError("cachePayload extraction boundaries changed")
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    # The selected production method, including comments and whitespace, is
    # unchanged; only its unavailable BasePipelineOperation wrapper is inert.
    method = source[start:end]
    if not method.endswith("    }\n"):
        raise ValueError("Unexpected cachePayload ending")
    return method


def generate(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if not (root / "SideStore").is_dir() or not (root / "LiveContainer").is_dir():
        raise ValueError("--root must contain SideStore and LiveContainer directories")
    here = Path(__file__).resolve().parent
    inputs, sources = [], {}
    for relative, expected in SOURCE_BLOBS.items():
        path = root / "SideStore" / relative
        data = path.read_bytes()
        observed = git_blob(data)
        if observed != expected:
            raise ValueError(f"Delivered source blob mismatch for {relative}: {observed} != {expected}")
        sources[relative] = data.decode("utf-8")
        inputs.append({"path": "SideStore/" + relative, "git_blob_sha1": observed, "sha256": sha256(data)})

    method = extract_cache_method(sources[next(iter(SOURCE_BLOBS))])
    fingerprint = sources["SideStore/Utils/common/AppBundleFingerprint.swift"]
    boundaries = (here / "BoundaryDoubles.swift").read_text()
    cases = (here / "Cases.swift").read_text()
    names = re.findall(r'\brecord\("([^"\n]+)"', cases)
    if names != EXPECTED_CASE_NAMES:
        raise ValueError("Cache fixture case names/order changed unexpectedly")

    def assemble(real_method, real_fingerprint):
        return "\n".join([
            "// Generated test-only fixture. Do not use as app production source.",
            boundaries, real_fingerprint,
            "enum CacheAppOperation {\n" + real_method + "}\n", cases,
        ])

    positive = assemble(method, fingerprint)
    weakened_fingerprint = replace_once(
        fingerprint, "hasher.update(data: chunk)",
        "hasher.update(data: Data(repeating: 0, count: chunk.count))",
    )
    # The same verification expression also occurs after publication. Target
    # only the existing-cache branch, leaving the final verification unchanged.
    weakened_conflict = replace_once(
        method,
        "if fm.fileExists(atPath: targetFileURL.path) {\n            guard AppBundleFingerprint.compute(for: targetFileURL) == signature else {",
        "if fm.fileExists(atPath: targetFileURL.path) {\n            guard fm.fileExists(atPath: targetFileURL.path) else { // NEGATIVE CONTROL: accept a conflicting existing cache.",
    )
    generated = {
        "Cache.swift": positive,
        "CacheNegativeSameSize.swift": assemble(method, weakened_fingerprint),
        "CacheNegativeConflict.swift": assemble(weakened_conflict, fingerprint),
    }
    output.mkdir(parents=True, exist_ok=True)
    outputs = []
    for name, text in generated.items():
        data = text.encode("utf-8")
        (output / name).write_bytes(data)
        outputs.append({"path": name, "sha256": sha256(data)})
    support = []
    for name in ["BoundaryDoubles.swift", "Cases.swift", "generate.py"]:
        data = (here / name).read_bytes()
        support.append({"path": name, "sha256": sha256(data)})
    receipt = {
        "schema": "install-chain-source-v1", "group": "cache", "passed": True,
        "inputs": inputs, "support": support, "generated_sources": outputs,
        "variants": [
            {
                "file": item["path"], "group": "cache",
                "case_names": EXPECTED_CASE_NAMES,
                "expected_failed_names": NEGATIVE_CONTROLS.get(item["path"], []),
                "sha256": item["sha256"],
                "expected_exit_code": 1 if item["path"] in NEGATIVE_CONTROLS else 0,
            }
            for item in outputs
        ],
        "cache_method_sha256": sha256(method.encode()),
        "expected_case_names": EXPECTED_CASE_NAMES, "expected_case_count": len(names),
        "negative_controls": [
            {"source": name, "expected_failed_cases": failures, "expected_exit_code": 1}
            for name, failures in NEGATIVE_CONTROLS.items()
        ],
        "production_source_unchanged": True,
        "swift_executed": False, "network_executed": False,
        "native_signing_device_executed": False,
    }
    (output / "sources.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(generate(args.root, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
