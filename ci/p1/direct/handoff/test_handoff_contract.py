from copy import deepcopy
import json
from pathlib import Path
import unittest

from handoff_contract import (ACK_KEYS, CLOCK, GEOMETRY_KEYS, HandoffState, InvalidHandoff,
                              PROOF_HASH_KEYS, PROOF_KEYS, PROOF_TRUE_KEYS, REQUEST_KEYS,
                              canonical, digest, parse, validate_ack, validate_geometry, validate_request)


def request():
    return dict(schema="p1-direct-baseline-geometry-v1", session="a" * 32, scenario="timeout",
                runnerBundleIdentifier="org.example.P1UITests.xctrunner", runnerPID=202,
                simulatorUDID="00000000-1111-2222-3333-444444444444",
                geometry=dict(coordinateSpace="XCTest-screen-points", orientation="portrait-up",
                              copyIdentifier="signin.prompt.copy-details", copyLabel="Copy Details", copyFrame=[100, 300, 200, 40],
                              markerIdentifier="p1-video-marker", markerFrame=[100, 400, 192, 16],
                              baselineIdentifier="p1-video-baseline-ready", baselineFrame=[100, 450, 200, 40],
                              windowFrame=[0, 0, 400, 800], anchors=[
                                  dict(identifier=f"p1-direct-anchor-{n}", ordinal=n, frame=frame)
                                  for n, frame in enumerate(([10, 10, 96, 16], [290, 10, 96, 16],
                                                              [10, 770, 96, 16], [290, 770, 96, 16]), 1)],
                              features=[dict(identifier=f"p1-direct-feature-{n}", ordinal=n, frame=frame)
                                        for n, frame in enumerate(([3.5, 3.5, 3, 3], [393.5, 3.5, 3, 3],
                                                                  [3.5, 793.5, 3, 3], [393.5, 793.5, 3, 3]), 1)],
                              registrationModel="whole-source-view-to-observed-support-v1",
                              sourceLocalityEstablished=False),
                sampleBeforeUptime=111, sampleAfterUptime=112, observerEnteredUptime=110,
                methodStartedUptime=100, deadlineUptime=230, waitLimitSeconds=120,
                methodLimitSeconds=240, clock=CLOCK, clockEquivalenceAssumed=False, admissionEligible=False)


def proof(request_data):
    req = validate_request(request_data)
    row = dict(schema="p1-direct-owned-capture-ready-v1", session=req["session"], geometryRequestSHA256=digest(request_data),
               captureInstance="b" * 32, simulatorUDID=req["simulatorUDID"], guiPID=101, windowID=99, helperPID=102,
               firstCompleteFrameIndex=0, firstCompleteFrameDisplayTime=str((1 << 64) - 1),
               captureErrors=[], ownershipErrors=[], admissionEligible=False)
    row.update({key: True for key in PROOF_TRUE_KEYS})
    row.update({key: digest(key.encode()) for key in PROOF_HASH_KEYS})
    return row


def ack(request_data, proof_row=None):
    req = validate_request(request_data)
    p = proof(request_data) if proof_row is None else proof_row
    return dict(schema="p1-direct-baseline-ack-v1", session=req["session"], geometryRequestSHA256=digest(request_data),
                captureReadyProof=p, captureReadyProofSHA256=digest(canonical(p)), admissionEligible=False)


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.request = request()
        self.request_data = canonical(self.request)

    def invalid_ack(self, row):
        with self.assertRaises(InvalidHandoff):
            validate_ack(canonical(row), self.request_data)

    def invalid_proof(self, p):
        self.invalid_ack(ack(self.request_data, p))

    def invalid_request(self, row):
        with self.assertRaises(InvalidHandoff):
            validate_request(canonical(row))

    def test_valid_bound_ack_is_never_native_proof(self):
        data = canonical(ack(self.request_data))
        result = validate_ack(data, self.request_data)
        self.assertEqual(result["acknowledgementSHA256"], digest(data))
        self.assertEqual(result["proofBytes"], canonical(proof(self.request_data)))
        self.assertTrue(result["bindingOnly"])
        self.assertFalse(result["nativeOwnershipVerified"])
        self.assertFalse(result["admissionEligible"])

    def test_all_scenarios_preserve_geometry_contract(self):
        for scenario in ("timeout", "replacement", "dismissal"):
            with self.subTest(scenario=scenario):
                row = request(); row["scenario"] = scenario
                self.assertEqual(validate_request(canonical(row))["scenario"], scenario)

    def test_unknown_scenario_rejected(self):
        self.request["scenario"] = "capability"
        self.invalid_request(self.request)

    def test_session_must_match_full_string(self):
        for value in ("a" * 32 + "\n", "A" * 32, "a" * 31, "a" * 33, True):
            with self.subTest(value=value):
                row = request(); row["session"] = value; self.invalid_request(row)

    def test_exact_request_keys(self):
        for key in REQUEST_KEYS:
            with self.subTest(key=key):
                row = request(); del row[key]; self.invalid_request(row)
        row = request(); row["extra"] = 1; self.invalid_request(row)

    def test_exact_geometry_keys(self):
        for key in GEOMETRY_KEYS:
            with self.subTest(key=key):
                row = request(); del row["geometry"][key]; self.invalid_request(row)

    def test_exact_acknowledgement_keys(self):
        for key in ACK_KEYS:
            with self.subTest(key=key):
                row = ack(self.request_data); del row[key]; self.invalid_ack(row)
        row = ack(self.request_data); row["extra"] = 1; self.invalid_ack(row)

    def test_exact_proof_keys(self):
        for key in PROOF_KEYS:
            with self.subTest(key=key):
                p = proof(self.request_data); del p[key]; self.invalid_proof(p)
        p = proof(self.request_data); p["extra"] = 1; self.invalid_proof(p)

    def test_wrong_ack_schema_session_or_request(self):
        for key, value in (("schema", "p1-capability-request-v1"), ("session", "c" * 32), ("geometryRequestSHA256", "0" * 64)):
            with self.subTest(key=key):
                row = ack(self.request_data); row[key] = value; self.invalid_ack(row)

    def test_wrong_proof_schema_session_or_request(self):
        for key, value in (("schema", "p1-owned-window-acquisition-v1"), ("session", "c" * 32), ("geometryRequestSHA256", "0" * 64)):
            with self.subTest(key=key):
                p = proof(self.request_data); p[key] = value; self.invalid_proof(p)

    def test_exact_raw_request_hash_not_reencoded_json(self):
        spaced = json.dumps(self.request, sort_keys=True, indent=2).encode()
        self.assertNotEqual(digest(spaced), digest(self.request_data))
        validate_ack(canonical(ack(spaced)), spaced)
        with self.assertRaises(InvalidHandoff):
            validate_ack(canonical(ack(self.request_data)), spaced)

    def test_stale_geometry_hash_rejected(self):
        row = request(); row["geometry"]["copyFrame"][0] += 1
        with self.assertRaises(InvalidHandoff):
            validate_ack(canonical(ack(self.request_data)), canonical(row))

    def test_wrong_exact_device_rejected(self):
        p = proof(self.request_data); p["simulatorUDID"] = "FFFFFFFF-1111-2222-3333-444444444444"
        self.invalid_proof(p)

    def test_lowercase_or_noncanonical_device_rejected(self):
        p = proof(self.request_data); p["simulatorUDID"] = "ffffffff-1111-2222-3333-444444444444"
        self.invalid_proof(p)

    def test_proof_hash_mismatch_rejected(self):
        row = ack(self.request_data); row["captureReadyProofSHA256"] = "0" * 64; self.invalid_ack(row)

    def test_missing_or_malformed_evidence_hashes(self):
        for key in PROOF_HASH_KEYS:
            for value in ("", "a" * 63, "G" * 64, True):
                with self.subTest(key=key, value=value):
                    p = proof(self.request_data); p[key] = value; self.invalid_proof(p)

    def test_capture_not_ready_rejected(self):
        for key in PROOF_TRUE_KEYS:
            for value in (False, 1, "true", None):
                with self.subTest(key=key, value=value):
                    p = proof(self.request_data); p[key] = value; self.invalid_proof(p)

    def test_any_capture_or_ownership_error_rejected(self):
        for key in ("captureErrors", "ownershipErrors"):
            for value in (["error"], "", {}, False):
                with self.subTest(key=key, value=value):
                    p = proof(self.request_data); p[key] = value; self.invalid_proof(p)

    def test_admission_claims_rejected(self):
        for value in (True, 0, None, "false"):
            row = ack(self.request_data); row["admissionEligible"] = value; self.invalid_ack(row)
            p = proof(self.request_data); p["admissionEligible"] = value; self.invalid_proof(p)

    def test_bad_host_process_or_window_identity(self):
        for key, values in {"guiPID": [True, 1, 2**31, 101.0], "helperPID": [True, 1, 101, 2**31],
                            "windowID": [False, 0, -1, 2**32], "firstCompleteFrameIndex": [True, -1, 2**53]}.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    p = proof(self.request_data); p[key] = value; self.invalid_proof(p)

    def test_exact_native_ticks_reject_lossy_or_invalid_values(self):
        for value in ("0", "01", "-1", "1e5", str(2**64), 1, 1.0, "1.0", "1\n"):
            with self.subTest(value=value):
                p = proof(self.request_data); p["firstCompleteFrameDisplayTime"] = value; self.invalid_proof(p)

    def test_duplicate_json_keys_rejected(self):
        data = canonical(ack(self.request_data))
        data = data[:-1] + b',"session":"' + b"a" * 32 + b'"}'
        with self.assertRaises(InvalidHandoff): validate_ack(data, self.request_data)

    def test_noncanonical_and_invalid_json_rejected(self):
        valid = ack(self.request_data)
        for data in (canonical(valid) + b"\n", json.dumps(valid).encode(), b"[]", b"null", b"\xff", b'{"x":NaN}',
                     b'{"x":Infinity}', b'{"x":1,"x":2}', b" ", b"{" + b" " * 8192 + b"}"):
            with self.subTest(data=data[:40]):
                with self.assertRaises(InvalidHandoff): validate_ack(data, self.request_data)

    def test_nonfinite_geometry_rejected(self):
        data = self.request_data.replace(b'"copyFrame":[100,', b'"copyFrame":[NaN,')
        with self.assertRaises(InvalidHandoff): validate_request(data)
        data = self.request_data.replace(b'"copyFrame":[100,', b'"copyFrame":[' + b"9" * 1000 + b",")
        with self.assertRaises(InvalidHandoff): validate_request(data)
        data = self.request_data.replace(b'"copyFrame":[100,', b'"copyFrame":[1e999,')
        with self.assertRaises(InvalidHandoff): validate_request(data)

    def test_geometry_bounds_types_and_clipping(self):
        for value in ([100, 300, 0, 40], [100, 300, -1, 40], [100, 300, True, 40],
                      [100, 300, 65537, 40], [-1, 300, 200, 40], [300, 300, 200, 40], [0, 0]):
            with self.subTest(value=value):
                row = request(); row["geometry"]["copyFrame"] = value; self.invalid_request(row)

    def test_four_distinct_present_ordered_anchors_required(self):
        for mutation in (lambda a: a.pop(), lambda a: a.append(deepcopy(a[0])),
                         lambda a: a.__setitem__(1, deepcopy(a[0])), lambda a: a.reverse()):
            row = request(); mutation(row["geometry"]["anchors"]); self.invalid_request(row)

    def test_anchor_overlap_rejected(self):
        for frame in ([100, 300, 10, 10], [100, 400, 10, 10], [100, 450, 10, 10], [11, 11, 96, 16]):
            row = request(); row["geometry"]["anchors"][1]["frame"] = frame; self.invalid_request(row)

    def test_four_actual_features_required_with_exact_identity_shape_and_adjacency(self):
        for mutation in (lambda a: a.pop(), lambda a: a.append(deepcopy(a[0])),
                         lambda a: a.__setitem__(1, deepcopy(a[0])), lambda a: a.reverse()):
            row = request(); mutation(row["geometry"]["features"]); self.invalid_request(row)
        for frame in ([3.5, 3.5, 2, 3], [-1, 4, 3, 3], [20, 30, 3, 3], [100, 300, 3, 3],
                      [100, 400, 3, 3], [100, 450, 3, 3], [11, 11, 3, 3], [393.5, 3.5, 3, 3]):
            row = request(); row["geometry"]["features"][0]["frame"] = frame; self.invalid_request(row)
        for key in ("identifier", "ordinal", "frame"):
            row = request(); del row["geometry"]["features"][0][key]; self.invalid_request(row)
        row = request(); row["geometry"]["features"][0]["extra"] = True; self.invalid_request(row)
        row = request(); row["geometry"]["sourceLocalityEstablished"] = True; self.invalid_request(row)
        row = request(); row["geometry"]["registrationModel"] = "ideal-centers"; self.invalid_request(row)

    def test_changed_orientation_or_label_rejected(self):
        for key, value in (("orientation", "landscape"), ("copyLabel", "Copied"), ("copyIdentifier", "wrong")):
            row = request(); row["geometry"][key] = value; self.invalid_request(row)

    def test_no_clock_equivalence_or_budget_extension(self):
        for key, value in (("clockEquivalenceAssumed", True), ("clock", "host"), ("methodLimitSeconds", 241),
                           ("waitLimitSeconds", 121), ("deadlineUptime", 231), ("sampleAfterUptime", 230),
                           ("sampleBeforeUptime", 109), ("methodStartedUptime", 0), ("runnerPID", True)):
            row = request(); row[key] = value; self.invalid_request(row)

    def test_method_remaining_budget_shortens_wait(self):
        row = request(); row.update(methodStartedUptime=1, observerEnteredUptime=235,
                                    sampleBeforeUptime=236, sampleAfterUptime=237, deadlineUptime=241)
        validate_request(canonical(row))
        row["deadlineUptime"] = 355; self.invalid_request(row)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.data = canonical(request())
        self.state = HandoffState(self.data)
        self.ack = canonical(ack(self.data))

    def ready_to_persist(self):
        self.state.poll(113, self.ack)
        self.state.recheck(114, request()["geometry"])

    def test_happy_path_has_no_release_before_receipt(self):
        self.assertEqual(self.state.poll(112.5), "waiting")
        self.ready_to_persist()
        written = []
        self.state.persist(115, written.append)
        self.assertEqual(len(written), 1)
        self.assertFalse(parse(written[0])["baselineTapObserved"])
        self.assertTrue(self.state.release(116))
        self.assertEqual(self.state.state, "released")
        self.assertEqual(self.state.ack_bytes, self.ack)

    def test_timeout_exactly_at_deadline(self):
        with self.assertRaises(InvalidHandoff): self.state.poll(230, self.ack)
        self.assertEqual(self.state.state, "failed")

    def test_absent_ack_never_releases(self):
        self.assertEqual(self.state.poll(229.99), "waiting")
        with self.assertRaises(InvalidHandoff): self.state.poll(230)

    def test_invalid_ack_fails_without_retry(self):
        with self.assertRaises(InvalidHandoff): self.state.poll(113, b"{}");
        with self.assertRaises(InvalidHandoff): self.state.poll(114, self.ack)

    def test_duplicate_ack_rejected(self):
        self.state.poll(113, self.ack)
        with self.assertRaises(InvalidHandoff): self.state.poll(114, self.ack)

    def test_geometry_change_during_wait_fails(self):
        self.state.poll(113, self.ack)
        geometry = request()["geometry"]; geometry["copyFrame"][0] += 1
        with self.assertRaises(InvalidHandoff): self.state.recheck(114, geometry)

    def test_feature_geometry_change_during_wait_fails(self):
        self.state.poll(113, self.ack)
        geometry = request()["geometry"]; geometry["features"][0]["frame"][0] += 1
        with self.assertRaises(InvalidHandoff): self.state.recheck(114, geometry)

    def test_receipt_failure_is_terminal(self):
        self.ready_to_persist()
        def fail(_): raise OSError("fsync failed")
        with self.assertRaises(InvalidHandoff): self.state.persist(115, fail)
        with self.assertRaises(InvalidHandoff): self.state.release(116)
        self.assertIn("fsync", self.state.failure)

    def test_durability_cost_is_within_deadline(self):
        self.ready_to_persist()
        self.state.persist(229.9, lambda data: None)
        with self.assertRaises(InvalidHandoff): self.state.release(230)

    def test_source_snapshot_is_not_mutable(self):
        row = request(); data = canonical(row); state = HandoffState(data)
        row["geometry"]["copyFrame"][0] = 999
        self.assertEqual(state.request_data, self.data)
        self.assertEqual(state.request["geometry"]["copyFrame"][0], 100)

    def test_release_before_acknowledgement_rejected(self):
        with self.assertRaises(InvalidHandoff): self.state.release(113)

    def test_release_before_receipt_rejected(self):
        self.ready_to_persist()
        with self.assertRaises(InvalidHandoff): self.state.release(115)

    def test_receipt_before_recheck_rejected(self):
        self.state.poll(113, self.ack)
        with self.assertRaises(InvalidHandoff): self.state.persist(114, lambda data: None)

    def test_clock_regression_fails_closed(self):
        with self.assertRaises(InvalidHandoff): self.state.poll(111, self.ack)

    def test_nan_clock_fails_closed(self):
        with self.assertRaises(InvalidHandoff): self.state.poll(float("nan"), self.ack)

    def test_no_second_release(self):
        self.ready_to_persist(); self.state.persist(115, lambda data: None); self.state.release(116)
        with self.assertRaises(InvalidHandoff): self.state.release(117)


if __name__ == "__main__":
    unittest.main()
