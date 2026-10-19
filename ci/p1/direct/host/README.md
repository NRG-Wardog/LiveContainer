# Direct-feedback host integration primitives

Local, tested primitives only. No native run, source publication, or timing admission.

`protocol_driver.py` preserves the original 29 requests and event order. Its
24 in-process Mach observations add no app commands. Each stage checks the
integrating collector's owned capture/process health and shared remaining
budget. Every failed response is retained; no request is retried. Completion
means only protocol completion, never timing or UI acceptance.

`fixture_channel.py` holds a descriptor for the exact caller-verified fresh app
scenario directory. Reads reject symlinks, FIFOs, hard links, oversized files,
replacement during reads, duplicate JSON keys, and root replacement. Atomic
request publication and response waits stay within the original five seconds
and the remaining shared budget. Raw request/response bytes and host brackets
are retained, including failures. Retention failures latch the channel closed.
The unchanged fixture responses have no nonce. The integrating caller must
prove the fresh container, source, session-bearing anchor journal, and directory
identity; a pathname is not an ownership proof.

Still required before execution:
- Authenticated app/runner container discovery after the retained XCTest-start hint.
- All eight source draw receipts, baseline/first-frame actual pixel geometry,
  registered process and immutable window proof before pre-baseline host ack.
- Absolute one-case budget and capture/error/owner checkpoints.
- Complete native method result and the original strip-complete journal before
  stopping the stream. A finish response alone cannot prove the final visible
  coverage boundary; post-export coverage must reject a missing tail.
- Descriptor-bound immutable event inventory with exact sequences and errors.
- Clock/protocol/pixel/geometry/cost/coverage validation and inclusive packaging.
- Exact owned helper/GUI and simulator cleanup with all failures retained.

## Local case sequencer

`native_case.py` owns one `testProbeTimeoutPixels` case's order, not its native
implementation. `Case(session, backend).run()` requires every named backend
operation and every validation/retention hook. There is no default backend, CLI,
process launcher, fabricated proof, or admission path. Its dependency contract
is documented on `Case` and `Evidence`; `native_runtime.py` must separately
implement and prove those adapters before execution is possible.

The sequencer supplies the exact one-method XCTest arguments (240-second method
and maximum 360-second command), source-guards the maintained bounded startup
hint reader while changing only its class/method globals, and performs exactly
one at-most-30-second lookup per app/runner role after that hint. The hint alone
never establishes session/container ownership. Actual runner geometry,
provisional raster registration, same-frame complete-stream promotion, and a
fully validated ownership/byte proof must precede acknowledgement. The native
adapter must launch with the remaining absolute command budget, rather than
resetting a fresh 360 seconds after delayed preparation.

The original `protocol_driver.Driver` runs all 29 requests. Its injected
checkpoint and its FixtureChannel/Journal remaining functions must use the
case's common observation budget. Both native result and original strip-complete
proofs must precede stream stop. `validate_collection` checks the terminal native
collection; full offline feedback/clock/coverage acceptance remains separate.

Every failure, including setup, evidence persistence, and earlier cleanup errors,
attempts all cleanup hooks in this order: native writer settlement, helper
settlement, owned GUI settlement, exact fixture stop, exact-created-device
cleanup, and final quiescence verification. This respects `fresh_device.stop_owned`
and `fresh_device.cleanup`'s all-host-writers-settled precondition. Cleanup uses
only the existing Scope cleanup reserve if the command budget has expired;
it never renews XCTest or capture execution. Aggregate cleanup maxima account
for existing inner operations: 15/15/25/45/75/10 seconds, still capped by Scope.
A failed cleanup or receipt never yields sequence completion.

`test_native_case.py` uses an explicitly synthetic backend. It tests every main
stage failure, each cleanup failure, failed persistence, expired budgets,
original command shape/order, immutable exact startup-marker identity, source
drift, single use, and required shared Driver checkpoints. Those tests establish
Python sequencing behavior only, not native ownership or performance.
