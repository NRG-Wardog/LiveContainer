# Local project preparation API

`project_setup.py` generates a disposable Xcode project from explicit, locally
owned source paths. It runs the sealed video `prepare` method, then reversibly
replaces exactly one app fixture fragment and one XCTest fixture fragment.
Production extraction, original actions/delays, and recovery methods are
preserved. This is Python/text preparation only: it does not build, launch,
execute XCTest, access the network, or establish native readiness/admission.

## Inputs and ownership

```python
from pathlib import Path
import project_setup

paths = dict(
    video_dir=Path("/owned/staging/video"),
    preflight_dir=Path("/owned/separate-preflight"),
    local_dir=Path("/owned/direct-feedback-local"),
)
observed = project_setup.source_hashes(source, builder, **paths)
# Independently verify ownership and approve this exact inventory before use.
expected = approved_source_hashes
prepared = project_setup.prepare(
    source, builder, fresh_build, fresh_output,
    **paths, expected_sources=expected,
)
```

- `source`: canonical absolute maintained `V3UnifiedShell.swift` path. Keep its
  `LiveContainerSwiftUI/Views/` layout and actual sibling
  `SideStoreSupport/SideStore.swift` support source when required by extraction.
- `builder`: canonical absolute directory containing the approved renderer,
  templates, baseline app fixture, and `p0_signin_project` fixture.
- `video_dir`: canonical absolute preserved video directory. Its original
  `../probe/capture.py` sibling is required. Both the full video capture source
  and exact reused `prepare` method are pinned in the adapter.
- `preflight_dir`: explicit canonical absolute directory containing
  `window_fixture.swift` and `runner_ui_tests.swift`. It need not be a video
  sibling; the adapter does not infer it from workspace ancestry.
- `local_dir`: explicit canonical absolute direct-feedback source directory.
  Its `host/project_setup.py` must be the executing module. To relocate this
  tree, import the adapter from that relocated tree, not the original tree.
- `fresh_build`, `fresh_output`: different, nonexisting, absolute, unlinked
  paths with existing canonical parents. Neither may contain the other. Paths
  must be fresh for every attempt; existing files/directories are not replaced.
- `expected_sources`: an exact plain `dict` matching `source_hashes(...)`.
  Hashing observes bytes; it does not establish ownership or approve them.
  Caller approval must cover the executing Python generators as well as inputs.

`source_hashes` returns a sorted relative-name-to-SHA-256 map covering preserved
video dependencies, probe, required preflight files, local adapter/generators/
candidates/bindings, production source/support, and builder renderer/templates/
project files. Linked inputs and oversized builder inventories are rejected.
The inventory is checked before and after generation. Callers must serialize
preparation because the preserved video importer temporarily uses short Python
module names; the adapter restores those names and import settings on exit.

## Return value and evidence

`prepare` returns a frozen `PreparedProject` with:

- `project`: generated `fresh_build/P0SignIn.xcodeproj` path
- `renderer`: imported preserved builder renderer module; returning it does not
  execute any of its native command operations
- `source_identity_bytes`: canonical JSON bytes, also retained as
  `fresh_output/source-identity.json`
- `receipt_bytes`: canonical JSON bytes, also retained as
  `fresh_output/direct-project-preparation.json`

`fresh_build/Sources` and `fresh_output/sources` contain identical source bytes.
`fresh_output/project` retains the project copy. The original source identity
is retained verbatim as `preserved-source-identity.json`; the new identity binds
its digest and every final generated source, explicitly distinguishes test-only
observer instrumentation from production instrumentation, and preserves the
base instrumentation description. Both new documents explicitly report
`nativeCompiled=false`, `nativeExecuted=false`, and `admissionEligible=false`.

Validation raises `ValueError` for controlled source/path/binding failures;
ordinary filesystem, JSON, or import failures can propagate their own exception
types. A failed attempt may leave partial build/output files. There is no
rollback or successful final receipt on a late validation failure. Retain and
inspect failed artifacts if useful, then choose new fresh paths for a retry.
This is source-binding validation, not a concurrent-mutation security boundary.

## Pure-local tests

From `direct-feedback-local`, run:

```sh
python3 -B -m unittest discover -s host -p test_project_setup.py -v
python3 -B -O -m unittest discover -s host -p test_project_setup.py -v
```

The tests copy inputs into temporary directories and run the real preserved
prepare and production text extraction. They verify exact two-fragment
reversibility, unchanged remaining sources/recovery, honest identity/receipt
hashes, explicit relocated paths, source drift before/during generation,
ambiguous boundaries, generated-candidate guards, fresh/unlinked paths, and
import-state restoration. Process-launch and network-connect tripwires guard
test execution. No Swift compilation, simulator execution, repository changes,
workflow publication, performance result, or admission claim is implied.

Defaults reference this workspace's maintained source/builder and preserved
video/preflight inputs. For another local staging layout, supply absolute
`P1_PROJECT_SOURCE`, `P1_PROJECT_BUILDER`, `P1_PROJECT_VIDEO`, and
`P1_PROJECT_PREFLIGHT` environment variables. Missing inputs fail rather than
skip. Only temporary copies are deliberately mutated.
