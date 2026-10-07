#!/usr/bin/env python3
"""Fail closed on zero, skipped, unexpected or missing selected native tests."""
import argparse
import json
from pathlib import Path
import re

EXPECTED = {
    "anisette": {"anisetteRequestHeadersCustomization", "anisetteDataResponseStructure", "anisetteHeadersDTORoundtrip"},
    "sidesign": {"deviceInitializationAndFiltering", "certificateRequestCSRGeneration", "developerPortalSingleton",
                 "archiveStoreRoundtrip", "archiveDeflateRoundtrip"},
    "jktcp-adapter": {"zero_window_persist_probe_recovers_lost_window_update", "retransmit_fires_after_rto",
        "connection_killed_after_max_retries", "ack_clears_unacked_queue", "sliding_window_sends_multiple_segments",
        "send_window_caps_in_flight_bytes", "syn_advertises_window_scale", "peer_window_scale_is_honored",
        "out_of_order_packet_dropped", "duplicate_packet_reacked_not_buffered"},
    "jktcp-packets": {"ipv4_checksum_matches_rfc_1071", "ipv4", "ipv6", "tcp"},
}


def verify(scope, text):
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    expected = EXPECTED[scope]
    if scope.startswith("jktcp-"):
        module = scope.removeprefix("jktcp-")
        matches = re.findall(r"^test " + module + r"::tests::([A-Za-z0-9_]+) \.\.\. ok$", text, re.M)
        summary = re.search(r"test result: ok\. (\d+) passed; 0 failed; 0 ignored;", text)
    else:
        matches = re.findall(r"Test ([A-Za-z0-9_]+)\(\) passed after", text)
        summary = re.search(r"Test run with (\d+) tests(?: in \d+ suites?)? passed after", text)
        started = set(re.findall(r"Test ([A-Za-z0-9_]+)\(\) started", text))
        if started - expected:
            raise ValueError("Unexpected Swift test execution: " + repr(started - expected))
    if set(matches) != expected or len(matches) != len(expected) or not summary or int(summary[1]) != len(expected):
        raise ValueError("Selected tests missing, skipped, duplicated or unexpected: " + scope)
    return {"scope": scope, "status": "PASS", "executed": len(matches), "tests": sorted(matches)}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("scope", choices=EXPECTED)
    p.add_argument("log", type=Path)
    p.add_argument("report", type=Path)
    a = p.parse_args()
    a.report.write_text(json.dumps(verify(a.scope, a.log.read_text()), indent=2) + "\n")
