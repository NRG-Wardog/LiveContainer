# Aggregate compatibility successor: fresh Apple Phase A

LOCAL SOURCE ONLY. The workflow remains REVIEW_REQUIRED. This candidate is neither an activated capture nor native evidence. Independent review must approve the exact frozen adapter, source inputs and workflow before any publication or run.

## Exact sources and ancestry

- AnisetteKit 56f9aab3b2726821ed460e770c531e72a8233b8b, tree 9fa391fa6486a08e2d3db96b0fc9b1c0b372fb65, sole parent 227dfd8c8456cd62e4ceff4971b17afb2003d7e8. Exact local reviewed equivalent: 7ebbb4ce0ce5756fe9d7bfe1899aaaa358c8b1e2. Changes are two default member initializers in one production header and two new header-only compatibility test files.
- SideSign e296f830780226e9ff27b84ad66bba114f71dafc, tree aedb16da10e4a334136c033618a09a5b746f4eb7, sole parent a3617d2eab547665480324034571cf22aa684257. Only Package.swift changes, pinning the exact new AK revision. The inherited genuine Package.resolved is unchanged; only this new capture's resolver-produced lock may feed a later lock-only child. No future lock is invented or prefilled.
- Capture host is a direct sole-parent successor to successful host 4df0baa4f92274983a0d750cc5c3a3553600296b/tree 3b3ff76bec2d99729a34f4c484e90d624ff9de46. That prior run 39309171320 is historical evidence only. The cumulative overlay remains exhaustively restricted against product base 545438e1f0a89fdef375f73273c5c9fc2735cbce/tree e8014dd771c25c4a05dc76ab0aa304a233642a83. Product source stays unchanged.
- The dedicated new branch is validation/p0-fault-aggregate-phase-a. The old successful capture and its receipts remain immutable.

reviewed/aggregate-source-seal.json binds an additive, exact three-path delta against the prior diagnostic tree, its independent review, and the current full 67-file source inventory. The 65-file diagnostic inventory and all prior reviewed receipts remain byte-for-byte historical files. New commit/ref/full-tree readbacks and source-pin review use separate aggregate-prefixed paths. They are never replacements for native evidence.

## Finite command and test plan

The existing plan remains: 8 owner acquisition commands; 4 genuine/frozen resolution commands; 2 complete package rebuilds; 2 full framework-specific discoveries and 2 exact filtered executions (6 AK XCTest + 5 SideSign Swift Testing cases). The original owner run_tests.py is unchanged and still selects exactly 9 maintained unittest IDs.

Six explicit synthetic host suites are required:

1. Memory boundaries: 3 variants × 403 checks.
2. VM setup: 3 × 239 checks, 17 fault points each.
3. Metadata bounds: 3 × 713 checks.
4. Exactly the original 9 maintained aggregate unittest IDs, without skips.
5. Existing bounded diagnostics: 16 nested commands, 3 × 662 native checks plus two exact Swift decoder runs and 2 × 77 response-boundary assertions. Native nm/otool proof and real Apple CommonCrypto remain required.
6. The exact owner .ci/native-tests/test_fault_aggregate_compatibility.py: exactly FaultAggregateCompatibilityTests.test_warning_clean_legacy_and_explicit_aggregates. Two C++17 variants (normal; -O2 -DNDEBUG), each with -Wall -Wextra -Werror -pedantic, compile genuine production headers and run 18 inert value checks. No loader, engine, guest, private assets or network are used.

The sixth suite retains the one-ID unittest receipt, all four nested compile/run command/result/stdout/stderr receipts, and transient inputs/binaries through the existing observer. The verifier binds compiler /usr/bin/c++, exact argv/order/flags, owner/include/source paths, distinct temporary outputs, original zero-warning streams, exactly two 18-check outputs, and current hashes for all 67 source files. Missing/skipped/extra IDs, dropped warning flags, altered paths, changed source hashes, extra commands and nonzero/Boolean success fields fail closed. This is a separate suite, not a fabricated tenth run_tests.py case.

## Preserved Swift compiler/execution split

The existing exact 16-row diagnostic command plan is unchanged. Only swift-normal-compile and swift-optimized-compile run outside the outer synthetic wrapper, retaining Apple's compiler/plugin sandbox. Every generated Swift executable and all native diagnostic commands remain network-denied. The new aggregate suite, like the four pre-existing owner drivers, runs wholly under the original network-denial wrapper.

The four literal-only C++ fixture adaptations and exact Swift byte-span extraction remain unchanged. Production sources are never transformed. Full package rebuilds separately validate original Swift/native files. The prior failed Swift macro receipt is historical regression material only.

## Retention, scope and review

Owner/dependency Git trees and modes, commits, manifests, genuine before/after/terminal locks, SwiftPM state, pinned binary archives/frameworks, SDK, tool identities, compiler scratch inputs/products, raw nested streams and owned-process settlement remain retained. Retention bounds and full immutable evidence indexing are unchanged. The separately bounded failure-log view cannot replace the full capture.

No product/P2/UI source, application typecheck, IPA, device, Apple login, external provider, proprietary engine or guest execution is included. Leak sanitizer stays disabled and unclaimed; the pre-existing sanitizer variants stay fail-fast. Native success would mean only CAPTURED_FOR_INDEPENDENT_REVIEW, never release/build admission.

Portable review commands:

    python3 -B ci/p0defensive/prepare_inputs.py --host-root .
    python3 -B ci/p0defensive/native_gate.py --host-root . --inputs ci/p0defensive/inputs-phase-a.json
    python3 -B -m unittest discover -s ci/p0defensive/tests -v
    python3 -O -B -m unittest discover -s ci/p0defensive/tests -v

These adapter tests use inert Python/JSON fixtures and never run the owner C++/Swift/native suites. Exact activation remains a separate reviewed step. Any change after freezing requires a new inventory hash and review.
