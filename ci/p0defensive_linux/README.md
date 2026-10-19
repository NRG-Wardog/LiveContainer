# Defensive A+B Linux capture proposal

LOCAL ONLY; REVIEW_REQUIRED. Nothing here publishes, dispatches, builds an IPA,
executes guest/proprietary input, or links a real engine. Review the exact overlay
and its generated input digest independently before any activation.

Source: AnisetteKit e72d04b84123823c93e9162daffa73b7afcfd2c9, tree
a03f5a4284b67560629cdb52b8e6b246b835a56a, sole parent
e6e9d4aac698de2a5219aaef02c9a417da45f4e9. The final source review names the
local commit bf62027f02d87d4c950e6868fd94defa3f8bea73; retained authenticated
publication receipt binds that exact tree to the published commit above.

Capture-only host: LiveContainer 545438e1f0a89fdef375f73273c5c9fc2735cbce,
tree e8014dd771c25c4a05dc76ab0aa304a233642a83. Only the exact one-line build-job
branch exclusion and new workflow/ci/p0defensive_linux files are proposed.
All historical/reserve folders stay untouched. The full capture host blobs/modes
and exact OpenSSL/litehook Gitlink IDs are verified; those unused product child
checkouts must remain absent or empty. Anisette source checking remains recursive.

Fixed source scripts, each normal, optimized and ASan/UBSan:
- test_vm_setup_host.py: 231 x 3 = 693
- test_memory_boundaries_host.py: 403 x 3 = 1209
- test_cxx_allocation.py: (32 + 51) x 3 = 249
- test_elf_metadata_bounds.py: 713 x 3 = 2139
Total: 4290 assertions. LeakSanitizer is explicitly disabled. No aggregate test
discovery, run_tests.py, Swift, guest execution, or real-engine linking occurs.

The prior reviewed allocation contract is retained verbatim except its exact
A+B source-hash dictionary. Old generic source constants are replaced by a
strict complete 58-file successor seal, with exact commit/tree/sole parent and
working-copy checks. Complete source Git blobs, full pinned Unicorn archive,
exact twelve extracted headers, tool executable bytes, generated compiler inputs,
object/executable outputs, nested argv/environment/raw byte streams, and outer
owned-process settlement are retained. Metadata binaries are retained before
the source driver deletes its temporary directory.

The retention/lifecycle/observer files were copied from the separate pending
A+B adapter. Their original bytes are retained under reviewed/ only to document
provenance; that name does not grant review. This capture and adaptations remain
pending independent review. The observer is narrowed to exact pre-execution
nested command arrays and rejects unapproved flags or inputs.

Evidence indexing uses lstat and rejects symlink, hardlink, FIFO and other
special entries. Only the ordinary root evidence-index.json is excluded from
its own file digest; nested same-named files and all directories are indexed.
Unknown/unsettled writers block indexing/upload. A complete settled failure
bundle can be transported for diagnosis, but never becomes a successful result.

Local replay uses exact sealed synthetic scripts and records no fresh authenticated
fetch or network-denial claim. The proposed GitHub lane additionally verifies the
exact overlay parent, actual run identity, official source origin, and Linux network
namespace denial. The namespace payload drops back to the nonroot runner UID/GID,
clears supplemental groups and all capabilities, preserves only explicit PATH/HOME,
and verifies compiler resolution before any nested writes. RawStore permissions
remain private. Local replay does not substitute for that remote capture.
