# One optional owned-helper sampling experiment

Local-only candidate, based on 64132a61e7f12f2fe3be13bb8ccb85e50006dd37.
Execution is restricted to this isolated GitHub Actions CI account/workload:
GITHUB_ACTIONS=true, NRG-Wardog/LiveContainer, macOS runner, numeric run ID and
RUNNER_ENVIRONMENT=github-hosted and non-root equal real/effective UID are required.
Missing or self-hosted runner environments reject before any diagnostic child launch. It is not approved for a user
desktop, arbitrary PID, shared-user workload or third-party process. Environment
markers are routing constraints, not authentication of an untrusted caller.

No macOS command, remote workflow or privilege change has been executed during
Linux development. An independent review must precede publication or execution.

## Purpose and single stopping condition

The original first-overflow snapshot has writer 3 between writerOwnerBegin and
writerOwnerEnd, before region hashing or writing, with writer 4 queued. This
experiment asks which stacks recur in that owner's synchronous check. It does
not replace ownerValid or identify App Nap, scheduler contention, paging or I/O
from wall/CPU ratios. One sample attempt only; no retry after any failure.

## Capability and resource bounds

Before case preparation, use the existing Scope to launch a benign same-user
Python child, then try the installed /usr/bin/sample on that exact owned child
for one second at 10 ms. Both header and binary-image UUID/path identity must
validate. Missing tool, non-Darwin, unsupported syntax/report, explicit permission
denial, generic failure, time limit and output limit have distinct statuses.
Unsupported/denied capability means no helper sampling, never a privilege prompt,
sudo, fallback attachment tool, installation or permission/security change.

The proposed command syntax is validated by this actual Mac preflight, not
assumed available from Linux: sample PID DURATION 10 -file /dev/stdout.
Python launcher/framework layouts may make resolved sys.executable differ from
the sampled main executable path/UUID. That Mac runtime uncertainty is unproven
locally; a mismatch fails closed as unsupported. No returned path is adopted to
make the capability test pass. Combined
stdout/stderr is drained through a pipe into at most 512 KiB + one overflow byte;
no raw report is written to disk before identity validation. Output overflow
cancels the owned sampler. The synthetic report is discarded. Mach-O parsing
and file hashing are bounded at 128 MiB per image and reject unknown layouts.

Immediately before publish_roi, start ONE asynchronous five-second/10-ms sample
of the exact retained helper. The sampler's total launch/collection deadline is
at most eight seconds, additionally limited by the existing observation and Scope
deadlines. Scope's unchanged TERM/KILL/reap/disappearance cleanup remains the
only settlement path. Its existing cleanup can add up to 12 seconds and may
fail; this is not represented as an eight-second hard wall-clock guarantee.
Host scheduling can overrun any measured interval. Retain observed brackets.

Sample is intrusive statistical observation: approximately 500 requested sample
instants, possible thread suspensions, symbolication and CPU/I/O overhead. No
claim bounds its CPU overhead. Parent cleanup requests cancellation, attempts a
bounded join inside its unchanged cleanup deadline, and still attempts original
helper cleanup on failure. Unjoined diagnostic workers prevent an all-writers-
settled claim; the outer Scope/watchdog remains authoritative for descendants.
No per-frame diagnostic writes or additional Swift endpoint telemetry are added.
No global CPU/VM/I/O tooling is included because its installed syntax/capability
has not been verified. All capture limits, queues, deadlines and predicates,
process_scope.py and launch gates remain unchanged. Sample status never grants
capture success, conditional timing validity or admission.

## Ownership and residual limitation

No process is rediscovered by numeric PID. Before sampling, require the exact
registered OwnedProcess object, original Scope session, successful exec receipt,
unsettled registry row, exact helper argv/capture session, compiled image path
and SHA-256. The same retained object's poll must still return None after the
sampler is settled, and its image SHA/UUID identity must remain unchanged.
Popen caches a reaped exit: a replacement process with the same numeric PID
cannot make that original object live again. Reports from any exited or unknown
window are discarded without stack interpretation or raw-file retention.

For a usable report, require a unique Process/PID header, exact executable Path,
exact collector parent PID and matching executable LC_UUID in Binary Images.
Absent/duplicate/mismatched fields fail closed. Launch time is not inferred from
unrelated wall/monotonic clocks. There is no atomic task-port attachment proof:
the helper can exit between precheck and sample attach, so the tool may briefly
inspect a recycled PID. Post-liveness and strict report checks prevent accepting
that output, not the initial race. Independent review must explicitly accept
this best-effort diagnostic boundary or reject the experiment. Do not silently
add a reaping lease, task-port grant or broader process inspection to fix it.

## Interpretation

A validated report can identify recurring ownerValid/AppKit/path-resolution/wait
stacks during its aggregate collection window. It is not a complete timeline,
not exact off-CPU duration, and not proof of runnable-versus-blocked scheduler
state. Correlate its measured host interval with existing milestones; do not
assign an aggregate stack to a specific callback without evidence. No stall in
this one interval means inconclusive, not fixed. Apple documents sample's
statistical limitations and Thread State Trace's stronger syscall/state evidence:
https://developer.apple.com/library/archive/documentation/Performance/Conceptual/CodeSpeed/Articles/DiagnosingSlowness.html
https://developer.apple.com/videos/play/wwdc2023/10248/
