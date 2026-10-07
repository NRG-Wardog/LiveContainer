#!/usr/bin/env python3
"""Local proof fixtures only: no resolver, tool installation or native execution."""
import copy
import hashlib
import json
import subprocess
from pathlib import Path
import tempfile
import unittest

import prove_graph as proof

ROOT = Path(__file__).resolve().parents[2]


class LockProofTests(unittest.TestCase):
    def setUp(self):
        self.before = {"version": 3, "pins": [copy.deepcopy(proof.ANISETTE)] + [
            {"identity": "dependency" + str(n), "kind": "remoteSourceControl", "location": "https://example.invalid/" + str(n),
             "state": {"revision": "a" * 40, "branch": "main"}} for n in range(5)]}

    def test_genuine_new_hash_is_retained_without_pin_changes(self):
        after = {**copy.deepcopy(self.before), "originHash": "b" * 64}
        result = proof.compare_locks(self.before, after, "sidesign")
        self.assertEqual(result["originHash"], "b" * 64)

    def test_absent_hash_remains_explicitly_unresolved(self):
        result = proof.compare_locks(self.before, self.before, "sidesign")
        self.assertIsNone(result["originHash"])
        self.assertEqual(result["metadata_status"], "absent_requires_review")

    def test_any_unrelated_pin_object_change_is_rejected(self):
        for change in ("revision", "branch", "location", "kind"):
            after = copy.deepcopy(self.before)
            pin = after["pins"][1]
            if change in {"revision", "branch"}:
                pin["state"][change] = "changed"
            else:
                pin[change] = "changed"
            with self.subTest(change=change), self.assertRaises(ValueError):
                proof.compare_locks(self.before, after, "sidesign")

    def test_missing_extra_duplicate_pins_and_other_schema_fail(self):
        for change in ("missing", "extra", "duplicate", "schema"):
            after = copy.deepcopy(self.before)
            if change == "missing": after["pins"].pop()
            elif change == "extra": after["pins"].append({**after["pins"][1], "identity": "extra"})
            elif change == "duplicate": after["pins"].append(after["pins"][1])
            else: after["version"] = 4
            with self.subTest(change=change), self.assertRaises(ValueError):
                proof.compare_locks(self.before, after, "sidesign")

    def test_nonhex_null_or_unknown_metadata_fail(self):
        for changed in ({"originHash": None}, {"originHash": "invented"}, {"extraMetadata": True}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                proof.compare_locks(self.before, {**self.before, **changed}, "sidesign")

    def test_remote_anisette_cannot_become_a_branch_or_path(self):
        for value in ({"branch": "main", "revision": proof.ANISETTE["state"]["revision"]}, {"path": "../AnisetteKit"}):
            after = copy.deepcopy(self.before)
            after["pins"][0]["state"] = value
            with self.assertRaises(ValueError): proof.compare_locks(self.before, after, "sidesign")


class FilesystemProofTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="production-proof-fixture-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "owner"
        self.repo.mkdir()
        proof.acquisition_git(self.repo, "init", "--quiet")
        (self.repo / "Source.swift").write_text("let frozen = true\n")
        (self.repo / "Package.resolved").write_text('{"version":3,"pins":[]}\n')
        (self.repo / ".gitignore").write_text(".swiftpm/\n")
        proof.git(self.repo, "add", ".")
        proof.git(self.repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--quiet", "-m", "Fixture")
        proof.git(self.repo, "remote", "add", "origin", "https://github.com/NRG-Wardog/SideSign.git")
        self.entry = {"source_commit": proof.git(self.repo, "rev-parse", "HEAD"), "source_tree": proof.git(self.repo, "rev-parse", "HEAD^{tree}"), "repository": "NRG-Wardog/SideSign"}

    def test_only_root_lock_may_change_after_resolution(self):
        (self.repo / "Package.resolved").write_text('{"version":3,"pins":[],"originHash":"' + "b" * 64 + '"}\n')
        proof.verify_source(self.repo, "SideSign", self.entry, "Package.resolved")
        with self.assertRaises(ValueError): proof.verify_source(self.repo, "SideSign", self.entry)

    def test_hidden_runtime_mutation_is_rejected(self):
        proof.git(self.repo, "update-index", "--assume-unchanged", "Source.swift")
        (self.repo / "Source.swift").write_text("let frozen = false\n")
        with self.assertRaises(ValueError): proof.verify_source(self.repo, "SideSign", self.entry, "Package.resolved")

    def test_unobserved_swiftpm_metadata_is_not_broadly_allowed(self):
        (self.repo / ".swiftpm").mkdir()
        (self.repo / ".swiftpm/new-metadata.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "unreviewed generated"):
            proof.verify_source(self.repo, "SideSign", self.entry, "Package.resolved")

    def test_symlinked_root_and_git_file_worktree_are_supported(self):
        alias = self.root / "alias"
        alias.symlink_to(self.repo, target_is_directory=True)
        proof.verify_source(alias, "SideSign", self.entry)
        linked = self.root / "linked"
        proof.git(self.repo, "worktree", "add", "--quiet", "--detach", str(linked), self.entry["source_commit"])
        self.assertTrue((linked / ".git").is_file())
        proof.verify_source(linked, "SideSign", self.entry)

    def test_core_worktree_cannot_hide_an_unexpected_swift_source(self):
        redirected = self.root / "redirected"
        proof.acquisition_git(self.root, "clone", "--quiet", str(self.repo), str(redirected))
        (self.repo / "Injected.swift").write_text("let injected = true\n")
        proof.git(self.repo, "config", "core.worktree", str(redirected))
        # Demonstrate the old -C-only enumeration misses the actual source file.
        self.assertEqual(proof.acquisition_git(self.repo, "ls-files", "--others"), "")
        with self.assertRaisesRegex(ValueError, "unreviewed generated/untracked"):
            proof.verify_source(self.repo, "SideSign", self.entry)

    def test_phase_one_artifact_declarations_include_standalone_sidesign(self):
        import capture_binary_artifacts as artifacts
        standalone = self.root / "SideSign"
        proof.acquisition_git(self.root, "clone", "--quiet", str(self.repo), str(standalone))
        url = "https://example.invalid/frozen.zip"
        checksum = "a" * 64
        (standalone / "Package.swift").write_text('url: "' + url + '", checksum: "' + checksum + '"')
        proof.git(standalone, "add", "Package.swift")
        proof.git(standalone, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "Package")
        state = self.root / "results/workspace-state.json"
        records = artifacts.manifest_declarations(self.root, state, {"object": {"dependencies": []}})
        self.assertIn((url, checksum), records)
        self.assertIn(str(standalone), records[(url, checksum)])

    def test_genuine_submodule_gitfile_is_supported(self):
        parent = self.root / "parent"
        parent.mkdir()
        proof.acquisition_git(parent, "init", "--quiet")
        subprocess.run(["git", "-C", str(parent), "-c", "protocol.file.allow=always", "submodule", "add", str(self.repo), "child"], check=True, capture_output=True)
        child = parent / "child"
        proof.git(child, "remote", "set-url", "origin", "https://github.com/NRG-Wardog/SideSign.git")
        self.assertTrue((child / ".git").is_file())
        proof.verify_source(child, "SideSign", self.entry)



class SwiftPMMirrorOriginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.resolver = self.base / 'SourcePackages'
        self.mirror = self.resolver / 'repositories/AnisetteKit-fixture'
        self.checkout = self.resolver / 'checkouts/AnisetteKit'
        self.url = 'https://github.com/NRG-Wardog/AnisetteKit.git'
        source = self.base / 'source'
        source.mkdir()
        for command in (('init', '-q'), ('config', 'user.name', 'Fixture'), ('config', 'user.email', 'fixture@example.invalid')):
            self.run_git(source, *command)
        (source / 'source.cpp').write_text('void approved() {}')
        self.run_git(source, 'add', '.')
        self.run_git(source, 'commit', '-qm', 'Fixture')
        self.commit = self.run_git(source, 'rev-parse', 'HEAD').strip()
        self.mirror.parent.mkdir(parents=True)
        self.checkout.parent.mkdir(parents=True)
        subprocess.run(['git', 'clone', '--mirror', '--no-hardlinks', str(source), str(self.mirror)], check=True, capture_output=True)
        self.run_git(self.mirror, 'remote', 'set-url', 'origin', self.url)
        subprocess.run(['git', 'clone', '--shared', '--no-checkout', str(self.mirror), str(self.checkout)], check=True, capture_output=True)
        self.run_git(self.checkout, 'checkout', '--detach', self.commit)

    def run_git(self, root, *args):
        return subprocess.check_output(['git', '-C', str(root), *args], text=True, stderr=subprocess.PIPE)

    def verify(self):
        proof.verify_source(self.checkout, 'AnisetteKit', {'source_commit': self.commit, 'source_tree': self.run_git(self.checkout, 'rev-parse', 'HEAD^{tree}').strip()})
        return proof.verify_origin(self.checkout, self.url, self.commit, self.resolver)

    def test_real_shared_clone_retains_verified_local_mirror_origin(self):
        original = self.run_git(self.checkout, 'remote', 'get-url', 'origin')
        result = self.verify()
        self.assertEqual(result['kind'], 'swiftpm-local-mirror')
        self.assertEqual(result['repository'], self.url)
        self.assertEqual(result['commit'], self.commit)
        self.assertEqual(original, self.run_git(self.checkout, 'remote', 'get-url', 'origin'))

    def test_resolved_direct_https_origin_still_requires_approved_checkout_root(self):
        self.run_git(self.checkout, 'remote', 'set-url', 'origin', self.url)
        self.assertEqual(self.verify()['kind'], 'direct')
        wrong = self.base / 'wrong-source-packages'
        wrong.mkdir()
        with self.assertRaisesRegex(ValueError, 'checkout escaped'):
            proof.verify_origin(self.checkout, self.url, self.commit, wrong)

    def test_direct_owner_acquisition_stays_strict(self):
        with self.assertRaisesRegex(ValueError, 'wrong acquisition repository'):
            proof.verify_origin(self.checkout, self.url, self.commit)

    def test_wrong_mirror_upstream_is_rejected(self):
        self.run_git(self.mirror, 'remote', 'set-url', 'origin', 'https://github.com/other/AnisetteKit.git')
        with self.assertRaisesRegex(ValueError, 'upstream repository mismatch'): self.verify()

    def test_escaped_mirror_is_rejected(self):
        import shutil
        escaped = self.base / 'escaped-mirror'
        shutil.copytree(self.mirror, escaped)
        self.run_git(self.checkout, 'remote', 'set-url', 'origin', str(escaped))
        with self.assertRaisesRegex(ValueError, 'mirror escaped'): self.verify()

    def test_symlinked_mirror_is_rejected(self):
        alias = self.mirror.parent / 'mirror-alias'
        alias.symlink_to(self.mirror, target_is_directory=True)
        self.run_git(self.checkout, 'remote', 'set-url', 'origin', str(alias))
        with self.assertRaisesRegex(ValueError, 'mirror escaped'): self.verify()

    def test_wrong_shared_object_store_is_rejected(self):
        import shutil
        escaped = self.base / 'escaped-mirror'
        shutil.copytree(self.mirror, escaped)
        (self.checkout / '.git/objects/info/alternates').write_text(str(escaped / 'objects') + '\n')
        with self.assertRaisesRegex(ValueError, 'object store escaped'): self.verify()

    def test_unreviewed_second_object_store_hop_is_rejected(self):
        (self.mirror / 'objects/info/alternates').write_text(str(self.base / 'unreviewed-objects') + '\n')
        with self.assertRaisesRegex(ValueError, 'nested resolver object store'): self.verify()

    def test_shallow_mirror_is_rejected(self):
        (self.mirror / 'shallow').write_text(self.commit + '\n')
        with self.assertRaisesRegex(ValueError, 'shallow resolver mirror'): self.verify()

    def test_wrong_checkout_revision_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'checkout commit mismatch'):
            proof.verify_origin(self.checkout, self.url, 'a' * 40, self.resolver)


class InputGateTests(unittest.TestCase):
    def test_exact_published_phase_tuples_and_missing_phase_two_rejection(self):
        path = Path(__file__).with_name("inputs-sidesign.json")
        # This test checks the proposed input bytes, not workflow approval.
        doc = proof.load_inputs(path, "d55a0dc5179b6bfed4e62c491c161b506a0f224068257a5d3695db7ba2bcf0e1", "sidesign")
        self.assertEqual(doc["owners"]["SideSign"]["source_commit"], "0d451a6eca73358be8dfed6a89c4e227752d0083")
        self.assertEqual(doc["owners"]["SideSign"]["source_tree"], "702559ec7158d567de4b0cb383dc9d9f4bc20bf7")
        path = Path(__file__).with_name("inputs-sidestore.json")
        doc = proof.load_inputs(path, "a75b040498bcc02d8857c013a974db3dd769c71fc3312e6f0389f2086739d370", "sidestore")
        self.assertEqual(doc["owners"]["SideSign"]["source_commit"], "5ce52d12f1846e1a08fad30ed27c4cbadd176529")
        self.assertEqual(doc["owners"]["SideStore"]["source_commit"], "f6e9e0ed6c3f4d02e99a0dcff0660faa0e5372b8")
        self.assertTrue(doc["sidesign_lock_metadata_reviewed"])
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "inputs.json"
            for mutation in ("missing_owner", "unreviewed_metadata"):
                candidate = copy.deepcopy(doc)
                if mutation == "missing_owner": candidate["owners"]["SideStore"]["source_commit"] = None
                else: candidate["sidesign_lock_metadata_reviewed"] = False
                fixture.write_text(json.dumps(candidate))
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    proof.load_inputs(fixture, hashlib.sha256(fixture.read_bytes()).hexdigest(), "sidestore")

    def test_missing_independent_digest_is_rejected(self):
        path = Path(__file__).with_name("inputs-sidesign.json")
        with self.assertRaisesRegex(ValueError, "independent"):
            proof.load_inputs(path, "MISSING_INDEPENDENTLY_REVIEWED_SHA256", "sidesign")


class BuildAttributionTests(unittest.TestCase):
    def setUp(self):
        import plistlib
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.roots = {name: self.base / name for name in proof.ALL_OWNERS}
        self.framework = self.roots['minimuxer'] / 'DeviceGateway/LocalBinary/IDevice.xcframework'
        self.info = {'AvailableLibraries': [{'LibraryIdentifier': 'ios-arm64', 'LibraryPath': 'libidevice_ffi.a',
            'HeadersPath': 'Headers', 'SupportedPlatform': 'ios', 'SupportedArchitectures': ['arm64']}]}
        self.write(self.framework / 'Info.plist', plistlib.dumps(self.info))
        self.write(self.framework / 'ios-arm64/libidevice_ffi.a', b'!<arch> synthetic fixture')
        self.write(self.roots['idevice'] / 'target/aarch64-apple-ios/release/libidevice_ffi.a', b'!<arch> synthetic fixture')
        for path in ('ffi/idevice.h', 'cpp/include/idevice.h', 'swift/include/idevice.h'):
            self.write(self.roots['idevice'] / path, b'void fixture(void);')
        self.write(self.framework / 'ios-arm64/Headers/idevice.h', b'void fixture(void);')
        self.write(self.framework / 'ios-arm64/Headers/module.modulemap', b'module fixture {}')
        self.write(self.roots['idevice'] / 'swift/include/module.modulemap', b'module fixture {}')

    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def test_exact_archive_header_and_module_staging_pass(self):
        report = proof.verify_build_products(self.roots, self.roots["idevice"] / "target/aarch64-apple-ios/release/libidevice_ffi.a")
        self.assertEqual(report['library_sha256'], hashlib.sha256(b'!<arch> synthetic fixture').hexdigest())

    def test_different_archive_is_rejected(self):
        self.write(self.framework / 'ios-arm64/libidevice_ffi.a', b'wrong archive')
        with self.assertRaisesRegex(ValueError, 'differs from built Rust'): proof.verify_build_products(self.roots, self.roots["idevice"] / "target/aarch64-apple-ios/release/libidevice_ffi.a")

    def test_different_generated_header_is_rejected(self):
        self.write(self.roots['idevice'] / 'cpp/include/idevice.h', b'wrong header')
        with self.assertRaisesRegex(ValueError, 'header mismatch'): proof.verify_build_products(self.roots, self.roots["idevice"] / "target/aarch64-apple-ios/release/libidevice_ffi.a")

    def test_wrong_platform_and_escaped_slice_are_rejected(self):
        import plistlib
        self.info['AvailableLibraries'][0]['SupportedPlatform'] = 'macos'
        self.write(self.framework / 'Info.plist', plistlib.dumps(self.info))
        with self.assertRaisesRegex(ValueError, 'platform/architecture'): proof.verify_build_products(self.roots, self.roots["idevice"] / "target/aarch64-apple-ios/release/libidevice_ffi.a")
        self.info['AvailableLibraries'][0]['SupportedPlatform'] = 'ios'
        self.info['AvailableLibraries'][0]['LibraryPath'] = '../../../../elsewhere.a'
        self.write(self.framework / 'Info.plist', plistlib.dumps(self.info))
        with self.assertRaisesRegex(ValueError, 'escaped/missing'): proof.verify_build_products(self.roots, self.roots["idevice"] / "target/aarch64-apple-ios/release/libidevice_ffi.a")


class CompilerProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root, self.results, self.evidence = base / "sources", base / "results", base / "artifacts/provenance"
        self.logs = self.evidence.parent / "logs"
        for directory in (self.root, self.results, self.evidence, self.logs): directory.mkdir(parents=True)
        owners = {"SideStore": "AltStore/App.swift", "SideStore/Dependencies/SideSign": "Sources/Sign.swift",
                  "AnisetteKit": "Sources/Anisette.swift", "SideStore/Dependencies/minimuxer": "Sources/Transport.swift",
                  "LiveContainer": "LiveContainerSwiftUI/App.swift"}
        self.swift = []
        for name, relative in owners.items():
            repo = self.root / name
            repo.mkdir(parents=True, exist_ok=True)
            proof.acquisition_git(repo, "init", "-q")
            source = repo / relative
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("let fixture = true\n")
            proof.git(repo, "add", relative)
            proof.git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "Source")
            self.swift.append(source)
        self.file_list = self.results / "actual.SwiftFileList"
        self.file_list.write_text("\n".join(map(str, self.swift)))
        self.resolution = {"dependencies": {"anisettekit": {"path": str(self.root / "AnisetteKit")}}}
        manifests = {"idevice": "idevice/idevice/Cargo.toml", "idevice-ffi": "idevice/ffi/Cargo.toml", "jktcp": "jktcp/Cargo.toml"}
        self.metadata = {"packages": [{"name": name, "source": None, "manifest_path": str(self.root / relative)}
                                     for name, relative in manifests.items()]}
        self.metadata_path = self.evidence / "idevice-cargo-metadata.json"
        self.metadata_path.write_text(json.dumps(self.metadata))
        self.rust_log = self.logs / "idevice-build.log"
        self.rust_log.write_text("\n".join("Running rustc --crate-name " + name.replace("-", "_") + " --target aarch64-apple-ios src/lib.rs" for name in manifests))
        self.built = self.results / "cargo-target/aarch64-apple-ios/release/libidevice_ffi.a"
        self.linked = self.results / "sidestore-derived/Build/Products/libidevice_ffi.a"
        for archive in (self.built, self.linked):
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_bytes(b"Synthetic fixture, not a native archive")
        self.link_log = self.logs / "sidestore-production-build.log"
        self.link_log.write_text("/Applications/Xcode.app/usr/bin/clang -target arm64-apple-ios15.0 -o SideStore " + str(self.linked) + "\n")

    def verify(self):
        return proof.capture_compiler_inputs(self.root, self.results, self.evidence / "compiler-input-lists", self.resolution, "sidestore")

    def test_committed_sources_and_actual_archive_link_pass(self):
        self.assertEqual(len(self.verify()["owners"]), 5)
        self.link_log.write_text("/Applications/Xcode.app/usr/bin/clang -o SideStore -L" + str(self.linked.parent) + " -lidevice_ffi\n")
        self.assertEqual(self.verify()["actual_linker_inputs"][0]["sha256"], proof.sha(self.built))

    def test_canonical_aliases_in_actual_source_paths_pass(self):
        alias = self.root.parent / "source-alias"
        alias.symlink_to(self.root, target_is_directory=True)
        self.file_list.write_text("\n".join(str(alias / path.relative_to(self.root)) for path in self.swift))
        self.assertEqual(len(self.verify()["owners"]), 5)

    def test_unobserved_generated_source_report_cannot_whitelist_a_path(self):
        generated = self.results / "sidestore-derived/DerivedSources/resource_bundle_accessor.swift"
        generated.parent.mkdir(parents=True, exist_ok=True)
        generated.write_text("let unreviewed = true")
        (self.evidence / "generated-xcode-sources.json").write_text(json.dumps({"sources": {str(generated): {
            "owner": "SideStore", "kind": "invented", "target": "SideStore", "file_list": str(self.file_list)}}}))
        with self.assertRaisesRegex(ValueError, "Unreviewed or incomplete generated"):
            self.verify()

    def test_generated_sources_alone_cannot_supply_runtime_owner_coverage(self):
        known = proof.expected_sources({"SideStore": self.root / "SideStore", "LiveContainer": self.root / "LiveContainer"}, self.results)
        listings = {}
        for path, row in known.items():
            source = Path(path)
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("// synthetic generated source")
            listings.setdefault(Path(row["file_list"]), []).append(source)
        for file, sources in listings.items():
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("\n".join(map(str, sources)))
        for path, row in known.items():
            row.update(sha256=proof.sha(Path(path)), file_list_sha256=proof.sha(Path(row["file_list"])))
        (self.evidence / "generated-xcode-sources.json").write_text(json.dumps({"sources": known}))
        self.file_list.write_text("\n".join(map(str, self.swift[1:-1])))
        with self.assertRaisesRegex(ValueError, "Compiler input evidence missing for SideStore, LiveContainer"):
            self.verify()

    def test_registry_sourced_rust_owner_fails(self):
        self.metadata["packages"][0]["source"] = "registry+https://example.invalid"
        self.metadata_path.write_text(json.dumps(self.metadata))
        with self.assertRaisesRegex(ValueError, "outside explicit"):
            self.verify()

    def test_wrong_rust_manifest_fails(self):
        self.metadata["packages"][0]["manifest_path"] = str(self.root / "other/Cargo.toml")
        self.metadata_path.write_text(json.dumps(self.metadata))
        with self.assertRaisesRegex(ValueError, "outside explicit"):
            self.verify()

    def test_host_target_cannot_stand_in_for_ios_compilation(self):
        self.rust_log.write_text(self.rust_log.read_text().replace("aarch64-apple-ios", "aarch64-apple-darwin"))
        with self.assertRaisesRegex(ValueError, "iOS rustc"):
            self.verify()

    def test_replaced_xcode_archive_fails(self):
        self.linked.write_bytes(b"Unexpected prebuilt replacement")
        with self.assertRaisesRegex(ValueError, "different from local FFI"):
            self.verify()

    def test_nonexistent_swift_input_fails(self):
        self.file_list.write_text(self.file_list.read_text().replace("App.swift", "Invented.swift"))
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.verify()

    def test_existing_outside_owner_source_fails(self):
        outside = self.results / "outside.swift"
        outside.write_text("let outside = true\n")
        self.file_list.write_text(self.file_list.read_text() + "\n" + str(outside))
        with self.assertRaisesRegex(ValueError, "outside proven owner"):
            self.verify()

    def test_uncommitted_owner_source_fails(self):
        injected = self.swift[0].with_name("Injected.swift")
        injected.write_text("let injected = true\n")
        self.file_list.write_text(self.file_list.read_text() + "\n" + str(injected))
        with self.assertRaisesRegex(ValueError, "not a committed source"):
            self.verify()

    def test_unused_equal_archive_does_not_prove_the_linker_input(self):
        self.link_log.write_text("/Applications/Xcode.app/usr/bin/clang -o SideStore /unrelated/libidevice_ffi.a\n")
        with self.assertRaisesRegex(ValueError, "absent or outside Xcode"):
            self.verify()

    def test_echo_diagnostic_and_output_archive_are_not_link_inputs(self):
        for command in ("echo /Applications/Xcode.app/usr/bin/clang -o SideStore " + str(self.linked),
                        "/Applications/Xcode.app/usr/bin/clang -o " + str(self.linked)):
            self.link_log.write_text(command + "\n")
            with self.subTest(command=command), self.assertRaisesRegex(ValueError, "actual Xcode|actual IDevice"):
                self.verify()

    def test_mixed_search_path_forms_preserve_actual_linker_order(self):
        wrong = self.results / "outside-xcode"
        wrong.mkdir()
        (wrong / "libidevice_ffi.a").write_bytes(b"Wrong first-match archive")
        self.link_log.write_text("/Applications/Xcode.app/usr/bin/clang -o SideStore -L " + str(wrong) + " -L" + str(self.linked.parent) + " -lidevice_ffi\n")
        with self.assertRaisesRegex(ValueError, "outside Xcode"):
            self.verify()

    def test_competing_dynamic_library_cannot_be_ignored(self):
        self.link_log.write_text("/Applications/Xcode.app/usr/bin/clang -o SideStore -L" + str(self.linked.parent) + " -lidevice_ffi\n")
        for suffix in (".dylib", ".tbd"):
            competing = self.linked.with_suffix(suffix)
            competing.write_bytes(b"Competing dynamic library")
            with self.subTest(suffix=suffix), self.assertRaisesRegex(ValueError, "Competing dynamic"):
                self.verify()
            competing.unlink()

    def test_bare_library_flag_without_resolved_search_path_fails(self):
        self.link_log.write_text("/Applications/Xcode.app/usr/bin/clang -o SideStore -lidevice_ffi\n")
        with self.assertRaisesRegex(ValueError, "no actual archive"):
            self.verify()


class CommandBoundaryTests(unittest.TestCase):
    def test_production_offline_tests_reuse_runtime_canary_and_inner_sandbox_fix(self):
        script = Path(__file__).with_name("run-production.sh").read_text()
        self.assertIn("/usr/bin/sandbox-exec -p '(version 1) (allow default) (deny network*)'", script)
        self.assertIn("export -f offline", script)
        self.assertIn('verify_network_sandbox.py" "$EVIDENCE/provenance/network-sandbox-proof.json"', script)
        self.assertLess(script.index("verify_network_sandbox.py"), script.index("STAGE=fetch"))
        swift = [line for line in script.replace("\\\n", " ").splitlines() if "offline swift test " in line]
        self.assertEqual(len(swift), 1)
        for option in ("--skip-build", "--disable-sandbox", "--force-resolved-versions", "--filter"):
            self.assertIn(option, swift[0])
        self.assertNotIn('assemble_isolated_workspace.py" assemble', script)
        self.assertNotIn('swift package config set-mirror', script)


if __name__ == "__main__":
    unittest.main(verbosity=2)
