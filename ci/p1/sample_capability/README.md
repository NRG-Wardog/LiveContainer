# Owned-child sample capability diagnostic

Local-only proposal on validation/p1-sample-capability, based on published capability commit d4a36263787c6d2c15a1c95a89ab2e9520e7fc60. No publication or run is authorized by this document. Independent review is required before publication.

Original run 39349300984 proves a benign child launch, one sampler exit 0 and settled/reaped cleanup, but not report compatibility. Its broad ValueError catch and discarded invalid report do not identify the rejection. Python launcher/framework image mismatch remains a hypothesis.

The preceding capability-only run 39351614029 rejected at report-path/path-matches=false after a zero sampler exit; later parent/UUID checks were not reached. It does not prove the old run's cause or a Python framework image.

This entry verifies a sealed runtime closure (including the two launch gates), diagnostic source and checked-in probe.c, compiles one native probe, then invokes exactly one one-second /usr/bin/sample against that owned native child. Existing helper_sample._launch/_run, process_scope, launch_gate and minimal_gate bytes are unchanged. No helper, app build, simulator, XCTest, UI capture, source dependency resolution, package install, sudo, new permission or fallback sampler is invoked. No tests execute in the hosted diagnostic lane. The synthetic suite runs locally before review.

Fixed stages cover environment, installed tool, expected-image proof, child launch, pre/post sample liveness, sampler command/launch receipt, bounded report, UTF-8, each required header, PID, path, parent, format and UUID. Rejection codes are fixed literals, not exception messages or report values. Safe expected resolved path, file SHA256 and Mach-O UUIDs, expected PID/parent, sampler exit code and Boolean comparison outcomes are retained. Identity matching stays exact; the original parser also validates every accepted report. Neither valid nor invalid synthetic raw reports are saved, printed, interpreted or used for admission. A path rejection does not infer a framework image or inspect its stacks. Checks after the first failed original predicate are deliberately unevaluated.

Compilation has a separate 20-second command deadline within the existing 60-second scope, uses the same owned launch/settle and 512 KiB output cap, and discards all compiler raw output. Tool absence, tool permission denial, source mismatch, compile nonzero/denial/timeout/output limit and image rejection have distinct fixed stages/codes.

The existing 8-second post-compilation preflight deadline, 4-second sampler command bound, 512 KiB output cap, same-UID/non-root GitHub-hosted restriction and supervised owned cleanup are preserved. Scope uses the already-supported 60-second capability budget profile; no fixture is created. The workflow adds a three-minute outer job and one-minute diagnostic step limit. Non-availability exits 2 and retains metadata, rather than appearing as capability success. Quiescence remains a separate mandatory cleanup receipt.

## Separate automatic-workflow exclusion

The prior build.yml exclusion of this exact validation branch remains unchanged. It prevents the ordinary build/release from triggering on the capability branch. Existing P0 and full P1 workflows are byte-identical, with exact other-branch push filters. update_source.yml has only release/manual triggers. This proposal neither creates a PR nor a tag, release or manual dispatch. A later PR would independently trigger the ordinary pull_request build and is out of scope.

## Review and result interpretation

closure.json hashes every executable/imported repository file used by this lane; its digest is pinned in the workflow. The external review seal records the complete proposed Git tree and payload bytes. The full-capture helper_sample, process_scope, gates, entry, input seal and P1 workflow remain unchanged in the parent tree.

A future diagnostic would establish only its own exact rejection stage or compatible benign report under that hosted runner. It cannot retroactively prove the original run's precise cause, and cannot establish ownerValid timing, scheduler/pressure claims, capture success or P1 admission.

## Native probe contract

probe.c uses only the public nanosleep and errno APIs, sleeps for 30 seconds with EINTR continuation, performs no I/O, and never execs or creates children. The parent terminates/reaps it after the one-second sample. Compilation uses only the already-installed /Applications/Xcode_26.4.1.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/clang and that Xcode bundle's MacOSX.sdk, with fixed -std=c11 -O0 -Wall -Wextra -Werror -isysroot SDK SOURCE -o OUTPUT arguments. No download, package installation, xcrun fallback or alternate compiler is attempted in the hosted lane.

The executable is placed under a fresh private native-probe-* directory with a fixed p1-owned-native-probe leaf. Before launch its canonical resolved path, full file SHA256 and Mach-O UUIDs are frozen as expectedImage. The same image is checked again after sampling. Report PID, parent, path and UUID checks remain exact, and the original parser remains the final acceptance predicate. Source hash, full fixed compile argv, compiler/SDK paths and bounded compile outcome are retained as metadata. Compiler and probe process groups use the unchanged owned lifecycle. No binary or raw compiler/sample output is uploaded; only the three existing JSON metadata files are retained. The generated file remains within the ephemeral runner workspace, with all processes settled before upload.

Local Linux C compilation/liveness verifies only standard C syntax and owned lifecycle, not macOS toolchain or sampling support. The preceding Python candidate is preserved separately; this is a new native-only experiment.
