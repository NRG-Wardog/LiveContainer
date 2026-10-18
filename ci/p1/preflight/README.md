Current focused check deterministically omits only fixture tab-item identifiers and requires the structural proof route. It validates the observer path, not the intermittent OS propagation cause. Existing default launch behavior and original UI methods remain unchanged.

# Focused native tab identity confirmation

The first full recovery run found four real, labeled native TabBar buttons,
but no p1-tab-* identifiers on the initial no-banner/default screen. The
identifier-based resolver remains intact. Only when all identifier candidates
are absent, a tagged structural alternative requires one actual native TabBar,
exactly four ordered button leaves, exact labels, empty observed identifiers,
one selection, matching live/snapshot attributes and ancestry, finite in-view
geometry and independent query counts. Duplicate, foreign, partial-ID or
unavailable controls fail closed. No observed identifier is synthesized.

This run selects only the same default/no-banner geometry context in a focused
XCTest method, with the original short 180-second method and 480-second process
limits. It retains 1020/1140/1200 observation/cleanup/outer budgets and the
35-minute job/22-minute collection step. It cannot establish full recovery,
feedback timing, tablet coverage or production readiness. The prior full run
remains failed. No production code or full-matrix method body is changed.

# Original full phone recovery restoration

The explicit --full-recovery profile runs all four original recovery matrix
methods and the unchanged full layout_exports.verify validator. It retains
600 seconds per XCTest method and 2400 seconds for the single xcodebuild
process, exactly the original full recovery lane limits. These bounds do not
guarantee completion. No methods, branches, geometry predicates, callback
receipts, screenshots, Dynamic Type states or transitions are omitted.

The separate profile permits 3000 seconds for observation/setup/export,
3120 seconds to complete owned cleanup, and an outer collector wait of 3180
seconds. The workflow collection step is 55 minutes and job 65 minutes.
The original short capability profile remains 1020/1140/1200 and 180/480.
The known fresh-owned simulator lifecycle, install 120 infrastructure limit,
15-second cleanup command limits and deletion/absence proof are unchanged.
The wrapper wait budget starts after process spawn, not a hard bound on spawn.

A pass establishes only the phone recovery matrix for this exact source and
runtime. Feedback lifetime, input overlap, calibration, tablet coverage, full
baseline matrix, production acceptance and IPA readiness remain unestablished.
Any primary or cleanup failure remains failed. Prior capability evidence remains
separate and is not substituted for any matrix case.

# P1 phone recovery route restoration

## Bounded command launch receipts

The selected phone route now retains metadata-only launch receipts for its
`process_scope.Commands` calls. Each receipt binds a numeric command identity to
its exact owned PID, process group/session and process-scope nonce. Parent
monotonic brackets cover Popen, durable registration and gate release. The
trusted gate child emits a fixed `pre-exec reached` record immediately before
its exec attempt, plus a typed positive errno only if exec fails. This milestone
is not proof that the target image started, that xcrun/simctl ran user code, or
that CoreSimulator received or handled a request. Empty command output still
cannot establish the cause of a delay; no host-load cause is claimed.

All timestamps use the same host `time.monotonic` clock. A pre-spawn Python
3.10-or-newer guard enforces its shared-epoch macOS compatibility requirement. Popen-return brackets
cover launching the Python gate, registration brackets include registry fsync,
and release-to-pre-exec includes child scheduling, Python startup and gate
handling. These intervals cannot isolate any one of those causes. Parent read
brackets bound observation separately from the child's own timestamp. No wall
clock, app clock or service clock is combined with them.

Exact child ownership is retained before any fallible parent descriptor close;
a close failure still settles that child and cannot replace an earlier primary
error. An uncertain close is never retried using a possibly reused numeric FD.
The child owns the only inherited receipt writer. It is nonblocking and
close-on-exec; the target and descendants do not inherit it. The closed-schema
binary pipe permits at most two 65-byte records and one overflow detection byte.
The parent reads at most three times per existing child-wait poll, without a
new thread, observer process, service diagnostic, command or extra wait. Records
contain only fixed markers, numeric identity/timing/errno and the fixed-format
scope nonce, never arbitrary argv, environment or raw command output.

The original command allowance is one absolute deadline covering launch,
registration and wait. Expiry during registration does not release the child;
spawn does not renew the wait allowance, and ordinary commands remain capped
by the shared scope deadline. Cleanup keeps its existing independent allowance. A receipt first observed after that
deadline is unknown even if its child timestamp looks timely. Missing, partial,
malformed, out-of-order, wrong-identity, oversized or unclosed writer evidence
is unknown, retained and failing. A final nonblocking drain and reader closure
add no wait. Unknown observation failures remain in command cleanup errors so
the existing optional-uninstall dual settlement gate cannot ignore them.
A well-formed exec-failure receipt retains its errno and ordinary failed-command
status, including the existing optional-command allowance; it never supplies a
mandatory install success. Ordinary primary errors and actual settlement failures remain separately
retained, and mandatory fixture/simulator/scope cleanup remains unchanged.

The recorder and inactive bounded diagnostic/backstop callers do not opt into
this receipt protocol; their protocol, command selection and timeout allowances
stay unchanged. Scope.spawn callers share the error-path ownership/descriptor
hardening described above; direct-child backstop callers do not use Scope.spawn. The optional-uninstall guard, app/fixture sources, native checks,
UI/geometry criteria, command list, retry count and all configured timeout and
outer-budget values remain unchanged. Portable regressions exercise real child
commands and adversarial protocol/descriptor/deadline failures; they do not
establish Darwin, simulator or fresh UI success.


The selected workflow restores the phone-only `capture.py --execute` route from
`7f5fda4a936d2cc6f73ac744d8fc8320a1954b1d`, byte-for-byte except its refreshed
approved-input seal. It runs the existing 21-case native reader regression,
exact-source extracted fixture build, installation and phone landscape-target
recovery capability. It does not select `boot_diagnostic.py`, the opt-in bounded
backstop adapter, or any diagnostic-only resource/service probes. The preserved
diagnostic implementation and its evidence remain available as historical context.

The preceding restoration added a settlement gate after each of the two optional
pre-install uninstalls. Each call now returns its existing command receipt. A
following uninstall, installation or UI step requires both an empty
`cleanup_errors` list and `settled:true` for every registered writer. Checking
both matters: registry persistence can fail after a row has been marked settled.
An ordinary nonzero uninstall, including an absent app, remains allowed when its
cleanup succeeded and all writers settled. Failure enters the same mandatory
fixture cleanup, owned-simulator shutdown when applicable, scope close and failed
result retention. Final outer quiescence still controls indexing and transport.

This adds no subprocess, retry or timeout allowance. Production/fixture source,
native checks, actual control and geometry gates, the 180-second UI method,
existing 120-second readiness checks, 17-minute internal budget, 20-minute outer
budget, 22-minute collection step and 35-minute job remain unchanged. Neither
boot-only run establishes UI success; the restored route still needs its own
fresh evidence and cannot grant full-matrix or P1 admission.

## Retained inactive boot-only diagnostic design

The preceding diagnostic-only workflow invoked `boot_diagnostic.py` instead of
the phone recovery collector. That route performs one boot attempt on the exact
precreated phone UUID `B34C2F57-B98B-4C84-96E2-3170887BA2DB` and iOS 26.2 runtime.
The UUID must be uniquely present, available and initially Shutdown. A different
or already-Booted device fails without booting or shutting it down. Ownership is
registered before the boot attempt so even a partially successful boot command
is covered by the accepted exact-UUID cleanup and outer backstop.

This is a diagnostic, not a capability or acceptance run. There is no source
checkout, native-reader compile, fixture/app build, installation, app launch,
XCTest, calibration or UI execution. Every admission/capability flag stays false.
A successful exit means only that these diagnostics completed, bootstatus returned
success within its limit, and cleanup settled. Category counts locate observations
in the attempt's time window; they do not establish the cause of slow readiness
or prove that every service message concerned the selected simulator.

## Command and time bounds

There are at most 12 diagnostic probes, each with a 10-second command allowance:
Xcode version; macOS version; exact `simctl help bootstatus`; exact runtime
metadata; before/after device state; before/after VM counters; before/after known
simulator process counters; filesystem capacity counters; and one CoreSimulator
service-log query. The separate `simctl boot` allowance is 30 seconds and the
single `simctl bootstatus <UUID> -b` readiness allowance remains **120 seconds**.
There is no boot or readiness retry. Accepted final cleanup uses at most three
15-second commands: state query, shutdown if Booted, and independent final state.
The normal collector uses at most **17 owned groups and 315 seconds of command
allowances**, plus the unchanged bounded group settlement routines. If forced
outer cleanup is needed, it can add at most three more 15-second commands, so
the collector plus forced simulator cleanup is bounded to **20 command groups
and 360 seconds of requested command allowances**, excluding the outer collector
process itself and the previously reviewed bounded membership snapshots. An already-Shutdown observation
avoids the redundant shutdown and final query. These additive allowances are not
a guarantee against OS/filesystem overhead; the existing 17-minute internal,
20-minute outer, 22-minute Actions step and 35-minute job backstops remain intact.

The original `Scope.spawn`, owned-child PID reservation, `Scope.settle`, positive
Shutdown confirmation and original-byte packaging are unchanged. `budget.py`
adds an opt-in `--boot-diagnostic` adapter: it uses the same forced-backstop
quiescence decisions and direct-child ownership, but reads output into bounded
pipes and filters it before retention. The default phone path keeps its existing
command implementation. The adapter never replaces or resets the collector
registry, and unresolved backstop observers are still checked separately from
the final simulator state. Typed primary and cleanup failures are retained with
a fixed public exception message so arbitrary exception text cannot reach the
outer budget receipt. Diagnostic children write only into bounded pipes. An unresolved
child remains registered and blocks indexing and transport even after a later
Shutdown observation. A timed-out but positively settled command may retain
stable failed diagnostic evidence; it never becomes a successful diagnostic.
The readiness receipt is saved before any later probe, and cleanup/diagnostic
errors never overwrite its typed primary error or deadline.

## Retained data allowlist

Every command has a 256 KiB combined stdout/stderr in-memory limit (one additional
byte detects overflow). Raw output is never persisted except exact public vendor
help/version text from the fixed help/version commands, with strict format and
sensitive-path/token rejection. Only those commands can retain text; unexpected
stderr elsewhere is represented only by its byte count. Help is capped at 16 KiB.
No sensitive environment, credentials, arbitrary exception arguments or inspected
process arguments are collected. Device and runtime reducers retain only the fixed UUID/runtime,
state, availability, version and build; names, paths, unrelated devices and
runtime metadata are dropped before any file write.

Resource output retains numeric VM/disk counters. The process snapshot requests
`comm`, never `args`, and retains at most 32 rows for the fixed simulator service
allowlist, reduced to service name, PID/PPID, state, CPU percentage and RSS. Paths
and all unrelated names are discarded in memory. Truncated row counts are explicit.

One unified-log query spans only this boot/readiness attempt, rounded outward to
whole seconds and capped at 180 seconds. Its fixed known-service predicate, exact
start/end arguments, byte limit and completeness/truncation flags are retained.
The `p1-service-categories-v1` reducer accepts at most 2,048 records and retains
only known service/severity plus fixed boot/readiness/launchd/failure/timeout/
connection-invalidated/other category counts. It discards event text, paths,
identifiers and arbitrary metadata. There is no broad `simctl diagnose` archive.
Malformed JSON, oversized output, record-limit breaches, command timeouts and
unresolved cleanup remain visible typed failures; none can create an observation
or silently substitute truncated data for a complete result.

## Diagnostic redaction and provenance

Both the dedicated collector and boot-only outer CLI install a presentation-only
wrapper around the accepted membership snapshot. It preserves numeric membership
identity, availability and truncation, but reduces comm paths to allowlisted
executable basenames (unknown names receive a fixed label). Nested error fields
are rebuilt from a typed allowlist. This happens before GroupOperationError emits
or Scope persists a diagnostic; it changes no signals, ownership, waits or
settlement decisions. The original function is restored in a finally block. An unexpected redaction
failure produces an explicit unavailable/truncated diagnostic, never an absence
claim, and cannot replace the original group-operation error.

Before any diagnostic command, the collector retains the exact approved input
bytes, all sealed adapter source bytes (2 MiB/file, 16 MiB total), and the workflow
bytes. It checks their seals again and records the pinned production/builder
identities, source/workflow hashes, and only strictly validated public Actions
commit/run/attempt/repository identifiers. These sources are provenance only;
the production or builder repositories are not cloned or built.

## Receipt-only phase refinement

Published boot-only run [39139697936](https://github.com/NRG-Wardog/LiveContainer/actions/runs/39139697936)
on `e7f2f00cfb7b17a60d14c227f19e93cff32b9d27` retained a successful
bootstatus command with a 106.3895-second whole-command bracket and unchanged
120-second allowance. Later state/resource/service-log probes timed out. All 15
registered groups settled and exact Shutdown was independently established. This
is diagnostic context, not app/UI evidence or an established cause of the delays.

The successor changes receipts only. `phase_timing` adds fixed-size host
`time.monotonic` brackets around the spawn, wait and settle calls, plus the first
nonempty read and EOF read on each pipe. Missing observations remain null; a
raised call retains its before/after bracket with `returned:false`. A fixed phase
label locates the primary failure separately from cleanup errors. These readings
use the original command deadline; neither spawn nor any new marker resets it.
No new command, retry, timeout allowance, process-control action or raw-data
retention is introduced.

For the ordinary Scope, spawn return establishes only that registration completed
and the launch-gate release was issued. It does **not** observe the child consuming
the release, target exec, target startup or simulator readiness. The forced
backstop directly owns its child and likewise has no target-exec receipt. First
bytes/EOF are parent read observations, not child write/exit timestamps. The wait
and settle brackets include their existing implementation work. They locate
host-observed delays without attributing a cause.

The published help command exited zero with empty stdout and 442 stderr bytes,
but its exact ValueError receipt did not identify the failed guard. Code and
retained byte counts establish that stderr was selected and exclude the 16 KiB
size guard and UnicodeDecodeError; rejected text was intentionally not retained.
They cannot distinguish missing command marker, prefix mismatch, control
character or sensitive-pattern rejection. No defect in the accepted help text
set is established, so the successor preserves every predicate, its order and
exception type. It adds only fixed reason codes (`invalid-utf8`, `size-limit`,
`missing-command-marker`, `prefix-mismatch`, `control-character`, or
`sensitive-pattern`) plus selected stream and accepted/rejected/not-run status.
Unrecognized parser failures receive a fixed unclassified code; arbitrary
exception attributes and rejected text never enter the receipt or console.

## Diagnostic restoration history

The phone collector and fixture/UI files were unchanged during the boot-only
revisions. The current restoration above selects the original phone invocation
with a fresh seal and only the optional-uninstall settlement gate. Boot-only
results cannot supply missing phone recovery evidence or retroactively validate
either failed phone run.

---

# P1 phone recovery capability successor

This successor runs only the phone landscape-target recovery capability. It
retains the exact 21-case native reader regression, extracted fixture build,
strict raw recovery verifier, process cleanup and bounded original-byte packaging.
It does not run screenshot calibration, tablet UI, the full matrix, or an actual
application-host build. The CLI and sealed input scope reject tablet routing.

The result schema is `p1-phone-recovery-collection-v1` and its scope is
`phone-recovery-capability-only`. `capabilities_passed` describes only this one
selected recovery capability. Explicit calibration/tablet-executed and feedback/
input-proof flags remain false; every admission flag remains false. Cleanup or
source-verification failure still clears the collection/capability result.

Prior evidence remains immutable in [run 39118482058](https://github.com/NRG-Wardog/LiveContainer/actions/runs/39118482058)
on commit `3c4c92b87e29132056e94f3f3f9b838c92ab627f`: native reader 21/21
passed in both jobs; tablet nested-tab and no-banner rotation methods passed.
Phone Resume became fully visible and its ordinary tap fired the synthetic
callback, but subsequent fixture-receipt observation exhausted the 180-second
method limit. Both calibration capabilities failed fixed limits. Phone video
phase widths were 173.094/167.837/191.614 ms; tablet app pre-clock width was
57.606 ms. Tablet post-2 marker 1554 had no matching video frame, so it has no
valid nine-marker video mapping. Those prior findings are context only and
cannot contribute a fresh pass to this successor.

All source/dependency pins, the 180-second method allowance, bootstatus 120-second
limit, 17/20/35-minute collection/outer/job budgets and cleanup criteria stay
unchanged. Calibration code and its strict 20/120 ms gates remain preserved but
are not invoked. A later mapping strategy needs separate review and genuine
capability evidence before feedback timing can be admitted.

## Synthetic Details ordering correction

[Phone-only run 39120745869](https://github.com/NRG-Wardog/LiveContainer/actions/runs/39120745869)
on `fe05598803a342742b7125d0ad0d341d8d253e2e` verified the fresh
`resume-operation:1` callback after the visible ordinary Resume tap. The method
still failed its unchanged 180-second allowance later while scrolling to the
synthetic Next Recovery control. Its complete failed evidence remains retained.

This successor moves only the synthetic callback receipt and Next Recovery row
to the beginning of the Details List. The controls, actions, identifiers, List
container and styles are unchanged, and reversing that prefix reproduces the
exact historical fixture hash. Actual recovery controls and the Next Recovery
tap still require the same visible 44-point slice, ordinary physical input and
strict transition receipts. No elapsed-time, geometry or input criterion changes;
the phone-only runtime result must establish whether this setup correction works.
After the actual Open tap, destination readiness now observes the Details bar,
unique fixture List and usable Back control instead of waiting for an offscreen
lazy Text row. The same five-second bar wait and fresh foreground/session/window/
orientation/tab/kind/size checks bind readiness to the current navigation action.
Later branch/size observations, return navigation and real input gates remain.

## Preserved two-device calibration design (not executed here)

The preceding checkpoint restored the two short phone/tablet capability jobs after
the isolated cleanup regressions passed. It does not run the full matrix or
rebuild the actual application host. The extracted synthetic fixture is built
for these capability checks.

## Capability design

The preserved calibration design used **independent phone and tablet jobs**, each building the
exact-source extracted fixture and then collecting one screenshot-calibration
case plus narrowly scoped recovery capabilities. It does not run the full
feedback interaction or recovery matrix and cannot grant P1 admission. The
actual unsigned host at `bd5d9d87af76bfce0553d358bb3c6d45cbbc806a` was already
compiled in authenticated run 39052520386. No redundant host build is requested.

The previous run proved that the old simctl process-wide screenshot interval
was 2.4–4.2 seconds, wider than the fixed 120 ms bound. It also exposed early
runner teardown before the strip's completion journal. This experiment asks
whether a **public XCTest screenshot acquisition-only bracket** is usable. It
makes no assumption that the new route will meet the limits.

## Clock and evidence protocol

- A fresh random 128-bit session binds the app launch, runner environment,
  runner/app channels, every request, response, pixel receipt and completion.
  Only the actual built and allowlisted fixture/runner bundle IDs are used for
  supported `simctl get_app_container` discovery. No private XCTest selectors.
- The runner observes the actual identified production Copy Details button,
  takes a baseline screenshot, and physically taps a separate fixture
  `Baseline ready` button before the host begins pre-calibration.
- Each of pre/mid/post has eight app↔host and eight runner↔host causal exchanges,
  and three independent runner screenshots. The two SystemUptime domains are
  never assumed equivalent. The app accepts exactly 29 ordered requests; the
  runner exactly 35, including after-screenshot and host verification ack.
- Acquisition brackets contain only `app.screenshot()`. PNG encoding, XCTest
  attachment and background durable file write brackets are separately retained.
  Immutable runner request/response rows are fsync-backed before publication.
  Partial failures retain both channels once the worker has settled.
- Screenshot PNGs must match their exact XCTest method/device attachments.
  Actual Copy Details pixels and clock-strip IDs are decoded offline. Every
  plausible video interval matching an ID is unioned by its min/max hull.
  Independent observations can be intersected, alternative matches cannot.
- The original entire video and all finite ordered PTS are retained. The fixed
  evidence window starts at the real baseline-ready event and ends after
  post-calibration's finish command, including every potentially overlapping
  boundary frame. No interior gap can be trimmed to improve the result.
- App/runner clock widths remain ≤20 ms. Video and combined app/video mapping
  widths and every evidence-window gap remain ≤120 ms. Strip draw/tick costs
  remain ≤5 ms each and ≤10% measured CPU fraction. Draw brackets cross-check
  causality; they are **not** compositor presentation timestamps.
- XCTest waits until the host verifies the retained strip-complete journal and
  sends its exact SHA256 acknowledgement. A green XCTest alone cannot prove
  mapping feasibility, and calibration feasibility cannot prove feedback
  lifetime, input overlap or UI admission. Those later interaction tests retain
  actual `0.75 ≤ spacing < 2` and ordinary third-tap requirements unchanged.

All timing is conditional on continuous stable-unit-rate clocks and matching
rendered pixels. Acquisition brackets do not independently bound compositor
freshness or arbitrary nonlinear drift. This preflight does not exercise
clipboard notifications or infer any production timer-start/lifetime fact.

## Recovery scope and budgets

Phone runs the landscape-target capability. Tablet runs nested-tab selection
and no-banner rotation capabilities. All full-matrix requirements remain in
the separate full verifier; capability reports set `full_matrix_complete:false`.
The fixture's phone and iPad supported-orientation arrays are explicit; actual
scene orientation and viewport dimensions must still prove a successful turn.

Every recorder and command session is gated before exec until its identity is
retained in a fresh process registry. A 17-minute internal deadline bounds all
command waits. Explicit fixture termination and tracked session cleanup precede
partial-copy finalization. A 20-minute outer backstop independently verifies
remaining registered writer groups by read-only absence checks. Only actual
unreaped direct children authorize group signals. Evidence is indexed and
packaged only after a positive quiescence receipt; an unsafe timeout fails closed. Each 35-minute device job reserves the remaining time for
byte-preserving packaging/uploads, subject to checkout and runner overhead;
this is a budget, not a guarantee. Packaging always preserves the original
collection outcome, all partial files and hashes in ≤256 MiB separately uploaded
parts. It cannot convert a failed capability into success. No credentials or
account data are captured; all UI data are the reviewed synthetic fixtures.

The prior full workflow and inputs remain in immutable commit `b45fabeb`; a
future full run needs a separately reviewed successor and current seals. This
workflow does not activate those older inputs after recovery harness changes.


## Failure diagnostics when payload transport is unsafe

Command receipts retain the primary spawn/wait/exit exception separately from
cleanup exceptions. A cleanup EPERM never means that a group disappeared and
never replaces the original command failure. Termination classification also
rejects any unresolved command cleanup failure. Setup timeouts and the retained capability lane's 17/20/35-minute budgets remain
unchanged. The completed cleanup-only job had its own ten-minute ceiling.

On a failed process-group operation, a bounded read-only process-table snapshot
records only PID, PPID, PGID, UID, state and command name (not arguments or
environment). The snapshot uses a one-second collection bound plus a one-second cleanup
bound, 256 KiB and 32 matching rows. Cleanup attempts to kill/wait its direct
read-only child within the extra bound; failed cleanup remains unknown.
No privileged termination or permission changes are attempted.

P1_CAPABILITY_DIAGNOSTIC lines preserve safe typed command/phase failures and the
outer quiescence rejection in the ordinary Actions job log before the packaging
gate. Each JSON payload is at most 32 KiB. Arbitrary exception arguments are excluded;
only fixed harness gate reasons are printed verbatim. Phase-summary booleans are
explicitly unverified diagnostics, not raw XCTest evidence or admission receipts.
They do not permit indexing or archiving a potentially growing evidence tree.


## Verified cleanup repair retained by this restoration

The previous unpublished candidate was lost with its workspace and payload store.
The replacement was freshly implemented on published e72fd12d and reviewed as
tree e890f1e4, then published in f3de1b32. It does not reuse the prior c6f519d1
identity or claim that earlier test runs validated the replacement bytes.

Cleanup run [39108278899](https://github.com/NRG-Wardog/LiveContainer/actions/runs/39108278899)
passed all 83 exact reviewed regressions with zero skips on macOS 26.6.2 arm64.
Artifact 12129362082 has ZIP SHA256
`ca8a9debd0211f1b1e6826addc20fc45777da11c3af606500358322122109296`.
That run exercised synthetic child processes and mocked simulator-state receipts
only. It did not establish actual simulator shutdown, UI, or calibration success.
The earlier successor restored the two-device workflow from immutable e72fd12d
with a new seal. This phone-only successor retains that proven cleanup implementation.

OwnedProcess holds the actual start_new_session=True Popen child and serializes
all waits, polls and signals with a per-child lock. It reaps exited direct children
before probing their group. Only an unreaped child can reserve the PID needed to
authorize a signal. After reap, the old numeric PGID is read-only: surviving
children, reuse, and unknown EPERM all block transport. The outer backstop never
signals bare registry PGIDs. No privileged termination or permission changes occur.

An exact exclusively owned UUID query can independently prove Shutdown. Runtime
groups are flattened; duplicate/missing IDs, malformed or unsettled query receipts
fail. Already-Shutdown observations avoid redundant shutdown commands. Nonzero
shutdown remains a collection failure even if a later clean query proves Shutdown.
No exit-149 exception exists. Every host observer must also settle: a later state
query cannot erase an earlier observer's cleanup failure. Original timeouts and
cleanup errors remain distinct, and unresolved writers forbid indexing/packaging.

The accepted cleanup artifact contains the terminal regression result and log, excluding
any temporary writer payload. Passing establishes only these cleanup regressions,
not simulator, feedback, layout or product readiness. Existing setup deadlines and
all timing/layout criteria are unchanged.

Owned child spawning and signaling require the default SIGCHLD disposition. Ignored or custom handlers fail closed. This dedicated process does not install such handlers or use external child reapers; its owned-child lock serializes every retained Popen wait and signal.

## Bounded request-reader and small-drag correction

Run 39109242914 retained a generic request-file failure after request 21 while
request 22 was the current pathname. Atomic host replacement can unlink the old
inode while the runner still has it open, but the old receipt did not record
which stat predicate failed. This correction does not claim that race was the
proven native cause. Open/fstat/read/close failures now retain typed errno,
phase, mode/type, link count, size and inode/device observations.

Only a successfully inspected regular descriptor of valid bounded size with
zero links is discarded. Its bytes are never parsed or acknowledged, even when
unlinking is seen after reading. Each descriptor closes before return; a close
error is fatal and preserves any primary error. The next existing poll may open
the current pathname. At most 64 discarded observations are journaled; there is
no internal retry loop or new deadline. Hardlinks, symlinks, nonregular/empty/
oversized files and syscall failures still fail closed.

Before any source acquisition or simulator work, each short job compiles the
exact marked Swift reader block and runs 21 deterministic macOS filesystem
regressions. The generated source, block/test hashes, command logs and exact
case report are retained. The compile-time race hook is excluded from the
actual XCTest build. Compile/run limits are 60/10 seconds (toolchain query 10),
charged to the existing 17-minute internal budget. A failed native gate blocks
UI execution and remains a failed packaged collection.

Phone recovery evidence showed that 10-point drags made no measured scroll
progress with Resume still only 38 points visible. The corrected heuristic uses
a 24-point floor before the unchanged safe geometry caps. The 44-point visible
control requirement, measured progress/stall checks, ordinary tap and callback
proof remain mandatory. This source change does not establish reachability.
Bootstatus 120 seconds, all other budgets, 120 ms mapping limits and the full
matrix's future acceptance requirements remain unchanged.

## Same-runtime stall decision diagnostic
This successor runs no app build, install or UI. It uses one initially Shutdown
iOS26.2 fixed phone, two trivial minimal/full Python gate probes before and after
boot, and a prestarted bounded numeric sampler. Receipt failure is diagnostic;
owned process settlement is independently required. Budgets are 360s observations,
480s absolute collector cleanup deadline, and a 600s existing outer watchdog,
leaving 120s collector cleanup and 120s outer headroom. Existing command limits
remain 10s probes, 30s boot, 120s bootstatus, 15s exact-device cleanup commands.
The outer group backstop and packaging quiescence gate are retained. No retries.
First Python timestamp excludes interpreter loading and import time itself.
Missing timing evidence remains inconclusive; collection complete is not a
capability pass or successful readiness claim. Both gate files are source sealed.

The 600s outer limit is the existing owned collector wait deadline after spawn;
it is not a hard wall-clock guarantee around an OS-level blocked Popen itself.
The Actions 12-minute collection step is the enclosing platform backstop.
Probe receipts retain phase, mode, command ID and probes/commands.jsonl path;
boot/cleanup commands use their separate commands/ namespace.
The comparison requires image20261013.0424.1, Xcode26.4.1 build17E202 and
iOS26.2 build23C54. Image/runtime drift fails before claiming the simulator.

The next confirmation routes process_scope child entry through launch_gate.py
before parent-only imports. The generic child_main AST is identical, preserving
argument arrays, private gate, exact receipt and exec-error semantics. The full
label now means the process_scope entry with lean bootstrap, recorded explicitly
in stall-result.json. No runtime or command deadline changes.
A timed-out initial cleanup state query can proceed to exact-owned shutdown only
if writer_settled is explicitly true; unknown/malformed-state failures cannot.
The original timeout and command_failed remain, even after fresh Shutdown proof.

Fresh-device isolation: this diagnostic creates one uniquely named iPhone on the exact original iOS 26.2 runtime after deriving and verifying the original device type from current inventories. The original device is never booted, shut down or deleted. Creation intent and exact new UUID ownership precede boot; deletion and fresh absence are mandatory before evidence transport. Unknown creation outcomes fail closed. Budgets remain observation 360 s, cleanup deadline 480 s and outer wait 600 s; creation consumes the observation budget. This is a single ordered host comparison, not product acceptance or proof of device corruption.

Phone UI restoration uses the verified fresh-owned same-runtime route, preserving the original phone recovery method, source pins, assertions and deadlines. The first successful fresh sample is operational evidence only; host variation prevents a claim that the precreated device was corrupted. Created simulator deletion and fresh absence remain required by collector and outer packaging gates.

Phone UI retains the 1020-second observation deadline and adds an explicit cleanup cutoff at 1140 seconds, inside the original 1200-second outer wait. Individual cleanup commands remain capped at 15 seconds.

Pre-install removal is skipped only once for an exactly owned newly created simulator with no previous installation attempt and settled writers. The first install attempt is persisted before install; failed or interrupted attempts cannot reuse the exemption. Install remains limited to 30 seconds. Existing-device preparation keeps its original uninstall/settlement checks.

### One bounded install-completion observation

`--install-completion-diagnostic` stops before UI execution. It observes one installation for up to 120 seconds, within the unchanged 1020-second observation / 1140-second cleanup / 1200-second outer budgets. The original 30-second threshold remains explicit and its exceedance keeps the run failed even if installation later completes. This 120-second cap is a conservative observation envelope, not an empirically established completion bound. No retry is made at 30 seconds. Wait timestamps distinguish command completion/timeout from later host-writer settlement; neither asserts a service-side completion timestamp. Owned-created deletion and all cleanup failure retention remain mandatory. A timeout at 120 seconds ends this experiment rather than authorizing another increase.

### Restored phone UI infrastructure policy

Run39155245816 observed this pinned P1 fixture install complete in58.74 seconds, with clean launch receipt and settled writer. The current phone route therefore uses a120-second installation infrastructure allowance. Historical30-second exceedance remains a recorded metric; that earlier diagnostic remains failed. UI test/assertion/time allowances are unchanged.

For a current-session, exclusively owned-created simulator, fixture stopping now issues exact-UUID shutdown first, then verifies fresh Shutdown. This avoids two unnecessary app-terminate calls and a pre-shutdown query on a simulator whose ownership is already persisted. The shutdown and state-query limits remain15 seconds, within the same cleanup reserve. Repeated finalization can reuse an already-proven stopped flag only after validating ownership and settled writers; deletion still requires its own fresh state/absence proof. Preexisting devices use the prior route. Actual shutdown/query failures remain latched even if later recovery proves safety.

### Same-observation query reuse

The phone method in run39156182775 reached real UI and passed initial/post-Resume geometry, then exceeded its original180-second allowance. Query reuse captures frames once inside each geometry call or target-search attempt and uses one freshly validated tab snapshot for each final attachment. No observations survive a tap, drag, rotation, or new attempt. The original method sequence, geometry predicates, tab uniqueness/leaf-chain validation, live hittability checks, two causal metrics getter calls, search bounds, screenshot evidence, and UI deadlines remain unchanged.
