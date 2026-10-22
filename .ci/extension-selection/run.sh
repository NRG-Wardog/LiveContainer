#!/bin/bash
set -euo pipefail
# Usage: run.sh ROOT_WITH_LiveContainer_AND_SideStore OUTPUT
ROOT="${1:?source root required}"
OUT="${2:?output directory required}"
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$OUT"
python3 "$HERE/generate_fixture.py" --root "$ROOT" --output "$OUT" > "$OUT/generation.log"
command -v swiftc >/dev/null || { echo 'BLOCKED: swiftc unavailable; only source generation/static wiring checked.' >&2; exit 2; }
swiftc -swift-version 5 -parse-as-library "$OUT/Fixture.swift" -o "$OUT/fixture"
"$OUT/fixture" "$OUT/cases.json" | tee "$OUT/results.log"
# Fault injection reintroduces the issue at the ACTUAL extracted handler call.
# It is a mutation test, not an assertion that this is the full v3.1.0 source.
swiftc -swift-version 5 -parse-as-library "$OUT/NegativeControl.swift" -o "$OUT/negative-control"
ulimit -c 0
if "$OUT/negative-control" "$OUT/negative-cases.json" > "$OUT/negative-control.log" 2>&1; then
    echo 'FAIL: empty-excess mutation escaped regression coverage' >&2; exit 1
fi
grep -q 'fresh-nil-local-empty-excess-prompts-and-selects: prompt count' "$OUT/negative-control.log"
python3 - "$OUT" <<'PY'
import json,sys
from pathlib import Path
out=Path(sys.argv[1]); report=json.loads((out/'source-receipt.json').read_text())
report.update(swift_execution='passed-17-source-path-cases',empty_excess_mutation='rejected-at-fresh-prompt-count',native_signing_device_install='not-run')
(out/'execution-receipt.json').write_text(json.dumps(report,indent=2)+'\n')
PY
