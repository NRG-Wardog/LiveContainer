"""Generate the unchanged original independent screenshot recognition path."""
from pathlib import Path
from hashlib import sha256
HERE=Path(__file__).parent
SOURCE=HERE.parents[1]/'window-capture-candidate/ci/p1/video/decode.swift'
SHA='fda9fe8ec1eb475b070db56591287d0d7e4a73f3f7352f838cfc5d8d82e42ed4'

def build():
    source=SOURCE.read_text()
    if sha256(source.encode()).hexdigest()!=SHA:raise ValueError('original screenshot decoder drift')
    prefix=source[:source.index('var screenshots: [[String: Any]] = []')]
    a=source.index('var independent: [[String: Any]] = []')
    b=source.index('let asset',a)
    loop=source[a:b]
    # This source-bound path preserves every original independent recognition
    # predicate, actual crop and single-center marker decoder. It removes only
    # unrelated video decoding, which the direct-window lane does not use.
    suffix='''
let report: [String: Any] = ["schema": "p1-direct-independent-screenshots-v1",
    "independentScreenshots": independent, "admissionEligible": false,
    "scope": "original-independent-steady-state-pixels-only"]
try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys]).write(to: URL(fileURLWithPath: args[3]), options: .atomic)
'''
    return prefix+loop+suffix

if __name__=='__main__':(HERE/'independent_ocr.swift').write_text(build())
