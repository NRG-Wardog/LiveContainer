#!/usr/bin/env python3
"""Python-only source, extraction, pinning, and mutation-contract validation."""
from pathlib import Path
import argparse
import hashlib
import json
import tempfile

import generate


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def validate(root):
    root = Path(root).resolve()
    with tempfile.TemporaryDirectory(prefix="cache-source-contract-") as temp:
        out = Path(temp) / "generated"
        receipt = generate.generate(root, out)
        positive = (out / "Cache.swift").read_text()
        same_size = (out / "CacheNegativeSameSize.swift").read_text()
        conflict = (out / "CacheNegativeConflict.swift").read_text()
        source = (root / "SideStore/SideStore/Core/Operations/PipelineOperations/CacheAppOperation.swift").read_text()
        fingerprint = (root / "SideStore/SideStore/Utils/common/AppBundleFingerprint.swift").read_text()
        method = generate.extract_cache_method(source)
        check(method in positive, "Positive fixture changed the cache method")
        check(fingerprint in positive, "Positive fixture changed the real fingerprint")
        check("execute(parentProgress:" not in positive, "Fixture pulled in the unrelated iOS pipeline")
        check(receipt["expected_case_names"] == generate.EXPECTED_CASE_NAMES, "Case order drifted")
        check(len(receipt["expected_case_names"]) == 7, "Unexpected case count")
        check(receipt["native_signing_device_executed"] is False, "Source receipt overclaims execution")
        check(receipt["swift_executed"] is False, "Source receipt overclaims Swift execution")
        check(same_size == generate.replace_once(
            positive,
            "hasher.update(data: chunk)",
            "hasher.update(data: Data(repeating: 0, count: chunk.count))",
        ), "Same-size control changed more than its single mutation")
        check(conflict == generate.replace_once(
            positive,
            "if fm.fileExists(atPath: targetFileURL.path) {\n            guard AppBundleFingerprint.compute(for: targetFileURL) == signature else {",
            "if fm.fileExists(atPath: targetFileURL.path) {\n            guard fm.fileExists(atPath: targetFileURL.path) else { // NEGATIVE CONTROL: accept a conflicting existing cache.",
        ), "Conflict control changed more than its single mutation")
        for item in receipt["generated_sources"]:
            observed = hashlib.sha256((out / item["path"]).read_bytes()).hexdigest()
            check(observed == item["sha256"], "Generated receipt digest mismatch")
        check("precondition(" not in positive and "fatalError(" not in positive, "Fixture crashes rather than reporting failure")
        check("exit(passed ? 0 : 1)" in positive, "Runtime does not fail nonzero after printing results")

        # Validate input pin enforcement against only copied synthetic scratch
        # inputs. Never edit the requested production checkout.
        tampered_root = Path(temp) / "tampered-input"
        (tampered_root / "LiveContainer").mkdir(parents=True)
        for relative in generate.SOURCE_BLOBS:
            target = tampered_root / "SideStore" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((root / "SideStore" / relative).read_bytes())
        changed = tampered_root / "SideStore/SideStore/Utils/common/AppBundleFingerprint.swift"
        changed.write_bytes(changed.read_bytes() + b"\n// source mismatch probe\n")
        try:
            generate.generate(tampered_root, Path(temp) / "must-not-publish")
        except ValueError as error:
            check("Delivered source blob mismatch" in str(error), "Mismatch failed for the wrong reason")
        else:
            raise AssertionError("A mismatched source blob was accepted")

    return {
        "schema": "install-chain-source-tests-v1", "group": "cache", "passed": True,
        "test_count": 15, "swift_executed": False, "network_executed": False,
        "native_signing_device_executed": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.root), sort_keys=True))
