# Pending integrity capture extension

This successor is preparation only. It does not publish or activate anything.
The exact final resolver-lock child, lock-preserving source child, and SideStore
input must come from genuine reviewed evidence; pending tuple values stay null.
The original corrected A capture and its exact parser remain unchanged. A success
notification or artifact metadata alone is not original artifact replay.

## Reviewed patch versus actual source child

The reviewed local patch candidate is aed9e5ff3fa9d8d88c51788e82af9d780a41cbb9,
tree e05139bb18388abbe659f99ae0391b80fc2d3ea0, on b28fb0b72937849d4428e9ae313209b606f859b4.
It changes ten paths, including exactly one production line. It is only patch
identity. The immutable patch manifest records all exact before/after modes,
Git blobs and SHA-256 values, and original author and independent source-review
receipts are retained separately. Independent review SHA-256 is
661d9573cd73f55a8a83289836f69b6a016e6723502c6460c682b37c5d5815d1.
That review explicitly does not claim Apple compilation or runtime execution.

The executable graph adds sidesign_edges with exactly resolver_lock and
integrity_source. Each record has parent, commit, tree, and changes:

1. resolver_lock: sole-parent direct child of b28, changing only Package.resolved
   to the genuine independently replayed A observed/terminal bytes.
2. integrity_source: sole-parent direct child of resolver_lock, changing exactly
   the independently reviewed ten-path patch, with both Package.swift and the
   genuine resolver lock byte-identical across this source edge.

The SideSign owner retains b28 as base and names the final integrity source child
as commit/tree. Its changes equal the union of these two disjoint deltas. The
SideStore gitlink input names this final source child. It cannot name the lock
intermediate or the original patch candidate. Complete graph preparation requires
three distinct tuple bindings: SideSign_lock, SideSign, and SideStore.

Every source checkpoint retains the actual intermediate tree under
raw_resolver_lock_child_tree with label PHASE/SideSign-resolver-lock-child. Its
source_path is the captured SideSign checkout. raw_identity_objects contains the
original commit and recursive tree-listing bytes for all three SideSign revisions.
source-object-equivalence contains the seven owner proofs plus SideSign_edges.

## Source-only admission originals

The reviewed directory requires these independently bound originals:

- SideSign-lock.publication.json for the true intermediate and b28 parent
- SideSign.publication.json for the true source child and intermediate parent
- SideStore.publication.json for the gitlink-only input and known SideStore parent
- independent-descendant-clearance.json binding the A artifact and all three tuples
- independent-integrity-source-clearance.json binding the exact patch review,
  SideSign_lock/SideSign tuples and genuine lock digest

The integrity clearance has schema_version 1, scope
EXACT_LOCK_PRESERVING_INTEGRITY_SOURCE_CHILD, patch_review_sha256, SideSign_lock,
SideSign, lock_sha256, compiled_final_commit false and phase_b_execution_approved
false. These source-only clearances never grant capture activation. Final input
and overlay review and explicit activation remain separate requirements.

## Apple fixture evidence

After the unchanged genuine exact38 consumers and full unsigned builds, the
fixture uses the final SideSign source child and the already acquired exact
libdeflate package, with every subprocess under the existing deny-network sandbox.
No extra dependency fetch or resolution is permitted for this fixture. Its host
libdeflate build is separate from iOS products and fully retained.

Production download, resolve and hash methods, declarations, state fields, HTTP
response extension, genuine unzip helpers, and whole Archive.swift are copied
from exact hash-bound source spans. Only wrappers, Apple CryptoKit import and
explicit inert boundary doubles are synthetic. Inline ZIP entries named like
libraries contain inert text. No native provider, guest engine, account data,
provisioning or network call is executed.

Eight exact cases cover matching lower/uppercase digests, absent/empty optional
hashes, mismatch without/with an existing pair, malformed mismatching archive,
and malformed nonempty hash metadata. Declared mismatch must precede temporary
ZIP/write/extraction/provider operations, retain any pair/provider, reset caching
state and allow a real second matching invocation. Exactly two existing directory
calls still precede verification. Success cases use the genuine archive code.

provenance/library-integrity.json references retained exact source, span manifest,
generated Swift, inert fixture bytes, dependency lock/workspace/source/build,
compiler inputs/outputs, executable identity and raw command stdout/stderr,
exit-code and owned-process settlement. Exact ordered case output and complete
raw command closure are mandatory. A claimed count or summary alone cannot pass.
The independent parser must replay this closure before accepting the eight cases.

All old source tests, parser modules, network-deny policy, exact38 IDs, compiled
resources and final SideStore lock-equivalence semantics remain intact. Passing
these synthetic cases does not authenticate existing caches, enforce atomic pair
publication, prove metadata authenticity, exercise compressed ZIP content, or
establish the original initializer failure cause.
