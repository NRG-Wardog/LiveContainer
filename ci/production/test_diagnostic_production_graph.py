"""Diagnostic resolver changes one reviewed pin; historical behavior stays strict."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import types
import unittest
from unittest.mock import patch

import prove_graph as proof
import run_diagnostic_sidestore_suite as suites


class DiagnosticLockProofTests(unittest.TestCase):
    def setUp(self):
        self.target = {**proof.ANISETTE, "state": {"revision": "e530b84687ebea2e7d1115119e1a6d18372de14b"}}
        self.before = {"version": 3, "pins": [copy.deepcopy(proof.ANISETTE)] + [
            {"identity": "dependency" + str(n), "kind": "remoteSourceControl",
             "location": "https://example.invalid/" + str(n),
             "state": {"revision": "a" * 40, "branch": "main"}} for n in range(5)]}
        self.after = copy.deepcopy(self.before)
        self.after["pins"][0] = copy.deepcopy(self.target)

    def check(self, before=None, after=None, target=None):
        return proof.compare_locks(before or self.before, after or self.after, "sidesign", target or self.target)

    def test_exact_revision_transition_preserves_five_other_pins(self):
        result = self.check()
        self.assertFalse(result["pin_objects_unchanged"])
        self.assertTrue(result["approved_diagnostic_anisette_transition"])
        self.assertEqual(len(result["pins"]), 6)
        self.assertEqual(result["pins"]["anisettekit"], self.target)

    def test_frozen_resolve_accepts_identical_final_pins(self):
        self.assertTrue(self.check(before=self.after)["pin_objects_unchanged"])

    def test_legacy_mode_does_not_accept_diagnostic_pin(self):
        with self.assertRaises(ValueError):
            proof.compare_locks(self.before, self.after, "sidesign")

    def test_unrelated_revision_branch_kind_or_location_is_rejected(self):
        for field in ("revision", "branch", "kind", "location"):
            value = copy.deepcopy(self.after)
            pin = value["pins"][1]
            (pin["state"] if field in {"revision", "branch"} else pin)[field] = "changed"
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.check(after=value)

    def test_unknown_initial_anisette_revision_is_rejected(self):
        value = copy.deepcopy(self.before)
        value["pins"][0]["state"]["revision"] = "c" * 40
        with self.assertRaises(ValueError):
            self.check(before=value)

    def test_missing_extra_and_duplicate_pins_are_rejected(self):
        for kind in ("missing", "extra", "duplicate"):
            value = copy.deepcopy(self.after)
            if kind == "missing": value["pins"].pop()
            elif kind == "extra": value["pins"].append({**value["pins"][1], "identity": "extra"})
            else: value["pins"].append(value["pins"][1])
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.check(after=value)

    def test_target_cannot_switch_repository_or_use_a_branch(self):
        for changes in ({"location": "https://example.invalid/AnisetteKit.git"},
                        {"state": {"revision": self.target["state"]["revision"], "branch": "main"}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.check(target={**self.target, **changes})

    def test_real_origin_hash_presence_and_absence_are_retained(self):
        self.assertIsNone(self.check()["originHash"])
        self.assertEqual(self.check(after={**self.after, "originHash": "d" * 64})["originHash"], "d" * 64)
        for value in (None, "invented", "A" * 64):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.check(after={**self.after, "originHash": value})

    def test_two_app_transition_preserves_all_nine_unrelated_pins(self):
        before = copy.deepcopy(self.before)
        before["pins"] += [{**copy.deepcopy(before["pins"][1]), "identity": "extra" + str(n)} for n in range(4)]
        after = copy.deepcopy(before)
        after["pins"][0] = self.target
        result = proof.compare_locks(before, after, "sidestore", self.target)
        self.assertEqual(len(result["pins"]), 10)
        after["pins"][-1]["state"]["revision"] = "f" * 40
        with self.assertRaisesRegex(ValueError, "outside the exact diagnostic"):
            proof.compare_locks(before, after, "sidestore", self.target)


class DiagnosticPhaseTwoInputTests(unittest.TestCase):
    """Synthetic metadata exercises approval boundaries; it is not native evidence."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.original = proof.PRODUCTION_DIR
        self.patch = patch.object(proof, "PRODUCTION_DIR", self.directory)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        (self.directory / "diagnostic/dependencies").mkdir(parents=True)
        shutil.copyfile(self.original / "diagnostic/accepted-to-diagnostic-delta.json",
                        self.directory / "diagnostic/accepted-to-diagnostic-delta.json")
        shutil.copyfile(self.original / "diagnostic/focused-native-verification.json",
                        self.directory / "diagnostic/focused-native-verification.json")
        self.delta = json.loads((self.directory / "diagnostic/accepted-to-diagnostic-delta.json").read_text())
        self.data = json.loads((self.original / "inputs-adi-sidestore.json").read_text())
        self.data["sidesign_lock_metadata_reviewed"] = True
        self.bases = {}
        for n, name in enumerate(("SideSign", "SideStore"), start=1):
            self.data["owners"][name].update(source_commit=str(n) * 40, source_tree=str(n + 2) * 40)
            accepted = self.delta["accepted_graph"][name]
            basis = {"accepted": {k: accepted[k] for k in ("commit", "tree")},
                "source_registry_sha256": proof.DIAGNOSTIC_REGISTRY,
                "candidate": {"commit": self.data["owners"][name]["source_commit"],
                              "tree": self.data["owners"][name]["source_tree"]}}
            if name == "SideStore":
                checkpoint = self.delta["diagnostic_source_tuple"][name]
                basis.update(source_delta_sha256=proof.DIAGNOSTIC_DELTA,
                    source_checkpoint={k: checkpoint[k] for k in ("commit", "tree")},
                    sidesign={"repository": "https://github.com/NRG-Wardog/SideSign.git",
                        "commit": self.data["owners"]["SideSign"]["source_commit"],
                        "tree": self.data["owners"]["SideSign"]["source_tree"],
                        "basis_sha256": self.data["dependency_bases"]["SideSign"]["sha256"]})
            self.bases[name] = basis
            self.save_basis(name)
        self.data["resolver_receipts"]["SideSign"] = self.document("SideSign", "resolver", {"fixture": True})

    def document(self, owner, kind, data):
        relative = "diagnostic/dependencies/" + owner + "-" + kind + ".json"
        target = self.directory / relative
        target.write_text(json.dumps(data) + "\n")
        return {"path": relative, "sha256": proof.sha(target)}

    def save_basis(self, owner):
        self.data["dependency_bases"][owner] = self.document(owner, "basis", self.bases[owner])

    def load(self, data=None):
        path = self.directory / "inputs.json"
        path.write_text(json.dumps(data or self.data) + "\n")
        return proof.load_inputs(path, proof.sha(path), "sidestore")

    def test_missing_published_owner_identity_remains_rejected(self):
        data = copy.deepcopy(self.data)
        data["owners"]["SideStore"]["source_commit"] = None
        with self.assertRaisesRegex(ValueError, "verified published commit/tree required"):
            self.load(data)

    def test_complete_bound_inputs_allow_pending_app_resolution(self):
        self.assertIsNone(self.load()["resolver_receipts"]["SideStore"])
        self.assertEqual(proof.diagnostic_basis(self.data, "sidestore", "SideStore")[1],
                         self.data["dependency_bases"]["SideStore"]["sha256"])

    def test_unchanged_transport_and_diagnostic_runtime_owners_cannot_move(self):
        for owner in proof.ALL_OWNERS - {"SideStore", "SideSign"}:
            data = copy.deepcopy(self.data)
            data["owners"][owner]["source_commit"] = "f" * 40
            with self.subTest(owner=owner), self.assertRaisesRegex(ValueError, "Diagnostic source identity changed"):
                self.load(data)

    def test_final_child_tree_and_basis_digest_must_match_app_basis(self):
        for field in ("commit", "tree", "basis_sha256"):
            data = copy.deepcopy(self.bases["SideStore"])
            self.bases["SideStore"]["sidesign"][field] = "f" * (64 if field == "basis_sha256" else 40)
            self.save_basis("SideStore")
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "exact final SideSign"):
                self.load()
            self.bases["SideStore"] = data

    def test_missing_phase_one_receipt_or_review_is_rejected(self):
        for missing in ("receipt", "review", "basis"):
            data = copy.deepcopy(self.data)
            if missing == "receipt": data["resolver_receipts"]["SideSign"] = None
            elif missing == "review": data["sidesign_lock_metadata_reviewed"] = False
            else: data["dependency_bases"]["SideStore"] = None
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                self.load(data)

    def test_unapproved_receipt_bytes_and_path_are_rejected(self):
        for field, value in (("sha256", "f" * 64), ("path", "../SideSign-resolver.json")):
            data = copy.deepcopy(self.data)
            data["resolver_receipts"]["SideSign"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.load(data)

    def test_prior_focused_native_proof_cannot_be_omitted_or_replaced(self):
        for change in (None, {"path": "diagnostic/focused-native-verification.json", "sha256": "f" * 64}):
            data = copy.deepcopy(self.data)
            data["focused_native_validation"] = change
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "Previously reviewed"):
                self.load(data)
        receipt = self.directory / "diagnostic/focused-native-verification.json"
        receipt.write_text(receipt.read_text() + "\n")
        with self.assertRaises(ValueError):
            self.load()

    def test_source_checkpoint_cannot_be_replaced_by_accepted_parity(self):
        self.bases["SideStore"]["source_checkpoint"] = self.bases["SideStore"]["accepted"]
        self.save_basis("SideStore")
        with self.assertRaisesRegex(ValueError, "exact final SideSign"):
            self.load()

    def test_owner_receipt_is_forwarded_and_unresolved_child_is_rejected(self):
        receipt = self.data["resolver_receipts"]["SideSign"]
        entry = self.data["owners"]["SideSign"]
        result = {"owner": "SideSign", "status": "diagnostic_dependency_transition_pass",
            "production_ready": False, "commit": entry["source_commit"], "tree": entry["source_tree"],
            "diagnostic_basis_sha256": self.data["dependency_bases"]["SideSign"]["sha256"],
            "lock_status": "reviewed_resolver_observed_lock", "resolver_receipt_sha256": receipt["sha256"]}
        with patch.object(proof.subprocess, "run") as command:
            command.return_value.stdout = json.dumps(result)
            proof.diagnostic_owner_proof(self.directory, self.data, "sidestore", "SideSign")
            args = command.call_args.args[0]
            self.assertIn(str(self.directory / receipt["path"]), args)
            self.assertIn(receipt["sha256"], args)
            result["lock_status"] = "accepted_lock_retained_pending_resolution"
            command.return_value.stdout = json.dumps(result)
            with self.assertRaisesRegex(ValueError, "real reviewed SideSign resolver lock"):
                proof.diagnostic_owner_proof(self.directory, self.data, "sidestore", "SideSign")


class DiagnosticSuiteInventoryTests(unittest.TestCase):
    def module(self):
        module = types.ModuleType("fixture")
        named = {key.split(".")[1]: lambda self: None for key in suites.SUPERSEDED}
        named.update({"test_retained_" + str(n): lambda self: None for n in range(42)})
        named["__module__"] = "fixture"
        module.SourceContracts = type("SourceContracts", (unittest.TestCase,), named)
        return module

    def test_each_original_test_runs_once_in_exactly_one_scope(self):
        module = self.module()
        current = {test.id() for test in suites.select_suite(module)}
        historical = {test.id() for test in suites.select_suite(module, historical=True)}
        self.assertEqual((len(current), len(historical)), (42, 4))
        self.assertFalse(current & historical)
        self.assertEqual(len(current | historical), 46)

    def test_missing_added_or_renamed_historical_assertions_fail_closed(self):
        for change in ("add", "remove", "rename"):
            module = self.module()
            cls = module.SourceContracts
            if change != "add":
                delattr(cls, "test_whole_owner_tree_exact_hashes_modes_and_inventory")
            if change != "remove":
                setattr(cls, "test_unreviewed", lambda self: None)
            with self.subTest(change=change), self.assertRaises(ValueError):
                suites.select_suite(module)


class DiagnosticCompilerInputTests(unittest.TestCase):
    def setUp(self):
        root, results = Path("/diagnostic/source"), Path("/diagnostic/results")
        self.requirements = proof.diagnostic_compiler_requirements(root, results,
            {"dependencies": {"anisettekit": {"path": "/diagnostic/results/sidestore-packages/checkouts/AnisetteKit"}}})
        self.records = {}
        self.logs = {"sidestore": "", "livecontainer": ""}
        for source, spec in self.requirements.items():
            self.records.setdefault(spec["owner"], []).append({"file": spec["file_list"],
                "inputs": [{"path": source, "blob": "a" * 40, "sha256": "b" * 64}]})
            self.logs[spec["build"]] += ("builtin-Swift-Compilation -- /reviewed/toolchain/swiftc -c "
                "-module-name " + spec["target"] + " -target arm64-apple-ios15.0 -sdk /reviewed/iPhoneOS26.4.sdk @" + spec["file_list"] + "\n")

    def test_every_changed_swift_source_requires_its_exact_target_list(self):
        self.assertEqual(len(proof.verify_diagnostic_compiler_inputs(self.records, self.requirements, self.logs)), 4)
        for source, spec in self.requirements.items():
            records = copy.deepcopy(self.records)
            for record in records[spec["owner"]]:
                record["inputs"] = [item for item in record["inputs"] if item["path"] != source]
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, "missing from its exact app target"):
                proof.verify_diagnostic_compiler_inputs(records, self.requirements, self.logs)

    def test_same_filename_elsewhere_or_wrong_app_target_cannot_supply_coverage(self):
        for kind in ("source", "target"):
            records = copy.deepcopy(self.records)
            record = records["LiveContainer"][1]
            if kind == "source": record["inputs"][0]["path"] = "/unreviewed/SideStore.swift"
            else: record["file"] = record["file"].replace("SideStoreSupport", "LiveContainerSwiftUI")
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                proof.verify_diagnostic_compiler_inputs(records, self.requirements, self.logs)

    def test_actual_ios_compilation_is_required_not_echo_or_host_commands(self):
        for kind in ("echo", "host", "missing"):
            logs = copy.deepcopy(self.logs)
            if kind == "echo": logs["livecontainer"] = logs["livecontainer"].replace("builtin-Swift-Compilation --", "echo")
            elif kind == "host": logs["livecontainer"] = logs["livecontainer"].replace("arm64-apple-ios15.0", "arm64-apple-macos15.0")
            else: logs["livecontainer"] = ""
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "No actual iPhoneOS Swift compilation"):
                proof.verify_diagnostic_compiler_inputs(self.records, self.requirements, logs)


if __name__ == "__main__":
    unittest.main()
