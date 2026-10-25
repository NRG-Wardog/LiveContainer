# Russian unified interface

The development candidate adds `ru` to the host language picker as **Русский**.
The host persists it in its captured `V3AppLanguage` defaults, applies left-to-right
layout, and resolves Russian region/script variants to the same catalog. It never
writes `AppleLanguages` or guest language preferences. The native Objective-C
localization path resolves the same host selection.

The catalog contains Russian for all 2,154 existing keys, including setup,
refresh/scheduling, sources, App ID expiry, signing/reuse controls, ordered
providers, local Anisette, recovery notices, guest controls and accessibility
copy. No English catalog entries or other locales were changed. Existing upstream
Russian was independently reviewed alongside 1,804 newly translated custom keys.
The 108 reviewed corrections to inherited Russian are pinned in
`tests/fixtures/russian_reviewed_existing.json`; they fix semantic reversals,
omitted safety information, labels and plural grammar, not just spelling.

Six direct plural entries and the two substitutions in the folder-move message
have Russian `one`, `few`, `many` and `other` forms. Product names and format-only
strings intentionally remain unchanged; their finite allowlist is tested.
Unknown provider prose still fails closed in Russian while diagnostic identifiers
and copyable original technical information are retained. Ordinary missing owned
keys retain the existing English/source fallback policy.

Russian `InfoPlist.strings` is included in the existing project variant group
with the same generic guest permission-purpose keys as English. iOS controls
system permission-dialog language; the host picker does not override system UI.

## Validation

- `python3 -B -m unittest discover -s tests -p test_russian_localization.py -v`
  checks exhaustive coverage, format/whitespace parity, plural/substitution
  structure, missing/copied/invalid-format negative controls, both host language
  routes, picker persistence wiring and permission-resource wiring. With Swift
  available it compiles the real `V3Localization.swift` for selector, repeated
  persistence, LTR, date locale, safe prose and fallback execution.
- Existing setup and pairing native fixture generators now cover Russian as well
  as all historical locales. Historical four-locale comparisons remain intact;
  Russian baseline absences are reported per locale, not counted as translations.
- The integration repository owns final compiled-catalog, packaged-resource and
  Russian numeric-plural checks in the consolidated candidate CI.

Linux static checks are not an Xcode build, rendered iPhone review or device
acceptance. Native execution and final package admission must pass for the exact
integrated commit before delivery. Text completeness does not prove that every
long Russian string fits every device size; that remains a visual/device check.
