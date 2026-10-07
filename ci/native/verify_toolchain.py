#!/usr/bin/env python3
"""Require the exact reviewed native toolchain, independent of app-directory aliases."""
import json
from pathlib import Path
import subprocess
import sys


def validate_versions(xcode, sdk, rust, cargo):
    if xcode.strip().splitlines() != ["Xcode 26.4.1", "Build version 17E202"]:
        raise ValueError("Require exactly Xcode 26.4.1 build 17E202")
    if sdk.strip() != "26.4":
        raise ValueError("Require exactly the iPhoneOS 26.4 SDK")
    for name, value in (("rustc", rust), ("cargo", cargo)):
        if not value.startswith(name + " 1.98.1 "):
            raise ValueError("Require reviewed preinstalled " + name + " 1.98.1")
    return {"xcode": xcode.strip(), "iphoneos_sdk": sdk.strip(),
            "rustc": rust.strip(), "cargo": cargo.strip(), "status": "PASS"}


if __name__ == "__main__":
    read = lambda args: subprocess.check_output(args, text=True)
    result = validate_versions(read(["xcodebuild", "-version"]),
        read(["xcrun", "--sdk", "iphoneos", "--show-sdk-version"]),
        read(["rustc", "--version"]), read(["cargo", "--version"]))
    Path(sys.argv[1]).write_text(json.dumps(result, indent=2) + "\n")
