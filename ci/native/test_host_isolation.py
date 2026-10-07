#!/usr/bin/env python3
"""Local structural regression checks for the selected validation host branch."""
import copy
from pathlib import Path
import re
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
BASE = "fb5a23f256b7c687fcd0149ac968d18830034463"
BRANCH = "validation/runtime-source-141776ba"
PRODUCTION_BRANCH = "validation/production-dependencies-141776ba"
GUARD = ("github.ref != 'refs/heads/" + BRANCH + "' && github.head_ref != '" + BRANCH +
         "' && github.base_ref != '" + BRANCH + "'")

GUARD += (" && github.ref != 'refs/heads/" + PRODUCTION_BRANCH + "' && github.head_ref != '" + PRODUCTION_BRANCH +
          "' && github.base_ref != '" + PRODUCTION_BRANCH + "'")


def baseline(relative):
    return subprocess.check_output(["git", "--no-replace-objects", "-C", str(ROOT), "show", BASE + ":" + relative], text=True)


class HostIsolationTests(unittest.TestCase):
    def test_checkout_cleanup_does_not_write_global_safe_directory(self):
        workflow = yaml.load((ROOT / ".github/workflows/runtime-owner-native-validation.yml").read_text(), Loader=yaml.BaseLoader)
        job = workflow["jobs"]["native-validation"]
        self.assertEqual(job["steps"][0]["with"]["set-safe-directory"], "false")
        self.assertEqual(job["steps"][0]["with"]["persist-credentials"], "false")
        self.assertEqual(job["env"]["GIT_CONFIG_GLOBAL"], "/dev/null")

    def setUp(self):
        self.path = ".github/workflows/build.yml"
        self.original = yaml.load(baseline(self.path), Loader=yaml.BaseLoader)
        self.current = yaml.load((ROOT / self.path).read_text(), Loader=yaml.BaseLoader)

    def test_validation_push_is_excluded_and_tag_behavior_preserved(self):
        self.assertEqual(self.current["on"]["push"], {"branches-ignore": [BRANCH, PRODUCTION_BRANCH], "tags": ["**"]})

    def test_all_legacy_jobs_explicitly_exclude_validation_dispatch_and_pr(self):
        self.assertEqual(self.current["jobs"]["build"]["if"], GUARD)
        self.assertEqual(self.current["jobs"]["release__nightly"]["if"],
                         GUARD + " && (" + self.original["jobs"]["release__nightly"]["if"] + ")")

    def test_original_workflow_semantics_are_otherwise_unchanged(self):
        normalized = copy.deepcopy(self.current)
        normalized["on"]["push"] = self.original["on"]["push"]
        del normalized["jobs"]["build"]["if"]
        normalized["jobs"]["release__nightly"]["if"] = self.original["jobs"]["release__nightly"]["if"]
        self.assertEqual(normalized, self.original)

    def test_update_source_has_no_push_or_run_chaining_and_is_unchanged(self):
        path = ".github/workflows/update_source.yml"
        self.assertEqual((ROOT / path).read_text(), baseline(path))
        workflow = yaml.load((ROOT / path).read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(set(workflow["on"]), {"release", "workflow_dispatch"})

    def test_new_workflow_has_exact_host_branch_push_and_read_permissions(self):
        workflow = yaml.load((ROOT / ".github/workflows/runtime-owner-native-validation.yml").read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(workflow["on"]["push"]["branches"], [BRANCH])
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        self.assertEqual(workflow["jobs"]["native-validation"]["if"],
                         "github.repository == 'NRG-Wardog/LiveContainer' && github.ref == 'refs/heads/" + BRANCH + "'")

    def test_production_workflow_is_separate_read_only_and_fail_closed(self):
        workflow = yaml.load((ROOT / ".github/workflows/production-dependency-validation.yml").read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(workflow["on"], {"push": {"branches": [PRODUCTION_BRANCH]}})
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        job = workflow["jobs"]["production-graph"]
        self.assertEqual(job["if"], "github.repository == 'NRG-Wardog/LiveContainer' && github.ref == 'refs/heads/" + PRODUCTION_BRANCH + "'")
        self.assertEqual(job["env"]["PRODUCTION_PHASE"], "sidesign")
        self.assertEqual(job["env"]["APPROVED_PRODUCTION_INPUTS_SHA256"], "MISSING_INDEPENDENTLY_REVIEWED_SHA256")
        self.assertEqual(job["steps"][0]["with"]["persist-credentials"], "false")
        self.assertEqual(job["steps"][0]["with"]["set-safe-directory"], "false")
        self.assertEqual(job["env"]["GIT_CONFIG_GLOBAL"], "/dev/null")
        self.assertEqual(job["steps"][-1]["with"]["path"].splitlines(), ["artifacts/logs/**", "artifacts/provenance/**"])

    def test_map_approval_is_a_literal_or_explicit_review_placeholder(self):
        workflow = yaml.load((ROOT / ".github/workflows/runtime-owner-native-validation.yml").read_text(), Loader=yaml.BaseLoader)
        value = workflow["jobs"]["native-validation"]["env"]["APPROVED_OWNER_REFERENCE_MAP_SHA256"]
        self.assertTrue(value == "MISSING_SEPARATELY_REVIEWED_SHA256" or re.fullmatch(r"[0-9a-f]{64}", value))


if __name__ == "__main__":
    unittest.main(verbosity=2)
