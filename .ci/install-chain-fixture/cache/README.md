# Group C: real cache method, synthetic filesystem

This test-only generator extracts the delivered `CacheAppOperation.cachePayload`
method unchanged and includes the full delivered `AppBundleFingerprint.swift`
unchanged. It does not compile the full iOS operation or call its asynchronous
pipeline. The real Foundation copy, move, filesystem checks, and CryptoKit SHA256
remain intact. Only `InstalledApp` destination routing and `OperationError` are
small inert boundary types. The routing shape is synthetic and is not evidence
of production CoreData directory behavior.

## Inputs and generation

Run Python with a root containing the delivered `SideStore` and `LiveContainer`
checkout directories:

```sh
python3 cache/test_source.py --root "$SOURCE_ROOT"
python3 cache/generate.py --root "$SOURCE_ROOT" --output "$OUTPUT/cache"
```

Support files are resolved beside the generator, never from a different version
of the test in the production checkout. Production inputs come only from
`--root/SideStore`, and both full-file Git blob IDs are pinned to the delivered
baseline. `sources.json` contains full input hashes, generated hashes, extracted
method hash, ordered case names, and exact negative-control expectations.

## Bounded runtime coverage (extended mode/name review)

Each case owns a fresh UUID-named directory beneath the macOS temporary directory
and removes only that directory. All app payloads are tiny, made-up bytes and
synthetic plists. Neither symlink case references an external or personal file.

1. New cache publication verifies content and preserves the original.
2. Identical repeated caching preserves content and the target directory inode.
3. A same-size content edit produces a different key and retains the old cache.
4. A root symlink input is rejected without changes.
5. A nested symlink input is rejected without changes.
6. An existing conflicting payload is rejected with all original bytes retained.
7. An obstructing regular file at the destination parent causes failure without
   modifying source or cached bytes.

The seventh case covers destination-directory creation failure, not an injected
mid-copy failure. The thirteen additional cases are:

8–16. Root and nested directories explicitly set to 0777/0755/0700, each under
umask 0022/0077/0000. Each includes regular and hidden files explicitly set to
0444/0555/0644/0755. The previous process umask is restored after each case.
17–18. Composed and decomposed Unicode directory/file names in separate cases,
including hidden files. The filesystem may normalize names during initial
creation; each case tests the resulting source name bytes against its copy,
not whether two canonically equivalent spellings yield different keys.
19. Permission-only source update gets a new key, keeps the previous cache,
and repeated updated source reuses the new inode.
20. Legitimate hidden-file content update gets a new key and keeps the old cache.

Every mode/name case observes an independent real Foundation copy and also calls
the unmodified production cache method, including its own real copy, verification,
and publication. It checks byte/mode/raw-name preservation, unchanged input,
repeat-cache inode reuse, and no leftover staging directories. A cache failure
is recorded verbatim alongside source/copy fingerprints and hex-encoded filename
bytes to permission maps, even when the independent copy differs.

The report's additive `copy_observations` field carries those synthetic details.
Hex filename map keys avoid Swift String canonical equality concealing changes.
No case claims concurrent publication, interrupted copies, CoreData persistence,
Apple signing, security-scoped access, or iOS installation coverage.

## Test-only macOS execution contract

The owner CI may compile and run `Cache.swift` plus each negative source with the
macOS Swift toolchain using `-swift-version 5 -parse-as-library`. The fixture has
an explicit `@main` entry point. Local preparation does not execute Swift or native code.
There are no app builds, signing operations, network calls, device operations,
credentials, pairing files, or personal provisioning profiles in this fixture.

Each runtime emits one JSON record before exiting. The schema is
`install-chain-runtime-v1`, group `cache`, with twenty ordered `{name, passed}`
case objects, aggregate Boolean `passed`, and
`native_signing_device_executed: false`. `failure_details` contains synthetic
failure descriptions keyed by case name. Positive execution must exit zero with
all twenty cases true. A failed case prints the report and exits one rather than
crashing at a precondition.

The two deliberate mutations must each exit one, with **exactly** their specified
case false and all other cases true:

- `CacheNegativeSameSize.swift` replaces content bytes with equal-length zeroes
  while hashing. Expected failure: `same_size_content_change_changes_key`.
- `CacheNegativeConflict.swift` bypasses only the existing-target verification
  guard. Expected failure: `existing_key_conflict_preserves_original_bytes`.

A compiler failure, absent JSON, unexpected failed case, or all-green negative
control is not successful negative-control evidence.
