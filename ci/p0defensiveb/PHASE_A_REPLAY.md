# Frozen defensive diagnostic Phase A replay

This adapter is for `defensive-diagnostic-phase-a-swift-split-v1` only. It never treats the previous
login artifact, review, lock or command counts as evidence for this capture.
All prospective native identities remain unresolved until original successful
capture bytes and an independent review exist.

## Fixed source closure

- Active frozen input SHA256: `1f129661ec646e3a7781bbca795603fe908d2ab72ecfd0d06affead097f8c62c`
- Activated host tree: `3b3ff76bec2d99729a34f4c484e90d624ff9de46`
- Required host sole parent: `1f1230372551c4aa0a4f39d93f58be76a8ee163d`
- Direct-parent tree: `32ef2a048de23323fae43d8765e119e80379d3cd`
- Cumulative overlay basis: LC `545438e1f0a89fdef375f73273c5c9fc2735cbce` / `e8014dd771c25c4a05dc76ab0aa304a233642a83`
- Frozen closure manifest SHA256: `ed9b9bf8c963b2447c3b28b434c9c8a4d5be41a3e2bf076260a8701642ccff6b`
- Active source branch: `validation/p0-defensive-diagnostic-phase-a-swift-split`

The exact corrected emitter source freeze is
`7fc229ae6a4d201de39c78920fd4941fe8d978e36339d796e7fd91e741bca165`.
Its original independent source review is retained as emitter-independent-review.json.
The separate parser source review and freeze are preserved unchanged alongside it;
neither is the unknown independent review of a successful actual capture.
Failed run 39300623354 remains explicitly ineligible. No successful corrected
capture exists in this preparation, and its publication is not authorized here.

`prior_adapter/frozen-closure.json` binds all 63 original adapter/input/workflow
files. The dormant workflow is retained verbatim; the expected original host
contains exactly the independently activated approval-anchor substitution.
All members are authenticated before private imports. Extra files, caches,
links, missing members and changed bytes fail closed. Archive Python is never
imported. The five owner host drivers are separately source-hash pinned and
replayed using an in-memory filesystem and fake subprocess interfaces; no
retained binary or native compiler is executed.

## Public Python APIs

- `make_draft_prior()` returns fixed source bindings and nullable actual tuple.
- `validate_prior_inputs(prior, execution=False)` accepts partially supplied
  unknowns but type-checks every present value. `execution=True` requires the
  entire original tuple, upload-identity digest and independent-review binding.
- `verify_original_capture(prior, receipts, prior_adapter, roots)` performs the
  original capture replay before Phase B exists. It returns `report`,
  `replay_report_sha256`, `original_receipt_sha256`, and `lock_bytes`.
- `verify_prior_capture(prior, receipts, prior_adapter, roots, current,
  inputs_path, inputs_raw, work_root)` adds strict current-run retrieval and the
  original independent review. It returns `report` and `lock_bytes`.

`roots` maps `AnisetteKit`, `SideSign` and `LiveContainer` to ordinary local Git
repositories containing the exact frozen source/base objects. Extra current
Phase B roots are allowed. No source checkout is written. All source reads are
against explicit immutable commits, so the later SideSign lock-only child may
be checked out while its frozen Phase A parent objects are read.

`current` has exactly `repository`, `run_id`, `run_attempt`, `host_commit` and
must match the actual Phase B process's GitHub environment. Current input bytes
must match both the supplied path and the exact `prior_phase_a` object.

## Pending binding shape

The top-level prior keys are exactly:

- `schema_version`: integer 1
- `source_basis`: `defensive-diagnostic-phase-a-swift-split-v1`
- `phase`: `phase-a`
- `approved_inputs_sha256`: fixed input above
- `frozen_adapter_sha256`: fixed closure digest above
- `upload_identity_sha256`: null until original upload bytes are reviewed
- `independent_review`: null, or `{receipt_sha256, reviewer}`
- `expected`: repository, run_id, run_attempt, host_commit, host_tree,
  artifact_id, artifact_sha256, artifact_size, lock_sha256,
  evidence_index_sha256

The draft knows only repository and frozen host tree in `expected`; every actual
run/commit/artifact/size/lock/index remains null. IDs are positive integers,
never booleans or numeric strings. Filling a tuple is not execution admission.

## Original acquisition and offline review, before Phase B

Preserve the exact authenticated original bytes under a receipt directory:

- `run-api.json`: official run-attempt GET body
- `artifact-list-api.json`: exact complete authenticated run-artifact listing body
- `artifact-api.json`: selected/derived complete artifact object from that listing;
  this is not mislabeled as a whole single-artifact HTTP response
- `commit-api.json`: official Git commit GET body
- `artifact.zip`: original uploaded archive, no extraction or rewriting
- `upload-identity.json`: exact seven-field original upload-action output

Populate the actual expected tuple and `upload_identity_sha256`. Leave
`independent_review` null while conducting independent review. Then run:

```
python3 -B ci/p0defensiveb/phase_a_replay_original.py \
  --prior-json actual-prior.json \
  --receipts original-phase-a \
  --source-roots-json read-only-source-roots.json \
  --report original-replay.json
```

The report is source-specific and deterministic from original captured bytes.
It contains original capture paths, never current Phase B paths, run identity,
retrieval metadata or the independent receipt. `replay_report_sha256` is SHA256
of UTF-8 `json.dumps(report, sort_keys=True, separators=(',', ':'),
allow_nan=False)`, with no trailing newline. The same implementation produces
that exact report during Phase B. This prevents a circular requirement for a
future Phase B run.

The offline API does not authenticate acquisition or issue independent
approval. A separate reviewer must inspect authenticated original provenance
and actual replay, then author the independent receipt below. The final Phase B
input binds the unchanged original receipt's SHA256 and reviewer. No verifier
function fabricates, rewrites or upgrades a review attestation.

## Exact original independent-review schema

The original JSON object has exactly these keys:

- `schema_version`: integer 1
- `status`: `INDEPENDENT_DEFENSIVE_DIAGNOSTIC_PHASE_A_REVIEW_PASSED`
- `reviewer`: same nonempty identity bound in prior.independent_review
- `source_basis`, `expected`, `approved_inputs_sha256`,
  `frozen_adapter_sha256`: exact original prior values
- `original_receipt_sha256`: exactly the returned map with keys `run_api`,
  `artifact_api`, `artifact_list_api`, `commit_api`, `archive`, `upload_identity`
- `replay_report_sha256`: exact returned stable report hash
- `checks`: exactly the following keys, each JSON true:
  - authenticated_original_capture
  - ordered_argv_cwd_environment
  - owned_writer_settlement
  - source_origin_full_tree
  - resolved_package_sources
  - binary_archive_raw_members
  - tool_sdk_compiler_product_bytes
  - finite_test_execution
  - genuine_observed_terminal_lock
  - complete_raw_evidence_index
- `scope`: exactly `execution_admitted`, `production_ready`, `guest_execution`,
  `live_provider_or_apple_requests`, `compiled_final_lock_child`, each JSON false

Store the unchanged original receipt and upload output in
`ci/p0defensiveb/reviewed/independent-review.json` and `upload-identity.json`.
Also store the exact original observations as `original-run-api.json`,
`original-artifact-api.json`, `original-artifact-list-api.json`, and
`original-commit-api.json` in that same reviewed directory. The gate copies all
six files under the same names into the fresh runtime receipt directory. The
adapter inventory seals their bytes and the original independent receipt hashes
all four API observations, ZIP and upload output. Original API hashes are never
replaced by fresh current-run GET hashes.

The complete listing must have exactly `total_count` and `artifacts`, an exact
positive count matching the list length, no repeated artifact IDs, and exactly
one matching actual artifact ID. The complete selected object must equal the
parsed `artifact-api.json`, including `node_id` and all other fields. The stable
original report includes `artifact_original_provenance` with the listing hash,
selected-object hash, artifact ID and
`SELECTED_FROM_AUTHENTICATED_RUN_ARTIFACT_LIST` label. Original selection may be
byte-extracted or explicitly derived; it is never described as an untouched
single-artifact response.

## Current-run retrieval

`retrieve_prior.py` uses only four authenticated official GitHub GET endpoints
in exact order: run attempt, artifact, Git commit, artifact ZIP. It is invoked by
an owned outer command at its sealed path. It creates a fresh no-follow output
directory only after all prior bindings, current-run identity and token presence
have passed. Token access is restricted to the helper environment and nested
`gh` environment; no token is placed in argv, output or receipts. No ambient GH
config, alternate host, proxy, CA, pager or loader override reaches `gh`.

Limits are 900 seconds/request, 1500 seconds total, 16 MiB/API JSON, 8 GiB
compressed artifact, 64 KiB headers and 64 KiB stderr. The outer owned command
must have a positive timeout at most 1800 seconds. The gate adds
`retrieval-receipts.json` only after actual successful process-group settlement.
`retrieval-helper.json` alone says `RETRIEVED_UNSETTLED` and cannot admit anything.
The current outer exact argv, cwd, finite environment, zero return codes,
no-signals cleanup, group identity, joined pipes and reaped leader are replayed.
Every nested GET, body hash/length and current input/helper hash is bound.
The finite current Phase B environment requires both `LANG` and `LC_ALL` to be
`en_US.UTF-8`, matching the macOS gate. This does not modify the original frozen
Phase A environment.

### Original observations and fresh GET bodies

The runtime `run-api.json`, `artifact-api.json`, and `commit-api.json` remain
fresh actual HTTP response bodies. Their exact hash/length and official endpoint
are checked against the current owned request/settlement receipts. They never
stand in for the sealed original observations named `original-*.json`.

Both sets independently pass the same exact source/capture identity checks.
Then their complete parsed JSON must match, except for whitespace/key-order
serialization and valid UTC ISO8601 `updated_at` fields on run and artifact
objects. Timestamp presence cannot change. Every other field remains exact,
including unknown metadata, jobs/logs URL routes, node_id, success/status,
run/attempt/branch/workflow, commit/tree/sole parent, artifact ID/hash/size and
expired status. Commit metadata has no exceptions. Original run observation
must come from the authenticated exact attempt endpoint; initial run-level reads
remain separate and are not normalized into attempt observations.

Fresh response hashes and classified metadata changes appear separately as
`current_api_sha256` and `current_api_comparison` only after the stable original
replay digest and independent review have been checked. The original report and
receipt hash map are unchanged by fresh transport metadata.

## Original raw replay coverage

The complete original evidence index must exactly match every ZIP member.
The ZIP is descriptor-bound, streaming-hashed, lazily read and never extracted.
Central-directory/member/count/expansion bounds and path/mode/collision checks
precede use. Every referenced retained blob must exist, match SHA256, byte length,
Git SHA1/SHA256 blob identities and modes. Every retained tree/link is replayed;
unreferenced or missing blobs fail. The fixed Phase A 8 GiB logical retention
budget applies independently of the later Phase B product budget.

The exact corrected emitter yields 44 ordered top-level commands and five
source-derived host lanes. The diagnostic lane replays all 16 logical/executed
command joins, with only its two exact Swift compilation rows outside the
network-denial wrapper; the other 14 rows retain network denial. Generated
source, retained compiler products, dSYM closure, CommonCrypto bindings,
finite counts, raw output and result assertions remain exact. No retained
executable is run by the replay. The four established lanes retain their
source-derived command inventories. These are expected source contracts,
not evidence of a successful run by themselves.

Original source stages, host overlay, dependency workspace-state raw bytes,
package commit/tree/listing objects, pinned original dependency ZIP members,
compiler/tool/SDK trees and generated products are required. The real SideSign
`before` must equal frozen b28fb0b7's source lock; `after` and
`terminal-observed` must be byte-identical. Only the AK pin and resolver originHash
may change. The future lock-only SideSign child is explicitly not directly
compiled by Phase A.

## Portable tests

Run normal and optimized without network or native builds:

```
python3 -B -m unittest discover -s ci/p0defensiveb/tests -p 'test_prior_phase_a.py' -v
python3 -O -B -m unittest discover -s ci/p0defensiveb/tests -p 'test_prior_phase_a.py' -v
python3 -B -m unittest discover -s ci/p0defensiveb/tests -p 'test_retrieve_prior.py' -v
python3 -O -B -m unittest discover -s ci/p0defensiveb/tests -p 'test_retrieve_prior.py' -v
python3 -B -m unittest discover -s ci/p0defensiveb/tests -p 'test_phase_a_host_replay.py' -v
python3 -O -B -m unittest discover -s ci/p0defensiveb/tests -p 'test_phase_a_host_replay.py' -v
```

These use explicitly synthetic bytes and a fake local `gh`; they establish
fail-closed implementation behavior, never genuine native evidence.

## Immutable source and portable fixture boundary

Production parser modules are copied byte-for-byte from the independently
cleared corrected parser. This B overlay changes only its two offline test
modules' local source lookup. The full finite B CI driver runs their tests
alongside every historical B test without skips. Fixture bytes, real Git OIDs,
tree reconstruction and complete reviewed source hashes remain checked.
The actual capture paths, provider policy, graph admission, source locks and
original/fresh API distinction are not replaced with fixtures.
