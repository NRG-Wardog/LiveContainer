"""Version-isolated v2 source, resolver and compiler-proof boundaries."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import prove_graph as proof
import test_diagnostic_production_graph as first_version_tests


class VersionTwoSourceTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.directory)
        self.original = proof.PRODUCTION_DIR
        shutil.copytree(self.original / "diagnostic-v2", self.directory / "diagnostic-v2")
        self.patcher = patch.object(proof, "PRODUCTION_DIR", self.directory)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.data = json.loads((self.original / "inputs-adi-v2-sidesign.json").read_text())
        self.delta = json.loads((self.directory / "diagnostic-v2/accepted-to-diagnostic-delta.json").read_text())
        self.data["owners"]["SideSign"].update(source_commit="1" * 40, source_tree="2" * 40)
        accepted = self.delta["accepted_graph"]["SideSign"]
        basis = {"accepted": {k: accepted[k] for k in ("commit", "tree")},
            "candidate": {"commit": "1" * 40, "tree": "2" * 40},
            "source_registry_sha256": self.data["source_registry_sha256"]}
        target = self.directory / "diagnostic-v2/dependencies/SideSign-basis.json"
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(basis))
        self.data["dependency_basis"]["sha256"] = proof.sha(target)

    def load(self, data=None):
        path = self.directory / "inputs.json"
        path.write_text(json.dumps(data or self.data))
        return proof.load_inputs(path, proof.sha(path), "sidesign")

    def test_complete_v2_source_binding_preserves_accepted_v1_parent(self):
        self.assertEqual(self.load()["source_basis"], "maintained-adi-consumption-v2")
        self.assertEqual(proof.diagnostic_variant(self.data)["previous_anisette"],
                         self.delta["accepted_graph"]["AnisetteKit"]["commit"])

    def test_cross_version_registry_path_and_runtime_tuple_are_rejected(self):
        for field in ("registry", "path", "owner", "source_basis"):
            data = copy.deepcopy(self.data)
            if field == "registry": data["source_registry_sha256"] = proof.DIAGNOSTIC_REGISTRY
            elif field == "path": data["dependency_basis"]["path"] = "diagnostic/dependencies/SideSign-basis.json"
            elif field == "owner": data["owners"]["AnisetteKit"]["source_commit"] = proof.DIAGNOSTIC_VARIANTS["maintained-adi-consumption-v2"]["previous_anisette"]
            else: data["source_basis"] = "maintained-adi-consumption-v3"
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.load(data)

    def test_unresolved_owner_or_basis_digest_is_rejected(self):
        for field in ("owner", "digest"):
            data = copy.deepcopy(self.data)
            if field == "owner": data["owners"]["SideSign"]["source_commit"] = None
            else: data["dependency_basis"]["sha256"] = None
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.load(data)

    def test_v2_reuses_exact_seven_plus_six_receipt(self):
        data = json.loads((self.original / "inputs-adi-v2-sidestore.json").read_text())
        self.assertEqual(proof.focused_native_receipt(data, self.delta)["tests"]["SideStore_with_LiveContainer_peer"], 6)
        data["focused_native_validation"] = {"path": "diagnostic/focused-native-verification.json", "sha256": proof.FOCUSED_NATIVE_RECEIPT}
        with self.assertRaisesRegex(ValueError, "Previously reviewed"):
            proof.focused_native_receipt(data, self.delta)

    def test_historical_fixture_remains_original_parity_commit(self):
        self.assertEqual(proof.HISTORICAL_SIDESTORE["commit"], "dd4f0ca36e8ef1d858548f583c65842a8fc0ced3")
        self.assertNotEqual(proof.HISTORICAL_SIDESTORE["commit"], self.delta["accepted_graph"]["SideStore"]["commit"])

    def test_phase_two_requires_v2_app_checkpoint_and_bound_child_basis(self):
        data = json.loads((self.original / "inputs-adi-v2-sidestore.json").read_text())
        data["owners"]["SideSign"] = self.data["owners"]["SideSign"]
        data["owners"]["SideStore"].update(source_commit="3" * 40, source_tree="4" * 40)
        data["sidesign_lock_metadata_reviewed"] = True
        data["dependency_bases"]["SideSign"] = self.data["dependency_basis"]
        receipt = self.directory / "diagnostic-v2/dependencies/SideSign-resolver.json"
        receipt.write_text('{"fixture_only": true}')
        data["resolver_receipts"]["SideSign"]["sha256"] = proof.sha(receipt)
        accepted = self.delta["accepted_graph"]["SideStore"]
        checkpoint = self.delta["diagnostic_source_tuple"]["SideStore"]
        basis = {"accepted": {k: accepted[k] for k in ("commit", "tree")},
            "candidate": {"commit": "3" * 40, "tree": "4" * 40},
            "source_registry_sha256": data["source_registry_sha256"],
            "source_delta_sha256": proof.diagnostic_variant(data)["delta"],
            "source_checkpoint": {k: checkpoint[k] for k in ("commit", "tree")},
            "sidesign": {"repository": "https://github.com/NRG-Wardog/SideSign.git", "commit": "1" * 40,
                "tree": "2" * 40, "basis_sha256": self.data["dependency_basis"]["sha256"]}}
        path = self.directory / data["dependency_bases"]["SideStore"]["path"]
        path.write_text(json.dumps(basis))
        data["dependency_bases"]["SideStore"]["sha256"] = proof.sha(path)
        self.assertEqual(proof.diagnostic_basis(data, "sidestore", "SideStore")[0], path)
        basis["accepted"] = proof.HISTORICAL_SIDESTORE
        path.write_text(json.dumps(basis))
        data["dependency_bases"]["SideStore"]["sha256"] = proof.sha(path)
        with self.assertRaisesRegex(ValueError, "accepted source transition"):
            proof.diagnostic_basis(data, "sidestore", "SideStore")


class VersionTwoLockTests(unittest.TestCase):
    def test_exact_v1_to_v2_pin_transition_preserves_every_other_pin(self):
        previous = {**proof.ANISETTE, "state": {"revision": "e530b84687ebea2e7d1115119e1a6d18372de14b"}}
        target = {**proof.ANISETTE, "state": {"revision": "f494494ede88890555df345054f7fbb87b53aea5"}}
        for phase, count in (("sidesign", 6), ("sidestore", 10)):
            before = {"version": 3, "pins": [previous] + [{"identity": str(n), "state": {"revision": "a" * 40}}
                for n in range(count - 1)]}
            after = {**before, "pins": [target] + copy.deepcopy(before["pins"][1:])}
            with self.subTest(phase=phase):
                self.assertEqual(len(proof.compare_locks(before, after, phase, target, previous)["pins"]), count)
                wrong = {**before, "pins": [proof.ANISETTE] + before["pins"][1:]}
                with self.assertRaisesRegex(ValueError, "initial Anisette"):
                    proof.compare_locks(wrong, after, phase, target, previous)
                after["pins"][-1]["state"]["revision"] = "b" * 40
                with self.assertRaisesRegex(ValueError, "outside the exact diagnostic"):
                    proof.compare_locks(before, after, phase, target, previous)


class VersionTwoCompilerTests(first_version_tests.DiagnosticCompilerInputTests):
    def setUp(self):
        super().setUp()
        self.requirements = proof.diagnostic_compiler_requirements(Path("/diagnostic/source"), Path("/diagnostic/results"),
            {"dependencies": {"anisettekit": {"path": "/diagnostic/results/sidestore-packages/checkouts/AnisetteKit"}}},
            "maintained-adi-consumption-v2")
        for source, spec in list(self.requirements.items())[4:]:
            self.records["SideStore"].append({"file": spec["file_list"],
                "inputs": [{"path": source, "blob": "a" * 40, "sha256": "b" * 64}]})

    def test_every_changed_swift_source_requires_its_exact_target_list(self):
        self.assertEqual(len(proof.verify_diagnostic_compiler_inputs(self.records, self.requirements, self.logs)), 6)
        for source, spec in self.requirements.items():
            records = copy.deepcopy(self.records)
            for record in records[spec["owner"]]:
                record["inputs"] = [item for item in record["inputs"] if item["path"] != source]
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, "missing from its exact app target"):
                proof.verify_diagnostic_compiler_inputs(records, self.requirements, self.logs)


if __name__ == "__main__":
    unittest.main()
