#include <assert.h>
#include <float.h>
#include <stdio.h>
#include "MultitaskSupport/LCGuestSafeAreaGeometry.h"

static const LCGuestSafeAreaTransform identity = {1, 0, 0, 1, 0, 0};
static const LCGuestSafeAreaInsets input = {59, 0, 34, 0};
static const LCGuestSafeAreaInsets sentinel = {11, 12, 13, 14};

static void assert_equal(LCGuestSafeAreaInsets a, LCGuestSafeAreaInsets b) {
    assert(a.top == b.top && a.left == b.left && a.bottom == b.bottom && a.right == b.right);
}

static void reject(LCGuestSafeAreaInsets source, LCGuestSafeAreaTransform transform) {
    LCGuestSafeAreaInsets result = sentinel;
    assert(!LCGuestScaleSafeAreaInsets(source, transform, &result));
    assert_equal(result, sentinel); // Never partially overwrite incoming settings.
}

int main(void) {
    const LCGuestSafeAreaInsets cases[] = {
        {0, 0, 0, 0}, {20, 0, 0, 0}, {59, 0, 34, 0},
        {0, 59, 21, 59}, {24, 0, 20, 0}, {7.5, 9.25, 11.75, 13.5}
    };
    // Exercise the old arithmetic unchanged over identity, common scale-slider
    // values, unequal axis scales and positive scales outside the slider range.
    const double scales[] = {0.1, 0.5, 0.75, 1, 1.25, 1.5, 2, 10};
    unsigned checked = 0;
    for (unsigned i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        for (unsigned x = 0; x < sizeof(scales) / sizeof(scales[0]); ++x) {
            for (unsigned y = 0; y < sizeof(scales) / sizeof(scales[0]); ++y) {
                LCGuestSafeAreaTransform transform = {scales[x], 0, 0, scales[y], 47, -19};
                LCGuestSafeAreaInsets result = sentinel;
                LCGuestSafeAreaInsets original = {
                    cases[i].top / transform.d, cases[i].left / transform.a,
                    cases[i].bottom / transform.d, cases[i].right / transform.a
                };
                assert(LCGuestScaleSafeAreaInsets(cases[i], transform, &result));
                assert_equal(result, original);
                ++checked;
            }
        }
    }
    const LCGuestSafeAreaTransform bad_transforms[] = {
        {0, 0, 0, 1, 0, 0}, {1, 0, 0, 0, 0, 0},
        {-1, 0, 0, 1, 0, 0}, {1, 0, 0, -1, 0, 0},
        {NAN, 0, 0, 1, 0, 0}, {1, 0, 0, INFINITY, 0, 0},
        {INFINITY, 0, 0, 1, 0, 0}, {1, 0, 0, NAN, 0, 0},
        {0, 1, -1, 0, 0, 0}, {1, 0.01, 0, 1, 0, 0},
        {1, 0, 0.01, 1, 0, 0}, {1, NAN, 0, 1, 0, 0},
        {1, 0, NAN, 1, 0, 0}, {1, INFINITY, 0, 1, 0, 0},
        {1, 0, INFINITY, 1, 0, 0}, {1, 0, 0, 1, NAN, 0},
        {1, 0, 0, 1, 0, INFINITY}
    };
    for (unsigned i = 0; i < sizeof(bad_transforms) / sizeof(bad_transforms[0]); ++i) {
        reject(input, bad_transforms[i]);
    }
    const double invalid[] = {-1, NAN, INFINITY, -INFINITY};
    for (unsigned i = 0; i < sizeof(invalid) / sizeof(invalid[0]); ++i) {
        reject((LCGuestSafeAreaInsets){invalid[i], 0, 34, 0}, identity);
        reject((LCGuestSafeAreaInsets){59, invalid[i], 34, 0}, identity);
        reject((LCGuestSafeAreaInsets){59, 0, invalid[i], 0}, identity);
        reject((LCGuestSafeAreaInsets){59, 0, 34, invalid[i]}, identity);
    }
    // A finite positive divisor may still overflow the result.
    reject((LCGuestSafeAreaInsets){DBL_MAX, 0, 0, 0},
           (LCGuestSafeAreaTransform){1, 0, 0, DBL_MIN, 0, 0});
    reject((LCGuestSafeAreaInsets){0, DBL_MAX, 0, 0},
           (LCGuestSafeAreaTransform){DBL_MIN, 0, 0, 1, 0, 0});
    assert(!LCGuestScaleSafeAreaInsets(input, identity, NULL));
    LCGuestSafeAreaInsets alias = input;
    assert(LCGuestScaleSafeAreaInsets(alias, identity, &alias));
    assert_equal(alias, input);
    printf("GUEST_SAFE_AREA_GEOMETRY_PASS valid_cases=%u\n", checked);
    return 0;
}
