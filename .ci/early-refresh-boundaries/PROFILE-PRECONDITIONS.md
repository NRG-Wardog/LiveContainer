# Finite profile preconditions (add-on)

This add-on reuses `generate_regression.py`'s exact model/chain extraction. It adds only the exact PipelineExecutor catch body and synthetic typed inputs corresponding to six known local guards. It does not run the original profile, progress or mapping methods, and does not exercise a provider, native device library, account, or network.

Generate and statically validate:

    python3 LiveContainer/.ci/early-refresh-boundaries/generate_profile_regression.py --candidate-root "$CANDIDATE" --output "$OUTPUT"

Outputs: `profile-preconditions.swift` and `profile-sources.json`. The receipt records all production/support/fixture hashes and 25 expected runtime case names. The original 24-case early-refresh fixture remains unchanged.

Only after separately authorized matching CI is available:

    swiftc -swift-version 5 -parse-as-library "$OUTPUT/profile-preconditions.swift" -o "$OUTPUT/profile-preconditions"
    "$OUTPUT/profile-preconditions" "$OUTPUT/profile-cases.json"

Require status `pass`, exact ordered equality with the receipt's expected case names, count 25, and false native-provider/network flags. Generation/static checks do not establish successful Swift compilation/execution or a device cause.

The additional field is optional. Invalid, wrong-type, orphaned, over-capacity or wrong-scope `local_precondition` observations are omitted without losing the primary envelope or other valid fields. Unrelated malformed fields retain the existing strict rejection. The six admitted values never contain raw messages, paths, app-group names, or identifiers. Only the actual refresh/profile-fetch boundary emits them. Existing OperationError throws and business handling are unchanged.

English catalog entries for the 11 fixed messages/recoveries are supplied by the coordinated UI overlay, not this package.

The full catch closure includes the exact production `lcPreservationCertificateFacts` and `lcSigningHash` helpers with CryptoKit SHA256. Minimal typed context surfaces retain the original non-preservation defaults (false/nil); original25 runtime inputs and expectations are unchanged. Generation rejects a missing helper, fake hash substitution, missing CryptoKit import, or missing preservation context member before native compilation. This closure correction does not claim to exercise preservation certificate branches here; those are covered by the dedicated producer and consumer fixtures.
