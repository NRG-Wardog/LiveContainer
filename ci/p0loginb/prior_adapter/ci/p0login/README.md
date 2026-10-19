# Fresh P0 login trace Phase A capture proposal

Local proposal only. The workflow is dedicated-branch-push/manual, dedicated-branch-only, read-only, and deliberately blocked by REVIEW_REQUIRED until separate adapter/input/workflow approval. No remote run, source publication, resolver output, native result or production admission is created by preparation.

Source seal: 0caa11b1135abbf9c3905c601d100475b91f8d011237033ab47d1f96fad116e8.
Publication tuples: 9c0da8c5be4eb6ebac50a006225e371ed9a1a3008e5e79dd4e30d71a906eba5a.
All four full commit/tree tuples, source changes and the finite 33-path source allowlist (plus the one genuine SideSign AK manifest pin) are checked. No lock changes are accepted as Phase A source input. The only existing workflow delta inserts a build-job condition excluding exactly `refs/heads/validation/p0-login-trace-phase-a` in `.github/workflows/build.yml`; original triggers and all other job bytes remain identical. Both before/after workflow bytes and the exact insertion are checked. The inherited dependency/gitlink graph stays recorded and unpopulated; it is not a compilable final app graph.

## Local review commands

From p0-login-validation-plan:

    python3 -B capture-candidate/ci/p0login/prepare_inputs.py --host-root capture-candidate --trees trees --output capture-candidate/ci/p0login/inputs-phase-a.json
    python3 -B -m unittest discover -s capture-candidate/ci/p0login/tests -v
    python3 -B -O -m unittest discover -s capture-candidate/ci/p0login/tests -v

Preparation reads immutable Git objects, not staged/working bytes. Its printed digest is a proposal identifier, not permission or approval. The input generator, frozen documents, runner, lifecycle, tests and audit are all included in the exact adapter inventory. Workflow template code is included in the reviewed input hash, normalizing only its sole approved-input digest field to REVIEW_REQUIRED to avoid a hash cycle. Any non-sentinel value must equal the exact reviewed input hash. The actual capture host must be a direct single-parent child of exact LC source with only new adapter files, the dedicated workflow and the exact ordinary-build job guard; full source bytes and actual host commit/tree are checked before and after execution. Do not regenerate source documents or permit paths to make a failed gate pass.

## Native execution contract

Require macos-26 arm64, selected Xcode 26.4.1 build17E202, Swift6.3.1 and clang21.0.0 exact recorded tool text. The previous tool-version text is an expected environment contract only; no old validation result is inherited. Swift version stdout and driver stderr are matched as exact separately decoded text streams under the unchanged text-mode capture, including stdout final newline and stderr trailing space. Python text-mode newline normalization still applies. This exact split was observed in failed Phase A run39209074594, artifact ZIP SHA25649f293de4c3b1c184610986f7097d10160af7970aee7bbdfb5c2e8af867740ef; that run stopped at toolchain comparison before source acquisition and supplies no native-test or resolver evidence. Any actual difference fails closed. Capture uname and macOS/iOS SDK paths anew.

Resolve SideSign through its ordinary Package.swift in a fresh external scratch directory with dependency caches disabled. Save before/after bytes before validation. Require identical package identity sets and every non-AnisetteKit pin; the sole changed pin must match the exact AK source commit. The originHash must be real resolver output. Repeat force-resolved resolution, prove the actual workspace-state graph, clean exact dependency source trees and bounded local SwiftPM mirror origins. No source patching, mirror rewriting, fabricated locks, originHash editing or binary stand-ins.

Typecheck the two production pure-Swift trace/error files with Swift6 complete strict concurrency. Parse every changed Swift source. Compile both ordinary packages with build-tests, without running them implicitly. Inspect and bind all test-module source hashes before discovery. Run discovery using explicit complementary XCTest/SwiftTesting flags. Its complete stdout, removing blank lines only, must exactly equal six AK or five SideSign IDs. A zero-test result, noise or ID change fails; never widen a filter.

AK execution disables Swift Testing entirely. Its separate dangerous real online provisioning test never runs. Run only the six anchored LoginDiagnosticTraceTests XCTest methods. SideSign disables XCTest and runs only the five anchored safe core tests; its filter permits the documented Swift Testing source-location suffix. Require exact starts/passes/counts/no skips. The AK output must exclude account@example.invalid, TOKEN-CANARY, PASSWORD-CANARY, BLOB-CANARY, SECRET and ORIGINAL. Do not reject finite diagnostic outcome=failed rows or decimal numbers that can occur in timing.

The host suites execute exact production C/Swift boundaries with finite API doubles, plus ELF metadata units in normal/optimized/ASan+UBSan modes (713 checks each, LSan explicitly unavailable). Run exact enumerated Python test IDs for the native boundary, SideSign source parity/privacy, and both owners’ login/init/ADI-consumption contracts; skips/expected failures fail. Each mirror suite clears inherited owner selectors, sets only its own owner selector, and verifies the imported module ROOT/PEER/PRODUCER against independent exact checkouts before tests run; init_diagnostics cannot silently prefer the SideStore root for a LiveContainer invocation. Network-denying sandbox is supplementary. It cannot itself prevent guest execution.

The Linux-only allocator/hook driver is not run or relabeled as macOS evidence. Real-engine TLS/constructor drivers are excluded from this no-guest lane; only their API-double/metadata counterparts are covered here. Existing separately evidenced Linux allocation validation remains separate, with no inherited source-tuple claim. No Apple library, real ADI engine invocation, online provisioning, guest payload, app launch or device login is permitted.

## Evidence and Phase B boundary

A 120-minute aggregate deadline leaves 30 minutes of the workflow budget for settlement and artifact transport. Every top-level command records argv, cwd, fixed environment, separate stdout/stderr, exit and owned-process settlement. All nested Python fixture/metadata compiler/run commands retain their original invocation/results and log additional observation records. Inherited/redirected child streams stay in the outer raw logs according to the unchanged fixture stream settings. No post-reap nonzero signal is sent. Unsettled or unknown writers prevent index creation and upload. Settled failures preserve actual logs/partial locks with failed status.

After builds/tests, require unchanged resolver locks, all owner source bytes and dependency checkouts. Index only after command groups settle. Upload then retain the actual returned artifact ID/digest in the GitHub job summary; a later authenticated finalizer must bind that artifact identity and evidence-index digest. An index cannot truthfully contain its own later archive digest. CAPTURED_FOR_REVIEW is not approval.

Phase B is deliberately unsupported by this adapter. It requires independent review of the real Phase A artifact and committing exactly its observed SideSign lock bytes, followed by updated SideStore gitlink and genuine app resolver capture. Phase B must compile the actual unsigned UIKit app graph, including maintained native transport outputs; no placeholder framework. SideStore’s normal build creates an internal SideBackup.ipa resource, so a future receipt must distinguish that internal product from the final requested distribution IPA rather than claim no archive of any kind existed. No old gate is changed.

## Second isolated parser retry

Run 39210026679 reached actual AnisetteKit build and its six selected XCTest cases, but the capture failed when one intact pass event was interleaved inside a LOGIN_TRACE line. The previous line-leading token count saw 11 events while the exact event parser found 12. This proposal counts every literal `Test Case ` token, independent of line position, and leaves exact identities, start/pass counts, completion summaries, failure/skip rejection, canary rejection and finite filters unchanged.

The fixtures under `tests/fixtures/interleaved-xctest.*` retain the exact recorded decoded stdout/stderr bytes from archive SHA256 `927b5b8beaaa9511331c80af008532fba66a9a615fa02750a971d25a4d9ce30f`, with member hashes and failed-run provenance. They are parser regressions only; no failed capture is promoted and no native test success is inherited by the next run. Adversarial mutations retain unknown/malformed/failed/skipped/cancelled/duplicate/missing event rejection. Source, toolchain, lifecycle, test selection and workflow are unchanged.
