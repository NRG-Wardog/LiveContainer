# Foreground VPN refresh recovery evidence

Generate with `python3 generate_fixture.py --candidate-root <root> --output <out>`.
Generation only reads sources and writes an extracted fixture and source hashes. It never compiles or executes Swift.

The fixture extracts the actual host recovery eligibility/orchestration, activation waiter and return-marker rules; actual SideStore finite readiness classifier and OperationError; and the current shared failure/manifest model. Synthetic callbacks replace pipeline, app activation and settling effects. Native CI can compile with `swiftc -parse-as-library <out>/vpn-refresh-recovery.swift -o <binary>` and execute `<binary> <out>/result.json`.

Coverage includes strict correlated all-app pre-mutation evidence; finite VPN reasons; no arbitrary invalidVPN recovery; no partial success, unknown outcome, or background activation; one total handoff including initial preflight; one post-return pipeline recheck; cancellation, lost ownership, launch/settlement failure and late callbacks. No actual VPN, device, Keychain, authentication, provider or network action runs. Real UIKit/NWPathMonitor effects are not exercised; extracted preflight and activation methods additionally run against injected platform boundaries as described below. An on-device VPN-off refresh remains required for full behavioral validation.

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
refresh success. This historical cold-peer classifier case is retained alongside the scoped source-producer regression below.
Generation/static checks are not Swift compilation, runtime results or proof
that the user's device reached this branch. On-device cold VPN-off validation
still needs the resulting branch diagnostics after an admitted build.

## Addressless-interface batch regression

The fixture now contains 89 cases: the original 72 unchanged cases plus 17
source-owned host/service integration cases. Generation composes the SideStore
`tests/vpn_transport_recovery` extractor and its hash-verified historical policy,
transport snapshot and unavailable-error blocks. No invented error text or
handwritten copy of the transport or host eligibility predicates is used.

Both host `hasTunnelInterface` and the service's full `NetworkIfaceScanner` read
the same synthetic `getifaddrs` storage. An up addressless `utun0` passes the
unchanged host preflight without an initial enable request, while the service
rejects it as unusable. The old producer emits ineligible `invalidVPN`; the new
same-snapshot producer emits the existing `noVPN` / `vpnUnavailable` tuple.
No production host/wire schema or allowlist is expanded.

The integrated path executes extracted production early-boundary preservation,
structured error capture, `CombinedFailure.capture`, per-app wire encoding,
`CombinedVerification.sanitized`, binary-plist serialization/deserialization,
`verifyRefreshManifest`, `performRefreshWithVPNRecovery`, and the full preflight
and activation implementation. The complete shared failure and manifest models
are asserted byte-identical between SideStore and LiveContainer.

Only platform effects are doubled: in-memory preferences, OS interface/address
storage, Wi-Fi path observations, UIApplication.open completion/lifecycle events,
and refresh completion. The actual activation method supplies the official
`localdevvpn://enable?scheme=fixture-livecontainer` URL to the injected open API.
The two-app case checks one open decision and one retry after return; the retry
must independently pass the extracted service policy. Returning alone never
forces readiness. The real two-second settlement delay remains in the fixture.
Native UIKit, app launching, device installation, VPN/network, Keychain, signing,
Apple authentication and providers are not executed.

New negative cases cover unchanged unconfigured/missing-pairing/unsupported
backend failures, a mixed two-app failure, partial success, background/inactive
host, URL rejection, changed request ownership, uncertain mutation and an
already-consumed initial activation. Existing cancellation, run/request/ledger,
finite-reason, complete-manifest and one-shot guards remain covered by the
original 72 cases.

`cold-peer-source.json` labels its old full-file hashes and commit as historical
baseline provenance, not the current dependency revision. Current cold-peer
checks bind the unchanged exact endpoint-error guard block plus unchanged
endpoint/internal-error sources. The generated receipt separately records full
current dependency bytes and the complete transport fixture input closure in
`transport_fixture_inputs_sha256`. Generation is not a Swift compile/run result;
CI must compile and execute all 89 cases before this regression is claimed to
pass. Real-device VPN-off behavior remains a separate validation requirement.

The extracted activation flag storage has one explicit test-only observation
hook: `leftHost` keeps its original false initial value and original production
assignments, with a `didSet` acknowledgement added. Fake UIApplication waits
for that acknowledgement before delivering the active notification. It never
sets the flag itself. This avoids Task.yield timing assumptions, sleeps or
polling. The generator proves one exact insertion and a byte-exact round trip
back to the original state declaration; both hashes and the hook are recorded
in `fixture_observation_hook`. All preflight, activation and scheduler method
bodies remain byte-exact production extracts.
