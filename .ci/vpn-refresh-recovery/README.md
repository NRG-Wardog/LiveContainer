# Foreground VPN refresh recovery evidence

Generate with `python3 generate_fixture.py --candidate-root <root> --output <out>`.
Generation only reads sources and writes an extracted fixture and source hashes. It never compiles or executes Swift.

The fixture extracts the actual host recovery eligibility/orchestration, activation waiter and return-marker rules; actual SideStore finite readiness classifier and OperationError; and the current shared failure/manifest model. Synthetic callbacks replace pipeline, app activation and settling effects. Native CI can compile with `swiftc -parse-as-library <out>/vpn-refresh-recovery.swift -o <binary>` and execute `<binary> <out>/result.json`.

Coverage includes strict correlated all-app pre-mutation evidence; finite VPN reasons; no arbitrary invalidVPN recovery; no partial success, unknown outcome, or background activation; one total handoff including initial preflight; one post-return pipeline recheck; cancellation, lost ownership, launch/settlement failure and late callbacks. No actual VPN, device, Keychain, authentication, provider or network action runs. UIKit/NWPathMonitor integration is source-asserted, not exercised by the fixture. An on-device VPN-off refresh remains required for full behavioral validation.
