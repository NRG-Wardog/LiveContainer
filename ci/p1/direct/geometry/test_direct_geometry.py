"""Synthetic arithmetic/contract tests only; no native/pixel measurements."""
from dataclasses import replace
from fractions import Fraction as F
import unittest

import direct_geometry as g


S = "0123456789abcdef0123456789abcdef"


def crop(name, rect):
    data = bytes(rect.byte_count)
    return g.Crop(name, rect, data, g.digest(data))


def fixture():
    identity = g.Identity(S, 123, 456, 230, 240, g.Box(0, 0, 100, 100),
                          g.Box(0, 0, 230, 240), 1, 1)
    anchors, regions = [], [g.Region("control", g.Box(25, 30, 75, 40), "control"),
                            g.Region("marker", g.Box(30, 70, 70, 75), "marker")]
    for index, (x, y) in enumerate(((5, 5), (95, 5), (5, 95), (95, 95)), 1):
        name = "a" + str(index)
        anchors.append(g.Anchor(name, S, g.Interval(x, x), g.Interval(y, y),
                                g.Interval(2*x+10-F(1, 4), 2*x+10+F(1, 4)),
                                g.Interval(2*y+20-F(1, 4), 2*y+20+F(1, 4)),
                                g.PixelRect(2*x+9, 2*y+19, 3, 3), name))
        regions.append(g.Region(name, g.Box(x-2, y-2, x+2, y+2), "anchor"))
    return [identity, tuple(anchors), ("a1", "a2", "a3"), ("a4",), tuple(regions),
            crop("full", g.PixelRect(0, 0, 230, 240))]


def frozen():
    return g.freeze(*fixture())


def bundle(f):
    return tuple(crop(name, rect) for name, rect in f.rois)


def plan(**changes):
    base = g.RetentionPlan(6000, 1024*1024, 4096, 16*1024*1024, 16*1024*1024,
                           32*1024*1024, 64*1024*1024, 128*1024*1024,
                           4*g.GIB, 12*g.GIB)
    return replace(base, **changes)


class ExactGeometry(unittest.TestCase):
    def test_valid_overdetermined_geometry_never_admits(self):
        f = frozen()
        report = g.GeometryValidator(f).validate(0, f.identity, f.anchors, bundle(f))
        self.assertTrue(report["primitiveValid"])
        self.assertFalse(report["admissionEligible"])
        self.assertEqual(len(report["bundleSHA256"]), 64)
        self.assertEqual(report["viewportProof"], "fit-derived-containment-in-BGRA-frame")

    def test_outward_bounds_include_uncertainty_and_padding(self):
        self.assertEqual(dict(frozen().rois)["control"], g.PixelRect(58, 78, 104, 24))

    def test_exact_fractional_scale(self):
        observations = [(g.Interval(0, 0), g.Interval(F(1, 3), F(1, 3))),
                        (g.Interval(10, 10), g.Interval(F(46, 3), F(46, 3)))]
        poly = g._fit_axis(observations)
        self.assertEqual(poly, ((F(3, 2), F(1, 3)),))
        self.assertEqual(g._map(poly, g.Interval(1, 2)), g.Interval(F(11, 6), F(10, 3)))

    def test_app_coordinate_uncertainty_is_preserved(self):
        poly = g._fit_axis([(g.Interval(-1, 1), g.Interval(-1, 1)),
                            (g.Interval(9, 11), g.Interval(19, 21))])
        bound = g._map(poly, g.Interval(5, 5))
        self.assertLessEqual(bound.lo, 10)
        self.assertGreaterEqual(bound.hi, 10)

    def test_float_boolean_and_nonfinite_coordinates_rejected(self):
        for value in (True, 1.0, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(g.InvalidEvidence):
                g.Interval(value, value)

    def test_unbounded_or_reflected_scale_rejected(self):
        for obs in ([(g.Interval(1, 1), g.Interval(2, 2))]*3,
                    [(g.Interval(0, 0), g.Interval(10, 10)),
                     (g.Interval(10, 10), g.Interval(0, 0))]):
            with self.assertRaises(g.InvalidEvidence):
                g._fit_axis(obs)

    def test_missing_or_reused_validation_anchor_rejected(self):
        for validation in ((), ("a1",)):
            args = fixture(); args[3] = validation
            with self.assertRaises(g.InvalidEvidence):
                g.freeze(*args)

    def test_wrong_session_and_duplicate_anchor_rejected(self):
        for rows in ((replace(fixture()[1][0], session="f"*32),)+fixture()[1][1:],
                     fixture()[1][:3]+(fixture()[1][0],)):
            args = fixture(); args[1] = rows
            with self.assertRaises(g.InvalidEvidence):
                g.freeze(*args)

    def test_collinear_fit_anchors_rejected(self):
        args = fixture()
        args[1] = tuple(replace(a, app_y=a.app_x) for a in args[1])
        with self.assertRaisesRegex(g.InvalidEvidence, "collinear"):
            g.freeze(*args)

    def test_midpoint_separation_cannot_hide_possible_collinearity(self):
        args = fixture()
        ranges = ((10, 10), (20, 10), (10, 20))
        args[1] = tuple(replace(a, app_x=g.Interval(0, x), app_y=g.Interval(0, y))
                        for a, (x, y) in zip(args[1][:3], ranges)) + args[1][3:]
        with self.assertRaisesRegex(g.InvalidEvidence, "collinear"):
            g.freeze(*args)

    def test_independent_validation_anchor_mismatch_rejected(self):
        args = fixture(); a = args[1][-1]
        args[1] = args[1][:-1] + (replace(a, pixel_x=g.Interval(205, 205),
                                           footprint=g.PixelRect(204, 209, 3, 3)),)
        with self.assertRaises(g.InvalidEvidence):
            g.freeze(*args)

    def test_validation_cannot_tune_frozen_viewport_or_crops(self):
        args = fixture()
        args[1] = tuple(replace(a, pixel_x=g.Interval(a.pixel_x.midpoint-5, a.pixel_x.midpoint+5),
                                footprint=g.PixelRect(int(a.pixel_x.midpoint)-5, int(a.pixel_y.midpoint)-1, 11, 3))
                         for a in args[1])
        before = g.freeze(*args)
        a = args[1][-1]
        args[1] = args[1][:-1] + (replace(a, pixel_x=g.Interval(203, 204)),)
        after = g.freeze(*args)
        self.assertEqual(before.derived_viewport, after.derived_viewport)
        self.assertEqual(before.rois, after.rois)

    def test_whole_app_projection_must_fit_even_if_rois_fit(self):
        args = fixture(); args[0] = replace(args[0], app_viewport=g.Box(-20, 0, 100, 100))
        with self.assertRaisesRegex(g.InvalidEvidence, "derived app viewport"):
            g.freeze(*args)

    def test_content_rect_is_not_an_exact_guest_viewport(self):
        args = fixture(); args[0] = replace(args[0], content_rect=g.Box(2, 3, 222, 233))
        self.assertEqual(g.freeze(*args).derived_viewport, frozen().derived_viewport)

    def test_holdout_cannot_shrink_unsafe_full_projection(self):
        args = fixture()
        args[1] = tuple(replace(a, pixel_x=g.Interval(a.pixel_x.midpoint-5, a.pixel_x.midpoint+5),
                                footprint=g.PixelRect(int(a.pixel_x.midpoint)-5, int(a.pixel_y.midpoint)-1, 11, 3))
                         for a in args[1])
        a = args[1][-1]
        args[1] = args[1][:-1] + (replace(a, pixel_x=g.Interval(200, 200)),)
        args[0] = replace(args[0], width=212)
        args[5] = crop("full", g.PixelRect(0, 0, 212, 240))
        with self.assertRaisesRegex(g.InvalidEvidence, "derived app viewport"):
            g.freeze(*args)

    def test_unretained_anchor_rejected(self):
        args = fixture(); args[4] = args[4][:-1]
        with self.assertRaisesRegex(g.InvalidEvidence, "not retained"):
            g.freeze(*args)

    def test_fiducial_intersecting_control_rejected(self):
        args = fixture(); args[4] = (replace(args[4][0], app_box=g.Box(3, 3, 75, 40)),) + args[4][1:]
        with self.assertRaisesRegex(g.InvalidEvidence, "intersects"):
            g.freeze(*args)

    def test_fiducial_intersecting_strip_rejected(self):
        args = fixture(); args[4] = args[4][:1] + (replace(args[4][1], app_box=g.Box(3, 70, 97, 97)),) + args[4][2:]
        with self.assertRaisesRegex(g.InvalidEvidence, "intersects"):
            g.freeze(*args)

    def test_crop_cannot_be_clamped(self):
        args = fixture(); args[0] = replace(args[0], width=210)
        args[5] = crop("full", g.PixelRect(0, 0, 210, 240))
        args[4] = (replace(args[4][0], app_box=g.Box(25, 30, 100, 40)),) + args[4][1:]
        with self.assertRaisesRegex(g.InvalidEvidence, "clip"):
            g.freeze(*args)

    def test_full_context_hash_and_bounds_required(self):
        for value in (replace(fixture()[5], sha256="0"*64), crop("full", g.PixelRect(0, 0, 229, 240))):
            args = fixture(); args[5] = value
            with self.assertRaises(g.InvalidEvidence):
                g.freeze(*args)


class FrameConsistency(unittest.TestCase):
    def test_all_anchors_and_raw_crops_required(self):
        f = frozen()
        for anchors, crops in ((f.anchors[:-1], bundle(f)), (f.anchors, bundle(f)[:-1])):
            with self.assertRaises(g.InvalidEvidence):
                g.GeometryValidator(f).validate(0, f.identity, anchors, crops)

    def test_wrong_identity_variants_rejected(self):
        f = frozen()
        for identity in (replace(f.identity, session="f"*32), replace(f.identity, owner_pid=124),
                         replace(f.identity, window_id=457), replace(f.identity, content_scale=2),
                         replace(f.identity, content_rect=g.Box(1, 1, 229, 239)),
                         replace(f.identity, scale_factor=2)):
            with self.subTest(identity=identity), self.assertRaises(g.InvalidEvidence):
                g.GeometryValidator(f).validate(0, identity, f.anchors, bundle(f))

    def test_drift_and_later_recovery_stay_failed(self):
        f = frozen(); validator = g.GeometryValidator(f)
        moved = tuple(replace(a, pixel_x=g.Interval(a.pixel_x.midpoint+F(1, 2), a.pixel_x.midpoint+F(3, 4)))
                      for a in f.anchors)
        with self.assertRaisesRegex(g.InvalidEvidence, "common frozen"):
            validator.validate(0, f.identity, moved, bundle(f))
        with self.assertRaisesRegex(g.InvalidEvidence, "latched"):
            validator.validate(1, f.identity, f.anchors, bundle(f))

    def test_separate_frames_need_one_joint_transform(self):
        f = frozen(); validator = g.GeometryValidator(f)
        right = tuple(replace(a, pixel_x=g.Interval(a.pixel_x.midpoint+F(1, 5), a.pixel_x.midpoint+F(1, 4)))
                      for a in f.anchors)
        left = tuple(replace(a, pixel_x=g.Interval(a.pixel_x.midpoint-F(1, 4), a.pixel_x.midpoint-F(1, 5)))
                     for a in f.anchors)
        validator.validate(0, f.identity, right, bundle(f))
        with self.assertRaisesRegex(g.InvalidEvidence, "common frozen"):
            validator.validate(1, f.identity, left, bundle(f))

    def test_fiducial_footprint_movement_rejected(self):
        f = frozen(); a = f.anchors[0]
        changed = (replace(a, footprint=replace(a.footprint, x=a.footprint.x-1, width=4)),) + f.anchors[1:]
        with self.assertRaisesRegex(g.InvalidEvidence, "footprint moved"):
            g.GeometryValidator(f).validate(0, f.identity, changed, bundle(f))

    def test_frozen_crop_and_hash_are_checked(self):
        f = frozen(); crops = bundle(f)
        for first in (replace(crops[0], sha256="f"*64),
                      crop(crops[0].name, replace(crops[0].rect, x=crops[0].rect.x+1))):
            with self.assertRaises(g.InvalidEvidence):
                g.GeometryValidator(f).validate(0, f.identity, f.anchors, (first,)+crops[1:])

    def test_immutable_crop_bytes_required(self):
        f = frozen(); crops = bundle(f)
        with self.assertRaises(g.InvalidEvidence):
            g.GeometryValidator(f).validate(0, f.identity, f.anchors,
                                           (replace(crops[0], bgra=bytearray(crops[0].bgra)),)+crops[1:])

    def test_reordered_sample_and_boolean_index_rejected(self):
        f = frozen(); validator = g.GeometryValidator(f)
        validator.validate(1, f.identity, f.anchors, bundle(f))
        with self.assertRaises(g.InvalidEvidence):
            validator.validate(1, f.identity, f.anchors, bundle(f))
        with self.assertRaises(g.InvalidEvidence):
            g.GeometryValidator(f).validate(True, f.identity, f.anchors, bundle(f))

    def test_status_indices_may_intervene_without_being_invented_frames(self):
        f = frozen(); validator = g.GeometryValidator(f)
        validator.validate(1, f.identity, f.anchors, bundle(f))
        validator.validate(4, f.identity, f.anchors, bundle(f))
        self.assertEqual(validator.last_index, 4)


class AbsenceSemantics(unittest.TestCase):
    def test_expected_dismissal_is_never_positive(self):
        result = g.observation_role("expected-absent", scenario="dismissal", verified_expected_absence=True)
        self.assertFalse(result["resetWitness"])
        self.assertFalse(result["copiedWitness"])
        self.assertFalse(result["admissionEligible"])

    def test_absence_cannot_break_claimed_chain(self):
        with self.assertRaises(g.InvalidEvidence):
            g.observation_role("expected-absent", scenario="dismissal", verified_expected_absence=True, in_copied_chain=True)

    def test_absence_requires_both_scenario_and_external_verification(self):
        for scenario, verified in (("timeout", True), ("replacement", True), ("dismissal", False)):
            with self.assertRaises(g.InvalidEvidence):
                g.observation_role("expected-absent", scenario=scenario, verified_expected_absence=verified)

    def test_only_actual_reset_and_copied_labels_are_positive(self):
        self.assertTrue(g.observation_role("Copy Details", scenario="dismissal")["resetWitness"])
        self.assertTrue(g.observation_role("Copied", scenario="dismissal", in_copied_chain=True)["copiedWitness"])
        for label in ("unknown", "", "Copy Details or Copied", None):
            with self.assertRaises(g.InvalidEvidence):
                g.observation_role(label, scenario="dismissal")

    def test_absence_conflicting_with_positive_label_rejected(self):
        with self.assertRaises(g.InvalidEvidence):
            g.observation_role("Copy Details", scenario="dismissal", verified_expected_absence=True)


class Retention(unittest.TestCase):
    def test_inclusive_proposed_plan_and_peak(self):
        result = plan().bounds()
        self.assertEqual(6000*1024*1024, 6291456000)
        self.assertEqual(result["rawBytes"], 3*g.GIB)
        self.assertEqual(result["rawByteLimit"], 3*g.GIB)
        self.assertLess(result["archiveBytes"], 4*g.GIB)
        self.assertGreater(result["peakDiskBytes"], 3*result["evidenceBytes"])
        self.assertFalse(result["admissionEligible"])

    def test_all_context_journal_metadata_and_archive_overhead_count(self):
        p = plan(); bounds = p.bounds()
        with self.assertRaisesRegex(g.InvalidEvidence, "inclusive"):
            replace(p, case_inclusive_limit=bounds["archiveBytes"]-1).bounds()
        self.assertEqual(replace(p, case_inclusive_limit=bounds["archiveBytes"]).bounds(), bounds)

    def test_peak_and_multiple_cases_rejected(self):
        p = plan()
        for changed in (replace(p, peak_disk_limit=p.bounds()["peakDiskBytes"]-1), replace(p, case_count=2),
                        replace(p, archive_limit=5*g.GIB), replace(p, record_limit=6001),
                        replace(p, record_limit=12000), replace(p, roi_bytes_per_record=1024*1024+1)):
            with self.assertRaises(g.InvalidEvidence):
                changed.bounds()

    def test_actual_crop_geometry_must_fit_plan(self):
        result = g.check_geometry_plan(frozen(), plan())
        self.assertGreater(result["measuredROIPerFrameBytes"], 0)
        with self.assertRaises(g.InvalidEvidence):
            g.check_geometry_plan(frozen(), plan(roi_bytes_per_record=1))

    def test_maximum_record_inventory_includes_noncomplete_rows(self):
        ledger = g.RetentionLedger(plan())
        for _ in range(6000):
            ledger.record((), b"idle")
        self.assertEqual(ledger.records, 6000)
        with self.assertRaisesRegex(g.InvalidEvidence, "record ceiling"):
            ledger.record((), b"idle")
        with self.assertRaisesRegex(g.InvalidEvidence, "latched"):
            ledger.verify_archive_size(24000)

    def test_maximum_raw_payload_and_one_byte_over(self):
        payload = bytes(1024*1024)
        ledger = g.RetentionLedger(plan())
        ledger.record((payload,), b"m")
        self.assertEqual(ledger.raw, 1024*1024)
        with self.assertRaisesRegex(g.InvalidEvidence, "per-record"):
            ledger.record((payload, b"x"), b"m")
        with self.assertRaisesRegex(g.InvalidEvidence, "latched"):
            ledger.record((), b"m")

    def test_exact_cumulative_three_gib_and_one_pixel_over_latches(self):
        payload = bytes(1024*1024)
        ledger = g.RetentionLedger(plan())
        for _ in range(3072):
            ledger.record((payload,), b"m")
        self.assertEqual(ledger.raw, 3*g.GIB)
        self.assertEqual(ledger.records, 3072)
        with self.assertRaisesRegex(g.InvalidEvidence, "cumulative raw"):
            ledger.record((b"pixel"[:4],), b"m")
        self.assertEqual(ledger.raw, 3*g.GIB)
        self.assertEqual(ledger.records, 3072)
        with self.assertRaisesRegex(g.InvalidEvidence, "latched"):
            ledger.record((), b"m")
        with self.assertRaises(g.InvalidEvidence):
            plan(raw_limit=3*g.GIB+1).bounds()
        self.assertEqual(plan(record_limit=2).bounds()["rawBytes"], 2*1024*1024)

    def test_archive_four_gib_boundary_and_one_byte_over(self):
        small = plan(record_limit=1, roi_bytes_per_record=1, metadata_bytes_per_record=1,
                     context_bytes=0, journal_bytes=0, ancillary_bytes=0,
                     archive_overhead_bytes=4*g.GIB-2, temporary_bytes=0)
        self.assertEqual(small.bounds()["archiveBytes"], 4*g.GIB)
        with self.assertRaisesRegex(g.InvalidEvidence, "inclusive"):
            replace(small, archive_overhead_bytes=4*g.GIB-1).bounds()
        ledger = g.RetentionLedger(small); ledger.record((b"x",), b"m")
        self.assertEqual(ledger.verify_archive_size(4*g.GIB)["archiveBytes"], 4*g.GIB)
        with self.assertRaises(g.InvalidEvidence):
            ledger.verify_archive_size(4*g.GIB+1)

    def test_actual_inventory_and_archive_size(self):
        ledger = g.RetentionLedger(plan())
        ledger.record((b"abcd",), b"meta")
        ledger.record((), b"idle")
        ledger.fixed_bytes("context", b"abc")
        ledger.fixed_bytes("journal", b"x")
        ledger.fixed_bytes("ancillary", b"yz")
        report = ledger.verify_archive_size(18+100)
        self.assertEqual(report["evidenceBytes"], 18)
        self.assertFalse(report["admissionEligible"])

    def test_record_and_byte_overflows_latch(self):
        for p, payload, metadata in ((plan(record_limit=1), (b"a",), b"m"),
                                     (plan(roi_bytes_per_record=1), (b"aa",), b"m"),
                                     (plan(metadata_bytes_per_record=1), (), b"mm")):
            ledger = g.RetentionLedger(p)
            if p.record_limit == 1:
                ledger.record(payload, metadata)
            with self.assertRaises(g.InvalidEvidence):
                ledger.record(payload, metadata)
            with self.assertRaisesRegex(g.InvalidEvidence, "latched"):
                ledger.record((), b"m")

    def test_fixed_bytes_and_archive_overhead_fail_closed(self):
        ledger = g.RetentionLedger(plan(context_bytes=1))
        with self.assertRaises(g.InvalidEvidence):
            ledger.fixed_bytes("context", b"aa")
        ledger = g.RetentionLedger(plan(archive_overhead_bytes=1))
        ledger.record((b"abcd",), b"m")
        with self.assertRaises(g.InvalidEvidence):
            ledger.verify_archive_size(7)

    def test_boolean_budget_and_size_rejected(self):
        with self.assertRaises(g.InvalidEvidence):
            plan(record_limit=True).bounds()
        with self.assertRaises(g.InvalidEvidence):
            g.RetentionLedger(plan()).verify_archive_size(True)


if __name__ == "__main__":
    unittest.main()
