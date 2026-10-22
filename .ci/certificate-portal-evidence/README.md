# Certificate portal JSON to IPC to Copy regression

Run generate_regression.py with --candidate-root, --baseline-root and --output.
Each source root uses the acquired graph layout, including SideStore/Dependencies/SideSign.
The exact delivered baseline must be extracted from verified local Git objects by the CI gate.
No source snapshot, network request, production mutation or runtime execution is embedded here.

Each variant extracts its own production service, host, proxy, pipeline and SideSign source.
Only source-extraction helpers and inert fixture support come from the frozen candidate.
The portalCertificates() diff remains exactly the bounded finite-observation wrapper;
independent merged changes elsewhere in AppDelegate.swift are permitted.
All original 15 portal cases and assertions are preserved. Four local identity NSError causes add direct and nested-wrapper assertions, for 19 cases per variant. Each new case also checks wrong-domain, unknown-code and outer-cancellation controls through the service and host, plus preservation of validated outer context and observed HTTP/server fields. Incompatible outer auth-response tuples are explicitly trimmed without discarding the finite primary identity diagnosis.
The portal suite keeps identity admission/context inert; the dedicated identity suite owns the real lease/context bodies.
Baseline production extraction remains exact; the new four-case harness explicitly asserts that the delivered baseline lacks the new finite identity diagnosis.

The consolidated gate compiles each service with module name SideSign, and compiles each host separately.
Run each service with its cases.plist path, then its matching host with cases.plist and results.json.
Generation and Python controls are not native compilation or runtime evidence.
