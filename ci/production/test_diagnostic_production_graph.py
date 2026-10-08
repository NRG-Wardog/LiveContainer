"""Diagnostic resolver changes one reviewed pin; historical behavior stays strict."""
import copy
import unittest

import prove_graph as proof


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


if __name__ == "__main__":
    unittest.main()
