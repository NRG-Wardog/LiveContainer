# Actual early-refresh boundaries

Portable, source-extracted regression. The candidate variant reads every production function and the entire shared failure model from the explicitly supplied integrated candidate root. The baseline variant reads its production functions from an exact pinned baseline. Both use extraction/in-memory harness support from the candidate only. There is no overlay-path fallback, workspace default, network access, provider execution, or legacy 36-case runtime invocation.

## Required inputs

Both roots contain `LiveContainer/` and `SideStore/` subdirectories. `baseline-inputs.json` lists all 21 required baseline production files with repository, exact commit, Git object path, and SHA256. Pins are LiveContainer cb21f150e8907d2f8ed1bc7658342bac3fbb9926 and SideStore 638fa62ce2a540efe6c92dd20c282c32ddc0b2e6. Baseline hashes are verified before generation. These files may be extracted offline with `git show <commit>:<git_object_path>` from the already-fetched matching repositories. No fixture command fetches a repository.

Candidate production inputs have the same 21 paths. Candidate-only support:

- `LiveContainer/.ci/comprehensive-diagnostics/generate_wire_fixture.py`
- `LiveContainer/.ci/comprehensive-diagnostics/refresh_failure_doubles.swift`
- `LiveContainer/.ci/comprehensive-diagnostics/refresh_handler_doubles.swift`
- `LiveContainer/.ci/comprehensive-diagnostics/refresh_failure_harness.swift`
- `SideStore/tests/refresh_failure/pipeline_harness.swift`

The generator reuses only the block/model extraction functions and necessary harness declarations. It excludes the old case entrypoint and producer-injection helper entirely.

## Generate and statically validate

```sh
python3 "$CANDIDATE/LiveContainer/.ci/early-refresh-boundaries/test_contract.py" \
  --candidate-root "$CANDIDATE" --baseline-root "$BASELINE" --output "$OUTPUT"
```

For generation without the additional static contract, invoke `generate_regression.py` with the same three required arguments. There are no default source roots. Optional `--variants baseline` generates only the baseline when candidate integration is not ready.

Outputs are `baseline/early-refresh.swift`, `baseline/sources.json`, `candidate/early-refresh.swift`, `candidate/sources.json`, and, for the contract command, `contract.json`. Each receipt has canonical repo-relative `inputs_sha256`, separate candidate-only `support_inputs_sha256`, package `fixture_inputs_sha256`, explicit input/support roots, and the generated source hash.

## Proposed authorized CI compile/run commands

```sh
for variant in baseline candidate; do
  swiftc -swift-version 5 -parse-as-library "$OUTPUT/$variant/early-refresh.swift" \
    -o "$OUTPUT/$variant/early-refresh"
  "$OUTPUT/$variant/early-refresh" "$OUTPUT/$variant/cases.json"
done
```

The gate must require each report's status `pass`, correct variant, exactly 24 cases, and exact ordered equality of `cases` to `expected_case_names` in that variant's source receipt. Also verify `native_provider_executed` and `network_executed` remain false and hash the generated artifacts.

Twelve baseline cases intentionally assert generic VERIFY-C11, unknown source/cause, and redacted underlying evidence. Candidate cases assert finite readiness/preflight responsibility while retaining cancellation, existing pairing/structured evidence, unknown-error privacy, run/request correlation gates, nonrefresh/mixed batch behavior, and success/cellular/cached-team policies. No readiness or team check is skipped.

Local status: source extraction/static validation only. Swift compilation/runtime are NOT RUN, not a device cause or acceptance result. Matching CI is mandatory. The local preparation helper is intentionally not part of this package.

After identity admission was introduced, the candidate projection retains both exact PipelineRunner.perform and performUsingAdmittedRoute bodies. The latter contains the unchanged readiness/preflight and mutation ordering. Only the lease-admission interface is inert here; the dedicated identity suite owns real lease behavior. All original 24 cases and 101 static checks remain, plus one exact-helper extraction check (102 total).

The existing AppManager refresh body now captures admission before Task.detached. Its capture/withScope/close interfaces are inert here, while the dedicated identity fixture covers real lease state. Completion and failure propagation remain the exact extracted production method.
