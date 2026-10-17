# Short P1 capability preflight

This successor runs **independent phone and tablet jobs**, each building the
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
(or terminates) remaining registered writer groups. Evidence is indexed and
packaged only after a positive quiescence receipt; an unsafe timeout fails closed. Each 35-minute device job reserves the remaining time for
byte-preserving packaging/uploads, subject to checkout and runner overhead;
this is a budget, not a guarantee. Packaging always preserves the original
collection outcome, all partial files and hashes in ≤256 MiB separately uploaded
parts. It cannot convert a failed capability into success. No credentials or
account data are captured; all UI data are the reviewed synthetic fixtures.

The prior full workflow and inputs remain in immutable commit `b45fabeb`; a
future full run needs a separately reviewed successor and current seals. This
workflow does not activate those older inputs after recovery harness changes.
