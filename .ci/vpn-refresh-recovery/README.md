# Foreground VPN refresh recovery evidence

Generate with `python3 generate_fixture.py --candidate-root <root> --output <out>`.
Generation only reads sources and writes an extracted fixture and source hashes. It never compiles or executes Swift.

The fixture extracts the actual host recovery eligibility/orchestration, activation waiter and return-marker rules; actual SideStore finite readiness classifier and OperationError; and the current shared failure/manifest model. Synthetic callbacks replace pipeline, app activation and settling effects. Native CI can compile with `swiftc -parse-as-library <out>/vpn-refresh-recovery.swift -o <binary>` and execute `<binary> <out>/result.json`.

Coverage includes strict correlated all-app pre-mutation evidence; finite VPN reasons; no arbitrary invalidVPN recovery; no partial success, unknown outcome, or background activation; one total handoff including initial preflight; one post-return pipeline recheck; cancellation, lost ownership, launch/settlement failure and late callbacks. No actual VPN, device, Keychain, authentication, provider or network action runs. UIKit/NWPathMonitor integration is source-asserted, not exercised by the fixture. An on-device VPN-off refresh remains required for full behavioral validation.

## Cold VPN-off local peer regression

The exact minimuxer local-VPN missing-endpoint guard emits noDevice, not noVPN.
A generic utun interface can pass host preflight without a usable LocalDevVPN
peer, so the old finite recovery allowlist missed this pre-mutation result.
The candidate preserves noDevice and adds peerAddressUnavailable only for the
full source-pinned guard string, at refreshReadiness. It does not classify an
arbitrary noDevice, remote endpoint, pairing, backend, transport-policy, signing,
or installation error as a VPN activation opportunity.

OriginalRefreshReadinessFacts.swift is the byte-exact extracted prior classifier;
cold-peer-source.json binds its hash and the actual minimuxer guard sources at
1d033920660c6f50b8f30c4c333f025867cd9e96. Full checkouts also validate those three
actual dependency source hashes. Sparse generation explicitly reports that only
the pinned provenance receipt was available. The generated Swift cases compare
the old and candidate classifiers, then exercise candidate model round-trip,
all-app eligibility and actual one-shot orchestration with fake external effects.

The supported localdevvpn://enable?scheme= request, foreground restriction,
30-second return timeout, 2-second grace plus Wi-Fi/interface re-observation,
real pipeline readiness recheck, single-flight owner and request/ledger checks
are unchanged. Neither the callback nor an interface proves activation or
refresh success. Only the one exact new pre-mutation eligibility case is added.
Generation/static checks are not Swift compilation, runtime results or proof
that the user's device reached this branch. On-device cold VPN-off validation
still needs the resulting branch diagnostics after an admitted build.
