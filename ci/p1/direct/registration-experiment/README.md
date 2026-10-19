# Synthetic registration feasibility and negatives

This isolated study uses an explicit exact-area synthetic renderer, real packet decoders, and actual BGRA component observations. It does not reproduce or verify UIKit/CoreAnimation filtering, native AX, capture ownership, source exclusivity, timing, or admission. All native/admission flags remain false.

## Result

Representative app 402×874 points inside a 574×1316 BGRA frame:

- Broad packet whole-UIView correspondences fail closed: fit-derived viewport `[-389,-59,963,1375]` clips the frame. Restricting the observed side to one actual packet pixel still leaves viewport `[-273,-51,697,1285]` and fails.
- Four isolated 2×2-point magenta features use whole source AX rectangles × complete observed qualifying pixel-support intervals, with no ideal center or guessed rendering-edge constant. Their actual raster opaque supports are `[12,52,14,54]`, `[560,52,562,54]`, `[12,1262,14,1264]`, `[560,1262,562,1264]`.
- Three fit features yield viewport `[3,43,571,1273]`; the fourth is checked without narrowing/refitting. Six full-control/marker/packet-plus-feature ROIs cost 410,496 BGRA bytes, within the revised local 512KiB/6000-record profile. The superseded 256KiB profile would reject this case. This is a bounded design feasibility result, not a product-criterion change.
- The prior 40%-inset live-cell intersection is unresolved. Whole-source-cell guaranteed intersections retain complete unit pixels under every feasible transform; the unchanged opaque/uniform decoder reads marker 456 from actual raster bytes. The conditional rule was independently reviewed and promoted in `../pixels/live_strip.py`; `inset_strip.py` preserves the former rule solely for comparison, and `whole_strip.py` is the exact reviewed experiment.
- Fractional shifted 1.40 and 1.39 cases also freeze; the 1.42 case still rejects viewport clipping even though its diagnostic strip can decode. Diagnostic decoding never rescues failed geometry.
- Moving only the fourth actual feature down 12 source points leaves all nonce boards and first three supports unchanged, still passes the fixed outward adjacency gate, and fails the holdout constraint. No fit retry is attempted.

## Explicit conditional model

Each full-session/ordinal board is source-bound to its UIView. Each exact-magenta component is assumed to originate exclusively within the corresponding source-owned clipped feature UIView whose whole actual AX rectangle is measured. A single upright positive axis-aligned affine transform is assumed. Native source locality/exclusivity and filtering behavior are prerequisites requiring separate validation. Same-colored foreign replacement cannot be authenticated by adjacency alone.

The detector requires exactly four 4-connected components, at most 256 qualifying pixels total, and each component no larger than 16×16. Every qualifying pixel is exactly opaque BGRA magenta. Pairing is fixed ordinal-relative outward-corner adjacency, with a declared coarse packet-span association bound; it never chooses whichever assignment fits. The association bound is not a precision estimate.

## Files and tests

`explore.py`, `tiny_features.py`, `magenta_components.py`, `whole_strip.py`, `inset_strip.py`, and `test_experiment.py` contain the complete experiment. Binary frames and JSON reports are synthetic retained artifacts. Hashes bind exact inputs/dependencies. A report records the source version at its generation time, not later edits.

Run `python3 -B -m unittest discover -s p1-stall-isolation/direct-feedback-local/registration-experiment -v` from the workspace root, also with `-O`.

Tests check exact detector bounds, foreign/extra/missing/ambiguous pixels, immutable byte bindings, whole-rectangle failure, full-control ROI containment, fourth-only movement, true fractional-transform membership in correlated fit inequalities, every retained unit-pixel support against feasible and true source-cell bounds, opaque/uniform values, clipping, and exact promoted source equivalence. These are mathematical/source tests and synthetic raster tests, never native compilation or execution.
