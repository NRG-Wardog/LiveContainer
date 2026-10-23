# Setup connection evidence

The generator extracts the actual host-only setup policy, actual strict terminal-summary verifier, and full shared failure model (including its decoder) from the explicitly supplied integrated candidate root. The harness supplies only synthetic in-memory ledger records and failure wires. It runs no VPN/device/provider/network operations.

Generate and statically check:

    python3 LiveContainer/.ci/setup-connection-evidence/generate_fixture.py --candidate-root "$CANDIDATE" --output "$OUTPUT"

Proposed CI-only compile/run, not performed during local preparation:

    swiftc -swift-version 5 -parse-as-library "$OUTPUT/setup-connection.swift" -o "$OUTPUT/setup-connection"
    "$OUTPUT/setup-connection" "$OUTPUT/cases.json"

Require the cases JSON status to be pass and its ordered case names/count to exactly match sources.json. Check the source hashes and generated SHA256. There are 25 cases, including arbitrary utun detection, matched readiness failures, stale/wrong correlation, newer signing/pending outcomes, strict success, malformed/ambiguous chronology, cancellation, and unknown-kind privacy.

Generation is not native compilation, execution, UI rendering, VPN confirmation, or device acceptance. No pairing configuration or refresh fail-closed transport guard is changed by this policy. Green explicitly means the latest verified refresh with a currently detected tunnel interface, not provider identity or current service availability.

CoreDevice remains neutral after successful refresh because the result does not identify CoreDevice rather than Lockdown transport. The test checks every outcome rejects inferred green CoreDevice status. Run-state notifications and matching test-ledger observations synchronously refresh the connection rows. New setup copy uses only the finite V3SetupConnectionCopy allowlist with the existing owned English fallback; arbitrary provider copy remains fail-closed.

The generator also checks the exact host LocalDevVPN activation message scope in both shared-model mirrors: refresh, network stage, localDevVPNUnavailable, and unavailable or timedOut only. These messages precede the generic timeout message. Seven source-mutation negatives reject changed operation, stage, cause, code, raw provider copy, missing override, and wrong timeout precedence. This is static source validation, not execution of the Swift formatter. Both keys require en/he/zh-Hans/zh-Hant/ru translations.
