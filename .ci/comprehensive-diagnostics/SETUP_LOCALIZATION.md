# Setup title localization regression

## Cause and scope

The delivered Setup Assistant sends its row titles through `V3LocalizedText`, which renders them with the strict `V3Localization.prose` API. The exact owned title keys `JIT-Less`, `Wi-Fi`, and `CoreDevice` were absent from `Localizable.xcstrings` in all four supported locales, including English. Their existing status detail keys were present, so a healthy row could have a green indicator and a correct body while its title displayed the unavailable-language placeholder.

The patch adds only those three catalog keys. These technical names intentionally stay unchanged in English, Hebrew, Simplified Chinese, and Traditional Chinese. All 12 row titles now use the finite `V3SetupTitle` enum. Only values of that type get selected-locale, English, and source-title fallback, including missing and empty translations. Visible and accessibility titles use the same locale.

Dynamic row details and provider errors still use the original fail-closed prose renderer. The localization change does not reclassify readiness, change routing, or change original diagnostic/copy payloads. The combined candidate can independently include the pairing saved-selection fix. Its 10 explicit new status keys are translated in all four locales; saved file selection remains distinct from current device-connection evidence.

## Source contract (no build)

Run from an assembled source tree, passing an unmodified delivered baseline separately:

    python3 .ci/comprehensive-diagnostics/test_setup_localization_contract.py \
      --candidate-root /path/to/candidate/LiveContainer \
      --baseline-root /path/to/delivered/LiveContainer \
      --output /path/to/evidence

The inventory derives titles and owned display literals from the actual Setup Assistant, setup store, JIT-Less and host-signing presentations, outstanding-item labels, pairing prerequisites, and schedule format definitions. It rejects missing/empty/untranslated catalog entries in any supported locale. The combined source has 157 keys and 628 localized values. Against the original delivered catalog, current-source coverage fails for exactly the 3 title keys plus 10 new pairing keys, in all four locales. Against the first localization freeze, only the 10 new pairing keys fail. The candidate has no missing entries. Each of the 628 locale entries is removed in turn to verify that the coverage gate catches the regression.

The source contract also verifies finite typed title call sites, unchanged dynamic detail rendering, and byte-for-byte identical Setup Assistant state/rendering/control bodies after normalizing only the title-type/rendering edits. It permits independent pairing changes elsewhere in the combined UI instead of requiring the entire UI file or setup store to be unchanged. Strict localization and raw-copy implementations and every pre-existing catalog entry remain identical. Catalog additions are limited to the explicit 3 title keys and 10 pairing keys. The pairing keys are checked against their actual presentation declarations and the unchecked-connection branch of the pairing view. It generates real renderer fixtures and checks their hashes but does not compile or execute Swift.

## Native renderer fixture (separate authorized build)

    python3 .ci/comprehensive-diagnostics/generate_setup_localization_fixture.py \
      --candidate-root /path/to/candidate/LiveContainer \
      --baseline-root /path/to/delivered/LiveContainer \
      --output /path/to/native-evidence --run

The fixture uses the entire actual `V3Localization.swift` and both actual pure pairing presentation enums, not reimplementations. Generated bundles exercise every source-owned key, all typed titles, missing locale directories, missing title entries, empty translations, absent bundles, English/source fallback, strict dynamic-detail fallback, unchanged raw diagnostic messages, secret canaries, and all three schedule frequencies. With a baseline supplied, it reproduces each finite missing key in that baseline catalog. Baseline and candidate paths are portable CLI inputs; `--livecontainer-root` remains an alias for `--candidate-root`. The baseline may be the original delivery or the first title-localization freeze.

The native fixture is Foundation-only, with no network, authentication, app launch, or device actions. Its successful execution does not establish SwiftUI rendering or device behavior. Source-only evidence explicitly reports native execution as not run.
