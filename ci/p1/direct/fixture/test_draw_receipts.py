from copy import deepcopy
import unittest

from draw_receipts import InvalidDrawReceipts, validate_initial_draw_receipts

SESSION = "0123456789abcdef0123456789abcdef"


def common(kind, uptime):
    return dict(type=kind, schema="p1-" + kind + "-v1", session=SESSION, uptime=uptime,
                clock="app-ProcessInfo.systemUptime", timingMeaning="fixture-draw-only",
                displayTimeEstablished=False, admissionEligible=False,
                enqueuedUptime=20, journalStartUptime=21, priorWrites=[])


def draw(anchor, ordinal=1, uptime=None, source="packet"):
    before = anchor + (4 if source == "feature" else 0) if uptime is None else uptime
    return dict(common("direct-anchor-draw", before), source=source, anchor=anchor, draw=ordinal,
                beforeUptime=before, afterUptime=before + 0.001)


def inventory():
    return dict(common("direct-anchor-initial-draws", 9),
                firstDrawSources=[dict(source=s, anchor=a) for s in ("packet", "feature") for a in range(1, 5)],
                initialDrawsEnqueued=True, retainedEvidenceRequired=True)


def events():
    # Original start may be journaled before a queued receipt whose draw was
    # earlier. Event file order must not be mistaken for global draw-time order.
    return [dict(type="start", uptime=10)] + [draw(a, source=s) for s in ("packet", "feature") for a in range(1, 5)] + [inventory()]


class DrawReceiptTests(unittest.TestCase):
    def rejects(self, rows):
        with self.assertRaises(InvalidDrawReceipts):
            validate_initial_draw_receipts(rows, SESSION)

    def test_all_eight_retained_first_draws(self):
        proof = validate_initial_draw_receipts(events(), SESSION)
        self.assertEqual(proof["initialDrawEventIndices"], [1, 2, 3, 4, 5, 6, 7, 8])
        self.assertEqual(proof["inventoryEventIndex"], 9)
        self.assertFalse(proof["admissionEligible"])
        self.assertFalse(proof["displayTimeEstablished"])

    def test_missing_initial_receipt_even_with_ready_flag(self):
        for anchor in range(1, 5):
            self.rejects([r for r in events() if r.get("anchor") != anchor])

    def test_missing_early_or_repeated_inventory(self):
        self.rejects(events()[:-1])
        self.rejects([inventory()] + events())
        self.rejects(events() + [inventory()])

    def test_session_clock_and_presentation_claims_rejected(self):
        for key, value in (("session", "f" * 32), ("clock", "mach"),
                           ("timingMeaning", "presentation"), ("displayTimeEstablished", True),
                           ("admissionEligible", True), ("uptime", 2), ("uptime", float("nan")),
                           ("enqueuedUptime", 0), ("journalStartUptime", 19)):
            rows = events(); rows[1][key] = value
            with self.subTest(key=key, value=value): self.rejects(rows)

    def test_missing_and_unknown_fields_rejected(self):
        for key in events()[1]:
            rows = events(); del rows[1][key]
            self.rejects(rows)
        rows = events(); rows[1]["displayTime"] = 123
        self.rejects(rows)

    def test_later_error_remains_fatal_after_inventory(self):
        self.rejects(events() + [dict(type="direct-anchor-receipt-error", error="overflow")])
        rows = events() + [draw(1, 2, 10)]; rows[-1]["error"] = "invalid-anchor-draw"
        self.rejects(rows)

    def test_later_draw_retained_and_costed(self):
        rows = events() + [draw(1, 2, 10)]
        self.assertEqual(validate_initial_draw_receipts(rows, SESSION)["drawReceiptCount"], 9)

    def test_all_512_successful_draw_rows_are_retained(self):
        rows = events()
        for ordinal in range(2, 65):
            for number, (source, anchor) in enumerate((s, a) for s in ("packet", "feature") for a in range(1, 5)):
                row = draw(anchor, ordinal, 10 + ordinal * 8 + number, source)
                row["enqueuedUptime"] = row["afterUptime"] + 1
                row["journalStartUptime"] = row["enqueuedUptime"] + 1
                rows.append(row)
        self.assertEqual(validate_initial_draw_receipts(rows, SESSION)["drawReceiptCount"], 512)

    def test_recreation_gap_cap_and_boolean_ordinals(self):
        for anchor, ordinal in ((1, 1), (1, 3), (1, 65), (True, 2), (5, 1), (1, True)):
            self.rejects(events() + [draw(anchor, ordinal, 10)])

    def test_inventory_requires_exact_eight_and_booleans(self):
        for key, value in (("firstDrawSources", [{"source":"packet", "anchor": True}]),
                           ("firstDrawSources", inventory()["firstDrawSources"][:-1]), ("initialDrawsEnqueued", 1),
                           ("retainedEvidenceRequired", False)):
            rows = events(); rows[-1][key] = value
            self.rejects(rows)

    def test_each_tagged_source_required_and_not_interchangeable(self):
        for source in ("packet", "feature"):
            for anchor in range(1, 5):
                self.rejects([r for r in events() if (r.get("source"), r.get("anchor")) != (source, anchor)])
        for source in ("foreign", 1, True, "packet\n"):
            rows = events(); rows[1]["source"] = source; self.rejects(rows)
        rows = events(); rows[5]["source"] = "packet"; self.rejects(rows)
        rows = events(); rows[-1]["firstDrawSources"].reverse(); self.rejects(rows)

    def test_input_is_not_mutated(self):
        rows = events(); original = deepcopy(rows)
        validate_initial_draw_receipts(rows, SESSION)
        self.assertEqual(rows, original)


if __name__ == "__main__":
    unittest.main()
