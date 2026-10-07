#!/usr/bin/env python3
"""Network-free adversarial checks for CI guards; never run native owner suites."""
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import collect_provenance
import capture_binary_artifacts
import validate_inputs as inputs
import verify_test_results as counts
import verify_toolchain

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="guard-fixture-", dir=ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)


class ReferenceApprovalTests(FixtureCase):
    def setUp(self):
        super().setUp()
        self.document = json.loads((HERE / "owner-reference-map.json").read_text())
        for entry in self.document["owners"].values():
            if entry["source_commit"].startswith("MISSING"):
                entry["source_commit"] = "1" * 40
        self.path = self.root / "map.json"

    def write(self, document=None):
        self.path.write_text(json.dumps(document or self.document))
        return inputs.sha256(self.path)

    def test_complete_independently_pinned_fixture_is_accepted(self):
        self.assertEqual(inputs.load_map(self.path, self.write()), self.document)

    def test_pending_candidate_cannot_self_approve(self):
        document = copy.deepcopy(self.document)
        document["owners"]["SideStore"]["source_commit"] = "MISSING_REVIEWED_REMOTE_COMMIT"
        with self.assertRaisesRegex(ValueError, "missing reviewed"):
            inputs.load_map(self.path, self.write(document))

    def test_absent_or_placeholder_approval_rejected(self):
        self.write()
        for digest in (None, "", "MISSING_SEPARATELY_REVIEWED_SHA256", "a" * 63):
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                inputs.load_map(self.path, digest)

    def test_changed_map_cannot_reuse_prior_approval(self):
        digest = self.write()
        self.document["owners"]["SideSign"]["source_commit"] = "2" * 40
        self.write()
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            inputs.load_map(self.path, digest)

    def test_frozen_tree_cannot_be_changed_even_with_new_digest(self):
        self.document["owners"]["SideSign"]["source_tree"] = "2" * 40
        with self.assertRaisesRegex(ValueError, "changed frozen"):
            inputs.load_map(self.path, self.write())

    def test_original_identity_cannot_be_changed(self):
        self.document["owners"]["jktcp"]["original_source_commit"] = "2" * 40
        with self.assertRaises(ValueError):
            inputs.load_map(self.path, self.write())

    def test_missing_extra_and_empty_owners_rejected(self):
        for change in ("missing", "extra", "empty"):
            doc = copy.deepcopy(self.document)
            if change == "missing":
                del doc["owners"]["idevice"]
            elif change == "extra":
                doc["owners"]["unreviewed"] = doc["owners"]["idevice"]
            else:
                doc["owners"] = {}
            with self.subTest(change=change), self.assertRaises(ValueError):
                inputs.load_map(self.path, self.write(doc))

    def test_embedded_approval_and_moving_reference_rejected(self):
        for change in ("approval", "branch"):
            doc = copy.deepcopy(self.document)
            if change == "approval":
                doc["approved_sha256"] = "a" * 64
            else:
                doc["owners"]["LiveContainer"]["source_commit"] = "main"
            with self.subTest(change=change), self.assertRaises(ValueError):
                inputs.load_map(self.path, self.write(doc))

    def test_reviewed_assembler_copy_is_exact(self):
        inputs.approved_file(HERE / "assemble_isolated_workspace.py",
            "1a06fbd858ebb6b1eaf2f49426528391b1f5325d05aa481a5ce9ed187bb8476b")


class CheckoutGuardTests(FixtureCase):
    def setUp(self):
        super().setUp()
        inputs.git(self.root, "init", "--quiet")
        (self.root / "source.swift").write_text("let frozen = true\n")
        (self.root / ".gitignore").write_text("ignored.swift\n")
        inputs.git(self.root, "add", ".")
        inputs.git(self.root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                   "commit", "--quiet", "-m", "Local guard fixture")
        self.commit = inputs.git(self.root, "rev-parse", "HEAD")
        self.tree = inputs.git(self.root, "rev-parse", "HEAD^{tree}")

    def verify(self):
        inputs.verify_checkout(self.root, self.commit, self.tree)

    def test_clean_exact_source_passes(self):
        self.verify()

    def test_wrong_commit_or_tree_rejected(self):
        for commit, tree in (("0" * 40, self.tree), (self.commit, "0" * 40)):
            with self.subTest(commit=commit, tree=tree), self.assertRaises(ValueError):
                inputs.verify_checkout(self.root, commit, tree)

    def test_ignored_source_injection_rejected(self):
        (self.root / "ignored.swift").write_text("malicious source")
        with self.assertRaisesRegex(ValueError, "ignored source"):
            self.verify()

    def test_hidden_assume_unchanged_byte_mutation_rejected(self):
        inputs.git(self.root, "update-index", "--assume-unchanged", "source.swift")
        (self.root / "source.swift").write_text("let frozen = false\n")
        with self.assertRaisesRegex(ValueError, "byte drift"):
            self.verify()

    def test_working_symlink_substitution_rejected(self):
        inputs.git(self.root, "update-index", "--assume-unchanged", "source.swift")
        (self.root / "source.swift").unlink()
        (self.root / "source.swift").symlink_to(".gitignore")
        with self.assertRaisesRegex(ValueError, "mode changed"):
            self.verify()

    def test_shared_object_alternates_rejected(self):
        (self.root / ".git/objects/info/alternates").write_text(str(self.root / ".git/objects") + "\n")
        with self.assertRaisesRegex(ValueError, "alternates forbidden"):
            self.verify()


class SelectedTestCountTests(unittest.TestCase):
    def valid_log(self, scope):
        names = sorted(counts.EXPECTED[scope])
        if scope.startswith("jktcp-"):
            prefix = scope.removeprefix("jktcp-") + "::tests::"
            return "\n".join("test " + prefix + n + " ... ok" for n in names) + f"\ntest result: ok. {len(names)} passed; 0 failed; 0 ignored; 0 measured; 2 filtered out\n"
        return "\n".join("✔ Test " + n + "() passed after 0.001 seconds." for n in names) + f"\n✔ Test run with {len(names)} tests passed after 0.1 seconds.\n"

    def test_exact_3_5_10_4_selected_test_groups_pass(self):
        for scope in counts.EXPECTED:
            with self.subTest(scope=scope):
                self.assertEqual(counts.verify(scope, self.valid_log(scope))["executed"], len(counts.EXPECTED[scope]))

    def test_zero_missing_duplicated_and_wrong_summary_fail(self):
        for scope in counts.EXPECTED:
            log = self.valid_log(scope)
            wrong_summary = log.replace("passed;", "ignored;") if scope.startswith("jktcp-") else log.replace("passed after", "skipped after")
            variants = ("", log[log.index("\n"):], log + log.splitlines()[0], wrong_summary)
            for value in variants:
                with self.subTest(scope=scope, value=value[:35]), self.assertRaises(ValueError):
                    counts.verify(scope, value)

    def test_unexpected_live_swift_test_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unexpected Swift test"):
            counts.verify("anisette", self.valid_log("anisette") + "\nTest unicornAnisetteProvisioningAndHeaders() started.\n")


class WorkflowSafetyTests(unittest.TestCase):
    def test_exact_reviewed_toolchain_passes(self):
        result = verify_toolchain.validate_versions("Xcode 26.4.1\nBuild version 17E202\n", "26.4\n",
            "rustc 1.98.1 (48a229cea 2026-09-01)", "cargo 1.98.1 (797e8a9bc 2026-08-05)")
        self.assertEqual(result["status"], "PASS")

    def test_alias_label_and_other_builds_are_rejected(self):
        for xcode in ("Xcode 26.4\nBuild version 17E202", "Xcode 26.4.1\nBuild version WRONG", "Xcode 26.6\nBuild version 17F113"):
            with self.subTest(xcode=xcode), self.assertRaises(ValueError):
                verify_toolchain.validate_versions(xcode, "26.4", "rustc 1.98.1 (fixture)", "cargo 1.98.1 (fixture)")

    def test_sdk_and_rust_drift_are_rejected(self):
        for sdk,rust,cargo in (("26.5","rustc 1.98.1 (fixture)","cargo 1.98.1 (fixture)"),
                ("26.4","rustc 1.99.0 (fixture)","cargo 1.98.1 (fixture)"),
                ("26.4","rustc 1.98.1 (fixture)","cargo 1.99.0 (fixture)")):
            with self.subTest(sdk=sdk,rust=rust,cargo=cargo), self.assertRaises(ValueError):
                verify_toolchain.validate_versions("Xcode 26.4.1\nBuild version 17E202",sdk,rust,cargo)

    def test_historical_swiftpm_v7_schema_matches_parsers(self):
        fixture = json.loads((HERE / "fixtures/historical-swiftpm-v7-schema.json").read_text())
        self.assertEqual(fixture["version"], 7)
        self.assertFalse(fixture["provenance"]["isolated_native_run"])
        self.assertEqual({d["packageRef"]["identity"] for d in fixture["object"]["dependencies"]},
                         {"common", "devicegateway", "minimuxer", "sidesign"})
        for artifact in fixture["object"]["artifacts"]:
            source = artifact["source"]
            if source["type"] == "remote":
                self.assertEqual(set(source), {"type", "url", "checksum"})
                self.assertTrue(source["url"].startswith("https://"))
                self.assertRegex(source["checksum"], r"^[0-9a-f]{64}$")
            else:
                self.assertEqual(source, {"type": "local"})

    def test_shell_syntax(self):
        subprocess.run(["bash", "-n", str(HERE / "run-native.sh")], check=True)

    def test_yaml_branch_permissions_and_artifact_scope(self):
        import yaml  # Local structural check only; native CI does not install PyYAML.
        workflow = yaml.load((ROOT / ".github/workflows/runtime-owner-native-validation.yml").read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        self.assertEqual(set(workflow["on"]), {"push", "workflow_dispatch"})
        self.assertEqual(workflow["on"]["push"]["branches"], ["validation/runtime-source-141776ba"])
        job = workflow["jobs"]["native-validation"]
        self.assertIn("refs/heads/validation/runtime-source-141776ba", job["if"])
        self.assertEqual(job["runs-on"], "macos-26")
        steps = job["steps"]
        self.assertEqual(steps[0]["with"]["persist-credentials"], "false")
        self.assertEqual(set(steps[-1]["with"]["path"].split()), {"artifacts/logs/**", "artifacts/provenance/**"})
        self.assertEqual(sum("uses" in step for step in steps), 2)

    def test_pipeline_preserves_positive_filters_and_unsigned_builds(self):
        script = (HERE / "run-native.sh").read_text()
        self.assertNotIn("--allowProvisioning", script)
        self.assertNotIn("xcodebuild test", script)
        self.assertNotIn("git push", script)
        self.assertNotIn("gh release", script)
        self.assertEqual(script.count("CODE_SIGNING_ALLOWED=NO"), 2)
        self.assertIn("--filter 'anisetteRequestHeadersCustomization|anisetteDataResponseStructure|anisetteHeadersDTORoundtrip'", script)
        self.assertIn("(deny network*)", script)
        self.assertIn("cargo fetch --locked", script)
        self.assertIn("cargo build --frozen", script)


class CompilerEvidenceTests(FixtureCase):
    def setUp(self):
        super().setUp()
        self.w = self.root / "assembled"
        self.r = self.root / "results"
        self.d = self.root / "artifacts/provenance"
        self.logs = self.d.parent / "logs"
        for directory in (self.w, self.r, self.d, self.logs):
            directory.mkdir(parents=True, exist_ok=True)
        self.files = self.r / "owner.SwiftFileList"
        self.swift_paths = ["SideStore/AltStore/App.swift", "SideStore/Dependencies/SideSign/File.swift",
                            "AnisetteKit/Sources/File.swift", "SideStore/Dependencies/minimuxer/File.swift",
                            "LiveContainer/LiveContainerSwiftUI/App.swift"]
        self.files.write_text("\n".join(str(self.w / path) for path in self.swift_paths))
        self.packages = {"idevice": "idevice/idevice/Cargo.toml", "idevice-ffi": "idevice/ffi/Cargo.toml", "jktcp": "jktcp/Cargo.toml"}
        self.metadata = {"packages": [{"name": name, "source": None, "manifest_path": str(self.w / path)}
                                     for name, path in self.packages.items()]}
        self.metadata_path = self.d / "idevice-cargo-metadata.json"
        self.metadata_path.write_text(json.dumps(self.metadata))
        self.rust_log = self.logs / "idevice-build.log"
        self.rust_log.write_text("\n".join("Running rustc --crate-name " + name.replace("-", "_") + " --target aarch64-apple-ios src/lib.rs" for name in self.packages))
        (self.logs / "sidestore-build.log").write_text("/Applications/Xcode.app/Contents/Developer/usr/bin/clang -o SideStore -lidevice_ffi\n")
        self.original = self.r / "cargo-target/aarch64-apple-ios/release/libidevice_ffi.a"
        self.linked = self.r / "sidestore-derived/Build/Products/libidevice_ffi.a"
        for path in (self.original, self.linked):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"Synthetic parser fixture; not a compiled archive")

    def verify(self):
        collect_provenance.compile_inputs(self.w, self.r, self.d)

    def test_complete_parser_fixture_passes(self):
        self.verify()

    def test_missing_swift_owner_fails(self):
        self.files.write_text("\n".join(str(self.w / path) for path in self.swift_paths[:-1]))
        with self.assertRaisesRegex(ValueError, "compiler input evidence"):
            self.verify()

    def test_remote_rust_owner_fallback_fails(self):
        self.metadata["packages"][0]["source"] = "registry+https://example.invalid"
        self.metadata_path.write_text(json.dumps(self.metadata))
        with self.assertRaisesRegex(ValueError, "outside explicit"):
            self.verify()

    def test_missing_ios_rust_compile_fails(self):
        self.rust_log.write_text(self.rust_log.read_text().replace("--target aarch64-apple-ios", "--target aarch64-apple-darwin"))
        with self.assertRaisesRegex(ValueError, "iOS rustc"):
            self.verify()

    def test_different_staged_archive_fails(self):
        self.linked.write_bytes(b"Unexpected prebuilt replacement")
        with self.assertRaisesRegex(ValueError, "different from local FFI"):
            self.verify()


class BinaryArchiveEvidenceTests(FixtureCase):
    def setUp(self):
        super().setUp()
        self.w = self.root / "assembled"
        self.r = self.root / "results"
        self.w.mkdir()
        self.r.mkdir()
        zipped = io.BytesIO()
        with zipfile.ZipFile(zipped, "w") as archive:
            archive.writestr("Fixture.xcframework/Info.plist", "Fixture")
        self.payload = zipped.getvalue()
        self.checksum = hashlib.sha256(self.payload).hexdigest()
        self.url = "https://github.com/example/project/releases/download/fixture/archive.zip"
        owner = self.w / "AnisetteKit"
        owner.mkdir()
        (owner / "Package.swift").write_text(f'.binaryTarget(name: "Fixture", url: "{self.url}", checksum: "{self.checksum}")')
        inputs.git(owner, "init", "--quiet")
        inputs.git(owner, "add", "Package.swift")
        inputs.git(owner, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                   "commit", "--quiet", "-m", "Local binary declaration fixture")
        self.artifact = self.r / "Fixture.xcframework"
        self.artifact.mkdir()
        (self.artifact / "Info.plist").write_text("Fixture")
        self.state = self.r / "workspace-state.json"
        self.document = {"object": {"dependencies": [], "artifacts": [{"source": {"type": "remote", "url": self.url, "checksum": self.checksum}, "path": str(self.artifact)}]}}
        self.report = self.root / "proof.json"

    def verify(self, payload=None):
        self.state.write_text(json.dumps(self.document))
        response = io.BytesIO(self.payload if payload is None else payload)
        response.geturl = lambda: self.url
        with patch("sys.argv", ["capture", str(self.state), str(self.w), str(self.r), str(self.report)]), \
             patch.object(capture_binary_artifacts.urllib.request, "urlopen", return_value=response):
            capture_binary_artifacts.main()

    def test_exact_archive_and_extracted_evidence_pass(self):
        self.verify()
        proof = json.loads(self.report.read_text())
        self.assertEqual(proof["artifacts"][0]["independent_archive_sha256"], self.checksum)

    def test_changed_download_fails(self):
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.verify(b"changed")

    def test_changed_extracted_bytes_fail(self):
        (self.artifact / "Info.plist").write_text("Replaced after checksum verification")
        with self.assertRaisesRegex(ValueError, "bytes/links differ"):
            self.verify()

    def test_untracked_extracted_binary_fails(self):
        (self.artifact / "Unexpected.dylib").write_bytes(b"Injected")
        with self.assertRaisesRegex(ValueError, "bytes/links differ"):
            self.verify()

    def test_unknown_artifact_schema_fails(self):
        self.document["object"]["artifacts"][0]["source"]["type"] = "unknown"
        with self.assertRaisesRegex(ValueError, "Unknown artifact"):
            self.verify()

    def test_unapproved_url_fails(self):
        self.document["object"]["artifacts"][0]["source"]["url"] = self.url + "changed"
        with self.assertRaisesRegex(ValueError, "frozen manifest"):
            self.verify()

    def test_generated_manifest_cannot_authorize_new_archive(self):
        unexpected = self.url + "unexpected"
        inputs.git(self.w, "clone", "--quiet", "--local", "--no-hardlinks",
                   str(self.w / "AnisetteKit"), str(self.w / "SideStore"))
        generated = self.w / "SideStore/build"
        generated.mkdir(parents=True)
        (generated / "Package.swift").write_text(f'.binaryTarget(name: "Injected", url: "{unexpected}", checksum: "{self.checksum}")')
        self.document["object"]["artifacts"][0]["source"]["url"] = unexpected
        with self.assertRaises(ValueError):
            self.verify()

    def test_escaped_extracted_artifact_fails(self):
        self.document["object"]["artifacts"][0]["path"] = str(self.w)
        with self.assertRaisesRegex(ValueError, "escaped isolated"):
            self.verify()


if __name__ == "__main__":
    unittest.main(verbosity=2)
