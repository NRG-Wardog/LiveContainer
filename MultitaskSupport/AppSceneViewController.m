//
//  AppSceneView.m
//  LiveContainer
//
//  Created by s s on 2025/5/17.
//
#import "AppSceneViewController.h"
#import "DecoratedAppSceneViewController.h"
#import "LiveContainerSwiftUI-Swift.h"
#import "../LiveContainerSwiftUI/Utilities/LCUtils.h"
#import "PiPManager.h"
#import "Localization.h"
#import "LCSharedUtils.h"
#import "../LiveContainer/LCAppGroupSelectionPolicy.h"
#import "utils.h"
#import "UIKitPrivate+MultitaskSupport.h"
#include <math.h>

static double LCReturnAxisCenter(double origin, double length, double position) {
    if (!isfinite(origin) || !isfinite(length) || length < 0) return 0;
    if (!isfinite(position)) position = 0.5;
    position = fmin(1.0, fmax(0.0, position));
    double inset = fmin(30.0, length / 2.0);
    return origin + inset + position * fmax(0.0, length - 2.0 * inset);
}
static int LCReturnShouldHide(int running, int decorated, int maximized) {
    return !running || (decorated && !maximized);
}

// LC_GUEST_RETURN_V3: the control owns no guest process or scene.
static UIColor *LCGuestReturnColor(NSString *key, NSUInteger fallbackRGB) {
    id saved = [NSUserDefaults.lcSharedDefaults objectForKey:key];
    double value = [saved isKindOfClass:NSNumber.class] ? [saved doubleValue] : fallbackRGB;
    if (!isfinite(value) || value < 0 || value > 0xFFFFFF || floor(value) != value) value = fallbackRGB;
    NSUInteger rgb = (NSUInteger)value;
    return [UIColor colorWithRed:((rgb >> 16) & 0xFF) / 255.0
                           green:((rgb >> 8) & 0xFF) / 255.0
                            blue:(rgb & 0xFF) / 255.0 alpha:1.0];
}

@interface LCReturnControl : UIView
@property(nonatomic, strong) UIButton *button;
@property(nonatomic, copy) void (^action)(void);
@property(nonatomic) CGPoint position;
@property(nonatomic) CGRect keyboardFrame;
@property(nonatomic) BOOL collapsed;
@property(nonatomic, copy) NSString *expandedHint;
- (void)collapse;
@end
@implementation LCReturnControl
- (instancetype)initWithFrame:(CGRect)frame {
    if (!(self = [super initWithFrame:frame])) return nil;
    self.backgroundColor = UIColor.clearColor;
    self.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    NSArray *saved = [NSUserDefaults.lcSharedDefaults arrayForKey:@"LCReturnControlPosition"];
    self.position = CGPointMake(0.95, 0.25);
    if (saved.count == 2 && [saved[0] isKindOfClass:NSNumber.class] && [saved[1] isKindOfClass:NSNumber.class]) {
        double x = [saved[0] doubleValue], y = [saved[1] doubleValue];
        if (isfinite(x) && isfinite(y) && x >= 0 && x <= 1 && y >= 0 && y <= 1) self.position = CGPointMake(x, y);
    }
    if ([NSUserDefaults.lcSharedDefaults boolForKey:@"LCGuestReturnStartsCollapsed"]) [self collapse];
    self.button = [UIButton buttonWithType:UIButtonTypeSystem];
    self.button.backgroundColor = UIColor.secondarySystemBackgroundColor;
    self.button.layer.cornerRadius = 22;
    [self.button setImage:[UIImage systemImageNamed:@"arrow.uturn.backward.circle.fill"] forState:UIControlStateNormal];
    self.button.accessibilityLabel = @"Return to LiveContainer";
    self.button.accessibilityHint = @"Minimizes this guest without closing it";
    self.expandedHint = self.button.accessibilityHint;
    __weak typeof(self) weakControl = self;
    self.button.menu = [UIMenu menuWithTitle:@"" children:@[
        [UIAction actionWithTitle:@"Collapse Return Button" image:[UIImage systemImageNamed:@"sidebar.right"] identifier:nil handler:^(__kindof UIAction *action) {
            [weakControl collapse];
        }]
    ]];
    [self.button addTarget:self action:@selector(tapped) forControlEvents:UIControlEventTouchUpInside];
    [self.button addGestureRecognizer:[[UIPanGestureRecognizer alloc] initWithTarget:self action:@selector(drag:)]];
    [self addSubview:self.button];
    [NSNotificationCenter.defaultCenter addObserver:self selector:@selector(keyboard:) name:UIKeyboardWillChangeFrameNotification object:nil];
    [NSNotificationCenter.defaultCenter addObserver:self selector:@selector(keyboard:) name:UIKeyboardWillHideNotification object:nil];
    [NSNotificationCenter.defaultCenter addObserver:self selector:@selector(preferencesChanged:) name:NSUserDefaultsDidChangeNotification object:NSUserDefaults.lcSharedDefaults];
    [NSNotificationCenter.defaultCenter addObserver:self selector:@selector(preferencesChanged:) name:UIApplicationDidBecomeActiveNotification object:nil];
    NSLog(@"[LC_RETURN] CONTROL_SHOWN");
    return self;
}
- (void)dealloc { [NSNotificationCenter.defaultCenter removeObserver:self]; }
- (void)collapse {
    self.collapsed = YES;
    self.position = CGPointMake(self.position.x < 0.5 ? 0 : 1, self.position.y);
    [self setNeedsLayout];
    NSLog(@"[LC_RETURN] CONTROL_COLLAPSED");
}
- (void)preferencesChanged:(NSNotification *)note {
    if (!NSThread.isMainThread) {
        dispatch_async(dispatch_get_main_queue(), ^{ [self preferencesChanged:note]; });
        return;
    }
    // Appearance can change while a guest is retained. Never reset a user's
    // expanded/collapsed state during layout, keyboard changes, or activation.
    [self setNeedsLayout];
}
- (UIView *)hitTest:(CGPoint)point withEvent:(UIEvent *)event {
    UIView *hit = [super hitTest:point withEvent:event];
    return hit == self ? nil : hit;
}
- (CGRect)availableRect {
    CGRect rect = UIEdgeInsetsInsetRect(self.bounds, self.safeAreaInsets);
    if (self.window) {
        CGRect windowSafe = UIEdgeInsetsInsetRect(self.window.bounds, self.window.safeAreaInsets);
        CGRect intersection = CGRectIntersection(rect, [self convertRect:windowSafe fromView:self.window]);
        if (!CGRectIsNull(intersection)) rect = intersection;
    }
    if (!CGRectIsEmpty(self.keyboardFrame) && self.window) {
        CGRect keyboard = [self convertRect:self.keyboardFrame fromCoordinateSpace:self.window.screen.coordinateSpace];
        if (CGRectIntersectsRect(rect, keyboard) && CGRectGetMaxY(keyboard) >= CGRectGetMaxY(rect)) {
            rect.size.height = MAX(0, CGRectGetMinY(keyboard) - CGRectGetMinY(rect));
        }
    }
    return rect;
}
- (void)layoutSubviews {
    [super layoutSubviews];
    CGRect rect = [self availableRect];
    // A 44-point target must not be placed outside a tiny resized window.
    self.button.hidden = [NSUserDefaults.lcSharedDefaults boolForKey:@"LCHideReturnControl"] || CGRectIsNull(rect) || rect.size.width < 44 || rect.size.height < 44;
    if (self.button.hidden) return;
    self.button.accessibilityLabel = self.collapsed ? @"Show Return to LiveContainer" : @"Return to LiveContainer";
    self.button.accessibilityHint = self.collapsed ? @"Restores the Return button" : self.expandedHint;
    BOOL customColors = [NSUserDefaults.lcSharedDefaults boolForKey:@"LCGuestReturnCustomColors"];
    // nil restores the inherited system tint when custom colors are disabled.
    self.button.tintColor = customColors ? LCGuestReturnColor(@"LCGuestReturnTintRGB", 0x007AFF) : nil;
    UIColor *background = customColors ? LCGuestReturnColor(@"LCGuestReturnBackgroundRGB", 0xF2F2F7) : UIColor.secondarySystemBackgroundColor;
    self.button.backgroundColor = self.collapsed ? UIColor.clearColor : background;
    [self.button setImage:[UIImage systemImageNamed:self.collapsed ? (self.position.x < 0.5 ? @"chevron.compact.right" : @"chevron.compact.left") : @"arrow.uturn.backward.circle.fill"] forState:UIControlStateNormal];
    self.button.bounds = CGRectMake(0, 0, 44, 44);
    self.button.center = CGPointMake(LCReturnAxisCenter(rect.origin.x, rect.size.width, self.position.x),
                                    LCReturnAxisCenter(rect.origin.y, rect.size.height, self.position.y));
}
- (void)keyboard:(NSNotification *)note {
    self.keyboardFrame = [note.name isEqualToString:UIKeyboardWillHideNotification] ? CGRectZero : [note.userInfo[UIKeyboardFrameEndUserInfoKey] CGRectValue];
    [self setNeedsLayout];
}
- (void)drag:(UIPanGestureRecognizer *)gesture {
    CGRect rect = [self availableRect];
    CGPoint delta = [gesture translationInView:self];
    CGPoint center = self.button.center;
    double minX = LCReturnAxisCenter(rect.origin.x, rect.size.width, 0);
    double minY = LCReturnAxisCenter(rect.origin.y, rect.size.height, 0);
    double spanX = LCReturnAxisCenter(rect.origin.x, rect.size.width, 1) - minX;
    double spanY = LCReturnAxisCenter(rect.origin.y, rect.size.height, 1) - minY;
    self.position = CGPointMake(spanX > 0 ? MIN(1, MAX(0, (center.x + delta.x - minX) / spanX)) : 0.5,
                                spanY > 0 ? MIN(1, MAX(0, (center.y + delta.y - minY) / spanY)) : 0.5);
    if (self.collapsed) self.position = CGPointMake(self.position.x < 0.5 ? 0 : 1, self.position.y);
    [gesture setTranslation:CGPointZero inView:self];
    [self setNeedsLayout];
    [self layoutIfNeeded];
    if (gesture.state == UIGestureRecognizerStateEnded || gesture.state == UIGestureRecognizerStateCancelled) {
        [NSUserDefaults.lcSharedDefaults setObject:@[@(self.position.x), @(self.position.y)] forKey:@"LCReturnControlPosition"];
        NSLog(@"[LC_RETURN] CONTROL_MOVED");
    }
}
- (void)tapped {
    if (self.collapsed) {
        self.collapsed = NO;
        [self setNeedsLayout];
        NSLog(@"[LC_RETURN] CONTROL_RESTORED");
        return;
    }
    if (self.action) {
        // A retained guest should reopen as a tab when Start Collapsed is on.
        if ([NSUserDefaults.lcSharedDefaults boolForKey:@"LCGuestReturnStartsCollapsed"]) [self collapse];
        self.action();
    }
}
@end


@interface AppSceneViewController()
@property(nonatomic, strong) LCReturnControl *lcReturnControl;
@property int resizeDebounceToken;
@property CFTimeInterval lastResizeRequestTime;
@property CGPoint normalizedOrigin;
@property bool isNativeWindow;
@property NSUUID* identifier;
@end

@interface AppSceneViewController()
@property(nonatomic) UIWindowScene *hostScene;
@property(nonatomic) NSString *sceneID;
@property(nonatomic) NSExtension* extension;
@property(nonatomic) bool isAppTerminationCleanUpCalled;
@end

// Both guest and service scenes share one swizzle installation for the host process.
static void V3InitializeUIKitFixes(void) {
    static dispatch_once_t onceToken;
    dispatch_once(&onceToken, ^{ UIKitFixesInit(); });
}

@implementation AppSceneViewController

- (void)viewDidLayoutSubviews {
    [super viewDidLayoutSubviews];
    if (self.isAppTerminationCleanUpCalled) {
        [self.lcReturnControl removeFromSuperview];
        return;
    }
    if (!self.lcReturnControl) {
        self.lcReturnControl = [[LCReturnControl alloc] initWithFrame:self.view.bounds];
        __weak typeof(self) weakSelf = self;
        self.lcReturnControl.action = ^{ [weakSelf lcReturnToHost]; };
    }
    // Virtual-window chrome overlays the guest controller. Keep the control
    // above those input views, not inside the remotely hosted content layer.
    UIView *overlayHost = [self.delegate isKindOfClass:DecoratedAppSceneViewController.class]
        ? [(DecoratedAppSceneViewController *)self.delegate view] : self.view;
    if (self.lcReturnControl.superview != overlayHost) {
        [self.lcReturnControl removeFromSuperview];
        [overlayHost addSubview:self.lcReturnControl];
        NSLog(@"[LC_RETURN] CONTROL_ATTACHED layer=%@", overlayHost == self.view ? @"native" : @"virtual_window_chrome");
    }
    self.lcReturnControl.frame = [self.view convertRect:self.view.bounds toView:overlayHost];
    BOOL decorated = [self.delegate isKindOfClass:DecoratedAppSceneViewController.class];
    BOOL maximized = decorated && [(DecoratedAppSceneViewController *)self.delegate isMaximized];
    self.lcReturnControl.hidden = LCReturnShouldHide(self.isAppRunning, decorated, maximized);
    [overlayHost bringSubviewToFront:self.lcReturnControl];
}
- (void)lcReturnToHost {
    NSLog(@"[LC_RETURN] RETURN_REQUESTED pid=%d", self.pid);
    NSLog(@"[LC_RETURN] MODE_LIVEPROCESS");
    if (!self.isAppRunning) {
        NSLog(@"[LC_RETURN] RETURN_FAILED reason=guest_exited");
        [self appTerminationCleanUp];
        return;
    }
    if ([self.delegate isKindOfClass:DecoratedAppSceneViewController.class]) {
        [(DecoratedAppSceneViewController *)self.delegate minimizeWindow];
        NSLog(@"[LC_RETURN] GUEST_MINIMIZE_REQUESTED mode=LIVEPROCESS_PRESERVED_RETURN pid=%d", self.pid);
    } else if (self.lcActivateHost) {
        self.lcActivateHost();
    } else {
        NSLog(@"[LC_RETURN] RETURN_FAILED reason=host_activation_unavailable");
    }
}



- (instancetype)initWithBundleId:(NSString*)bundleId dataUUID:(NSString*)dataUUID delegate:(id<AppSceneViewControllerDelegate>)delegate {
    self = [super initWithNibName:nil bundle:nil];
    self.delegate = delegate;
    self.dataUUID = dataUUID;
    self.bundleId = bundleId;
    self.scaleRatio = 1.0;
    self.isAppTerminationCleanUpCalled = false;
    self.isNativeWindow = [NSUserDefaults.lcSharedDefaults integerForKey:@"LCMultitaskMode" ] == 1;
    
    static dispatch_once_t onceToken;
    dispatch_once(&onceToken, ^{
        V3InitializeUIKitFixes();
    });
    
    // init extension
    NSError* error = nil;
    _extension = [NSExtension extensionWithIdentifier:LCUtils.liveProcessBundleIdentifier error:&error];
    if(error) {
        [delegate appSceneVC:self didInitializeWithError:error];
        return nil;
    }
    _extension.preferredLanguages = @[];
    
    NSExtensionItem *item = [NSExtensionItem new];
    NSMutableArray* bookmarks = [NSMutableArray array];
    NSMutableDictionary *userInfo = @{
        @"hostUrlScheme": NSUserDefaults.lcAppUrlScheme,
        @"selected": _bundleId,
        @"selectedContainer": _dataUUID,
        @"bookmarks": bookmarks,
        @"lcHomePath": NSHomeDirectory(),
    }.mutableCopy;
    NSString *hostGroupID = LCValidatedAppGroupID([LCSharedUtils appGroupID], ^BOOL(NSString *groupID) {
        return [NSFileManager.defaultManager containerURLForSecurityApplicationGroupIdentifier:groupID] != nil;
    });
    if (hostGroupID) [userInfo setObject:hostGroupID forKey:@"lcAppGroupID"];
    
    NSString* launchAppUrlScheme = [NSUserDefaults.standardUserDefaults stringForKey:@"launchAppUrlScheme"];
    [NSUserDefaults.lcUserDefaults removeObjectForKey:@"launchAppUrlScheme"];
    if(launchAppUrlScheme) {
        [userInfo setValue:launchAppUrlScheme forKey:@"launchAppUrlScheme"];
    }
    
    NSURL *docURL = [NSFileManager.defaultManager URLsForDirectory:NSDocumentDirectory inDomains:NSUserDomainMask].lastObject;
    if ([NSUserDefaults.standardUserDefaults boolForKey:@"LCSharePrivateDataWithLiveProcess"]) {
        NSData* bookmarkData = [docURL bookmarkDataWithOptions:(1<<11) includingResourceValuesForKeys:0 relativeToURL:0 error:0];
        [bookmarks addObject:bookmarkData];
    } else {
        bool isSharedApp = false;
        NSBundle* bundle = [LCSharedUtils findBundleWithBundleId:bundleId isSharedAppOut:&isSharedApp];
        // when mutlitask with private app, we can restrict its sandbox to only its own container
        if (!isSharedApp) {
            NSURL *dataURL = [docURL URLByAppendingPathComponent:[NSString stringWithFormat:@"Data/Application/%@", dataUUID]];
            NSURL *tweaksURL = [docURL URLByAppendingPathComponent:@"Tweaks"];
            [bookmarks addObject:[bundle.bundleURL bookmarkDataWithOptions:(1<<11) includingResourceValuesForKeys:0 relativeToURL:0 error:0]];
            NSData* containerBookmark = [dataURL bookmarkDataWithOptions:(1<<11) includingResourceValuesForKeys:0 relativeToURL:0 error:0];
            if(containerBookmark) {
                [bookmarks addObject:containerBookmark];
            }
            [bookmarks addObject:[tweaksURL bookmarkDataWithOptions:(1<<11) includingResourceValuesForKeys:0 relativeToURL:0 error:0]];
        }
    }
    item.userInfo = userInfo;
    
    __weak typeof(self) weakSelf = self;
    [_extension setRequestCancellationBlock:^(NSUUID *uuid, NSError *error) {
        NSLog(@"[LC_GUEST_LIFECYCLE] PROCESS_CANCELLED pid=%d source=extension_request", weakSelf.pid);
        dispatch_async(dispatch_get_main_queue(), ^{
            // Preserve the original extension error before cleanup settles a pending launch.
            weakSelf.lcLaunchError = error;
            [weakSelf appTerminationCleanUp];
            [weakSelf.delegate appSceneVC:weakSelf didInitializeWithError:error];
        });
    }];
    [_extension setRequestInterruptionBlock:^(NSUUID *uuid) {
        NSLog(@"[LC_GUEST_LIFECYCLE] PROCESS_INTERRUPTED pid=%d source=extension_request", weakSelf.pid);
        [weakSelf appTerminationCleanUp];
    }];
    [_extension beginExtensionRequestWithInputItems:@[item] completion:^(NSUUID *identifier) {
        dispatch_async(dispatch_get_main_queue(), ^{
            if (self.isAppTerminationCleanUpCalled) return;
        if(identifier) {
            [MultitaskManager registerMultitaskContainerWithContainer:self.dataUUID];
            self.identifier = identifier;
            self.pid = [self.extension pidForRequestIdentifier:self.identifier];
            [delegate appSceneVC:self didInitializeWithError:nil];
            dispatch_async(dispatch_get_main_queue(), ^{
                [self setUpAppPresenter];
            });
        } else {
            NSError* error = [NSError errorWithDomain:@"LiveProcess" code:2 userInfo:@{NSLocalizedDescriptionKey: @"Failed to start app. Child process has unexpectedly crashed"}];
            [delegate appSceneVC:self didInitializeWithError:error];
        }
        });
    }];
    
    return self;
}

// V3_COMMAND_PATCH_V1: the service owns process lifetime; this owns presentation only.
- (instancetype)initWithServicePID:(int)pid delegate:(id<AppSceneViewControllerDelegate>)delegate {
    self = [super initWithNibName:nil bundle:nil];
    if (self) {
        self.delegate = delegate;
        self.pid = pid;
        self.bundleId = @"builtinSideStore";
        self.dataUUID = @"v3-service";
        self.scaleRatio = 1.0;
        V3InitializeUIKitFixes();
        dispatch_async(dispatch_get_main_queue(), ^{ [self setUpAppPresenter]; });
    }
    return self;
}

- (void)setUpAppPresenter {
    if (_isAppTerminationCleanUpCalled || !self.isAppRunning) {
        [self appTerminationCleanUp];
        return;
    }
    RBSProcessPredicate* predicate = [PrivClass(RBSProcessPredicate) predicateMatchingIdentifier:@(self.pid)];
    FBProcessManager *manager = [PrivClass(FBProcessManager) sharedInstance];
    // At this point, the process is spawned and we're ready to create a scene to render in our app
    RBSProcessHandle* processHandle = [PrivClass(RBSProcessHandle) handleForPredicate:predicate error:nil];
    [manager registerProcessForAuditToken:processHandle.auditToken];
    UIApplicationSceneSpecification *specification = [UIApplicationSceneSpecification specification];
    
    void (^updateSceneSettings)(id) = ^void(UIMutableApplicationSceneSettings *settings) {
        settings.canShowAlerts = YES;
        settings.cornerRadiusConfiguration = [[PrivClass(BSCornerRadiusConfiguration) alloc] initWithTopLeft:self.view.layer.cornerRadius bottomLeft:self.view.layer.cornerRadius bottomRight:self.view.layer.cornerRadius topRight:self.view.layer.cornerRadius];
        settings.displayConfiguration = UIScreen.mainScreen.displayConfiguration;
        settings.foreground = YES;
        //settings.interruptionPolicy = 2; // reconnect
        settings.level = 1;
        settings.persistenceIdentifier = self.dataUUID;
        settings.statusBarDisabled = !self.isNativeWindow;
        //settings.previewMaximumSize =
        //settings.deviceOrientationEventsEnabled = YES;
        if(!self.usesHostingControllerAPI) {
            settings.safeAreaInsetsPortrait = self.view.safeAreaInsets;
        }
    };
    void (^updateSceneClientSettings)(id) = ^void(UIMutableApplicationSceneClientSettings *clientSettings) {
        clientSettings.interfaceOrientation = UIInterfaceOrientationPortrait;
        clientSettings.statusBarStyle = 0;
    };

    if (@available(iOS 18.0, *)) {
        // Use new API for iOS 18+. While some of these APIs are available since 17.0, we're only interested in fixing event deferring issue
        _UISceneHostingControllerAdvancedConfiguration *config = [[_UISceneHostingControllerAdvancedConfiguration alloc] initWithProcessIdentity:processHandle.identity];
        config.sceneSpecification = specification;
        if (@available(iOS 27.0, *)) {} else {
            // on 27 manually adding this is not need, also setAdditionalExtensions: doesn't exist for some reason
            config.additionalExtensions = [NSOrderedSet orderedSetWithArray:@[
                PrivClass(_UISceneHostingEventDeferringExtension),
            ]];
        }
        self.hostingController = [[_UISceneHostingController alloc] initWithAdvancedConfiguration:config];
        /// !! do NOT use self.hostingController.sceneView here as it breaks keyboard focus on iOS 26 below. I have no idea why this happens even though both return the same object. Maybe sceneView didn't initialize its ViewController properly?
        self.contentView = self.hostingController.sceneViewController.view;
        self.contentView.clipsToBounds = NO;
        // _scenePresenter was a property in 26, but made only ivar in 27
        self.presenter = [self.contentView valueForKey:@"_scenePresenter"];
        self.sceneID = self.presenter.identifier;
        FBScene *scene = self.presenter.scene;
        [scene configureParameters:^(FBSMutableSceneParameters *parameters) {
            [parameters updateSettingsWithBlock:updateSceneSettings];
            [parameters updateClientSettingsWithBlock:updateSceneClientSettings];
        }];
        
        /// Fix keyboard focus by setting up event deferring extension. Previously we worked around it by changing identifier, but that broke other things
        _UISceneEventDeferringHostComponent *deferringComponent = self.hostingController._eventDeferringComponent;
        NSAssert(deferringComponent, @"Unexpectedly nil _UISceneEventDeferringHostComponent");
        if (@available(iOS 27.0, *)) { // _UIKeyboardArbiterUsesDeferringGraph()
            /// UIKitCore`__85-[_UIRemoteViewControllerSceneHostingImpl _viewServiceHostSessionDidConnectToClient:]_block_invoke
            /// iOS 27 requires setting up _UISceneEventDeferringHostComponent for keyboard focus to work
            
            /// Replicate these methods since they are made private
            /// -[_UISceneEventDeferringHostComponent setFirstResponderTrackingSelectionPath:]:
            [deferringComponent setValue:self forKey:@"_firstResponderTrackingSelectionPath"];
            // if (!deferringComponent->_flags.clientIsInChain) return;
            /// -[_UISceneEventDeferringHostComponent becomeFirstResponderIfNecessary]:
            // if (deferringComponent->_flags.maintainHostFirstResponderWhenClientWantsKeyboard)
            
            deferringComponent.grantBehavior = 2;
            deferringComponent.selectionRequestBehavior = 2;
        }
        /// UIKitCore`-[_UISceneHostingController createSceneWithConfiguration:]
        /// Lower iOS uses _UISceneHostingEventDeferringExtension, no further setup needed
        
        // Now it's time to get the initial settings from decorated VC
        [self.delegate appSceneVCWillActivateScene:self];
        [self addChildViewController:self.hostingController.sceneViewController];
        
        // For new API, let FBSSceneObserver send host scene events instead of NSExtensionContext
        NSNotificationCenter *center = NSNotificationCenter.defaultCenter;
        if (self.extension) [center removeObserver:self.extension name:UIApplicationDidBecomeActiveNotification object:UIApp];
        if (self.extension) [center removeObserver:self.extension name:UIApplicationWillResignActiveNotification object:UIApp];
        if (self.extension) [center removeObserver:self.extension name:UIApplicationDidEnterBackgroundNotification object:UIApp];
        if (self.extension) [center removeObserver:self.extension name:UIApplicationWillEnterForegroundNotification object:UIApp];
    } else {
        self.sceneID = [NSString stringWithFormat:@"sceneID:%@-%@", @"LiveProcess", self.dataUUID];
        FBSMutableSceneDefinition *definition = [PrivClass(FBSMutableSceneDefinition) definition];
        definition.identity = [PrivClass(FBSSceneIdentity) identityForIdentifier:self.sceneID];
        definition.clientIdentity = [PrivClass(FBSSceneClientIdentity) identityForProcessIdentity:processHandle.identity];
        definition.specification = specification;
        
        FBSMutableSceneParameters *parameters = [PrivClass(FBSMutableSceneParameters) parametersForSpecification:specification];
        [parameters updateSettingsWithBlock:updateSceneSettings];
        [parameters updateClientSettingsWithBlock:updateSceneClientSettings];
        FBScene *scene = [[PrivClass(FBSceneManager) sharedInstance] createSceneWithDefinition:definition initialParameters:parameters];
        self.presenter = [scene.uiPresentationManager createPresenterWithIdentifier:self.sceneID];
        [self.presenter modifyPresentationContext:^(UIMutableScenePresentationContext *context) {
            context.appearanceStyle = 2;
        }];
        [self.presenter activate];
        
        self.contentView = [[UIView alloc] init];
        [self.contentView addSubview:self.presenter.presentationView];
    }
    [self.view addSubview:_contentView];
    [self.view setNeedsLayout]; // Re-show control after asynchronous guest initialization.
    
    // If we have a staging URL scheme, pass it now
    NSString *launchUrl = [NSUserDefaults.standardUserDefaults stringForKey:@"launchAppUrlScheme"];
    if(launchUrl) {
        [NSUserDefaults.standardUserDefaults removeObjectForKey:@"launchAppUrlScheme"];
        [self openURLScheme:launchUrl];
    }
    
    __weak typeof(self) weakSelf = self;
    [self.extension setRequestInterruptionBlock:^(NSUUID *uuid) {
        NSLog(@"[LC_GUEST_LIFECYCLE] PROCESS_INTERRUPTED pid=%d source=extension_request", weakSelf.pid);
        [weakSelf appTerminationCleanUp];
    }];
    self.contentView.layer.anchorPoint = CGPointMake(0, 0);
    self.contentView.layer.position = CGPointMake(0, 0);
    
    [self.view.window.windowScene _registerSettingsDiffActionArray:@[self] forKey:self.sceneID];
}

- (void)terminate {
    if(self.isAppRunning) {
        [self.extension _kill:SIGTERM];
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(3 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
            [self.extension _kill:SIGKILL];
        });
    }
}

- (void)_performActionsForUIScene:(UIScene *)scene withUpdatedFBSScene:(id)fbsScene settingsDiff:(FBSSceneSettingsDiff *)diff fromSettings:(UIApplicationSceneSettings *)settings transitionContext:(id)context lifecycleActionType:(uint32_t)actionType {
    if(!self.isAppRunning) {
        [self appTerminationCleanUp];
    }
    if(!diff) return;
    
    UIMutableApplicationSceneSettings *baseSettings = [diff settingsByApplyingToMutableCopyOfSettings:settings];
    UIApplicationSceneTransitionContext *newContext = [context copy];
    newContext.actions = nil;
    [self.delegate appSceneVC:self didUpdateFromSettings:baseSettings transitionContext:newContext lifecycleActionType:actionType];
}

- (void)viewWillLayoutSubviews {
    /// For native window we let iPadOS handle it however it wants, which is usually live resize (autoresizingMask set in appSceneVCWillActivateScene)
    if(_contentView.autoresizingMask != (UIViewAutoresizingFlexibleWidth|UIViewAutoresizingFlexibleHeight)) {
        [self updateFrameWithSettingsBlock:nil];
    }
}
- (void)updateFrameWithSettingsBlock:(void (^)(UIMutableApplicationSceneSettings *settings))block {
    __block int currentDebounceToken = ++_resizeDebounceToken;
    dispatch_block_t queueBlock = ^{
        if(currentDebounceToken != self.resizeDebounceToken) {
            return;
        }
        [self updateSettingsWithBlock:^(UIMutableApplicationSceneSettings *settings) {
            settings.deviceOrientation = UIDevice.currentDevice.orientation;
            settings.interfaceOrientation = self.view.window.windowScene.interfaceOrientation;
            CGRect frame = self.view.frame;
            if(!self.usesHostingControllerAPI) {
                frame.size.width /= self.scaleRatio;
                frame.size.height /= self.scaleRatio;
            }
            if(UIInterfaceOrientationIsLandscape(settings.interfaceOrientation)) {
                CGSize size = frame.size;
                frame.size.width = size.height;
                frame.size.height = size.width;
            }
            settings.frame = frame;
            if(block) {
                block(settings);
            }
        }];
    };
    if(_shouldSkipDebounceOnce) {
        _shouldSkipDebounceOnce = NO;
        queueBlock();
    } else {
        dispatch_time_t delay = dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.05 * NSEC_PER_SEC));
        dispatch_after(delay, dispatch_get_main_queue(), queueBlock);
    }
}
- (void)updateSettingsWithBlock:(void(^)(UIMutableApplicationSceneSettings *settings))updateSettingsBlock {
    if(_shouldIgnoreSceneUpdates) {
        // Ignore all updates when in PiP mode
        return;
    }
    
    if(!_hostingController && self.contentView) {
        // Legacy path
        [self.presenter.scene updateSettingsWithBlock:updateSettingsBlock];
        return;
    }
    
    /// iOS 18.0 path, most are automatically handled by setting values to _UISceneHostingViewController
    /// This is also reachable on legacy path when contentView is nil during early setup
    UIMutableApplicationSceneSettings *tempSettings = [self.presenter.scene.settings mutableCopy];
    if(!tempSettings) {
        tempSettings = [UIMutableApplicationSceneSettings new];
    }
    updateSettingsBlock(tempSettings);
    CGRect frame = tempSettings.frame;
    if(UIInterfaceOrientationIsLandscape(tempSettings.interfaceOrientation)) {
        frame = CGRectMake(frame.origin.x, frame.origin.y, frame.size.height, frame.size.width);
    }
    
    if (self.contentView) {
        BOOL isiOS26 = NO;
        if(@available(iOS 19.0, *)) { if(@available(iOS 27.0, *)) {} else isiOS26 = YES; }
        // Discard position
        frame.origin = CGPointZero;
        self.contentView.frame = frame;
    } else {
        // This method can be called while contentView is nil to set up initial frame
        self.view.frame = frame;
    }
}

- (BOOL)isAppRunning {
    return !_isAppTerminationCleanUpCalled && _pid > 0 && getpgid(_pid) > 0;
}


- (void)appTerminationCleanUp {
    if (!NSThread.isMainThread) {
        dispatch_async(dispatch_get_main_queue(), ^{ [self appTerminationCleanUp]; });
        return;
    }
    if (_isAppTerminationCleanUpCalled) return;
    _isAppTerminationCleanUpCalled = true;
    self.lcReturnControl.hidden = YES;
    [self.lcReturnControl removeFromSuperview];
    if (self.sceneID) {
        [[PrivClass(FBSceneManager) sharedInstance] destroyScene:self.sceneID withTransitionContext:nil];
    }
    if (self.usesHostingControllerAPI) {
        if (@available(iOS 17.0, *)) {
            [self.hostingController invalidate];
            [self.hostingController.sceneViewController removeFromParentViewController];
            self.hostingController = nil;
        }
    } else if (self.presenter) {
        [self.presenter deactivate];
        [self.presenter invalidate];
    }
    self.presenter = nil;
    // Release the old registration BEFORE notifying code that may relaunch.
    [MultitaskManager unregisterMultitaskContainerWithContainer:self.dataUUID];
    [self.delegate appSceneVCAppDidExit:self];
}


- (void)setBackgroundNotificationEnabled:(bool)enabled {
    if(self.usesHostingControllerAPI) {
        /// Issue with new API: FBSSceneObserver takes priority over to send UIApplicationWillResignActiveNotification regressed #942,
        /// so here we make it foreground (UIApplicationDidBecomeActiveNotification) again.
        [self.presenter.scene updateSettingsWithBlock:^(UIMutableApplicationSceneSettings *settings) {
            settings.foreground = YES;
            settings.deactivationReasons = 0;
        }];
        return;
    }
    NSNotificationCenter *center = NSNotificationCenter.defaultCenter;
    if(enabled) {
        // Re-add UIApplicationDidEnterBackgroundNotification
        [center addObserver:self.extension selector:@selector(_hostDidEnterBackgroundNote:) name:UIApplicationDidEnterBackgroundNotification object:UIApp];
        [center addObserver:self.extension selector:@selector(_hostWillResignActiveNote:) name:UIApplicationWillResignActiveNotification object:UIApp];
    } else {
        // Remove UIApplicationDidEnterBackgroundNotification so apps like YouTube can continue playing video
        if (self.extension) [center removeObserver:self.extension name:UIApplicationDidEnterBackgroundNotification object:UIApp];
        if (self.extension) [center removeObserver:self.extension name:UIApplicationWillResignActiveNotification object:UIApp];
    }
}

- (void)viewDidMoveToWindow:(UIWindow *)newWindow shouldAppearOrDisappear:(BOOL)appear {
    [super viewDidMoveToWindow:newWindow shouldAppearOrDisappear:appear];
    if(!newWindow) {
        if(self.sceneID) {
            [self.view.window.windowScene _unregisterSettingsDiffActionArrayForKey:self.sceneID];
        }
        self.delegate = nil;
    }
}

- (void)openURLScheme:(NSString *)urlString {
    [self.presenter.scene updateSettingsWithTransitionBlock:^(id settings) {
        // pull from UserDefaults.standard.setValue(launchURLStr, forKey: "launchAppUrlScheme")
        UIApplicationSceneTransitionContext *context = [UIApplicationSceneTransitionContext new];
        NSURL *url = [NSURL URLWithString:urlString];
        context.payload = @{UIApplicationLaunchOptionsURLKey: urlString};
        context.actions = [NSSet setWithObject:[[UIOpenURLAction alloc] initWithURL:url]];
        return context;
    }];
}

- (void)handleStatusBarTapAction:(UIAction *)action {
    [self.presenter.scene updateSettingsWithTransitionBlock:^(id settings) {
        UIApplicationSceneTransitionContext *context = [UIApplicationSceneTransitionContext new];
        context.actions = [NSSet setWithObject:action];
        return context;
    }];
}

- (BOOL)usesHostingControllerAPI {
    return _hostingController != nil;
}

@end
 
