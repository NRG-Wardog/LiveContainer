//
//  VirtualWindowsHostView.h
//  LiveContainer
//
//  Created by Duy Tran on 22/2/26.
//
@import UIKit;

API_AVAILABLE(ios(16.0))
@interface VirtualWindowsHostView: UIView
@property(nonatomic) BOOL shouldForwardTapAction;
- (BOOL)attachToHostView:(UIView *)hostView NS_SWIFT_NAME(attach(toHostView:));
- (BOOL)handleStatusBarTapAction:(UIAction *)action;
@end
