# Defensive ELF metadata bounds capture

This is an additive, isolated capture lane for the reviewed AnisetteKit defensive
metadata change. It is not a builder-admission bypass or a reproduction build.
The historical `ci/p0init` capture and every historical receipt remain unchanged.
The generic upstream build explicitly ignores `validation/p0-elf-metadata-bounds`.

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
source or creates locks by editing JSON. Phase two cannot be sealed until that
actual artifact and the dependency-only SideStore successor exist.

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
records are historical evidence for their original source tuples. Function/file
fingerprints identify a narrow unchanged portion; they do not turn historical
execution into fresh execution of the modified whole loader.

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
