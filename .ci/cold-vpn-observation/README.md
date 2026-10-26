# Cold VPN interface observation

The host waits within the same manual activation attempt for Wi-Fi and an up
`utun` interface observation, with a ten-second monotonic deadline, cancellation,
foreground-return and exact run/request ownership checks. This is **not** proof
of the selected VPN provider, peer connectivity, or CoreDevice readiness.
SideStore must still perform its owned pre-mutation readiness gate. Integrate
this change with that backend gate, not as an alternative to it.

Run `REQUIRE_SWIFT_COLD_VPN_TESTS=1 python3 -B test_contract.py` on macOS.
`COLD_VPN_EVIDENCE_DIR` optionally receives JSON source-bound receipts. The suite
compiles extracted production policy plus the actual NWPathMonitor adapter for
an iOS15 simulator deployment target, and executes policy/ownership timelines
with a deterministic virtual clock on the host. No VPN, device or account is
accessed. The existing `vpn-refresh-recovery` suite additionally preserves the
one-handoff, no-blind-replay and terminal-failure coverage.
