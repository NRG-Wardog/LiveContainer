# Frozen compiled-resource expectations

These files are expected data only. They do not prove a current build, native execution, UI selection, or successful login.

- `compiled-translations.json` is a byte-for-byte copy of the retained P2 fixture at `p2-form-direction/builder/tests/fixtures/p2_localization_contracts/compiled-translations.json`. Its SHA-256 is `23d7e7dc60e88e23cf80814eaf6328e998079150dbd7d10b52c38b4eafe3bcb5`.
- `resource-contract.json` extracts literal plural/permission constants from the retained P2 helpers and exact simple-plural category values from LiveContainer commit `545438e1f0a89fdef375f73273c5c9fc2735cbce`. Its SHA-256 is `2c13e60cd322428393c79785e41067d60ee6f6f69a7d4ba6a09ac1fc5ff9ce9f`.
- The current source catalog SHA-256 is `a99d3776639f767c0b9a85432be6d129a5a95b437d0919304383ac9f4c39d9ba`. All 2,081 frozen scalar translations in each of the four languages match that current catalog.
- The manifest records the exact original helper and resource-logic hashes. Original scripts requested under the login release candidate were absent in that snapshot; retained P2 originals were used as expected-data provenance instead.

The standalone `resource_contract.py` uses the resource logic from `p2-composed-builder-checks/p2_product.py`, including exact simple-plural categories and argument formatting. It checks four language catalogs, 24 simple-plural language rows, four exact compound-plural rows, and seven permission resources with exactly 32 purpose keys plus the bundle name. It retains the inherited temporary-location disclaimer and never invents a scalar temporary-location permission.

Integration calls `resource_contract.verify_app(actual_app, current_livecontainer_root)`. For a retained archive reader, call `verify_compiled_resources(read, inventory_names, current_livecontainer_root)`. Both validate the current source catalog and every checked compiled resource byte hash. Product identity, Mach-O platform, signing, complete app inventory, graph admission, and network denial remain responsibilities of the enclosing fresh capture.

The adapter imports no historical source-root override. It reads only its frozen local data and caller-supplied current compiled/source roots.
