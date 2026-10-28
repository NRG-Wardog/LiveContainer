# Bounded host guest-launch diagnostics

The current process keeps only the last launch's fixed phase tokens, at most16 entries. No app name, bundle/container identifier, PID, path, provider message, account data or internal generation is exported or persisted. A new admitted multitask attempt resets this snapshot before signing. Late results from older attempts cannot overwrite it.

`callback_completed` means a launch callback returned a positive PID, not that the guest is visible, usable or JIT-ready. Native-window requests have outer request/completion phases only. Recognized local error codes classify missing lookup, host attachment and early exit; other failures remain generic.

`V3LogsView` appends the snapshot to existing startup diagnostics before checking service readiness, so the existing Copy Logs path can include it without starting or contacting the service. The snapshot resets when the host process exits.

Run `python3 -B tests/run_guest_launch_diagnostics.py --require-native --output <fresh-output>` on macOS. This compiles/executes exact Objective-C storage/methods and completion classification, then exact Swift reload/copy policy linked to those methods with a synthetic service. It also typechecks the actual new Objective-C method declarations and Swift call forms against the iOS15 deployment target. Unrelated header imports are omitted explicitly, not replaced with guessed signatures. This is not a UIKit alert/rendering or physical guest-launch test.
