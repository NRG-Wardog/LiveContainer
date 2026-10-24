#!/usr/bin/env python3
"""Extract Group B from pinned production Swift. No Swift/native execution here."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re

PINS = {
    "SideStore/Core/Operations/PipelineOperations/UserCustomizationOperation.swift": "e19c82202cff5ba435e9df95c5635b4e93090686",
    "SideStore/Core/Operations/PipelineExecutionHandler.swift": "9f6da15d97129ca25415a8ef1f5182c558818a59",
    "AltStore/Core/Extensions/UserDefaults+AltStore.swift": "5365dae0655896c06e11bf45674129152928147e",
}
KEYS = ("customizeInfoPlist", "customizeEntitlements", "customizeAppId", "customizeAppIcon", "customizeProvisioningProfile")
CASE_NAMES = (
    "absent_preferences_no_handler_nil_result",
    "registered_false_preferences_no_handler_nil_result",
    "persisted_false_preferences_no_handler_nil_result",
    "persisted_true_customizeInfoPlist_survives_registration_and_reaches_actual_default",
    "persisted_true_customizeEntitlements_survives_registration_and_reaches_actual_default",
    "persisted_true_customizeAppIcon_survives_registration_and_reaches_actual_default",
    "persisted_true_customizeProvisioningProfile_survives_registration_and_reaches_actual_default",
    "persisted_true_app_id_supported_default_choice",
    "supported_app_id_cancel_propagates",
    "nil_target_guard_preserved_with_all_flags_false",
    "store_update_skips_true_flags_and_nil_target",
    "direct_default_info_plist_targets_exact_error",
    "direct_default_info_plist_single_exact_error",
    "direct_default_entitlements_targets_exact_error",
    "direct_default_entitlements_single_exact_error",
    "direct_default_icon_exact_error",
    "direct_default_provisioning_exact_error",
)
NEGATIVE_CONTROLS = {
    "drop-persisted-true": {"intended_failing_cases": list(CASE_NAMES[3:9])},
    "bypass-info-plist": {"intended_failing_cases": [CASE_NAMES[3]]},
}


def checked(path: Path, expected: str) -> str:
    data = path.read_bytes()
    actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if actual != expected:
        raise ValueError(f"Source blob mismatch: {path}: {actual} != {expected}")
    return data.decode("utf-8")


def block(source: str, declaration: str) -> str:
    """Balanced braces, adequate for these exact hash-pinned declarations."""
    if source.count(declaration) != 1:
        raise ValueError(f"Expected one declaration: {declaration}")
    start = source.index(declaration)
    opening = source.index("{", start)
    depth = 0
    for position in range(opening, len(source)):
        if source[position] == "{":
            depth += 1
        elif source[position] == "}":
            depth -= 1
            if depth == 0:
                return source[start:position + 1]
    raise ValueError(f"Unclosed declaration: {declaration}")


def generate(root: Path, output: Path, preferences_source: Path | None = None, mutation: str = "none") -> dict:
    operation_path, handler_path, preferences_path = PINS
    # Unified testCI root contains sibling SideStore and LiveContainer checkouts.
    # A direct SideStore root also works for a sparse source-only preparation.
    if (root / "SideStore" / operation_path).is_file():
        root = root / "SideStore"
    operation = checked(root / operation_path, PINS[operation_path])
    handler = checked(root / handler_path, PINS[handler_path])
    preferences = checked(preferences_source or root / preferences_path, PINS[preferences_path])
    # Preserve the entire operation class. Only framework imports are omitted and
    # the preference receiver is explicitly redirected to the isolated native suite.
    operation_class = block(operation, "final class UserCustomizationOperation:")
    replacements = operation_class.count("UserDefaults.standard")
    if replacements != 9:
        raise ValueError(f"Unexpected preference-receiver count: {replacements}")
    operation_class = operation_class.replace("UserDefaults.standard", "testDefaults")
    declarations = [block(handler, signature) for signature in (
        "enum AppGroupResolution:", "enum ProfileCustomizationChoice:",
        "protocol UserCustomizationHandler:", "extension UserCustomizationHandler {",
    )]
    properties = [block(preferences, f"@objc var {key}: Bool")
                  .replace("@objc ", "", 1) for key in KEYS]
    registration = {}
    for key in KEYS:
        matches = re.findall(r"#keyPath\(UserDefaults\." + key + r"\): (false|true),", preferences)
        if matches != ["false"]:
            raise ValueError(f"Unexpected registration for {key}: {matches}")
        registration[key] = False
    support = (Path(__file__).parent / "Support.swift").read_text()
    tests = (Path(__file__).parent / "Cases.swift").read_text()
    if mutation == "drop-persisted-true":
        marker = "// MUTATION_POINT_DROP_PERSISTED_TRUE"
        assert tests.count(marker) == 1
        tests = tests.replace(marker, "testDefaults.removeObject(forKey: key)")
    elif mutation == "bypass-info-plist":
        marker = "if testDefaults.customizeInfoPlist {"
        assert operation_class.count(marker) == 1
        operation_class = operation_class.replace(marker, "if false && testDefaults.customizeInfoPlist {")
    elif mutation != "none":
        raise ValueError(mutation)
    manifest = {
        "schema": "install-chain-source-manifest-v1", "group": "customization",
        "source_blobs": PINS, "mutation": mutation,
        "case_names": list(CASE_NAMES),
        "negative_control": NEGATIVE_CONTROLS.get(mutation),
        "transformations": ["omit CoreData/SideSign imports; retain entire operation class",
                            "UserDefaults.standard -> testDefaults (9 occurrences)",
                            "extract actual UserCustomizationHandler, its entire default extension, and two enums",
                            "extract five exact preference properties; strip @objc only",
                            "extract five false registration values; replace #keyPath spelling by property names"],
        "runtime_boundary": "isolated Foundation UserDefaults; inert Auth/DB/model/pipeline boundaries",
        "native_execution_performed_by_generator": False,
    }
    header = "// Generated source-extracted Group B; NOT a model of execute().\n// Source blobs: " + json.dumps(PINS, sort_keys=True) + "\n"
    native_registration = "let extractedRegistrationDefaults: [String: Any] = [\n" + "\n".join(f'    "{key}": false,' for key in registration) + "\n]\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(header + support + "\n" + "\n\n".join(declarations)
                      + "\n\nextension UserDefaults {\n" + "\n".join(properties) + "\n}\n"
                      + native_registration + "\n" + operation_class + "\n\n" + tests)
    output.with_suffix(".sources.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, nargs="?", help="Source root containing SideStore/ (or direct SideStore root)")
    parser.add_argument("output", type=Path, nargs="?", help="Generated standalone Fixture.swift path")
    parser.add_argument("--root", type=Path, dest="root_option")
    parser.add_argument("--output", type=Path, dest="output_option")
    parser.add_argument("--preferences-source", type=Path, help="Optional exact pinned preferences file if source snapshot is sparse")
    parser.add_argument("--mutation", choices=("none", "drop-persisted-true", "bypass-info-plist"), default="none")
    args = parser.parse_args()
    root, output = args.root_option or args.root, args.output_option or args.output
    if root is None or output is None:
        parser.error("root and output are required (positionals or --root/--output)")
    print(json.dumps(generate(root, output, args.preferences_source, args.mutation), sort_keys=True))


if __name__ == "__main__":
    main()
