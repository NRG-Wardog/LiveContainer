# C++ allocation successor capture

This is an additive, isolated capture lane for the reviewed AnisetteKit C++
allocation correction at `161435bcc0344e1a9853669455c1ca8d9dda2bf1`, tree
`0df50020ddd774a5b7ab941944501f1ecd591a4a`. It is not a builder-admission bypass or
a reproduction build. Historical `ci/p0init`, `ci/p0bounds`, their workflows and
receipts remain unchanged. The generic upstream build explicitly ignores both
`validation/p0-cxx-allocation` and `validation/p0-cxx-allocation-linux`.

The inventory baseline is the prior bounds owner graph: AnisetteKit `9c876820`,
SideSign `74a79cc4`, and SideStore `6e9f367d`; other maintained owners stay fixed.
The source basis is `p0-cxx-allocation-v1`. Both workflows and their proposed
input hashes require independent review before publication or triggering.

## Independent Linux allocation-helper capture

`.github/workflows/p0-cxx-allocation-linux.yml` runs only on the dedicated Linux
branch, on Ubuntu 24.04. Its input graph contains only the exact AnisetteKit
owner. `allocation_gate.py` reuses the normal lane's source validation,
read-only acquisition and owned-process-group settlement. It validates that a
network namespace denies network access before running the host-only driver.

The exact normal app Unicorn archive is checksum-verified, but only header
bytes are extracted. No engine library or proprietary payload is linked or
executed. The existing Linux driver compiles the production allocator and the
hook/procedure harness with finite host doubles: allocator 32 plus hook 51
checks in each of normal, optimized, and ASan+UBSan variants. LeakSanitizer is
explicitly disabled. All 12 source-dependency hashes and exact compiler/linker
argv are verified; source and header bytes must remain unchanged.

The artifact contains `allocation-units/{normal,optimized,sanitized}.json`,
their `-hooks.json` counterparts, and `allocation-units/result.json`. The latter
is copied byte-for-byte to `provenance/allocation-helper.json`. Approved inputs,
source-before/source-after, raw logs/exit codes/group settlement, tool versions,
header origin/checksum, and the authenticated current GitHub run fields are
retained in the indexed artifact. A later finalizer binds the authentic GitHub
artifact ID/digest into `allocation-helper-run.json`; this workflow cannot
invent that post-upload identity. Linux results cannot replace macOS resolution
or build evidence.

## Phase one: genuine SideSign dependency resolution

The sealed inputs bind the exact AnisetteKit source/tree and the package-only
SideSign successor. The old Package.resolved is preserved as the actual `before`
file. SwiftPM performs genuine resolution. The `after` bytes are captured directly,
then frozen resolution must reproduce them unchanged. Every unrelated package
pin, checkout source, origin and bounded SwiftPM mirror chain is checked.

The capture runs all 713 metadata checks in normal, optimized and ASan+UBSan
variants with no guest payload or proprietary input. macOS LeakSanitizer is
explicitly disabled; AddressSanitizer and UndefinedBehaviorSanitizer remain on.
It also runs the eight production C/Swift boundary tests with finite host VM and
I/O doubles, plus the five selected ordinary SideSign offline unit tests and a
real SideSign macOS build. The doubles do not link Unicorn or execute guest code.
The real native constructor fixture, canonical guest83 fixture, constructor driver
and downloaded Apple libraries are never executed in this lane.

Only the observed Package.resolved bytes may be committed in a lock-only
SideSign descendant after review. Neither this script nor the workflow publishes
source or creates locks by editing JSON. Phase one uses SideSign
`3cb03aaae12fcab0a0bc6e0075536a23fc30bdff`, whose only change from the baseline is
its immutable AnisetteKit manifest pin. Phase two cannot be sealed until that
actual artifact and the dependency-only SideStore successor exist. The current
`inputs-sidestore.json` is an explicitly pending document that the gate rejects.

## Phase two: final source graph and iOS compilation

A separate reviewed input update binds the observed phase-one run, attempt,
artifact digest, evidence-index digest and exact source tuples. It verifies the
SideSign descendant changes only its genuine observed lock. The existing sealed
host/service consumer suites, source compatibility checks, full child graph,
transport build, actual Xcode resolution and unsigned Release iPhoneOS builds of
SideStore and unchanged maintained LiveContainer remain required. An observed
SideStore lock may subsequently be published only as a reviewed lock-only change.

## Evidence/admission boundary

`CAPTURED_FOR_REVIEW` does not mean approved for production. Current receipts must
say `guest_execution=false`, `ADI_executed=false`, `device_validation=false`,
`production_ready=false` and `ipa_built=false`. Historical constructor/guest83
records are historical evidence for their original source tuples, inherited
through bounds validation host `6edd04bdeca008faf0f5e3c56d0ff42ac097e7d8`.
Fingerprints identify only the unchanged TLS/diagnostic headers and complete
`run_library_constructors` definition. The changed import router and procedure
driver are deliberately excluded. These narrow byte identities do not turn
historical execution into fresh execution of the modified whole loader.

A later additive builder evidence basis may bind independently reviewed source
and lock deltas, historical evidence identities, these safe host tests and actual
iOS compilation. It must retain all prior source, lock, artifact, contract and IPA
verification gates and explicitly model the changed coverage. No existing builder
basis, review anchor, expected test count or historical receipt is changed here.
Device sign-in acceptance remains an external physical-device check.

## Failure capture and artifact transport

Every long-running command owns a fresh session and records primary failure,
bounded child cleanup and positive pipe/group settlement. No nonzero signal is
sent after the leader is reaped. Unknown or surviving writers prevent evidence
index creation and artifact upload. The workflow emits only a bounded error
summary in that case. Actual resolver after-bytes are retained before validating
them; available partial locks are retained as observed bytes on settled failure,
without a successful-resolution claim.
