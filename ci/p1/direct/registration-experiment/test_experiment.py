from copy import deepcopy
from hashlib import sha256
import unittest

import explore as e
import magenta_components as m
import tiny_features as tiny
import whole_strip
import inset_strip


def pixel_frame(points, width=80, height=80):
    data = bytearray(bytes((128, 128, 128, 255)) * width * height)
    for x, y in points:
        at = (y * width + x) * 4
        data[at:at + 4] = m.MAGENTA
    return bytes(data), width, height, width * 4


class ComponentTests(unittest.TestCase):
    def test_four_components_preserve_actual_full_pixel_support(self):
        points = {(x, y) for ox, oy in ((4, 4), (70, 4), (4, 70), (70, 70))
                  for x in (ox, ox + 1) for y in (oy, oy + 1)}
        raw, w, h, stride = pixel_frame(points)
        result = m.locate(raw, w, h, stride)
        self.assertEqual(result["qualifyingPixels"], 16)
        self.assertEqual(result["frame"]["sha256"], sha256(raw).hexdigest())
        self.assertEqual(result["components"][0]["bounds"], [4, 4, 6, 6])
        self.assertEqual(result["components"][0]["pixels"], [[4, 4], [5, 4], [4, 5], [5, 5]])
        self.assertFalse(result["sourceLocalityEstablished"])
        self.assertFalse(result["admissionEligible"])

    def test_missing_and_extra_components_rejected(self):
        for points in ({(4, 4), (70, 4), (4, 70)}, {(4, 4), (70, 4), (4, 70), (70, 70), (40, 40)}):
            with self.assertRaises(ValueError): m.locate(*pixel_frame(points))

    def test_qualifying_pixel_limit(self):
        points = {(x, y) for x in range(20) for y in range(20)}
        with self.assertRaisesRegex(ValueError, "256"): m.locate(*pixel_frame(points))

    def test_component_dimension_limit(self):
        points = {(x, 2) for x in range(17)} | {(4, 70), (70, 4), (70, 70)}
        with self.assertRaisesRegex(ValueError, "16 by 16"): m.locate(*pixel_frame(points))

    def test_diagonal_pixels_remain_distinct_components(self):
        points = {(4, 4), (5, 5), (70, 4), (4, 70), (70, 70)}
        with self.assertRaisesRegex(ValueError, "four"): m.locate(*pixel_frame(points))

    def test_near_magenta_or_nonopaque_not_promoted(self):
        raw, w, h, stride = pixel_frame({(4, 4), (70, 4), (4, 70), (70, 70)})
        for color in (bytes((254, 0, 255, 255)), bytes((255, 1, 255, 255)), bytes((255, 0, 255, 254))):
            changed = bytearray(raw); changed[(4 * w + 4) * 4:(4 * w + 4) * 4 + 4] = color
            with self.assertRaises(ValueError): m.locate(bytes(changed), w, h, stride)

    def test_shape_and_mutability_rejections(self):
        raw, w, h, stride = pixel_frame({(4, 4), (70, 4), (4, 70), (70, 70)})
        for args in ((bytearray(raw), w, h, stride), (raw[:-1], w, h, stride), (raw, True, h, stride),
                     (raw, 2049, h, stride), (raw, w, h, stride + 1)):
            with self.assertRaises(ValueError): m.locate(*args)


class ActualRenderedExperiment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw, cls.report = tiny.trial()
        cls.packets = cls.report["packets"]
        cls.components = cls.report["componentObservation"]

    def test_real_decoder_finds_all_four_full_session_packets(self):
        self.assertEqual([r["anchor"] for r in self.packets["anchors"]], [1, 2, 3, 4])
        self.assertTrue(all(r["session"] == e.SESSION for r in self.packets["anchors"]))
        self.assertEqual(self.packets["frame"]["sha256"], sha256(self.raw).hexdigest())

    def test_real_opaque_components_are_not_ideal_centers(self):
        self.assertEqual(self.components["qualifyingPixels"], 16)
        for row in self.components["components"]:
            left, top, right, bottom = row["bounds"]
            self.assertEqual((right - left, bottom - top), (2, 2))
        self.assertEqual(self.components["frame"]["sha256"], sha256(self.raw).hexdigest())

    def test_pairing_does_not_depend_on_component_iteration_order(self):
        shuffled = deepcopy(self.components); shuffled["components"].reverse()
        self.assertEqual(m.pair_to_packets(shuffled, self.packets), m.pair_to_packets(self.components, self.packets))

    def test_wrong_frame_binding_rejected(self):
        changed = deepcopy(self.components); changed["frame"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "bytes differ"): m.pair_to_packets(changed, self.packets)

    def test_foreign_component_outside_adjacency_rejected(self):
        changed = deepcopy(self.components); changed["components"][0]["bounds"] = [300, 600, 302, 602]
        with self.assertRaisesRegex(ValueError, "foreign"): m.pair_to_packets(changed, self.packets)

    def test_ambiguous_adjacency_rejected_without_trying_fits(self):
        changed = deepcopy(self.components)
        changed["components"][1]["bounds"] = [8, 50, 10, 52]
        with self.assertRaisesRegex(ValueError, "ambiguous"): m.pair_to_packets(changed, self.packets)

    def test_whole_source_rectangles_remain_too_broad(self):
        result = e.diagnose(self.raw, self.packets["frame"]["stride"], self.packets,
                            "whole-support", (e.F(7, 5), e.F(28, 5), e.F(231, 5)))
        self.assertFalse(result["geometryFreezeSucceeded"])
        self.assertIn("viewport", result["geometryFailure"])

    def test_tiny_feature_intervals_pass_only_geometry(self):
        self.assertTrue(self.report["geometryFreezeSucceeded"])
        self.assertEqual(self.report["fitAnchors"], ["anchor-1", "anchor-2", "anchor-3"])
        self.assertEqual(self.report["independentHoldout"], ["anchor-4"])
        self.assertEqual(self.report["viewportOutwardPixels"], [3, 43, 571, 1273])
        for row in self.report["anchorIntervals"]:
            self.assertEqual(e.F(*row["appX"]["hi"]) - e.F(*row["appX"]["lo"]), 2)
            self.assertEqual(e.F(*row["pixelX"]["hi"]) - e.F(*row["pixelX"]["lo"]), 2)
        self.assertFalse(self.report["admissionEligible"])

    def test_revised_local_retention_cap_is_explicit(self):
        self.assertEqual(self.report["diagnosticROIBytes"], 410496)
        self.assertTrue(self.report["exceedsSuperseded256KiB"])
        self.assertTrue(self.report["fitsCurrent1MiB"])
        self.assertEqual(self.report["recordCap"], 6000)

    def test_live_strip_uncertainty_is_not_collapsed(self):
        self.assertFalse(self.report["stripInteriorsFound"])
        self.assertEqual(self.report["stripFailure"], "unresolved cell interior")
        self.assertTrue(any(row["wholePixelCount"] == 0 for row in self.report["stripCellXInteriorDiagnostics"]))

    def test_whole_source_cell_intersections_decode_actual_pixels(self):
        result = self.report["wholeCellExperiment"]
        self.assertTrue(result["interiorsFound"])
        self.assertIsNone(result["failure"])
        self.assertEqual(result["decoded"]["marker"], 456)
        self.assertEqual(len(result["cells"]), 24)
        self.assertFalse(result["admissionEligible"])

    def test_every_retained_unit_pixel_fits_every_feasible_transform(self):
        anchors = self.report["anchorIntervals"][:3]
        def axis(name):
            rows = []
            for a in anchors:
                source, pixel = a["app" + name], a["pixel" + name]
                rows.append((e.g.Interval(e.F(*source["lo"]), e.F(*source["hi"])),
                             e.g.Interval(e.F(*pixel["lo"]), e.F(*pixel["hi"]))))
            return e.g._fit_axis(rows)
        xp, yp = axis("X"), axis("Y")
        mx, my, _, _ = next(r["rectangle"] for r in self.report["diagnosticROIs"] if r["role"] == "marker")
        for index, (left, top, right, bottom) in enumerate(self.report["wholeCellExperiment"]["cells"]):
            for scale, translation in xp:
                self.assertLessEqual(scale * (105 + index * 8) + translation, left + mx)
                self.assertGreaterEqual(scale * (105 + (index + 1) * 8) + translation, right + mx)
            for scale, translation in yp:
                self.assertLessEqual(scale * 730 + translation, top + my)
                self.assertGreaterEqual(scale * 746 + translation, bottom + my)


    def test_fourth_feature_only_movement_rejects_without_refit(self):
        # Move only fourth feature down by 12 source points, inside frame.
        # Measured AX input remains unchanged, simulating a locality violation.
        # Fixed outward adjacency still passes, so rejection must be holdout.
        moved = e.FEATURE_RECTS[:3] + ((396, 880, 2, 2),)
        raw, stride = e.render(tiny_features=True, strip=True, feature_rects=moved)
        packets = e.registration.locate_registration(raw, e.WIDTH, e.HEIGHT, stride, e.SESSION)
        components = m.locate(raw, e.WIDTH, e.HEIGHT, stride)
        paired = m.pair_to_packets(components, packets)
        self.assertEqual([a["observedDarkRingBounds"] for a in packets["anchors"]],
                         [a["observedDarkRingBounds"] for a in self.packets["anchors"]])
        self.assertEqual([r["component"]["bounds"] for r in paired[:3]],
                         [r["component"]["bounds"] for r in self.report["pairedComponents"][:3]])
        with self.assertRaisesRegex(e.g.InvalidEvidence, "no common frozen transform"):
            tiny.trial(rendered_feature_rects=moved)

    def test_fractional_raster_truth_and_all_admitted_pixel_support(self):
        cases = ((e.F(7,5), e.F(61,10), e.F(467,10), True),
                 (e.F(139,100), e.F(761,100), e.F(556,10), True),
                 (e.F(71,50), e.F(79,50), e.F(1873,50), False))
        for scale, tx, ty, frozen in cases:
            with self.subTest(scale=scale, tx=tx, ty=ty):
                _, report = tiny.trial(scale=scale, tx=tx, ty=ty)
                self.assertEqual(report["geometryFreezeSucceeded"], frozen)
                # True transform satisfies every exact fit half-plane; checking
                # independent marginal bounds alone would lose correlation.
                for anchor in report["anchorIntervals"][:3]:
                    for axis, translation in (("X", tx), ("Y", ty)):
                        source, pixel = anchor["app" + axis], anchor["pixel" + axis]
                        self.assertLessEqual(e.F(*pixel["lo"]), scale*e.F(*source["hi"])+translation)
                        self.assertLessEqual(scale*e.F(*source["lo"])+translation, e.F(*pixel["hi"]))
                self.assertFalse(report["admissionEligible"])
                whole = report["wholeCellExperiment"]
                self.assertEqual(whole["decoded"]["marker"], 456)
                mx, my, _, _ = next(r["rectangle"] for r in report["diagnosticROIs"] if r["role"] == "marker")
                for index, (left, top, right, bottom) in enumerate(whole["cells"]):
                    self.assertLess(left, right); self.assertLess(top, bottom)
                    self.assertLessEqual(scale*(105+index*8)+tx, left+mx)
                    self.assertGreaterEqual(scale*(105+(index+1)*8)+tx, right+mx)
                    self.assertLessEqual(scale*730+ty, top+my)
                    self.assertGreaterEqual(scale*746+ty, bottom+my)
                if not frozen:
                    self.assertIn("viewport", report["geometryFailure"])

    def test_whole_cell_unknown_nonuniform_and_transparent_fail(self):
        x, y, width, height = next(r["rectangle"] for r in self.report["diagnosticROIs"] if r["role"] == "marker")
        stride = self.packets["frame"]["stride"]
        data = b"".join(self.raw[row * stride + x * 4:row * stride + (x + width) * 4] for row in range(y, y + height))
        cells = self.report["wholeCellExperiment"]["cells"]
        cx, cy, _, _ = cells[0]
        at = (cy * width + cx) * 4
        for color in (bytes((128, 128, 128, 255)), bytes((0, 0, 0, 0)), bytes((255, 255, 255, 255))):
            modified = bytearray(data); modified[at:at + 4] = color
            with self.assertRaises(ValueError): e.live_strip.decode(bytes(modified), width, height, cells)

    def test_whole_cell_experiment_changes_only_inset(self):
        parent = e.Path(inset_strip.__file__).read_text()
        parent = parent[parent.index("def _exact("): ]
        candidate = e.Path(whole_strip.__file__).read_text()
        candidate = candidate[candidate.index("def _exact("):]
        restored = candidate.replace('    # Experimental whole-source-cell intersection, no 40% inset.\n    # Every retained unit pixel must fit every feasible transform.',
                                     '    # marker=(left,top,width,height), crop=(x,y,width,height). Use middle40%\n    # source-cell interiors, then intersect over every feasible transform.')
        restored = restored.replace("Fraction(0)", "Fraction(3,10)").replace("Fraction(1)", "Fraction(7,10)")
        self.assertEqual(parent, restored)

    def test_promoted_rule_matches_reviewed_experiment_exactly(self):
        parent = e.Path(e.live_strip.__file__).read_text()
        parent = parent[parent.index("def _exact("):parent.index("\ndef decode(")]
        candidate = e.Path(whole_strip.__file__).read_text()
        candidate = candidate[candidate.index("def _exact("):]
        candidate = candidate.replace('Experimental whole-source-cell intersection, no 40% inset.',
                                      'Whole-source-cell intersection; no chosen center or rendering-error bound.')
        self.assertEqual(parent, candidate)

    def test_whole_cell_still_rejects_unresolved_transform(self):
        with self.assertRaisesRegex(ValueError, "unresolved"):
            whole_strip.cell_interiors((0, 0, 192, 16), ((1, 0), (1, 10)), ((1, 0),), (0, 0, 202, 16))


if __name__ == "__main__":
    unittest.main()
