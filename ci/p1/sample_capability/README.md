# Owned-child sample capability diagnostic

Local-only proposal on validation/p1-sample-capability, based on published commit 09d75d765a6c63b27fccae3529c8b224100278b3. No publication or run is authorized by this document. Independent review is required before publication.

Original run 39349300984 proves a benign child launch, one sampler exit 0 and settled/reaped cleanup, but not report compatibility. Its broad ValueError catch and discarded invalid report do not identify the rejection. Python launcher/framework image mismatch remains a hypothesis.

This entry verifies a sealed runtime closure (including the two launch gates) and diagnostic source, then invokes exactly one one-second /usr/bin/sample against one benign Python child. Existing helper_sample._launch/_run, process_scope, launch_gate and minimal_gate bytes are unchanged. No helper, app build, simulator, XCTest, UI capture, source dependency resolution, sudo, new permission or fallback sampler is invoked. No tests execute in the hosted diagnostic lane. The synthetic suite runs locally before review.

Fixed stages cover environment, installed tool, expected-image proof, child launch, pre/post sample liveness, sampler command/launch receipt, bounded report, UTF-8, each required header, PID, path, parent, format and UUID. Rejection codes are fixed literals, not exception messages or report values. Safe expected resolved path, file SHA256 and Mach-O UUIDs, expected PID/parent, sampler exit code and Boolean comparison outcomes are retained. Identity matching stays exact; the original parser also validates every accepted report. Neither valid nor invalid synthetic raw reports are saved, printed, interpreted or used for admission. A path rejection does not infer a framework image or inspect its stacks. Checks after the first failed original predicate are deliberately unevaluated.

The existing 8-second preflight deadline, 4-second sampler command bound, 512 KiB output cap, same-UID/non-root GitHub-hosted restriction and supervised owned cleanup are preserved. Scope uses the already-supported 60-second capability budget profile; no fixture is created. The workflow adds a three-minute outer job and one-minute diagnostic step limit. Non-availability exits 2 and retains metadata, rather than appearing as capability success. Quiescence remains a separate mandatory cleanup receipt.

## Separate automatic-workflow exclusion

The only modification to an existing file is .github/workflows/build.yml: add this exact validation branch to its push branches-ignore list. This is required because the published ordinary build workflow otherwise triggers on the new branch. Existing P0 and full P1 workflows are byte-identical, with exact other-branch push filters. update_source.yml has only release/manual triggers. This proposal neither creates a PR nor a tag, release or manual dispatch. A later PR would independently trigger the ordinary pull_request build and is out of scope.

## Review and result interpretation

closure.json hashes every executable/imported repository file used by this lane; its digest is pinned in the workflow. The external review seal records the complete proposed Git tree and payload bytes. The full-capture helper_sample, process_scope, gates, entry, input seal and P1 workflow remain unchanged in the parent tree.

A future diagnostic would establish only its own exact rejection stage or compatible benign report under that hosted runner. It cannot retroactively prove the original run's precise cause, and cannot establish ownerValid timing, scheduler/pressure claims, capture success or P1 admission.
