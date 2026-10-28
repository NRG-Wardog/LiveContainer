//
//  VirtualWindowsHostView.m
//  LiveContainer
//
//  Created by Duy Tran on 22/2/26.
//
#import "DecoratedAppSceneViewController.h"
#import "VirtualWindowsHostView.h"
#include <math.h>

@implementation VirtualWindowsHostView
- (instancetype)init {
    self = [super initWithFrame:CGRectZero];
    self.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    self.shouldForwardTapAction = YES;
    return self;
}
// LC_VIRTUAL_HOST_ATTACHMENT_V1: own a stable root overlay, never a SwiftUI
// implementation-detail child (the language bridge can be its first child).
- (BOOL)attachToHostView:(UIView *)hostView {
    NSAssert(NSThread.isMainThread, @"Guest host attachment must run on main");
    CGRect bounds = hostView.bounds;
    if (!hostView || hostView == self || [hostView isDescendantOfView:self] ||
        !hostView.window || CGRectIsEmpty(bounds) || CGRectIsInfinite(bounds) ||
        !isfinite(bounds.origin.x) || !isfinite(bounds.origin.y) ||
        !isfinite(bounds.size.width) || !isfinite(bounds.size.height)) return NO;
    if (self.superview != hostView) [hostView addSubview:self];
    self.frame = bounds;
    self.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    [hostView bringSubviewToFront:self];
    return self.window == hostView.window;
}
- (BOOL)handleStatusBarTapAction:(UIAction *)action {
    if(!self.shouldForwardTapAction) return NO;
    // grab the frontmost app window, if it's visible pass this event to it
    UIView *frontmostView = self.subviews.lastObject;
    if(!frontmostView.hidden) {
        DecoratedAppSceneViewController *decoratedVC = (id)frontmostView._viewDelegate;
        [decoratedVC.appSceneVC handleStatusBarTapAction:action];
    }
    return !frontmostView.hidden;
}
- (UIView *)hitTest:(CGPoint)point withEvent:(UIEvent *)event {
    UIView* hitView = [super hitTest:point withEvent:event];
    if(hitView == self) {
        self.shouldForwardTapAction = NO;
        return nil;
    } else {
        self.shouldForwardTapAction = YES;
        return hitView;
    }
}
@end
