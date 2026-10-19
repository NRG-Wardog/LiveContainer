# Independent bounded-fault diagnostic source review

## Conclusion

No remaining source-level blocker found in the reviewed successor. Recommend accepting the exact component for the separately gated source-inventory composition step. This is not approval to publish, activate a capture, execute guest code, or claim an initializer47/device-login repair.

Final reviewed source:
- Commit: `e0267064280008cee34846a00eba1d7eb7aeba5c`
- Tree: `4d31646c46a7af3d911bb9d52eeffe9cbc26a3dd`
- Checkout: `p0-bounded-fault-diagnostic-review-fix`
- Base: `e72d04b84123823c93e9162daffa73b7afcfd2c9`, tree `a03f5a4284b67560629cdb52b8e6b246b835a56a`
- Complete chain: base → `1856fb87ed9cda5e7c04c1d544d68dc134a89f7c` → inventory-only `e856ac7bf552a06cbe3eb266e8848676f26cd280` → reviewed fix `e0267064280008cee34846a00eba1d7eb7aeba5c`
- Exactly 24 cumulative changed paths; 65 tracked files verified against actual Git blobs and SHA-256. Final worktree clean. All tracked bytes identical before and after independent tests.
- Author freeze: SHA-256 `ba44ebcfc9c1fb22d9870fce3b68cbdb42dc1f0b1678aeae2133988f32858a41`; its 65-file inventory and 24-path list independently match.

The authoritative independent receipts are under `final-e0267064/`. Root-level test receipts concern the earlier e856ac7b review and its now-fixed issue. `superseded-1856fb87/` retains the first run whose whole-tree closure correctly failed after a concurrent author inventory update. Those older results are not represented as final-source validation.

## Finding resolved during review

The first source version returned `Guard::Changed` immediately upon seeing accessible low memory. That skipped validation of later overlapping or malformed metadata and made the diagnostic order-dependent. A low accessible region followed by overlap/malformed metadata returned Changed; reversing the records returned Unknown. Unknown permission bits also returned Changed. This contradicted the documented conservative Unknown rule.

An independent host-only probe reproduced the issue. The author created the separate four-file e0267064 successor. It validates every record in the at-most-256-entry response, rejects unknown permission bits and invalid/overlapping ranges, and only then chooses a result. The pairwise overlap check has a fixed maximum of 32,640 comparisons and performs no guest-memory access. The unchanged independent probe now returns Unknown for both record orders and unknown permission bits; valid single NONE/read cases remain Intact/Changed. Eleven regression assertions were added. The original candidate and its prior receipts were retained untouched.

## Source and lifecycle assessment

- The protection callback at `Native/Loader/elf_loader_emulator.cpp:151–160` maps only the three closed protection event types, records at most the first event, and unconditionally returns false. It has no engine call, memory read/write, mapping, permission change, retry, logging, file I/O, or allocation. The pre-existing UNMAPPED callback is unchanged.
- Pending state is a fixed member of each VM. Reset occurs before every procedure's validation, including invalid/poisoned calls. Caller-owned failure snapshots contain no target address. Separate VMs and copies have no shared diagnostic storage; pre-existing caller synchronization requirements still apply.
- Hook registration uses the checked constructor path. Failure closes the acquired engine before throwing. Existing setup unwind, isolated-VM state restoration, destructor cleanup, and poison behavior pass independent host regression. The added pending state, digest, and snapshot use fixed-size storage; the production hash adapter and runtime helpers are noexcept.
- Width is restricted to 1–256 or unknown. Target classification rejects crossing/overflowing or ambiguous library ranges. No numeric target offset is exported. Final-PC attribution requires one containing loaded-library span within the bounded arena; the exported ordinal and offset are normalized to 0–65535 and 0–805306367 together, or both unknown.
- The already-existing checked post-stop PC read is reused. Original emulation/read status is saved before optional metadata inspection and is not replaced by inspection failure. Completion, return encoding, v1 reason/engine/library/initializer semantics, and poison remain unchanged. Original engine13 and PC-read failure preservation were tested independently.
- Memory-region inspection occurs after stop, processes no more than 256 entries, reads no guest memory, and frees every non-null API result including error cases. Invalid, oversized, split, missing, malformed, or ambiguous metadata conservatively becomes Unknown. It is only a low-guard observation.
- `load_library_to_vm` hashes the exact buffer immediately after its successful read and file close, before parse/map/guest writes. It never reopens a pathname to compute the digest. Apple production uses only CommonCrypto streaming calls, capped at 65,536 bytes per update; other production platforms return unknown. Hash failure cannot turn a successful load into failure. Digests are fixed-size per-library values; only ordinals 0 and 1 are exported. Host known vectors, chunking, failures, all synthetic ELF-byte mutations, and replacement-on-disk after read were exercised.
- Serialization normalizes closed enums and coherent fields into a fixed 256-byte buffer. The independent maximum-value probe produced 173 bytes. Raw target/absolute PC, arbitrary names, symbols, paths, guest strings, registers, credentials, and import arguments do not enter this wire.
- The exact Swift source rejects unknown schema/marker, extras, noncanonical/out-of-range/oversized numeric fields, incoherent PC/access/width tuples, invalid/uppercase hashes, non-ASCII, and oversized strings. All three response paths remove `v3_constructor_fault` before returning a response/provisioning value, and only accepted bounded values contribute an error suffix. These are source-flow findings; Swift compilation/runtime execution was unavailable and is not claimed as passed.
- Optional native trace allocation failure preserves the original JSON pointer/content. The allocation-failure wrapper test and disabled-trace path passed. The public C header and Package.swift are byte-for-byte unchanged. The legacy `description()` implementation is unchanged. Internal C++ `LibraryInfo`, VM, procedure-failure, and constructor-failure layouts changed and require recompiling every native consumer; old/new objects must not be mixed.
- Optional last-import classification remains deliberately deferred. The marker `p0_fault_diag1` is a schema/implementation label, not a source hash. Future build/capture evidence must bind this exact component tree and asset ordinal/digests to its actual source/build/capture envelope.

## Independent execution results

All runs used synthetic host API/I/O doubles and owned metadata bytes only. No Unicorn library was linked; dynamic-link inspection of both bounded fixture modes confirms this. Twelve trusted Unicorn header files are hashed in `final-e0267064/closure.json`. No instruction interpreter, proprietary input, real engine/guest, native device, or Apple authentication was executed. No external publication or capture activation occurred. The reviewer changed only review artifacts, never candidate source.

- Bounded diagnostics: 6 variants × 662 checks, zero failures. Modes: production unknown-digest and explicit host-only CommonCrypto-call-shape adapter; each normal, optimized, and fail-fast ASan/UBSan.
- VM/setup: 3 variants × 239 checks; 17 injected setup failure points per mode; zero engine starts.
- Memory boundaries: 3 variants × 403 checks; zero failures/engine starts.
- C++ allocation: 3 variants × 32 allocator and 51 hook checks; zero failures.
- Metadata: 3 variants × 713 checks; zero failures.
- Constructor-driver result parser: all 6 host parser tests passed. The real-engine constructor fixture was not run.
- Maintained aggregate: 8 passed, 1 explicitly skipped because Swift compiler is unavailable.
- Exact new Swift decoder runtime harness: `not_run`, Swift compiler unavailable.
- Independent adversarial probe: all malformed/overlap-order/permission outcomes now match the conservative contract; 8 additional assertions passed; maximum wire 173 bytes; zero engine starts.
- Nine independent commands (seven suites plus supplemental probe compile/run) exited zero. All five source-bearing result inventories were cross-checked against final tracked SHA-256 values.
- ASan and UBSan ran fail-fast where declared. LeakSanitizer was explicitly disabled in this executor; no leak-sanitizer pass is claimed.

## Remaining gates

1. Real Swift compiler/API compilation and decoder/response-boundary runtime validation.
2. Apple SDK CommonCrypto header, ABI and linkage verification for the actual pinned native build. The host OpenSSL adapter validates call shape/data flow only and adds no production dependency.
3. Exact native-fork build/link and device execution, only when separately authorized.
4. Independent source-inventory composition and future exact build/capture binding. Existing A+B capture activation remains unchanged.
5. Actual faulting guest instruction, pointer origin, asset compatibility, import semantics and initializer47 repair remain unproven.

## Evidence map

- `final-e0267064/source-before.json`, `source-after-tests.json`: exact identity, full hashes, clean state, before/after closure and command exits.
- `final-e0267064/closure.json`: 65 Git blobs/byte hashes, 24-path closure, author-manifest agreement, trusted headers and dynamic-link evidence.
- `final-e0267064/review-commands.json`: complete independent outer commands; individual suite receipts retain compile/run commands and output.
- `final-e0267064/full-candidate.patch`, `review-fix.patch`: full base delta and focused reviewed correction.
- `final-e0267064/bounded/`, `setup/`, `memory/`, `cxx/`, `metadata/`: independent structured receipts.
- `final-e0267064/aggregate.stderr`, `parser.stderr`: unittest outcomes including the explicit Swift skip.
- `adversarial_metadata.stdout` and `final-e0267064/adversarial.stdout`: pre-fix reproduction and identical post-fix probe.
- `final-e0267064/author-component-freeze.json`: exact unmodified author seal; its then-pending review field is superseded only by this separate independent review, not rewritten.
