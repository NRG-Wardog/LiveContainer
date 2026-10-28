#import <Foundation/Foundation.h>
#import <dispatch/dispatch.h>
static id lookupValue; static NSError *lookupError;
@interface TestExtension:NSObject
+ (id)extensionWithIdentifier:(NSString *)identifier error:(NSError **)error;
- (int)pidForRequestIdentifier:(NSUUID *)identifier;
@end
@implementation TestExtension
- (int)pidForRequestIdentifier:(NSUUID *)identifier { return 123; }
+ (id)extensionWithIdentifier:(NSString *)identifier error:(NSError **)error { *error=lookupError;return lookupValue; }
@end
#define NSExtension TestExtension
@interface LCUtils:NSObject
+ (NSString *)liveProcessBundleIdentifier;
@end
@implementation LCUtils
+ (NSString *)liveProcessBundleIdentifier { return @"fixture.extension"; }
@end
static int registrations;
@interface MultitaskManager:NSObject
+ (void)registerMultitaskContainerWithContainer:(NSString *)data;
@end
@implementation MultitaskManager
+ (void)registerMultitaskContainerWithContainer:(NSString *)data { registrations++; }
@end
@class AppSceneViewController;
@protocol FixtureDelegate
- (void)appSceneVC:(AppSceneViewController *)vc didInitializeWithError:(NSError *)error;
- (void)appSceneVCAppDidExit:(AppSceneViewController *)vc;
@end
@interface AppSceneViewController:NSObject
@property(nonatomic,strong) id extension;
@property(nonatomic,strong) id<FixtureDelegate> delegate;
@property(nonatomic,strong) NSError *lcLaunchError;
@property(nonatomic) BOOL isAppTerminationCleanUpCalled;
@property(nonatomic) int pid;
@property(nonatomic) int cleanups;
@property(nonatomic,strong) NSString *dataUUID;
@property(nonatomic,strong) NSUUID *identifier;
@property(nonatomic) int presentations;
- (BOOL)lcPrepareGuestExtension;
- (void)appTerminationCleanUp;
- (void)simulateInterruption;
- (void)simulateCancellation:(NSError *)error;
- (void)simulateBeginCompletion:(NSUUID *)identifier;
- (void)setUpAppPresenter;
@end
@implementation AppSceneViewController
@@LOOKUP@@
- (void)appTerminationCleanUp { if(self.isAppTerminationCleanUpCalled)return;self.isAppTerminationCleanUpCalled=YES;self.cleanups++;[self.delegate appSceneVCAppDidExit:self]; }
- (void)simulateInterruption { __weak typeof(self) weakSelf=self; @@INTERRUPTION@@ }
- (void)simulateCancellation:(NSError *)error { __weak typeof(self) weakSelf=self; @@CANCELLATION@@ }
- (void)simulateBeginCompletion:(NSUUID *)identifier { id delegate=self.delegate; @@BEGIN@@ }
- (void)setUpAppPresenter { if(!self.isAppTerminationCleanUpCalled)self.presentations++; }
@end
@interface CompletionOwner:NSObject<FixtureDelegate>
@property(nonatomic) BOOL lcLaunchSettled;
@property(nonatomic,copy) void (^pidAvailableHandler)(NSNumber *,NSError *);
@property(nonatomic) int callbacks;
@property(nonatomic) int deliveries;
@property(nonatomic) BOOL running;
@property(nonatomic,strong) NSError *receivedError;
@end
@implementation CompletionOwner
@@SETTLE@@
- (void)appSceneVC:(AppSceneViewController *)vc didInitializeWithError:(NSError *)error { self.deliveries++;[self lcCompleteLaunch:vc error:error]; }
- (void)appSceneVCAppDidExit:(AppSceneViewController *)vc { [self lcCompleteLaunch:vc error:vc.lcLaunchError ?: [NSError errorWithDomain:@"LiveContainerReturn" code:410 userInfo:nil]]; }
@end
static void check(BOOL value, NSString *message) { if(!value){fprintf(stderr,"FAIL: %s\n",message.UTF8String);exit(1);} }
static void drain(void) { __block BOOL done=NO;dispatch_async(dispatch_get_main_queue(), ^{done=YES;});NSDate *end=[NSDate dateWithTimeIntervalSinceNow:5];while(!done && [end timeIntervalSinceNow]>0){[[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.001]];}check(done,@"main queue did not drain"); }
static void wire(CompletionOwner *owner) { owner.running=YES;__weak CompletionOwner *weak=owner;owner.pidAvailableHandler=^(NSNumber *pid,NSError *error){CompletionOwner *o=weak;o.callbacks++;o.running=NO;o.receivedError=error;}; }
int main(void) { @autoreleasepool {
 check(NSThread.isMainThread,@"fixture main thread");
 for(NSInteger mode=0;mode<4;mode++){
  lookupValue=mode>=2?[TestExtension new]:nil;lookupError=(mode==1||mode==3)?[NSError errorWithDomain:NSCocoaErrorDomain code:42 userInfo:nil]:nil;
  AppSceneViewController *vc=[AppSceneViewController new];CompletionOwner *owner=[CompletionOwner new];vc.delegate=owner;
  BOOL ready=[vc lcPrepareGuestExtension];check(ready==(mode==2),@"lookup result");check(owner.deliveries==0,@"failure delivered before wiring");wire(owner);drain();
  if(mode!=2){check(owner.callbacks==1&&!owner.running,@"lookup failure did not settle running state");check(vc.cleanups==1,@"cleanup exactly once");check(owner.receivedError.code==((mode==1||mode==3)?42:411),@"lookup reason lost");[owner appSceneVC:vc didInitializeWithError:nil];check(owner.callbacks==1,@"late completion replayed");}
  else {check(owner.callbacks==0 && owner.running,@"success lookup settled prematurely");[owner appSceneVC:vc didInitializeWithError:nil];check(owner.callbacks==1&&!owner.receivedError,@"success completion");}
 }
 lookupValue=[TestExtension new];lookupError=nil;
 AppSceneViewController *vc=[AppSceneViewController new];CompletionOwner *owner=[CompletionOwner new];vc.delegate=owner;
 [vc simulateInterruption];check(!vc.isAppTerminationCleanUpCalled,@"synchronous interruption settled before constructor return");wire(owner);drain();check(owner.callbacks==1&&!owner.running&&vc.cleanups==1,@"interruption did not settle wired callback");[vc simulateInterruption];drain();[owner appSceneVC:vc didInitializeWithError:nil];check(owner.callbacks==1,@"interruption duplicate/late callback replayed");
 lookupValue=nil;lookupError=[NSError errorWithDomain:NSPOSIXErrorDomain code:13 userInfo:nil];
 vc=[AppSceneViewController new];owner=[CompletionOwner new];vc.delegate=owner;[vc lcPrepareGuestExtension];wire(owner);[vc appTerminationCleanUp];drain();check(owner.callbacks==1&&owner.receivedError.code==13&&owner.deliveries==0,@"cleanup before queued lookup lost reason or delivered twice");
 lookupValue=[TestExtension new];lookupError=nil;vc=[AppSceneViewController new];owner=[CompletionOwner new];vc.delegate=owner;[vc lcPrepareGuestExtension];
 NSError *cancel=[NSError errorWithDomain:NSCocoaErrorDomain code:77 userInfo:nil];[vc simulateCancellation:cancel];check(!vc.isAppTerminationCleanUpCalled,@"cancellation before wiring");wire(owner);[vc simulateBeginCompletion:[NSUUID UUID]];drain();drain();check(owner.callbacks==1&&!owner.running&&owner.receivedError.code==77,@"cancellation reason/settlement");check(registrations==0&&vc.presentations==0,@"late begin registered or presented cleaned guest");
 [vc simulateCancellation:cancel];[vc simulateInterruption];drain();check(owner.callbacks==1&&vc.cleanups==1,@"duplicate terminal signal");
 puts("GUEST_LAUNCH_COMPLETION_PASS");return 0;
} }
