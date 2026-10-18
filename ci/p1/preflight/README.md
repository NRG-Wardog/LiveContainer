# P1 boot-only readiness diagnostic

The selected workflow temporarily invokes `boot_diagnostic.py` instead of the
preserved phone recovery collector. It performs one boot attempt on the exact
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

## Restoration

The original phone `capture.execute` path and its fixture/UI files are unchanged.
To restore that lane, review a successor workflow selecting the existing
`capture.py --execute --work ... --device-class phone` invocation and refresh the
input/workflow seal as usual. This boot-only result cannot supply missing phone
recovery evidence or retroactively validate either failed run.

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
