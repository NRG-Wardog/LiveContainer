// Public scalar validation for the host-to-guest safe-area conversion.
// UIKit owns the geometry; invalid or unsupported snapshots must not replace
// the scene settings supplied by its original update block.
#ifndef LC_GUEST_SAFE_AREA_GEOMETRY_H
#define LC_GUEST_SAFE_AREA_GEOMETRY_H

#include <stdbool.h>
#include <math.h>

typedef struct {
    double top, left, bottom, right;
} LCGuestSafeAreaInsets;

typedef struct {
    double a, b, c, d, tx, ty;
} LCGuestSafeAreaTransform;

static inline bool LCGuestSafeAreaInsetsAreValid(LCGuestSafeAreaInsets insets) {
    return isfinite(insets.top) && insets.top >= 0 &&
           isfinite(insets.left) && insets.left >= 0 &&
           isfinite(insets.bottom) && insets.bottom >= 0 &&
           isfinite(insets.right) && insets.right >= 0;
}

static inline bool LCGuestScaleSafeAreaInsets(LCGuestSafeAreaInsets source,
                                             LCGuestSafeAreaTransform transform,
                                             LCGuestSafeAreaInsets *result) {
    // This conversion is defined only for a positive axis-aligned scale.
    // Rotation/shear require a different conversion, not division by a/d.
    if (!result || !isfinite(transform.a) || !isfinite(transform.d) ||
        !isfinite(transform.tx) || !isfinite(transform.ty) ||
        transform.a <= 0 || transform.d <= 0 || transform.b != 0 || transform.c != 0 ||
        !LCGuestSafeAreaInsetsAreValid(source)) return false;
    LCGuestSafeAreaInsets scaled = {
        source.top / transform.d, source.left / transform.a,
        source.bottom / transform.d, source.right / transform.a
    };
    if (!LCGuestSafeAreaInsetsAreValid(scaled)) return false;
    *result = scaled;
    return true;
}

#endif
