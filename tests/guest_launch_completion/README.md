# Guest launch completion boundary

`python3 tests/run_guest_launch_completion.py --require-native --output /absolute/output`

On macOS this extracts the current production Objective-C extension lookup method,
request interruption/cancellation/completion blocks, and virtual-window terminal
completion method. Foundation executes them with an injected extension lookup and
small delegate/cleanup adapters. Two counterfactual copies must fail their intended
assertions: removing the nil-extension guard and making interruption synchronous.
The runner records hashes for all production inputs, itself, and the fixture.

Covered: nil extension with and without NSError, a returned extension with NSError,
successful lookup, main-queue wiring order, duplicate terminal signals, cancellation
before identifier delivery, reason preservation, late completion after cleanup, and
no late registration/presentation in that sequence.

The model's existing defer and banner error catch are bound by source contracts.
The fixture's `running` field is an adapter, not the real LCAppModel. UIKit containment,
visible alerts, real extension launch, process liveness and the native Swift scene
registry are not executed by this test. Those require separate qualification/device
observation. Linux output is explicitly STATIC_PASS_NATIVE_NOT_RUN and cannot
satisfy `--require-native`.
