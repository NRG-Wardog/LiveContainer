"""Validate retained fixture draw rows, not pixels, presentation, or admission.

Input is the complete ordered journal event inventory supplied by a separate
verified collector. Bytes/hash resolution, journal completeness and write-cost
validation remain the caller's responsibility. Never pass only a ready flag.
"""
from __future__ import annotations

import math
import re


class InvalidDrawReceipts(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise InvalidDrawReceipts(message)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


COMMON = {"type", "schema", "session", "uptime", "clock", "timingMeaning",
          "displayTimeEstablished", "admissionEligible", "enqueuedUptime",
          "journalStartUptime", "priorWrites"}
DRAW = {"source", "anchor", "draw", "beforeUptime", "afterUptime"}
INVENTORY = {"firstDrawSources", "initialDrawsEnqueued", "retainedEvidenceRequired"}


def validate_initial_draw_receipts(events, session):
    """Require all eight source-tagged retained draw=1 events before the single inventory event.

Also reject every later error, sequence restart/gap, or malformed draw in the
supplied journal. This prerequisite alone never authorizes baseline release.
"""
    require(type(session) is str and re.fullmatch(r"[0-9a-f]{32}", session), "invalid session")
    require(type(events) is list, "ordered retained event list required")
    sources = [(source, anchor) for source in ("packet", "feature") for anchor in range(1, 5)]
    next_draw = {key: 1 for key in sources}
    first = {}
    inventory_index = None
    last_draw_after = 0
    last_enqueued = 0
    costs = []
    for index, row in enumerate(events):
        require(type(row) is dict and type(row.get("type")) is str, "invalid journal row")
        kind = row["type"]
        if not kind.startswith("direct-anchor-"):
            continue
        require(kind in ("direct-anchor-draw", "direct-anchor-initial-draws"),
                "anchor error or unknown event prohibits readiness")
        require("error" not in row, "anchor draw error prohibits readiness")
        extra = DRAW if kind == "direct-anchor-draw" else INVENTORY
        require(set(row) == COMMON | extra, "unexpected or missing anchor receipt fields")
        require(row["schema"] == "p1-" + kind + "-v1" and row["session"] == session,
                "wrong draw schema or session")
        require(row["clock"] == "app-ProcessInfo.systemUptime" and
                row["timingMeaning"] == "fixture-draw-only" and
                row["displayTimeEstablished"] is False and row["admissionEligible"] is False,
                "draw-only clock meaning required")
        times = [row[key] for key in ("uptime", "enqueuedUptime", "journalStartUptime")]
        require(all(finite(value) for value in times) and times == sorted(times) and
                row["enqueuedUptime"] >= last_enqueued, "invalid journal clock brackets")
        require(type(row["priorWrites"]) is list, "journal write inventory required")
        last_enqueued = row["enqueuedUptime"]
        if kind == "direct-anchor-draw":
            source, anchor, draw = row["source"], row["anchor"], row["draw"]
            require(type(source) is str and source in ("packet", "feature"), "unknown draw source")
            key = (source, anchor)
            require(type(anchor) is int and key in next_draw and type(draw) is int and
                    1 <= draw <= 64 and draw == next_draw[key], "anchor draw gap, reuse, or cap")
            before, after = row["beforeUptime"], row["afterUptime"]
            require(finite(before) and finite(after) and row["uptime"] == before and
                    last_draw_after <= before <= after <= row["enqueuedUptime"],
                    "invalid draw-only clock brackets")
            last_draw_after = after
            next_draw[key] += 1
            if draw == 1:
                first[key] = index
            costs.append(after - before)
        else:
            require(inventory_index is None and set(first) == set(sources),
                    "all eight earlier initial draw receipts required exactly once")
            inventory = row["firstDrawSources"]
            require(type(inventory) is list and len(inventory) == 8 and
                    all(type(value) is dict and set(value) == {"source", "anchor"} and
                        type(value["source"]) is str and type(value["anchor"]) is int for value in inventory) and
                    inventory == [dict(source=source, anchor=anchor) for source, anchor in sources] and
                    row["initialDrawsEnqueued"] is True and row["retainedEvidenceRequired"] is True,
                    "invalid initial draw inventory")
            require(row["uptime"] >= last_draw_after, "inventory predates its draw receipts")
            inventory_index = index
    require(inventory_index is not None, "retained initial draw inventory missing")
    return {"schema": "p1-direct-anchor-prerequisite-v1", "session": session,
            "initialDrawEventIndices": [first[key] for key in sources],
            "initialDrawSources": [dict(source=source, anchor=anchor) for source, anchor in sources],
            "inventoryEventIndex": inventory_index, "drawReceiptCount": len(costs),
            "drawMaxSeconds": max(costs), "drawTotalSeconds": sum(costs),
            "displayTimeEstablished": False, "admissionEligible": False}
