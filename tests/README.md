# Maintained runtime source checks

Run from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
```

Python 3.9+ and a C compiler execute the portable checks. Swift and iPhoneOS SDK
checks explicitly skip if their toolchains are unavailable. The C harnesses use
maintained production headers/declarations; no integration patcher or historical
source template is imported or run. Only isolated test harnesses are assembled
in a temporary directory, never product source.

The migration manifest is a frozen OLD/NEW parity checkpoint, not permission to
rewrite expected hashes when a regression occurs. Future intentional runtime
changes need their own review and evidence. Structural guards are not substitutes
for Swift/UIKit/XPC compilation, render tests or device acceptance.

The App Group and CFBundle fixtures derive from the frozen integration tests
at 141776ba6ba38fc04a5e77f68b0cfc4e6c8842ee. Their MIT attribution is retained in
`LICENSES/sidestore-auto-refresh-MIT.txt`; production LiveContainer code remains
under its upstream license. The scanner fixture no longer contains a generated
or legacy runtime path; it exercises only the maintained implementation.

See `docs/migration/RUNTIME_SOURCE_MIGRATION.md` for scope, results and limitations.

## Pristine whole-tree validation

The checkpoint deliberately rejects every file not in the exact inventory,
including ignored files, `__pycache__`, empty extra directories and initialized
submodule contents. Use `-B` or `PYTHONDONTWRITEBYTECODE=1`, and run after committing
reviewed changes in a clean, non-recursive checkout. No prefix-based exemption is
granted to tests or documentation. Source expectations are anchored to immutable
historical objects; test/docs additions must match committed HEAD and index.

```sh
python -B tests/runtime_tree_gate.py "$PWD"
```

The adversarial suite mutates only disposable independent checkout copies. It
also demonstrates that inherited Git environment, replacement/graft views,
ignore rules, index hiding flags and local worktree settings cannot redirect or
hide the actual source inventory.
